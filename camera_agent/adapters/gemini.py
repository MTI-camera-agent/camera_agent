"""Gemini adapter for fixed-plan camera coaching."""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import replace
from typing import Any, Mapping

from google import genai
from google.genai import types

from ..config import DEFAULT_MODEL
from ..domain import (
    Overlay,
    PlanStep,
    PlanningDecision,
    PlanningRequest,
    ShotPlan,
    VerificationDecision,
    VerificationOutcome,
    VerificationRequest,
)

_CATEGORIES = ["composition", "pose", "viewpoint", "lighting", "exposure_focus"]

_COMMON_PROMPT = """
You are the vision tool inside a deterministic camera coaching harness. The
iPhone user alone controls camera direction, framing, zoom, focus, exposure,
pose, and shutter. You only analyze the supplied images and return structured
advice.

The current image is authoritative. Give one short, physical instruction.
Prioritize:
1. Acquire the named subject. If it is at an unintended frame edge, tell the
   user to pan/turn TOWARD it before changing distance. A subject on the left
   edge requires panning/turning left; a subject on the right requires right.
2. Correct framing and shot scale. A close shot is complete when the subject
   clearly dominates the frame without unwanted clipping. Never ask for closer
   movement when it already fills or overfills the frame.
3. Focus, exposure, pose, lighting, and refinements.

Do not mistake preview JPEG softness, shallow depth of field, or motion blur for
missed focus. A focus_changed observation is evidence that the user tapped.
Do not repeat a tap-to-focus instruction without clear current-image evidence.

Shot-scale semantics are strict:
- "A close shot/view of [object]" means the complete named object should occupy
  most of the frame while every meaningful outer boundary remains visible with
  a small margin. It does NOT mean cropping into its surface.
- Cropping the object to show only fabric, texture, or one part is allowed only
  when the intention explicitly asks for a detail, texture, macro, pattern, or
  named part.
- For clothing or another folded/draped object, preserve the whole garment as
  the subject. Do not ask the user to fill the entire frame with fabric.
- If the complete object is already dominant, the scale criterion is satisfied.
  If any meaningful boundary is clipped, instruct the user to move back or zoom
  wider before giving refinements.

Overlays must be grounded in the current image, use normalized coordinates, and
number at most three. When an instruction is spatial and its direction or
target can be located reliably, include one useful arrow, line, or rectangle.
Never claim to control the phone. Return only JSON matching the supplied schema.
""".strip()

_PLAN_PROMPT = (
    _COMMON_PROMPT
    + """

Create one fixed ordered plan of one to five observable criteria for the
intention. Include the complete useful plan even when criteria are already
satisfied, so a later changed frame can be checked against it. If the current
frame already satisfies the complete plan, return ready=true and no instruction.
Otherwise return the instruction for the first unsatisfied step and order the
plan from that step onward. The harness keeps this plan fixed until the user
enters a new intention.

When sample_allowed is true, include a concrete sample_instruction describing
the improved reference image to generate. Otherwise it must be null.
""".rstrip()
)

_VERIFY_PROMPT = (
    _COMMON_PROMPT
    + """

Verify only the active step in the fixed plan by comparing the older baseline
with the current image:
- hold: the active criterion is not yet satisfied. Do not invent another step.
- revise: the active criterion is not yet satisfied, but the current image
  justifies a more precise or corrective instruction (for example, move a bit
  closer, or zoom slightly wider after overshooting).
- advance: it is satisfied and another ordered step remains. Give one
  instruction for that next step.
- ready: it is satisfied and the fixed plan is complete.
- resume: only when was_ready=true and the current image no longer satisfies
  the fixed plan. Set step_index to the first failed step and give its
  instruction.

Never revise, reorder, add, or remove plan steps. For hold, instruction must be
null. For revise, instruction must contain the updated guidance. Set step_index
to null for hold, revise, advance, and ready.
When sample_allowed is true, include a concrete sample_instruction; otherwise
it must be null.
""".rstrip()
)

