from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from schemas.action import ActionSpec


class GoalSpec(BaseModel):
    objective: str = Field(..., min_length=1)
    success_criteria: list[str] = Field(default_factory=list)


class Plan(BaseModel):
    """Execution-ready plan produced by a planner."""

    goal: GoalSpec
    constraints: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    steps: list[ActionSpec] = Field(..., min_length=1)
    notes: str | None = None

    @field_validator("steps")
    @classmethod
    def require_unique_outputs(cls, steps: list[ActionSpec]) -> list[ActionSpec]:
        outputs = [step.output for step in steps if step.output]
        duplicates = {output for output in outputs if outputs.count(output) > 1}
        if duplicates:
            joined = ", ".join(sorted(duplicates))
            raise ValueError(f"Plan step outputs must be unique: {joined}")
        return steps
