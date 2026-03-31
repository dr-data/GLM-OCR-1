"""Settings panel widget - config form sidebar."""

from __future__ import annotations

from typing import Any

from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.widgets import Button, Input, Label, Select, Static, Switch
from textual.widget import Widget

from tui.config_manager import ConfigManager, GUI_SETTINGS
from tui.models import SettingChanged


class SettingsPanel(Widget):
    """Collapsible settings sidebar with config form fields."""

    DEFAULT_CSS = """
    SettingsPanel {
        dock: right;
        width: 42;
        border-left: solid $surface-lighten-2;
        display: none;
        padding: 1;
        overflow-y: auto;
    }
    SettingsPanel > Static.section-header {
        padding: 1 0 0 0;
        text-style: bold;
        color: $text;
    }
    SettingsPanel > Label {
        padding: 0 0 0 0;
        color: $text-muted;
    }
    SettingsPanel .setting-row {
        height: auto;
        padding: 0 0 1 0;
    }
    SettingsPanel > #settings-footer {
        height: auto;
        padding: 1 0;
    }
    SettingsPanel > #settings-footer > Button {
        margin: 0 1 0 0;
    }
    """

    def __init__(self, config_manager: ConfigManager, **kwargs) -> None:
        super().__init__(**kwargs)
        self._config = config_manager

    def compose(self) -> ComposeResult:
        yield Static("Settings", classes="section-header")
        yield Static("─" * 38)

        values = self._config.get_gui_values()

        # Mode
        is_maas = values.get("pipeline.maas.enabled", True)
        yield Label("Mode")
        yield Select(
            [("MaaS (Cloud)", "maas"), ("Self-hosted", "selfhosted")],
            value="maas" if is_maas else "selfhosted",
            id="setting-mode",
        )

        # MaaS settings
        yield Static("── MaaS ──", classes="section-header")
        yield Label("API Key")
        yield Input(
            value=str(values.get("pipeline.maas.api_key", "") or ""),
            placeholder="sk-xxx or ZHIPU_API_KEY env",
            password=True,
            id="setting-api-key",
        )
        yield Label("API URL")
        yield Input(
            value=str(values.get("pipeline.maas.api_url", "")),
            id="setting-api-url",
        )

        # Self-hosted settings
        yield Static("── Self-hosted ──", classes="section-header")
        yield Label("Host")
        yield Input(
            value=str(values.get("pipeline.ocr_api.api_host", "127.0.0.1")),
            id="setting-host",
        )
        yield Label("Port")
        yield Input(
            value=str(values.get("pipeline.ocr_api.api_port", 8080)),
            id="setting-port",
        )

        # Processing
        yield Static("── Processing ──", classes="section-header")
        yield Label("Output Dir")
        yield Input(
            value=str(values.get("tui.output_dir", "./output")),
            id="setting-output-dir",
        )
        yield Label("PDF DPI")
        yield Input(
            value=str(values.get("pipeline.page_loader.pdf_dpi", 200)),
            id="setting-dpi",
        )
        yield Label("Max Workers")
        yield Input(
            value=str(values.get("pipeline.max_workers", 16)),
            id="setting-workers",
        )
        yield Label("Layout Threshold")
        yield Input(
            value=str(values.get("pipeline.layout.threshold", 0.3)),
            id="setting-threshold",
        )

        # Post-processing toggles
        yield Static("── Post-processing ──", classes="section-header")

        yield Switch(
            value=bool(values.get("pipeline.result_formatter.enable_merge_formula_numbers", True)),
            id="setting-merge-formulas",
        )
        yield Label("Merge formula numbers")

        yield Switch(
            value=bool(values.get("pipeline.result_formatter.enable_merge_text_blocks", True)),
            id="setting-merge-text",
        )
        yield Label("Merge text blocks")

        yield Switch(
            value=bool(values.get("pipeline.result_formatter.enable_format_bullet_points", True)),
            id="setting-bullets",
        )
        yield Label("Format bullet points")

        yield Switch(
            value=bool(values.get("tui.convert_html_tables", True)),
            id="setting-table-convert",
        )
        yield Label("HTML tables -> MD tables")

        # Log level
        yield Static("── Logging ──", classes="section-header")
        yield Label("Log Level")
        yield Select(
            [("DEBUG", "DEBUG"), ("INFO", "INFO"), ("WARNING", "WARNING"), ("ERROR", "ERROR")],
            value=str(values.get("logging.level", "INFO")),
            id="setting-log-level",
        )

        # Footer buttons
        yield Static("")
        yield Static(f"Config: {self._config.config_path}", classes="section-header")

    # Map widget IDs to config paths
    _WIDGET_MAP = {
        "setting-api-key": ("pipeline.maas.api_key", "str"),
        "setting-api-url": ("pipeline.maas.api_url", "str"),
        "setting-host": ("pipeline.ocr_api.api_host", "str"),
        "setting-port": ("pipeline.ocr_api.api_port", "int"),
        "setting-output-dir": ("tui.output_dir", "str"),
        "setting-dpi": ("pipeline.page_loader.pdf_dpi", "int"),
        "setting-workers": ("pipeline.max_workers", "int"),
        "setting-threshold": ("pipeline.layout.threshold", "float"),
        "setting-merge-formulas": ("pipeline.result_formatter.enable_merge_formula_numbers", "bool"),
        "setting-merge-text": ("pipeline.result_formatter.enable_merge_text_blocks", "bool"),
        "setting-bullets": ("pipeline.result_formatter.enable_format_bullet_points", "bool"),
        "setting-table-convert": ("tui.convert_html_tables", "bool"),
    }

    def on_input_changed(self, event: Input.Changed) -> None:
        widget_id = event.input.id
        if widget_id and widget_id in self._WIDGET_MAP:
            path, type_hint = self._WIDGET_MAP[widget_id]
            value = self._coerce(event.value, type_hint)
            if value is not None:
                self._config.update_setting(path, value)
                self.post_message(SettingChanged(path, value))

    def on_switch_changed(self, event: Switch.Changed) -> None:
        widget_id = event.switch.id
        if widget_id and widget_id in self._WIDGET_MAP:
            path, _ = self._WIDGET_MAP[widget_id]
            self._config.update_setting(path, event.value)
            self.post_message(SettingChanged(path, event.value))

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "setting-mode":
            is_maas = event.value == "maas"
            self._config.update_setting("pipeline.maas.enabled", is_maas)
            self.post_message(SettingChanged("pipeline.maas.enabled", is_maas))
        elif event.select.id == "setting-log-level":
            self._config.update_setting("logging.level", str(event.value))
            self.post_message(SettingChanged("logging.level", str(event.value)))

    @staticmethod
    def _coerce(raw: str, type_hint: str) -> Any:
        raw = raw.strip()
        if not raw:
            return None
        try:
            if type_hint == "int":
                return int(raw)
            elif type_hint == "float":
                return float(raw)
            return raw
        except (ValueError, TypeError):
            return None
