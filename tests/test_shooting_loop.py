from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from agents.intent_agent import IntentAgent
from agents.shooting_planner_agent import ShootingPlannerAgent
from schemas.shooting import (
    AestheticInstructionDraft,
    GuidanceLayer,
    GuidanceOverlayPayload,
    IntentAgentOutput,
    IntentAnswer,
    IntentConflict,
    IntentQuestion,
    PlanAndEditAgentOutput,
    SceneFacts,
    ShootingPlanPayload,
    ShootingPlanStep,
)
from skills.qwen3vl_photo import PHOTO_INSTRUCTION_PROMPT
from workflow.shooting_loop import ShootingLoop


def test_shooting_loop_mock_end_to_end(tmp_path: Path) -> None:
    image = tmp_path / "02-input_frame.jpg"
    image.write_bytes(b"fake")
    plan_dir = tmp_path / "plans"

    facts = SceneFacts(narrative="人物偏左，未见远山。")
    draft = AestheticInstructionDraft(instruction="将人物调整至画面中心。")

    photo = MagicMock()
    photo.describe_scene.return_value = facts
    photo.draft_aesthetic_instruction.return_value = draft

    intent_client = MagicMock()
    intent_client.generate.return_value = IntentAgentOutput(
        draft_goal="断桥游客照，人物右侧",
        questions=[
            IntentQuestion(
                question_id="q1",
                text="美学建议居中，但你要求右侧，是否坚持右侧？",
                options=["坚持右侧", "接受居中"],
            )
        ],
        conflicts=[
            IntentConflict(
                summary="右侧 vs 居中",
                user_side="右侧",
                aesthetic_side="居中",
            )
        ],
    )
    plan_client = MagicMock()
    plan_client.generate.return_value = PlanAndEditAgentOutput(
        shooting_plan=ShootingPlanPayload(
            goal="断桥游客照，人物右侧",
            steps=[
                ShootingPlanStep(
                    step_id="s0_intent", title="意图确认", status="completed"
                ),
                ShootingPlanStep(
                    step_id="s1_coarse_act", title="粗调", status="in_progress"
                ),
                ShootingPlanStep(step_id="s2_fine_act", title="精调", status="pending"),
            ],
        ),
        coarse_guidance=GuidanceOverlayPayload(
            layers=[GuidanceLayer(kind="text", text="人物移到右侧")],
            advice_text="先站位到右侧三分线",
        ),
        edit_instruction="人物置于右侧三分线；不臆造远山。",
        intent_resolution_notes="用户坚持右侧；远山缺失则换机位。",
    )

    loop = ShootingLoop(
        photo_vlm=photo,
        intent_agent=IntentAgent(intent_client, MagicMock()),
        planner_agent=ShootingPlannerAgent(plan_client, MagicMock()),
        plan_dir=plan_dir,
    )
    # Prompt loader not used because clients are mocked after construct —
    # patch loaders on agents:
    loop._intent_agent._prompt_loader.load = MagicMock(  # type: ignore[method-assign]
        return_value=(
            "intent {user_intent} {scene_facts} {aesthetic_draft}"
        )
    )
    loop._planner_agent._prompt_loader.load = MagicMock(  # type: ignore[method-assign]
        return_value=(
            "plan {user_intent} {answers} {scene_facts} {aesthetic_draft} {conflicts}"
        )
    )

    phase = loop.collect_intent_phase(
        image_path=image,
        user_intent="在断桥拍游客照，湖面和远山，人物在右侧",
    )
    photo.draft_aesthetic_instruction.assert_called_once_with(image)
    assert phase.scene_facts is facts
    assert phase.aesthetic_draft is draft
    assert "右侧" in phase.questions[0].text

    result = loop.confirm_and_plan(
        user_intent="在断桥拍游客照，湖面和远山，人物在右侧",
        intent_phase=phase,
        answers=[IntentAnswer(question_id="q1", value="坚持右侧")],
    )
    assert result.plan_path.is_file()
    assert result.plan_bundle.edit_instruction.startswith("人物置于右侧")
    assert result.plan_bundle.aesthetic_draft.instruction == draft.instruction
    # Aesthetic call must never be invoked with user intent kwargs.
    assert photo.draft_aesthetic_instruction.call_args.kwargs == {}
    assert PHOTO_INSTRUCTION_PROMPT  # shared constant still imported/usable
