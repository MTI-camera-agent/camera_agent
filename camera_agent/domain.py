"""Small domain model for the fixed-plan camera coaching loop."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


@dataclass(frozen=True, slots=True)
class ImageData:
    data: bytes
    mime_type: str
    width: int
    height: int

    @property
    def byte_size(self) -> int:
        return len(self.data)


@dataclass(frozen=True, slots=True)
class ObservationContext:
    observation_id: int
    timestamp_ms: int
    reason: str
    intention: str
    camera: Mapping[str, Any]
    image_message_id: str
    image: ImageData
    received_monotonic: float = field(default_factory=time.monotonic)

    @property
    def camera_signature(self) -> tuple[Any, ...]:
        return (
            self.camera.get("lensID"),
            round(float(self.camera.get("zoomFactor", 0)), 3),
            self.camera.get("orientation"),
            self.camera.get("frameWidth"),
            self.camera.get("frameHeight"),
            round(float(self.camera.get("cropAspectRatio", 0)), 4),
        )


@dataclass(frozen=True, slots=True)
class Overlay:
    id: str
    kind: str
    points: tuple[tuple[float, float], ...]
    text: str | None = None
    color: str | None = None
    line_width: float | None = None
    expires_ms: int = 1800

    def to_wire(self) -> dict[str, Any]:
        value: dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "points": [{"x": x, "y": y} for x, y in self.points],
            "expiresInMilliseconds": self.expires_ms,
        }
        if self.text:
            value["text"] = self.text
        if self.color:
            value["color"] = self.color
        if self.line_width is not None:
            value["lineWidth"] = self.line_width
        return value


@dataclass(frozen=True, slots=True)
class PlanStep:
    id: str
    category: str
    criterion: str

    def to_prompt(self) -> dict[str, str]:
        return {
            "id": self.id,
            "category": self.category,
            "criterion": self.criterion,
        }


@dataclass(frozen=True, slots=True)
class ShotPlan:
    steps: tuple[PlanStep, ...]

    def to_prompt(self) -> list[dict[str, str]]:
        return [step.to_prompt() for step in self.steps]


@dataclass(frozen=True, slots=True)
class PlanningRequest:
    intention: str
    sample_allowed: bool
    camera: Mapping[str, Any]
    observation_reason: str
    current_image: ImageData


@dataclass(frozen=True, slots=True)
class PlanningDecision:
    assessment: str
    plan: ShotPlan
    ready: bool
    instruction: str | None
    overlays: tuple[Overlay, ...] = ()
    sample_instruction: str | None = None


class VerificationOutcome(StrEnum):
    HOLD = "hold"
    REVISE = "revise"
    ADVANCE = "advance"
    READY = "ready"
    RESUME = "resume"


@dataclass(frozen=True, slots=True)
class VerificationRequest:
    intention: str
    sample_allowed: bool
    plan: ShotPlan
    active_step_index: int
    current_instruction: str
    was_ready: bool
    camera: Mapping[str, Any]
    observation_reason: str
    baseline_image: ImageData
    current_image: ImageData


@dataclass(frozen=True, slots=True)
class VerificationDecision:
    outcome: VerificationOutcome
    assessment: str
    instruction: str | None
    step_index: int | None = None
    overlays: tuple[Overlay, ...] = ()
    sample_instruction: str | None = None


class CoachingEventKind(StrEnum):
    TASK_STARTED = "task_started"
    GUIDANCE = "guidance"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class CoachingEvent:
    kind: CoachingEventKind
    task_id: str
    context: ObservationContext
    intention: str
    step_id: str | None = None
    instruction: str | None = None
    overlays: tuple[Overlay, ...] = ()
    sample_instruction: str | None = None


@dataclass(frozen=True, slots=True)
class EditedImage:
    image: ImageData


_SAMPLE_PATTERNS = (
    r"\bgenerate\s+(?:me\s+)?(?:an?\s+)?(?:reference|example|sample)(?:\s+image)?\b",
    r"\bcreate\s+(?:me\s+)?(?:an?\s+)?(?:reference|example|sample)(?:\s+image)?\b",
    r"\bshow\s+(?:me\s+)?(?:an?\s+)?(?:reference|example|sample|pose)\b",
    r"\bvisuali[sz]e\s+(?:the\s+)?(?:pose|shot|result)\b",
    r"\b(?:with|using)\s+(?:an?\s+)?(?:generated\s+)?(?:reference|example|sample)(?:\s+image)?\b",
    r"\b(?:reference|example|sample)\s+image\b",
)


def normalize_intention(intention: str) -> str:
    return " ".join(intention.split())


def explicit_sample_permission(intention: str) -> bool:
    normalized = normalize_intention(intention).lower()
    return any(re.search(pattern, normalized) for pattern in _SAMPLE_PATTERNS)
