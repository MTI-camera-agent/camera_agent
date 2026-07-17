from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ActionStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    SKIPPED = "skipped"


class ActionSpec(BaseModel):
    """Provider-neutral action emitted by planning and consumed by tools."""

    action: str = Field(..., min_length=1, description="Registered tool action name.")
    args: dict[str, Any] = Field(default_factory=dict)
    output: str | None = Field(
        default=None,
        description="Optional artifact alias created by this action.",
    )
    requires: list[str] = Field(
        default_factory=list,
        description="Artifact aliases that must exist before this action runs.",
    )
    description: str | None = None


class ActionExecution(BaseModel):
    action: ActionSpec
    status: ActionStatus
    artifact_id: str | None = None
    message: str | None = None
