"""Main TUI application."""

from __future__ import annotations

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Vertical

from tui.config_manager import ConfigManager
from tui.models import (
    FileSelected,
    PipelineComplete,
    PipelineError,
    PipelinePreviewUpdate,
    PipelineProgressUpdate,
    PipelineStageUpdate,
    SettingChanged,
)
from tui.pipeline_runner import PipelineRunner
from tui.widgets.file_picker import FilePicker
from tui.widgets.log_panel import LogPanel
from tui.widgets.output_preview import OutputPreview
from tui.widgets.pipeline_diagram import PipelineDiagram
from tui.widgets.progress_panel import ProgressPanel
from tui.widgets.settings_panel import SettingsPanel
from tui.widgets.status_bar import StatusBar


class OcrTuiApp(App):
    """GLM-OCR Terminal UI."""

    TITLE = "GLM-OCR Pipeline"

    CSS = """
    Screen {
        layout: vertical;
    }
    #main-area {
        height: 1fr;
    }
    """

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("o", "focus_file", "Open", show=True),
        Binding("r", "run_pipeline", "Run", show=True),
        Binding("s", "toggle_settings", "Settings", show=True),
        Binding("l", "toggle_logs", "Logs", show=True),
        Binding("escape", "cancel", "Cancel"),
    ]

    def __init__(
        self,
        file_path: str = "",
        config_path: str | None = None,
    ) -> None:
        super().__init__()
        self._file_path = file_path
        self._config = ConfigManager(config_path)
        self._runner = PipelineRunner(self, self._config)

    def compose(self) -> ComposeResult:
        yield PipelineDiagram(id="diagram")
        yield FilePicker(initial_path=self._file_path, id="file-picker")
        yield ProgressPanel(id="progress")
        with Vertical(id="main-area"):
            yield OutputPreview(id="output")
        yield LogPanel(id="log-panel")
        yield SettingsPanel(self._config, id="settings")
        yield StatusBar(id="status-bar")

    def on_mount(self) -> None:
        # Set initial mode display
        is_maas = self._config.get("pipeline.maas.enabled", True)
        self.query_one("#status-bar", StatusBar).set_mode(
            "MaaS" if is_maas else "Self-hosted"
        )
        # Hide log panel by default
        self.query_one("#log-panel").display = False
        # Install log handler
        self.query_one("#log-panel", LogPanel).install_handler("glmocr")
        # If file was passed via CLI, set it
        if self._file_path:
            self.query_one("#status-bar", StatusBar).set_file(self._file_path)

    # ------------------------------------------------------------------
    # Key actions
    # ------------------------------------------------------------------

    def action_focus_file(self) -> None:
        inp = self.query_one("#file-input")
        inp.focus()

    def action_run_pipeline(self) -> None:
        picker = self.query_one("#file-picker", FilePicker)
        path = picker.get_path()
        if path:
            self.post_message(FileSelected(path))
        else:
            self.notify("No file selected. Press [O] to open.", severity="warning")

    def action_toggle_settings(self) -> None:
        panel = self.query_one("#settings", SettingsPanel)
        panel.display = not panel.display

    def action_toggle_logs(self) -> None:
        panel = self.query_one("#log-panel", LogPanel)
        panel.display = not panel.display

    def action_cancel(self) -> None:
        if self._runner.is_running:
            self._runner.cancel()
            self.notify("Cancelling...")
        else:
            # Close settings/logs if open
            settings = self.query_one("#settings", SettingsPanel)
            logs = self.query_one("#log-panel", LogPanel)
            if settings.display:
                settings.display = False
            elif logs.display:
                logs.display = False

    # ------------------------------------------------------------------
    # Message handlers
    # ------------------------------------------------------------------

    def on_file_selected(self, event: FileSelected) -> None:
        self._file_path = event.path
        self.query_one("#status-bar", StatusBar).set_file(event.path)
        self.query_one("#status-bar", StatusBar).set_status("Running...")
        self.query_one("#progress", ProgressPanel).reset()
        self._runner.start(event.path)

    def on_pipeline_stage_update(self, event: PipelineStageUpdate) -> None:
        self.query_one("#diagram", PipelineDiagram).update_stages(event.stages)

    def on_pipeline_progress_update(self, event: PipelineProgressUpdate) -> None:
        self.query_one("#progress", ProgressPanel).update_progress(event.progress)

    def on_pipeline_preview_update(self, event: PipelinePreviewUpdate) -> None:
        self.query_one("#output", OutputPreview).set_markdown(event.markdown)

    def on_pipeline_complete(self, event: PipelineComplete) -> None:
        self.query_one("#output", OutputPreview).set_markdown(event.markdown)
        self.query_one("#output", OutputPreview).set_output_path(event.output_path)
        self.query_one("#progress", ProgressPanel).set_complete(
            f"Saved: {event.output_path}"
        )
        self.query_one("#status-bar", StatusBar).set_status("Complete")
        self.query_one("#log-panel", LogPanel).write_log(
            f"Output saved to {event.output_path}"
        )
        self.notify(f"Done! Saved to {event.output_path}")

    def on_pipeline_error(self, event: PipelineError) -> None:
        self.query_one("#progress", ProgressPanel).set_error(event.error)
        self.query_one("#status-bar", StatusBar).set_status("Error")
        self.query_one("#log-panel", LogPanel).write_log(event.error, level="ERROR")
        self.notify(f"Error: {event.error}", severity="error")

    def on_setting_changed(self, event: SettingChanged) -> None:
        if event.key == "pipeline.maas.enabled":
            mode = "MaaS" if event.value else "Self-hosted"
            self.query_one("#status-bar", StatusBar).set_mode(mode)
