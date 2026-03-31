"""Scrollable log viewer widget."""

from __future__ import annotations

import logging
from datetime import datetime

from textual.widgets import RichLog
from textual.widget import Widget
from textual.app import ComposeResult


class TuiLogHandler(logging.Handler):
    """Python logging handler that writes to the TUI log panel."""

    def __init__(self, log_panel: LogPanel) -> None:
        super().__init__()
        self._panel = log_panel

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            self._panel.write_log(msg, level=record.levelname)
        except Exception:
            pass


class LogPanel(Widget):
    """Scrollable log viewer with level-based coloring."""

    DEFAULT_CSS = """
    LogPanel {
        height: 10;
        border-top: solid $surface-lighten-2;
    }
    LogPanel > RichLog {
        height: 1fr;
    }
    """

    _LEVEL_STYLES = {
        "DEBUG": "dim",
        "INFO": "",
        "WARNING": "yellow",
        "ERROR": "red bold",
        "CRITICAL": "red bold reverse",
    }

    def compose(self) -> ComposeResult:
        yield RichLog(highlight=True, markup=True, wrap=True, id="log-view")

    def write_log(self, message: str, level: str = "INFO") -> None:
        log_view = self.query_one("#log-view", RichLog)
        ts = datetime.now().strftime("%H:%M:%S")
        style = self._LEVEL_STYLES.get(level, "")
        if style:
            log_view.write(f"[{style}]{ts} [{level:>7s}] {message}[/{style}]")
        else:
            log_view.write(f"{ts} [{level:>7s}] {message}")

    def install_handler(self, logger_name: str = "glmocr") -> TuiLogHandler:
        """Install a logging handler that routes to this panel."""
        handler = TuiLogHandler(self)
        handler.setFormatter(logging.Formatter("%(message)s"))
        target_logger = logging.getLogger(logger_name)
        target_logger.addHandler(handler)
        return handler
