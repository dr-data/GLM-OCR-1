"""Background OCR pipeline runner for the TUI."""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path
from typing import Optional

from textual.app import App
from textual.worker import Worker, WorkerState

from tui.config_manager import ConfigManager
from tui.models import (
    PipelineComplete,
    PipelineError,
    PipelinePreviewUpdate,
    PipelineProgressUpdate,
    PipelineProgress,
    PipelineStageUpdate,
    StageState,
    StageStatus,
)

# Add project root to path for ocr_to_markdown import
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from ocr_to_markdown import convert_html_tables_in_markdown  # noqa: E402


def _make_stages(
    loading: StageStatus = StageStatus.IDLE,
    layout: StageStatus = StageStatus.IDLE,
    ocr: StageStatus = StageStatus.IDLE,
    output: StageStatus = StageStatus.IDLE,
    **details: str,
) -> list[StageState]:
    """Build the 4-stage state list."""
    return [
        StageState("PDF Input", loading, details.get("loading", "")),
        StageState("Layout", layout, details.get("layout", "")),
        StageState("OCR", ocr, details.get("ocr", "")),
        StageState("Markdown", output, details.get("output", "")),
    ]


class PipelineRunner:
    """Runs OCR in a background Textual worker thread."""

    def __init__(self, app: App, config_manager: ConfigManager) -> None:
        self._app = app
        self._config = config_manager
        self._cancel_event = threading.Event()
        self._worker: Optional[Worker] = None

    @property
    def is_running(self) -> bool:
        return self._worker is not None and self._worker.state == WorkerState.RUNNING

    def start(self, file_path: str) -> None:
        """Launch the pipeline in a background worker."""
        if self.is_running:
            return
        self._cancel_event.clear()
        self._worker = self._app.run_worker(
            self._run(file_path),
            name="ocr_pipeline",
            exclusive=True,
        )

    def cancel(self) -> None:
        """Request cancellation of the running pipeline."""
        self._cancel_event.set()
        if self._worker is not None:
            self._worker.cancel()

    async def _run(self, file_path: str) -> None:
        """Pipeline execution (runs in worker thread via Textual)."""
        from glmocr.api import GlmOcr

        convert_tables = self._config.get_tui_setting("convert_html_tables", True)
        output_dir = self._config.get_tui_setting("output_dir", "./output")

        # Stage: Loading
        self._post_stages(loading=StageStatus.RUNNING)

        sdk_kwargs = self._config.get_sdk_kwargs()
        overrides = self._config.get_pipeline_overrides()
        if overrides:
            sdk_kwargs["_dotted"] = overrides

        try:
            parser = GlmOcr(**sdk_kwargs)
        except Exception as e:
            self._app.post_message(PipelineError(f"Failed to initialize: {e}"))
            self._post_stages(loading=StageStatus.ERROR)
            return

        stop_monitor = threading.Event()

        try:
            # Start queue stats monitor for self-hosted mode
            use_maas = self._config.get("pipeline.maas.enabled", True)
            if not use_maas:
                monitor = threading.Thread(
                    target=self._monitor_progress,
                    args=(parser, stop_monitor),
                    daemon=True,
                )
                monitor.start()

            self._post_stages(
                loading=StageStatus.DONE,
                layout=StageStatus.RUNNING,
                ocr=StageStatus.RUNNING,
            )

            # Run pipeline with streaming
            all_markdown: list[str] = []
            file_count = 0

            for result in parser.parse(file_path, stream=True):
                if self._cancel_event.is_set():
                    break

                md = result.markdown_result or ""
                if convert_tables:
                    md = convert_html_tables_in_markdown(md)
                all_markdown.append(md)
                file_count += 1

                # Post preview update
                self._app.post_message(
                    PipelinePreviewUpdate("\n\n---\n\n".join(all_markdown))
                )

            if self._cancel_event.is_set():
                self._post_stages(
                    loading=StageStatus.DONE,
                    layout=StageStatus.ERROR,
                    ocr=StageStatus.ERROR,
                )
                self._app.post_message(PipelineError("Cancelled by user"))
                return

            # Stage: Output
            self._post_stages(
                loading=StageStatus.DONE,
                layout=StageStatus.DONE,
                ocr=StageStatus.DONE,
                output=StageStatus.RUNNING,
            )

            # Save result
            final_md = "\n\n---\n\n".join(all_markdown)
            stem = Path(file_path).stem
            out_dir = Path(output_dir) / stem
            out_dir.mkdir(parents=True, exist_ok=True)
            md_path = out_dir / f"{stem}.md"
            md_path.write_text(final_md, encoding="utf-8")

            # Also save via SDK for images/json
            try:
                result.save(output_dir=output_dir, save_layout_visualization=False)
            except Exception:
                pass  # Non-critical if save fails

            self._post_stages(
                loading=StageStatus.DONE,
                layout=StageStatus.DONE,
                ocr=StageStatus.DONE,
                output=StageStatus.DONE,
            )

            self._app.post_message(PipelineComplete(final_md, str(md_path)))

        except Exception as e:
            self._post_stages(
                loading=StageStatus.DONE,
                layout=StageStatus.ERROR,
                ocr=StageStatus.ERROR,
            )
            self._app.post_message(PipelineError(str(e)))
        finally:
            stop_monitor.set()
            try:
                parser.close()
            except Exception:
                pass

    def _monitor_progress(
        self, parser: object, stop: threading.Event
    ) -> None:
        """Poll queue stats every 300ms (self-hosted mode)."""
        while not stop.wait(0.3):
            stats = parser.get_queue_stats()  # type: ignore[attr-defined]
            if stats:
                progress = PipelineProgress(
                    stage="ocr",
                    pages_total=stats.get("page_queue_maxsize", 0),
                    pages_done=stats.get("page_queue_maxsize", 0)
                    - stats.get("page_queue_size", 0),
                    regions_total=stats.get("region_queue_maxsize", 0),
                    regions_done=stats.get("region_queue_maxsize", 0)
                    - stats.get("region_queue_size", 0),
                )
                self._app.post_message(PipelineProgressUpdate(progress))

    def _post_stages(self, **statuses: StageStatus) -> None:
        """Post a stage update message."""
        self._app.post_message(PipelineStageUpdate(_make_stages(**statuses)))
