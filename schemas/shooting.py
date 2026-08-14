"""Shooting-domain contracts (MVP P1). Independent of schemas.plan.Plan / ActionSpec."""

from __future__ import annotations

from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:10]}"


class IntentQuestion(BaseModel):
    question_id: str = Field(default_factory=lambda: _new_id("q"), alias="questionId")
    text: str = Field(..., min_length=1)
    options: list[str] = Field(default_factory=list)

    model_config = {"populate_by_name": True}


class IntentAnswer(BaseModel):
    question_id: str = Field(..., min_length=1, alias="questionId")
    value: str = Field(..., min_length=1)

    model_config = {"populate_by_name": True}


class IntentConflict(BaseModel):
    """Conflict between user intent, frame facts, and/or aesthetic draft."""

    conflict_id: str = Field(default_factory=lambda: _new_id("c"), alias="conflictId")
    summary: str = Field(..., min_length=1)
    user_side: str = Field(default="", alias="userSide")
    aesthetic_side: str = Field(default="", alias="aestheticSide")
    scene_side: str = Field(default="", alias="sceneSide")

    model_config = {"populate_by_name": True}


class SceneFacts(BaseModel):
    """Factual scene description from Qwen3-VL (general understanding; not aesthetic edit)."""

    narrative: str = Field(..., min_length=1)
    subjects: list[str] = Field(default_factory=list)
    composition_notes: list[str] = Field(default_factory=list, alias="compositionNotes")
    visible_landmarks: list[str] = Field(default_factory=list, alias="visibleLandmarks")
    missing_vs_typical_scenic: list[str] = Field(
        default_factory=list, alias="missingVsTypicalScenic"
    )

    model_config = {"populate_by_name": True}


class AestheticInstructionDraft(BaseModel):
    """Draft edit instruction from fine-tuned aesthetic prompt (no userIntent)."""

    instruction: str = Field(..., min_length=1)
    prompt_id: str = Field(
        default="photo_aesthetic_v2",
        description="Identifier of the fixed PHOTO_INSTRUCTION_PROMPT used.",
        alias="promptId",
    )

    model_config = {"populate_by_name": True}


GuidanceLayerKind = Literal[
    "rule_of_thirds",
    "bbox",
    "text",
    "arrow",
    "reference_overlay",
]


class GuidanceLayer(BaseModel):
    kind: GuidanceLayerKind
    active: bool = True
    text: str | None = None
    label: str | None = None
    position: str | None = None
    # normalized bbox [x, y, w, h] in 0..1 when kind == bbox
    normalized: list[float] | None = None

    @field_validator("normalized")
    @classmethod
    def validate_bbox(cls, value: list[float] | None) -> list[float] | None:
        """Accept only [x, y, w, h]; drop malformed values so LLM jitter does not fail Plan."""
        if value is None:
            return value
        if len(value) != 4:
            return None
        return value


class GuidanceOverlayPayload(BaseModel):
    frame_id: str = Field(default_factory=lambda: _new_id("f"), alias="frameId")
    layers: list[GuidanceLayer] = Field(default_factory=list)
    advice_text: str = Field(default="", alias="adviceText")

    model_config = {"populate_by_name": True}


StepStatus = Literal["pending", "in_progress", "completed", "skipped"]


class ShootingPlanStep(BaseModel):
    step_id: str = Field(..., min_length=1, alias="stepId")
    title: str = Field(..., min_length=1)
    status: StepStatus = "pending"
    skill_ids: list[str] = Field(default_factory=list, alias="skillIds")
    completion_criteria: dict[str, Any] = Field(
        default_factory=dict, alias="completionCriteria"
    )

    model_config = {"populate_by_name": True}


