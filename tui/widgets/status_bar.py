"""Bottom status bar widget."""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Shows mode, current file, and keyboard shortcuts."""

    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $surface;
        color: $text;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._mode = "MaaS"
        self._file = ""
        self._status = ""

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self._refresh_content()

    def set_file(self, path: str) -> None:
        self._file = path
        self._refresh_content()

    def set_status(self, status: str) -> None:
        self._status = status
        self._refresh_content()

    def on_mount(self) -> None:
        self._refresh_content()

    def _refresh_content(self) -> None:
        parts = [f"Mode: {self._mode}"]
        if self._file:
            from pathlib import Path
            parts.append(f"File: {Path(self._file).name}")
        if self._status:
            parts.append(self._status)
        parts.append("[Q]uit [O]pen [R]un [S]ettings [L]ogs")
        self.update(" │ ".join(parts))
