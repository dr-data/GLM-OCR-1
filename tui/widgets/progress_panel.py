"""Progress bar and counters widget."""

from __future__ import annotations

import time

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import ProgressBar, Static
from textual.widget import Widget

from tui.models import PipelineProgress


class ProgressPanel(Widget):
    """Displays progress bar with page/region counters."""

    DEFAULT_CSS = """
    ProgressPanel {
        height: 3;
        padding: 0 1;
    }
    ProgressPanel > Horizontal {
        height: 1;
    }
    ProgressPanel > ProgressBar {
        width: 1fr;
    }
    ProgressPanel > #stats-line {
        height: 1;
        color: $text-muted;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._start_time: float | None = None

    def compose(self) -> ComposeResult:
        yield ProgressBar(total=100, show_eta=False, id="pbar")
        yield Static("Ready", id="stats-line")

    def reset(self) -> None:
        self._start_time = time.monotonic()
        bar = self.query_one("#pbar", ProgressBar)
        bar.update(progress=0, total=100)
        self.query_one("#stats-line", Static).update("Starting...")

    def update_progress(self, progress: PipelineProgress) -> None:
        pct = progress.percent
        bar = self.query_one("#pbar", ProgressBar)
        bar.update(progress=pct, total=100)

        elapsed = ""
        if self._start_time:
            secs = int(time.monotonic() - self._start_time)
            m, s = divmod(secs, 60)
            elapsed = f"  Elapsed: {m:02d}:{s:02d}"

        stats = (
            f"Pages: {progress.pages_done}/{progress.pages_total}  "
            f"Regions: {progress.regions_done}/{progress.regions_total}"
            f"{elapsed}"
        )
        self.query_one("#stats-line", Static).update(stats)

    def set_complete(self, message: str = "Done") -> None:
        bar = self.query_one("#pbar", ProgressBar)
        bar.update(progress=100, total=100)

        elapsed = ""
        if self._start_time:
            secs = int(time.monotonic() - self._start_time)
            m, s = divmod(secs, 60)
            elapsed = f"  ({m:02d}:{s:02d})"

        self.query_one("#stats-line", Static).update(f"{message}{elapsed}")

    def set_error(self, message: str) -> None:
        self.query_one("#stats-line", Static).update(f"[red]{message}[/red]")