_OVERLAY_SCHEMA: dict[str, Any] = {
    "type": "array",
    "maxItems": 3,
    "items": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "id",
            "kind",
            "points",
            "text",
            "color",
            "line_width",
            "expires_ms",
        ],
        "properties": {
            "id": {"type": "string"},
            "kind": {
                "type": "string",
                "enum": ["arrow", "line", "rectangle", "circle", "path", "text"],
            },
            "points": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["x", "y"],
                    "properties": {
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                    },
                },
            },
            "text": {"type": ["string", "null"]},
            "color": {"type": ["string", "null"]},
            "line_width": {"type": ["number", "null"]},
            "expires_ms": {"type": ["integer", "null"]},
        },
    },
}

_STEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["id", "category", "criterion"],
    "properties": {
        "id": {"type": "string", "minLength": 1, "maxLength": 48},
        "category": {"type": "string", "enum": _CATEGORIES},
        "criterion": {"type": "string", "minLength": 1, "maxLength": 180},
    },
}

_PLAN_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "assessment",
        "ready",
        "steps",
        "instruction",
        "step_index",
        "overlays",
        "sample_instruction",
    ],
    "properties": {
        "assessment": {"type": "string", "minLength": 1, "maxLength": 600},
        "ready": {"type": "boolean"},
        "steps": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": _STEP_SCHEMA,
        },
        "instruction": {"type": ["string", "null"], "maxLength": 240},
        "step_index": {"type": ["integer", "null"], "minimum": 0, "maximum": 4},
        "overlays": _OVERLAY_SCHEMA,
        "sample_instruction": {"type": ["string", "null"], "maxLength": 600},
    },
}

_VERIFY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "outcome",
        "assessment",
        "instruction",
        "step_index",
        "overlays",
        "sample_instruction",
    ],
    "properties": {
        "outcome": {
            "type": "string",
            "enum": [outcome.value for outcome in VerificationOutcome],
        },
        "assessment": {"type": "string", "minLength": 1, "maxLength": 600},
        "instruction": {"type": ["string", "null"], "maxLength": 240},
        "step_index": {"type": ["integer", "null"], "minimum": 0, "maximum": 4},
        "overlays": _OVERLAY_SCHEMA,
        "sample_instruction": {"type": ["string", "null"], "maxLength": 600},
    },
}


class ModelOutputError(ValueError):
    pass


class GeminiReasoner:
    def __init__(
        self,
        *,
        model: str = DEFAULT_MODEL,
        api_key: str | None = None,
        max_output_tokens: int = 1200,
    ) -> None:
        key = api_key or os.environ.get("GEMINI_API_KEY")
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        self._client = genai.Client(api_key=key)
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def create_plan(self, request: PlanningRequest) -> PlanningDecision:
        state = {
            "intention": request.intention,
            "sample_allowed": request.sample_allowed,
            "camera": request.camera,
            "observation_reason": request.observation_reason,
        }
        payload = await self._generate(
            prompt=_PLAN_PROMPT,
            schema=_PLAN_SCHEMA,
            state=state,
            images=(("Current image", request.current_image),),
        )
        decision = parse_planning_decision(
            payload,
            sample_allowed=request.sample_allowed,
        )
        if request.sample_allowed and decision.sample_instruction is None:
            decision = replace(
                decision,
                sample_instruction=_sample_fallback(request.intention),
            )
        return decision

    async def verify_step(
        self,
        request: VerificationRequest,
    ) -> VerificationDecision:
        state = {
            "intention": request.intention,
            "sample_allowed": request.sample_allowed,
            "fixed_plan": request.plan.to_prompt(),
            "active_step_index": request.active_step_index,
            "active_step": request.plan.steps[request.active_step_index].to_prompt(),
            "current_instruction": request.current_instruction,
            "was_ready": request.was_ready,
            "camera": request.camera,
            "observation_reason": request.observation_reason,
        }
        payload = await self._generate(
            prompt=_VERIFY_PROMPT,
            schema=_VERIFY_SCHEMA,
            state=state,
            images=(
                ("Older baseline image", request.baseline_image),
                ("Current image", request.current_image),
            ),
        )
        has_next = request.active_step_index + 1 < len(request.plan.steps)
        return parse_verification_decision(
            payload,
            has_next=has_next,
            plan_size=len(request.plan.steps),
            was_ready=request.was_ready,
            sample_allowed=request.sample_allowed,
        )

    async def _generate(
        self,
        *,
        prompt: str,
        schema: Mapping[str, Any],
        state: Mapping[str, Any],
        images: tuple[tuple[str, Any], ...],
    ) -> Mapping[str, Any]:
        contents: list[Any] = [
            "Structured harness state:\n"
            + json.dumps(state, separators=(",", ":"), ensure_ascii=False)
        ]
        for label, image in images:
            contents.extend(
                [
                    f"{label}:",
                    types.Part.from_bytes(
                        data=image.data,
                        mime_type=image.mime_type,
                    ),
                ]
            )
        response = await self._client.aio.models.generate_content(
            model=self._model,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                max_output_tokens=self._max_output_tokens,
                response_mime_type="application/json",
                response_json_schema=schema,
            ),
        )
        if not response.text:
            raise ModelOutputError("Gemini returned no text")
        try:
            value = json.loads(response.text)
        except json.JSONDecodeError as error:
            raise ModelOutputError(f"Gemini returned invalid JSON: {error}") from error
        if not isinstance(value, Mapping):
            raise ModelOutputError("Gemini returned a non-object JSON value")
        return value


