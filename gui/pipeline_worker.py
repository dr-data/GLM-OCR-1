"""Async pipeline worker for the web GUI."""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Ensure project root is importable.
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ocr_to_markdown import convert_html_tables_in_markdown  # noqa: E402
from tui.config_manager import ConfigManager  # noqa: E402


@dataclass
class TaskState:
    """Mutable state object shared between the worker and SSE endpoint."""

    task_id: str
    filename: str
    file_path: str
    status: str = "pending"          # pending|loading|processing|saving|done|error
    stage: str = "idle"              # idle|pdf_input|layout|ocr|markdown
    stage_detail: str = ""
    pages_total: int = 0
    pages_done: int = 0
    regions_total: int = 0
    regions_done: int = 0
    markdown: str = ""
    regions_breakdown: str = ""      # e.g. "text:15 table:3 formula:2"
    json_data: str = ""              # JSON-serialized region data for highlight sync
    output_path: str = ""
    error: str = ""
    version: int = 0                 # bumped on every mutation for SSE change detection

    def _bump(self) -> None:
        """Increment the version counter."""
        self.version += 1

    def to_json(self) -> str:
        """Serialise current state to a JSON string."""
        return json.dumps(
            {
                "task_id": self.task_id,
                "filename": self.filename,
                "status": self.status,
                "stage": self.stage,
                "stage_detail": self.stage_detail,
                "pages_total": self.pages_total,
                "pages_done": self.pages_done,
                "regions_total": self.regions_total,
                "regions_done": self.regions_done,
                "markdown": self.markdown,
                "regions_breakdown": self.regions_breakdown,
                "output_path": self.output_path,
                "error": self.error,
                "version": self.version,
            }
        )


