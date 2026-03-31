"""Shared data models and Textual messages for the TUI."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from textual.message import Message


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class StageStatus(Enum):
    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StageState:
    """State of a single pipeline stage."""
    name: str
    status: StageStatus = StageStatus.IDLE
    detail: str = ""


@dataclass
class PipelineProgress:
    """Progress snapshot from the running pipeline."""
    stage: str = ""
    pages_total: int = 0
    pages_done: int = 0
    regions_total: int = 0
    regions_done: int = 0
    current_file: str = ""
    error: Optional[str] = None

    @property
    def percent(self) -> float:
        if self.pages_total == 0:
            return 0.0
        return (self.pages_done / self.pages_total) * 100.0


# ---------------------------------------------------------------------------
# Textual Messages (inter-widget communication)
# ---------------------------------------------------------------------------

class FileSelected(Message):
    """User selected a file to process."""
    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path


class PipelineStageUpdate(Message):
    """Pipeline stage statuses changed."""
    def __init__(self, stages: list[StageState]) -> None:
        super().__init__()
        self.stages = stages


class PipelineProgressUpdate(Message):
    """Progress counters updated."""
    def __init__(self, progress: PipelineProgress) -> None:
        super().__init__()
        self.progress = progress


class PipelinePreviewUpdate(Message):
    """Partial markdown preview available."""
    def __init__(self, markdown: str) -> None:
        super().__init__()
        self.markdown = markdown


class PipelineComplete(Message):
    """Pipeline finished successfully."""
    def __init__(self, markdown: str, output_path: str) -> None:
        super().__init__()
        self.markdown = markdown
        self.output_path = output_path


class PipelineError(Message):
    """Pipeline encountered an error."""
    def __init__(self, error: str) -> None:
        super().__init__()
        self.error = error


class SettingChanged(Message):
    """A config setting was changed in the GUI."""
    def __init__(self, key: str, value: Any) -> None:
        super().__init__()
        self.key = key
        self.value = value