def parse_planning_decision(
    payload: Mapping[str, Any],
    *,
    sample_allowed: bool = True,
) -> PlanningDecision:
    try:
        ready = bool(payload["ready"])
        steps = _parse_steps(payload.get("steps"))
        instruction = _optional_text(payload.get("instruction"))
        if not steps:
            raise ModelOutputError("plan requires at least one step")
        if not ready and not instruction:
            raise ModelOutputError("non-ready plan requires an instruction")
        if ready and instruction is not None:
            raise ModelOutputError("ready plan must not include an instruction")
        sample = _optional_text(payload.get("sample_instruction")) if sample_allowed else None
        return PlanningDecision(
            assessment=_required_text(payload["assessment"], "assessment"),
            plan=ShotPlan(steps),
            ready=ready,
            instruction=instruction,
            overlays=_parse_overlays(payload.get("overlays", [])),
            sample_instruction=sample,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ModelOutputError):
            raise
        raise ModelOutputError(f"invalid planning decision: {error}") from error


def parse_verification_decision(
    payload: Mapping[str, Any],
    *,
    has_next: bool,
    plan_size: int,
    was_ready: bool = False,
    sample_allowed: bool = True,
) -> VerificationDecision:
    try:
        outcome = VerificationOutcome(str(payload["outcome"]))
        instruction = _optional_text(payload.get("instruction"))
        raw_step_index = payload.get("step_index")
        step_index = int(raw_step_index) if raw_step_index is not None else None
        if outcome == VerificationOutcome.HOLD and instruction is not None:
            outcome = VerificationOutcome.REVISE
        if (
            outcome == VerificationOutcome.RESUME
            and not was_ready
            and instruction is not None
        ):
            outcome = VerificationOutcome.REVISE
        if outcome != VerificationOutcome.RESUME:
            step_index = None
        if was_ready and outcome in {
            VerificationOutcome.HOLD,
            VerificationOutcome.REVISE,
            VerificationOutcome.ADVANCE,
        }:
            if instruction is None:
                outcome = VerificationOutcome.READY
            else:
                outcome = VerificationOutcome.RESUME
                step_index = (
                    int(raw_step_index)
                    if raw_step_index is not None
                    else 0
                )
        if outcome == VerificationOutcome.REVISE and instruction is None:
            raise ModelOutputError("revise requires an instruction")
        if outcome == VerificationOutcome.ADVANCE:
            if not has_next:
                outcome = VerificationOutcome.READY
                instruction = None
            elif instruction is None:
                raise ModelOutputError("advance requires the next instruction")
        if outcome == VerificationOutcome.RESUME:
            if not was_ready:
                raise ModelOutputError("resume is valid only after ready")
            if instruction is None or step_index is None:
                raise ModelOutputError("resume requires step_index and instruction")
            if not 0 <= step_index < plan_size:
                raise ModelOutputError("resume step_index is outside the fixed plan")
        if outcome == VerificationOutcome.READY:
            instruction = None
            step_index = None
        sample = (
            _optional_text(payload.get("sample_instruction"))
            if sample_allowed
            and outcome
            in {
                VerificationOutcome.REVISE,
                VerificationOutcome.ADVANCE,
                VerificationOutcome.RESUME,
            }
            else None
        )
        return VerificationDecision(
            outcome=outcome,
            assessment=_required_text(payload["assessment"], "assessment"),
            instruction=instruction,
            step_index=step_index,
            overlays=_parse_overlays(payload.get("overlays", [])),
            sample_instruction=sample,
        )
    except (KeyError, TypeError, ValueError) as error:
        if isinstance(error, ModelOutputError):
            raise
        raise ModelOutputError(f"invalid verification decision: {error}") from error


