from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from schemas.action import ActionExecution


class Artifact(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex)
    kind: str
    path: Path | None = None
    data: dict[str, Any] = Field(default_factory=dict)
    source_action: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    model_config = ConfigDict(arbitrary_types_allowed=True)


class EvaluationReport(BaseModel):
    satisfied: bool
    score: float = Field(..., ge=0.0, le=1.0)
    missing: list[str] = Field(default_factory=list)
    suggestions: list[str] = Field(default_factory=list)
    summary: str


class ExecutionState(BaseModel):
    original_image: Path
    current_image: Path
    user_prompt: str
    iteration: int = 0
    artifacts: dict[str, Artifact] = Field(default_factory=dict)
    history: list[ActionExecution] = Field(default_factory=list)
    evaluations: list[EvaluationReport] = Field(default_factory=list)

    model_config = ConfigDict(arbitrary_types_allowed=True)

    def add_artifact(self, alias: str, artifact: Artifact) -> None:
        self.artifacts[alias] = artifact
        if artifact.kind == "image" and artifact.path is not None:
            self.current_image = artifact.path

    def resolve_path(self, alias_or_path: str | Path | None) -> Path:
        if alias_or_path is None:
            return self.current_image
        if isinstance(alias_or_path, Path):
            return alias_or_path
        if alias_or_path in {"current_image", "latest_image", "image"}:
            return self.current_image
        if alias_or_path in {"original_image", "input_image", "source_image"}:
            return self.original_image
        artifact = self.artifacts.get(alias_or_path)
        if artifact and artifact.path is not None:
            return artifact.path
        path = Path(alias_or_path)
        if path.exists():
            return path
        raise KeyError(f"Artifact or file path not found: {alias_or_path}")