class PipelineWorker:
    """Runs the GLM-OCR pipeline in a background thread."""

    def __init__(self, config: ConfigManager) -> None:
        self._config = config

    async def run(self, state: TaskState) -> None:
        """Public async entry-point — offloads to a thread."""
        await asyncio.to_thread(self._run_sync, state)

    @staticmethod
    def _probe_server_port(configured_port: int | None = None) -> int | None:
        """Try the configured port first, then common fallbacks."""
        import urllib.request
        candidates = [8090, 8080, 8091, 9090]
        if configured_port and configured_port not in candidates:
            candidates.insert(0, configured_port)
        elif configured_port:
            candidates.remove(configured_port)
            candidates.insert(0, configured_port)
        for port in candidates:
            try:
                req = urllib.request.Request(
                    f"http://localhost:{port}/v1/models", method="GET"
                )
                with urllib.request.urlopen(req, timeout=2):
                    return port
            except Exception:
                continue
        return None

    def _run_sync(self, state: TaskState) -> None:
        """Synchronous pipeline execution with auto-retry."""
        from glmocr.api import GlmOcr

        convert_tables = self._config.get_tui_setting("convert_html_tables", True)
        output_dir = self._config.get_tui_setting("output_dir", "./output")

        # --- Stage: loading ---
        state.status = "loading"
        state.stage = "pdf_input"
        state.stage_detail = "Initialising SDK…"
        state._bump()

        sdk_kwargs = self._config.get_sdk_kwargs()
        overrides = self._config.get_pipeline_overrides()
        if overrides:
            sdk_kwargs["_dotted"] = overrides

        mode = sdk_kwargs.get("mode", "maas")
        model = overrides.get("pipeline.ocr_api.model", "") if overrides else ""

        # --- Init with retry: if connection fails, probe for the server ---
        parser = None
        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                state.stage_detail = f"Initialising SDK ({mode} mode)…"
                if attempt > 0:
                    state.stage_detail += f" (retry {attempt}/{max_retries})"
                state._bump()
                parser = GlmOcr(**sdk_kwargs)
                break
            except (TimeoutError, ConnectionError, OSError) as exc:
                if attempt < max_retries and mode == "selfhosted":
                    # Try to auto-detect the correct port
                    state.stage_detail = "Connection failed, probing for server…"
                    state._bump()
                    configured_port = sdk_kwargs.get("ocr_api_port")
                    found_port = self._probe_server_port(configured_port)
                    if found_port:
                        sdk_kwargs["ocr_api_port"] = found_port
                        if overrides:
                            overrides.pop("pipeline.ocr_api.api_port", None)
                        state.stage_detail = f"Found server on port {found_port}, retrying…"
                        state._bump()
                        continue
                state.status = "error"
                state.error = f"Failed to initialise: {exc}"
                state._bump()
                return
            except Exception as exc:
                state.status = "error"
                state.error = f"Failed to initialise: {exc}"
                state._bump()
                return

        if parser is None:
            state.status = "error"
            state.error = "Failed to initialise after retries"
            state._bump()
            return

        stop_monitor = threading.Event()

        try:
            # Optional queue-stats monitor for self-hosted mode.
            use_maas = self._config.get("pipeline.maas.enabled", True)
            if not use_maas:
                monitor = threading.Thread(
                    target=self._monitor_progress,
                    args=(parser, state, stop_monitor),
                    daemon=True,
                )
                monitor.start()

            # --- Stage: processing (layout + ocr) ---
            state.status = "processing"
            state.stage = "pdf_input"
            state.stage_detail = f"Loading PDF: {Path(state.file_path).name}"
            state._bump()

            state.stage = "layout"
            state.stage_detail = "Running layout detection (PP-DocLayoutV3)…"
            state._bump()

            all_markdown: list[str] = []
            chunk_count = 0

            for result in parser.parse(state.file_path, stream=True):
                chunk_count += 1
                md = result.markdown_result or ""
                if convert_tables:
                    md = convert_html_tables_in_markdown(md)
                all_markdown.append(md)

                state.stage = "ocr"
                state.stage_detail = f"OCR complete for chunk {chunk_count}"
                if model:
                    state.stage_detail += f" (model: {model})"
                state.markdown = "\n\n---\n\n".join(all_markdown)
                state._bump()

            # Store JSON result for region highlight API
            try:
                if result and hasattr(result, 'json_result') and result.json_result:
                    import json as _json
                    state.json_data = _json.dumps(result.json_result, ensure_ascii=False)
            except Exception:
                pass

            # --- Stage: saving ---
            state.status = "saving"
            state.stage = "markdown"
            state.stage_detail = f"Writing output files ({chunk_count} chunks)…"
            state._bump()

            final_md = "\n\n---\n\n".join(all_markdown)
            stem = Path(state.file_path).stem
            out_dir = Path(output_dir) / stem
            out_dir.mkdir(parents=True, exist_ok=True)
            md_path = out_dir / f"{stem}.md"
            md_path.write_text(final_md, encoding="utf-8")

            try:
                result.save(output_dir=output_dir, save_layout_visualization=False)
            except Exception:
                pass  # non-critical

            # --- Done ---
            state.markdown = final_md
            state.output_path = str(md_path)
            state.status = "done"
            lines = len(final_md.splitlines())
            state.stage_detail = f"Complete — {lines} lines, saved to {md_path.name}"
            state._bump()

        except Exception as exc:
            state.status = "error"
            state.error = str(exc)
            state._bump()
        finally:
            stop_monitor.set()
            try:
                parser.close()
            except Exception:
                pass

    @staticmethod
    def _monitor_progress(
        parser: object,
        state: TaskState,
        stop: threading.Event,
    ) -> None:
        """Poll queue stats every 300 ms (self-hosted mode only)."""
        while not stop.wait(0.3):
            stats = parser.get_queue_stats()  # type: ignore[attr-defined]
            if stats:
                pages_loaded = stats.get("pages_loaded", 0)
                pages_in_queue = stats.get("page_queue_size", 0)
                state.pages_total = pages_loaded
                state.pages_done = max(0, pages_loaded - pages_in_queue)
                regions_enqueued = stats.get("regions_enqueued", 0)
                regions_in_queue = stats.get("region_queue_size", 0)
                state.regions_total = regions_enqueued
                state.regions_done = max(0, regions_enqueued - regions_in_queue)
                # Build region breakdown string
                by_label = stats.get("regions_by_label", {})
                if by_label:
                    parts = []
                    for lbl in ("text", "table", "formula", "skip"):
                        if lbl in by_label:
                            parts.append(f"{lbl}:{by_label[lbl]}")
                    state.regions_breakdown = " ".join(parts)
                state._bump()