def _parse_steps(values: Any) -> tuple[PlanStep, ...]:
    if not isinstance(values, list):
        raise ModelOutputError("steps must be an array")
    steps: list[PlanStep] = []
    ids: set[str] = set()
    for raw in values[:5]:
        step_id = _required_text(raw["id"], "step id")
        if step_id in ids:
            raise ModelOutputError("step ids must be unique")
        ids.add(step_id)
        category = str(raw["category"])
        if category not in _CATEGORIES:
            raise ModelOutputError(f"invalid step category: {category}")
        steps.append(
            PlanStep(
                id=step_id,
                category=category,
                criterion=_required_text(raw["criterion"], "criterion"),
            )
        )
    return tuple(steps)


def _parse_overlays(values: Any) -> tuple[Overlay, ...]:
    if not isinstance(values, list):
        return ()
    overlays: list[Overlay] = []
    ids: set[str] = set()
    for raw in values[:3]:
        try:
            overlay = _parse_overlay(raw)
        except (KeyError, TypeError, ValueError, ModelOutputError):
            continue
        if overlay.id not in ids:
            ids.add(overlay.id)
            overlays.append(overlay)
    return tuple(overlays)


def _parse_overlay(raw: Mapping[str, Any]) -> Overlay:
    overlay_id = _required_text(raw["id"], "overlay id")
    kind = str(raw["kind"])
    if kind not in {"arrow", "line", "rectangle", "circle", "path", "text"}:
        raise ModelOutputError("invalid overlay kind")
    points: list[tuple[float, float]] = []
    for raw_point in raw["points"]:
        x, y = float(raw_point["x"]), float(raw_point["y"])
        if not math.isfinite(x) or not math.isfinite(y) or not (0 <= x <= 1 and 0 <= y <= 1):
            raise ModelOutputError("invalid overlay point")
        points.append((x, y))
    if kind in {"arrow", "line", "path"} and len(points) < 2:
        raise ModelOutputError("overlay needs at least two points")
    if kind in {"rectangle", "circle"} and len(points) != 2:
        raise ModelOutputError("overlay needs exactly two points")
    text = _optional_text(raw.get("text"))
    if kind == "text" and (len(points) != 1 or not text):
        raise ModelOutputError("text overlay needs one point and text")
    color = _optional_text(raw.get("color"))
    if color and not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
        raise ModelOutputError("invalid overlay color")
    line_width = raw.get("line_width")
    if line_width is not None and (
        not math.isfinite(float(line_width)) or float(line_width) <= 0
    ):
        raise ModelOutputError("invalid overlay line width")
    expires_ms = int(raw.get("expires_ms") or 1800)
    if expires_ms <= 0:
        raise ModelOutputError("invalid overlay expiry")
    return Overlay(
        id=overlay_id,
        kind=kind,
        points=tuple(points),
        text=text,
        color=color,
        line_width=float(line_width) if line_width is not None else None,
        expires_ms=min(expires_ms, 2500),
    )


def _required_text(value: Any, label: str) -> str:
    text = _optional_text(value)
    if text is None:
        raise ModelOutputError(f"{label} must not be empty")
    return text


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _sample_fallback(intention: str) -> str:
    return (
        "Create a polished photographic reference based on the supplied image "
        f"that better realizes this shooting intention: {intention}"
    )
