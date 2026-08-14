from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from agents.intent_agent import IntentAgent
from agents.shooting_planner_agent import ShootingPlannerAgent
from schemas.shooting import IntentAnswer, IntentPhaseResult, PlanAndEditInstruction
from skills.qwen3vl_photo import Qwen3VLPhotoClient
from utils.file import ensure_dir


@dataclass(frozen=True)
class ShootingLoopResult:
    intent_phase: IntentPhaseResult
    plan_bundle: PlanAndEditInstruction
    plan_path: Path


class ShootingLoop:
    """P1 slow path: Qwen dual-call → Agent questions → answers → ShootingPlan."""

    def __init__(
        self,
        *,
        photo_vlm: Qwen3VLPhotoClient,
        intent_agent: IntentAgent,
        planner_agent: ShootingPlannerAgent,
        plan_dir: Path,
    ) -> None:
        self._photo_vlm = photo_vlm
        self._intent_agent = intent_agent
        self._planner_agent = planner_agent
        self._plan_dir = ensure_dir(plan_dir)

    def collect_intent_phase(
        self,
        *,
        image_path: Path,
        user_intent: str,
    ) -> IntentPhaseResult:
        scene_facts = self._photo_vlm.describe_scene(image_path)
        aesthetic_draft = self._photo_vlm.draft_aesthetic_instruction(image_path)
        return self._intent_agent.analyze(
            user_intent=user_intent,
            scene_facts=scene_facts,
            aesthetic_draft=aesthetic_draft,
        )

    def confirm_and_plan(
        self,
        *,
        user_intent: str,
        intent_phase: IntentPhaseResult,
        answers: list[IntentAnswer],
        plan_dir: Path | None = None,
    ) -> ShootingLoopResult:
        if not answers:
            raise ValueError("confirm_and_plan requires at least one answer")
        plan_bundle = self._planner_agent.plan(
            user_intent=user_intent,
            answers=answers,
            questions=intent_phase.questions,
            conflicts=intent_phase.conflicts,
            scene_facts=intent_phase.scene_facts,
            aesthetic_draft=intent_phase.aesthetic_draft,
        )
        out_dir = ensure_dir(plan_dir) if plan_dir is not None else self._plan_dir
        plan_path = out_dir / "shooting_plan.json"
        plan_path.write_text(
            json.dumps(plan_bundle.model_dump(by_alias=True), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        return ShootingLoopResult(
            intent_phase=intent_phase,
            plan_bundle=plan_bundle,
            plan_path=plan_path,
        )
