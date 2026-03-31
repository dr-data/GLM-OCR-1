"""Bidirectional YAML <-> GUI config manager."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


# Default config file search order.
_SEARCH_PATHS = [
    Path("tui_config.yaml"),
    Path("tui/tui_config.yaml"),
    Path.home() / ".glmocr" / "tui_config.yaml",
]

# Bundled default config shipped with the package.
_BUILTIN_DEFAULT = Path(__file__).with_name("tui_config.yaml")

# GUI-exposed settings: (display_label, dotted_config_path, type, default)
GUI_SETTINGS = [
    ("Mode", "pipeline.maas.enabled", "mode_select", True),
    ("API Key", "pipeline.maas.api_key", "password", ""),
    ("API URL", "pipeline.maas.api_url", "str", "https://open.bigmodel.cn/api/paas/v4/layout_parsing"),
    ("Host", "pipeline.ocr_api.api_host", "str", "127.0.0.1"),
    ("Port", "pipeline.ocr_api.api_port", "int", 8080),
    ("Output Dir", "tui.output_dir", "str", "./output"),
    ("PDF DPI", "pipeline.page_loader.pdf_dpi", "int", 200),
    ("Max Workers", "pipeline.max_workers", "int", 16),
    ("Layout Threshold", "pipeline.layout.threshold", "float", 0.3),
    ("Merge Formulas", "pipeline.result_formatter.enable_merge_formula_numbers", "bool", True),
    ("Merge Text", "pipeline.result_formatter.enable_merge_text_blocks", "bool", True),
    ("Bullet Points", "pipeline.result_formatter.enable_format_bullet_points", "bool", True),
    ("Table -> MD", "tui.convert_html_tables", "bool", True),
    ("Log Level", "logging.level", "log_select", "INFO"),
]


def _get_nested(data: dict, dotted_path: str, default: Any = None) -> Any:
    """Get a value from a nested dict using a dotted path."""
    keys = dotted_path.split(".")
    d = data
    for k in keys:
        if not isinstance(d, dict):
            return default
        d = d.get(k, default)
        if d is default:
            return default
    return d


def _set_nested(data: dict, dotted_path: str, value: Any) -> None:
    """Set a value in a nested dict using a dotted path."""
    keys = dotted_path.split(".")
    d = data
    for k in keys[:-1]:
        d = d.setdefault(k, {})
    d[keys[-1]] = value


class ConfigManager:
    """Manages config loading, saving, and sync between GUI and YAML."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._path = self._resolve_path(config_path)
        self._data: Dict[str, Any] = {}
        self.load()

    @staticmethod
    def _resolve_path(explicit: Optional[str]) -> Path:
        if explicit:
            return Path(explicit).resolve()
        for p in _SEARCH_PATHS:
            if p.exists():
                return p.resolve()
        return _BUILTIN_DEFAULT

    def load(self) -> Dict[str, Any]:
        """Load config from YAML file."""
        if self._path.exists():
            raw = self._path.read_text(encoding="utf-8")
            self._data = yaml.safe_load(raw) or {}
        else:
            # Load builtin defaults
            raw = _BUILTIN_DEFAULT.read_text(encoding="utf-8")
            self._data = yaml.safe_load(raw) or {}
        return self._data

    def save(self) -> None:
        """Write current config back to YAML."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                self._data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False,
            )

    @property
    def config_path(self) -> Path:
        return self._path

    def get(self, dotted_path: str, default: Any = None) -> Any:
        """Get a config value by dotted path."""
        return _get_nested(self._data, dotted_path, default)

    def update_setting(self, dotted_path: str, value: Any) -> None:
        """Update a single setting and persist to YAML."""
        _set_nested(self._data, dotted_path, value)
        self.save()

    def get_gui_values(self) -> Dict[str, Any]:
        """Return a dict of {dotted_path: current_value} for GUI settings."""
        result = {}
        for _label, path, _type, default in GUI_SETTINGS:
            result[path] = _get_nested(self._data, path, default)
        return result

    def get_tui_setting(self, key: str, default: Any = None) -> Any:
        """Get a TUI-specific setting."""
        return _get_nested(self._data, f"tui.{key}", default)

    def get_sdk_kwargs(self) -> Dict[str, Any]:
        """Build kwargs for GlmOcr() constructor from current config."""
        maas = self._data.get("pipeline", {}).get("maas", {})
        ocr_api = self._data.get("pipeline", {}).get("ocr_api", {})
        logging_cfg = self._data.get("logging", {})

        mode = "maas" if maas.get("enabled", True) else "selfhosted"

        kwargs: Dict[str, Any] = {"mode": mode}

        if maas.get("api_key"):
            kwargs["api_key"] = maas["api_key"]
        if maas.get("api_url"):
            kwargs["api_url"] = maas["api_url"]
        if maas.get("model"):
            kwargs["model"] = maas["model"]
        if maas.get("request_timeout"):
            kwargs["timeout"] = maas["request_timeout"]

        if mode == "selfhosted":
            if ocr_api.get("api_host"):
                kwargs["ocr_api_host"] = ocr_api["api_host"]
            if ocr_api.get("api_port"):
                kwargs["ocr_api_port"] = ocr_api["api_port"]

        if logging_cfg.get("level"):
            kwargs["log_level"] = logging_cfg["level"]

        return kwargs

    def get_pipeline_overrides(self) -> Dict[str, Any]:
        """Return dotted overrides for pipeline-specific settings."""
        overrides = {}
        # Pass through pipeline config settings that GlmOcr accepts via _dotted
        mappings = [
            ("pipeline.page_loader.pdf_dpi", "pipeline.page_loader.pdf_dpi"),
            ("pipeline.layout.threshold", "pipeline.layout.threshold"),
            ("pipeline.max_workers", "pipeline.max_workers"),
            ("pipeline.ocr_api.model", "pipeline.ocr_api.model"),
            ("pipeline.ocr_api.api_path", "pipeline.ocr_api.api_path"),
            ("pipeline.ocr_api.verify_ssl", "pipeline.ocr_api.verify_ssl"),
            ("pipeline.result_formatter.enable_merge_formula_numbers",
             "pipeline.result_formatter.enable_merge_formula_numbers"),
            ("pipeline.result_formatter.enable_merge_text_blocks",
             "pipeline.result_formatter.enable_merge_text_blocks"),
            ("pipeline.result_formatter.enable_format_bullet_points",
             "pipeline.result_formatter.enable_format_bullet_points"),
        ]
        for src, dst in mappings:
            val = _get_nested(self._data, src)
            if val is not None:
                overrides[dst] = val
        return overrides