class ShootingPlanPayload(BaseModel):
    plan_id: str = Field(default_factory=lambda: _new_id("plan"), alias="planId")
    scenario: str = Field(default="scenic_checkin")
    goal: str = Field(..., min_length=1)
    current_step_id: str = Field(default="s1_coarse_act", alias="currentStepId")
    steps: list[ShootingPlanStep] = Field(..., min_length=1)

    model_config = {"populate_by_name": True}


ReferencePreviewStatus = Literal["generating", "ready", "failed"]
ReferenceGenerator = Literal["qwen2511", "flux"]


class ReferencePreviewPayload(BaseModel):
    preview_id: str = Field(default_factory=lambda: _new_id("rp"), alias="previewId")
    status: ReferencePreviewStatus = "generating"
    data_ref: str | None = Field(default=None, alias="dataRef")
    source_frame_id: str = Field(default="", alias="sourceFrameId")
    width: int | None = None
    height: int | None = None
    latency_ms: int | None = Field(default=None, alias="latencyMs")
    generator: ReferenceGenerator = "qwen2511"
    error_message: str | None = Field(default=None, alias="errorMessage")

    model_config = {"populate_by_name": True}


class IntentAgentOutput(BaseModel):
    """Structured agent-only fields before merging authoritative Qwen payloads."""

    draft_goal: str = Field(..., min_length=1, alias="draftGoal")
    questions: list[IntentQuestion] = Field(..., min_length=1, max_length=2)
    conflicts: list[IntentConflict] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @field_validator("questions")
    @classmethod
    def limit_questions(cls, questions: list[IntentQuestion]) -> list[IntentQuestion]:
        if not (1 <= len(questions) <= 2):
            raise ValueError("questions must contain 1 or 2 items")
        return questions


class IntentPhaseResult(BaseModel):
    """Output of intent + conflict analysis (before user confirms)."""

    draft_goal: str = Field(..., min_length=1, alias="draftGoal")
    questions: list[IntentQuestion] = Field(..., min_length=1, max_length=2)
    conflicts: list[IntentConflict] = Field(default_factory=list)
    scene_facts: SceneFacts = Field(..., alias="sceneFacts")
    aesthetic_draft: AestheticInstructionDraft = Field(..., alias="aestheticDraft")

    model_config = {"populate_by_name": True}

    @field_validator("questions")
    @classmethod
    def limit_questions(cls, questions: list[IntentQuestion]) -> list[IntentQuestion]:
        if not (1 <= len(questions) <= 2):
            raise ValueError("questions must contain 1 or 2 items")
        return questions


class PlanAndEditInstruction(BaseModel):
    """Confirmed plan bundle for P1 (reference preview deferred to P3)."""

    shooting_plan: ShootingPlanPayload = Field(..., alias="shootingPlan")
    coarse_guidance: GuidanceOverlayPayload = Field(..., alias="coarseGuidance")
    edit_instruction: str = Field(..., min_length=1, alias="editInstruction")
    scene_facts: SceneFacts = Field(..., alias="sceneFacts")
    aesthetic_draft: AestheticInstructionDraft = Field(..., alias="aestheticDraft")
    reference_preview: ReferencePreviewPayload | None = Field(
        default=None, alias="referencePreview"
    )
    intent_resolution_notes: str = Field(
        default="",
        alias="intentResolutionNotes",
        description="How final editInstruction reconciles user intent vs aesthetic draft.",
    )

    model_config = {"populate_by_name": True}


class PlanAndEditAgentOutput(BaseModel):
    """Agent output without echoing Qwen payloads (merged by ShootingPlannerAgent)."""

    shooting_plan: ShootingPlanPayload = Field(..., alias="shootingPlan")
    coarse_guidance: GuidanceOverlayPayload = Field(..., alias="coarseGuidance")
    edit_instruction: str = Field(..., min_length=1, alias="editInstruction")
    intent_resolution_notes: str = Field(default="", alias="intentResolutionNotes")
    reference_preview: ReferencePreviewPayload | None = Field(
        default=None, alias="referencePreview"
    )

    model_config = {"populate_by_name": True}
