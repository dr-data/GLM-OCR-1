"""ASCII pipeline diagram widget."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from tui.models import StageState, StageStatus

# Status indicators and colors
_STATUS_ICONS = {
    StageStatus.IDLE: ("○", "dim"),
    StageStatus.RUNNING: ("◉", "cyan bold"),
    StageStatus.DONE: ("●", "green"),
    StageStatus.ERROR: ("✗", "red bold"),
}

_BOX_COLORS = {
    StageStatus.IDLE: "dim",
    StageStatus.RUNNING: "cyan",
    StageStatus.DONE: "green",
    StageStatus.ERROR: "red",
}


def _default_stages() -> list[StageState]:
    return [
        StageState("PDF Input"),
        StageState("Layout"),
        StageState("OCR"),
        StageState("Markdown"),
    ]


class PipelineDiagram(Static):
    """Renders an ASCII box-drawing pipeline visualization."""

    DEFAULT_CSS = """
    PipelineDiagram {
        height: 6;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._stages = _default_stages()

    def update_stages(self, stages: list[StageState]) -> None:
        self._stages = stages
        self._render_diagram()

    def on_mount(self) -> None:
        self._render_diagram()

    def _render_diagram(self) -> None:
        text = Text()
        box_w = 14
        stages = self._stages

        # Top border
        for i, stage in enumerate(stages):
            color = _BOX_COLORS[stage.status]
            text.append("┌" + "─" * box_w + "┐", style=color)
            if i < len(stages) - 1:
                text.append("───", style="dim")
        text.append("\n")

        # Name row
        for i, stage in enumerate(stages):
            color = _BOX_COLORS[stage.status]
            name = stage.name[:box_w].center(box_w)
            text.append("│", style=color)
            text.append(name, style="bold")
            text.append("│", style=color)
            if i < len(stages) - 1:
                text.append("──▶", style="cyan" if stage.status == StageStatus.DONE else "dim")
        text.append("\n")

        # Status row
        for i, stage in enumerate(stages):
            color = _BOX_COLORS[stage.status]
            icon, icon_style = _STATUS_ICONS[stage.status]
            label = stage.status.value
            cell = f" {icon} {label}"
            cell = cell[:box_w].ljust(box_w)
            text.append("│", style=color)
            text.append(cell, style=icon_style)
            text.append("│", style=color)
            if i < len(stages) - 1:
                text.append("   ", style="dim")
        text.append("\n")

        # Detail row
        for i, stage in enumerate(stages):
            color = _BOX_COLORS[stage.status]
            detail = (stage.detail or "")[:box_w].center(box_w)
            text.append("│", style=color)
            text.append(detail, style="dim italic")
            text.append("│", style=color)
            if i < len(stages) - 1:
                text.append("   ", style="dim")
        text.append("\n")

        # Bottom border
        for i, stage in enumerate(stages):
            color = _BOX_COLORS[stage.status]
            text.append("└" + "─" * box_w + "┘", style=color)
            if i < len(stages) - 1:
                text.append("   ", style="dim")

        self.update(text)
