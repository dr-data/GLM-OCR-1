"""File input selector widget."""

from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Button, Input, Static
from textual.widget import Widget

from tui.models import FileSelected

_SUPPORTED = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}


class FilePicker(Widget):
    """File path input with validation."""

    DEFAULT_CSS = """
    FilePicker {
        height: 3;
        padding: 0 1;
        layout: horizontal;
    }
    FilePicker > Static {
        width: 7;
        padding: 1 0 0 0;
    }
    FilePicker > Input {
        width: 1fr;
    }
    FilePicker > Button {
        width: 12;
        min-width: 12;
    }
    """

    def __init__(self, initial_path: str = "", **kwargs) -> None:
        super().__init__(**kwargs)
        self._initial = initial_path

    def compose(self) -> ComposeResult:
        yield Static(" File: ")
        yield Input(
            value=self._initial,
            placeholder="Path to PDF or image file...",
            id="file-input",
        )
        yield Button("Run [R]", variant="success", id="run-btn")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._validate_and_select(event.value)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-btn":
            inp = self.query_one("#file-input", Input)
            self._validate_and_select(inp.value)

    def set_path(self, path: str) -> None:
        inp = self.query_one("#file-input", Input)
        inp.value = path

    def get_path(self) -> str:
        return self.query_one("#file-input", Input).value.strip()

    def _validate_and_select(self, raw: str) -> None:
        path = raw.strip()
        if not path:
            self.notify("No file specified", severity="warning")
            return
        p = Path(path).expanduser()
        if not p.exists():
            self.notify(f"File not found: {path}", severity="error")
            return
        if p.is_file() and p.suffix.lower() not in _SUPPORTED:
            self.notify(
                f"Unsupported format: {p.suffix} (use PDF/PNG/JPG)",
                severity="error",
            )
            return
        self.post_message(FileSelected(str(p.resolve())))
