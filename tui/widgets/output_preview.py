"""Scrollable markdown output preview widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown, Static, Button
from textual.containers import Horizontal
from textual.widget import Widget


class OutputPreview(Widget):
    """Displays the OCR markdown output with copy/save buttons."""

    DEFAULT_CSS = """
    OutputPreview {
        height: 1fr;
        border: solid $surface-lighten-2;
    }
    OutputPreview > #preview-header {
        height: 1;
        padding: 0 1;
        background: $surface;
    }
    OutputPreview > #md-view {
        height: 1fr;
        overflow-y: auto;
        padding: 0 1;
    }
    OutputPreview > #preview-header > Static {
        width: 1fr;
    }
    OutputPreview > #preview-header > Button {
        min-width: 8;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._markdown = ""
        self._output_path = ""

    def compose(self) -> ComposeResult:
        with Horizontal(id="preview-header"):
            yield Static(" Output Preview")
            yield Button("Copy", variant="default", id="copy-btn")
        yield Markdown("*No output yet*", id="md-view")

    def set_markdown(self, md: str) -> None:
        self._markdown = md
        viewer = self.query_one("#md-view", Markdown)
        viewer.update(md if md else "*No output yet*")

    def set_output_path(self, path: str) -> None:
        self._output_path = path

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "copy-btn":
            if self._markdown:
                import pyperclip  # noqa: delay import, optional dep
                try:
                    pyperclip.copy(self._markdown)
                    self.notify("Copied to clipboard")
                except Exception:
                    self.notify("Copy failed (install pyperclip)", severity="warning")
            else:
                self.notify("Nothing to copy", severity="warning")
