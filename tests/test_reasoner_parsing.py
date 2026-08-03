from __future__ import annotations

import pytest

from camera_agent.adapters.gemini import (
    GeminiReasoner,
    ModelOutputError,
    parse_planning_decision,
    parse_verification_decision,
)
from camera_agent.domain import ImageData, PlanningRequest, VerificationOutcome
from tests.helpers import JPEG, camera


def test_parse_fixed_plan_and_grounded_overlay() -> None:
    parsed = parse_planning_decision(
        {
            "assessment": "Plant is on the right edge.",
            "ready": False,
            "steps": [
                {
                    "id": "acquire",
                    "category": "composition",
                    "criterion": "Plant is centered and fully visible.",
                }
            ],
            "instruction": "Pan right to center the plant.",
            "overlays": [
                {
                    "id": "direction",
                    "kind": "arrow",
                    "points": [{"x": 0.5, "y": 0.5}, {"x": 0.8, "y": 0.5}],
                    "color": "#00FF00",
                    "line_width": 3,
                    "expires_ms": 1800,
                }
            ],
            "sample_instruction": None,
        }
    )
    assert parsed.plan.steps[0].criterion.startswith("Plant")
    assert parsed.instruction == "Pan right to center the plant."
    assert parsed.overlays[0].points[-1] == (0.8, 0.5)


def test_hold_with_refined_instruction_becomes_revision() -> None:
    parsed = parse_verification_decision(
        {
            "outcome": "hold",
            "assessment": "The step is not complete.",
            "instruction": "Zoom in a little more.",
            "step_index": None,
            "overlays": [],
            "sample_instruction": None,
        },
        has_next=True,
        plan_size=2,
    )
    assert parsed.outcome.value == "revise"
    assert parsed.instruction == "Zoom in a little more."


def test_harmless_step_index_is_ignored() -> None:
    parsed = parse_verification_decision(
        {
            "outcome": "hold",
            "assessment": "The step is not complete.",
            "instruction": None,
            "step_index": 0,
            "overlays": [],
            "sample_instruction": None,
        },
        has_next=True,
        plan_size=2,
    )
    assert parsed.outcome == VerificationOutcome.HOLD
    assert parsed.step_index is None


def test_advance_from_final_step_normalizes_to_ready() -> None:
    parsed = parse_verification_decision(
        {
            "outcome": "advance",
            "assessment": "The final step is satisfied.",
            "instruction": "Take the shot.",
            "step_index": None,
            "overlays": [],
            "sample_instruction": None,
        },
        has_next=False,
        plan_size=1,
    )
    assert parsed.outcome == VerificationOutcome.READY
    assert parsed.instruction is None


def test_premature_resume_normalizes_to_same_step_revision() -> None:
    parsed = parse_verification_decision(
        {
            "outcome": "resume",
            "assessment": "The plant still needs to be centered.",
            "instruction": "Pan slightly left to center the plant.",
            "step_index": 0,
            "overlays": [],
            "sample_instruction": None,
        },
        has_next=True,
        plan_size=2,
        was_ready=False,
    )
    assert parsed.outcome == VerificationOutcome.REVISE
    assert parsed.instruction == "Pan slightly left to center the plant."
    assert parsed.step_index is None


def test_current_image_can_satisfy_remaining_plan_at_once() -> None:
    parsed = parse_verification_decision(
        {
            "outcome": "ready",
            "assessment": "The current image satisfies the complete plan.",
            "instruction": None,
            "step_index": None,
            "overlays": [],
            "sample_instruction": None,
        },
        has_next=True,
        plan_size=2,
    )
    assert parsed.outcome == VerificationOutcome.READY


def test_ready_plan_still_requires_fixed_criteria_for_later_regression() -> None:
    with pytest.raises(ModelOutputError):
        parse_planning_decision(
            {
                "assessment": "Already ideal.",
                "ready": True,
                "steps": [],
                "instruction": None,
                "overlays": [],
                "sample_instruction": None,
            }
        )


async def test_explicit_reference_gets_fallback_edit_instruction() -> None:
    class StubReasoner(GeminiReasoner):
        def __init__(self) -> None:
            pass

        async def _generate(self, **_):
            return {
                "assessment": "Move closer.",
                "ready": False,
                "steps": [
                    {
                        "id": "scale",
                        "category": "composition",
                        "criterion": "Shirt fills the frame.",
                    }
                ],
                "instruction": "Move closer.",
                "step_index": None,
                "overlays": [],
                "sample_instruction": None,
            }

    decision = await StubReasoner().create_plan(
        PlanningRequest(
            intention="A close shirt view with a reference image",
            sample_allowed=True,
            camera=camera(),
            observation_reason="intention_updated",
            current_image=ImageData(JPEG, "image/jpeg", 32, 32),
        )
    )
    assert decision.sample_instruction
    assert "close shirt view" in decision.sample_instruction
