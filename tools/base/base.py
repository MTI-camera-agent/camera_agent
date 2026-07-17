from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from schemas.action import ActionSpec
from schemas.state import ExecutionState
from schemas.tool import ToolSpec


class ExecutionOptions(BaseModel):
    replace_background_refine_disabled_iterations: set[int] = Field(default_factory=set)

    def disable_replace_background_refine(self, iteration: int) -> bool:
        return iteration in self.replace_background_refine_disabled_iterations


class ToolContext(BaseModel):
    state: ExecutionState
    output_dir: Path
    mask_dir: Path
    services: dict[str, Any]
    reporter: Any | None = None
    execution_options: ExecutionOptions = Field(default_factory=ExecutionOptions)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def output_path(self, action: ActionSpec, suffix: str = ".png") -> Path:
        stem = action.output or action.action
        return self.output_dir / f"iter_{self.state.iteration:02d}_{stem}{suffix}"

    def mask_path(self, action: ActionSpec, suffix: str = ".png") -> Path:
        stem = action.output or action.action
        return self.mask_dir / f"iter_{self.state.iteration:02d}_{stem}{suffix}"


class ToolResult(BaseModel):
    artifact_kind: str
    path: Path | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class ImageTool(Protocol):
    @property
    def spec(self) -> ToolSpec:
        ...

    def run(self, action: ActionSpec, context: ToolContext) -> ToolResult:
        ...
