"""Typed contracts shared by the GUI, registry, and workflow adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Mapping


class WorkflowMode(str, Enum):
    """Execution environments for workflows that have an environment choice."""

    TEST = "TEST"
    PRODUCTION = "PROD"


class ParameterKind(str, Enum):
    """Input controls supported by the generic workflow detail page."""

    TEXT = "text"
    INPUT_FILE = "input_file"
    MULTI_INPUT_FILE = "multi_input_file"
    OUTPUT_FILE = "output_file"
    PERCENT = "percent"
    NAME_LIST = "name_list"


@dataclass(frozen=True)
class ParameterDefinition:
    key: str
    label: str
    kind: ParameterKind
    default: Any = ""
    help_text: str = ""
    required: bool = True
    minimum: float | None = None
    maximum: float | None = None
    file_types: tuple[tuple[str, str], ...] = ()
    default_extension: str = ""


@dataclass(frozen=True)
class WorkflowContext:
    workflow_id: str
    parameters: Mapping[str, Any]
    mode: WorkflowMode | None = None


@dataclass(frozen=True)
class WorkflowResult:
    success: bool
    message: str
    output_path: Path | None = None
    log_path: Path | None = None


WorkflowRunner = Callable[[WorkflowContext], WorkflowResult]


@dataclass(frozen=True)
class WorkflowDefinition:
    workflow_id: str
    name: str
    description: str
    category: str
    runner: WorkflowRunner
    parameters: tuple[ParameterDefinition, ...] = field(default_factory=tuple)
    supported_modes: tuple[WorkflowMode, ...] = field(default_factory=tuple)
    production_warning: str = (
        "This process will create or transmit production output."
    )

    @property
    def default_mode(self) -> WorkflowMode | None:
        """Always prefer TEST when a workflow offers an environment choice."""
        if WorkflowMode.TEST in self.supported_modes:
            return WorkflowMode.TEST
        if self.supported_modes:
            return self.supported_modes[0]
        return None
