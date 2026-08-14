from __future__ import annotations

import pytest
from pydantic import ValidationError

from schemas.shooting import (
    AestheticInstructionDraft,
    GuidanceLayer,
    GuidanceOverlayPayload,
    IntentAnswer,
    IntentConflict,
    IntentPhaseResult,
    IntentQuestion,
    PlanAndEditAgentOutput,
    PlanAndEditInstruction,
    SceneFacts,
    ShootingPlanPayload,
    ShootingPlanStep,
)


def test_intent_question_alias_roundtrip() -> None:
    q = IntentQuestion.model_validate(
        {"questionId": "q1", "text": "半身还是全身？", "options": ["半身", "全身"]}
    )
    assert q.question_id == "q1"
    dumped = q.model_dump(by_alias=True)
    assert dumped["questionId"] == "q1"


def test_intent_phase_requires_one_or_two_questions() -> None:
    facts = SceneFacts(narrative="人物偏左，未见远山。")
    draft = AestheticInstructionDraft(instruction="将人物调整至画面中心并优化姿态。")
    with pytest.raises(ValidationError):
        IntentPhaseResult(
            draftGoal="x",
            questions=[],
            sceneFacts=facts,
            aestheticDraft=draft,
        )
    ok = IntentPhaseResult(
        draft_goal="断桥游客照",
        questions=[IntentQuestion(text="是否坚持人物在右侧？", options=["是", "否"])],
        scene_facts=facts,
        aesthetic_draft=draft,
        conflicts=[
            IntentConflict(
                summary="美学居中 vs 用户右侧",
                user_side="人物在右侧",
                aesthetic_side="人物居中",
            )
        ],
    )
    assert len(ok.questions) == 1


def test_plan_and_edit_preserves_trace_fields() -> None:
    facts = SceneFacts(narrative="桥面，人物左侧。", visible_landmarks=["断桥"])
    draft = AestheticInstructionDraft(instruction="居中构图，半身。")
    plan = ShootingPlanPayload(
        goal="断桥游客照，人物右侧",
        steps=[
            ShootingPlanStep(step_id="s0_intent", title="意图确认", status="completed"),
            ShootingPlanStep(
                step_id="s1_coarse_act", title="粗调", status="in_progress"
            ),
        ],
    )
    bundle = PlanAndEditInstruction(
        shooting_plan=plan,
        coarse_guidance=GuidanceOverlayPayload(
            layers=[GuidanceLayer(kind="text", text="人物移到右侧三分线")],
            advice_text="先站位",
        ),
        edit_instruction="人物置于右侧三分线，保留湖面；不臆造远山。",
        scene_facts=facts,
        aesthetic_draft=draft,
        intent_resolution_notes="用户坚持右侧；远山缺失则换机位而非生造。",
    )
    data = bundle.model_dump(by_alias=True)
    assert data["editInstruction"].startswith("人物置于右侧")
    assert data["aestheticDraft"]["instruction"] == draft.instruction
    assert data["sceneFacts"]["narrative"] == facts.narrative


def test_guidance_bbox_non_four_floats_dropped() -> None:
    layer = GuidanceLayer(kind="bbox", normalized=[0.1, 0.2], label="point_like")
    assert layer.normalized is None
    assert layer.label == "point_like"
    ok = GuidanceLayer(kind="bbox", normalized=[0.55, 0.3, 0.35, 0.5])
    assert ok.normalized == [0.55, 0.3, 0.35, 0.5]


def test_plan_agent_output_tolerates_point_normalized() -> None:
    """Regression: LLM sometimes emits [x,y] points instead of [x,y,w,h]."""
    out = PlanAndEditAgentOutput.model_validate(
        {
            "shootingPlan": {
                "goal": "断桥游客照",
                "steps": [
                    {"stepId": "s0_intent", "title": "意图确认", "status": "completed"},
                    {
                        "stepId": "s1_coarse_act",
                        "title": "粗调",
                        "status": "in_progress",
                    },
                ],
            },
            "coarseGuidance": {
                "adviceText": "接受居中构图",
                "layers": [
                    {"kind": "bbox", "normalized": [0.1, 0.1], "label": "a"},
                    {"kind": "bbox", "normalized": [0.8, 0.8], "label": "b"},
                ],
            },
            "editInstruction": "人物居中，保留湖面。",
            "intentResolutionNotes": "用户不接受右侧",
        }
    )
    assert out.coarse_guidance.advice_text == "接受居中构图"
    assert all(layer.normalized is None for layer in out.coarse_guidance.layers)
    assert len(out.coarse_guidance.layers) == 2


def test_intent_answer_alias() -> None:
    ans = IntentAnswer.model_validate({"questionId": "q1", "value": "全身"})
    assert ans.question_id == "q1"
    assert ans.value == "全身"
