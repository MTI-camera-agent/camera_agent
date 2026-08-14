from __future__ import annotations

import json

from agents.prompt_loader import PromptLoader
from models.protocols import StructuredVisionClient
from schemas.shooting import (
    AestheticInstructionDraft,
    IntentAnswer,
    IntentConflict,
    IntentQuestion,
    PlanAndEditAgentOutput,
    PlanAndEditInstruction,
    SceneFacts,
)


class ShootingPlannerAgent:
    """Main-agent final ShootingPlan + editInstruction after user answers."""

    def __init__(
        self,
        client: StructuredVisionClient,
        prompt_loader: PromptLoader,
    ) -> None:
        self._client = client
        self._prompt_loader = prompt_loader

    def plan(
        self,
        *,
        user_intent: str,
        answers: list[IntentAnswer],
        questions: list[IntentQuestion],
        conflicts: list[IntentConflict],
        scene_facts: SceneFacts,
        aesthetic_draft: AestheticInstructionDraft,
    ) -> PlanAndEditInstruction:
        template = self._prompt_loader.load("shooting_planner.md")
        answers_payload = [
            {
                "questionId": a.question_id,
                "value": a.value,
                "questionText": next(
                    (q.text for q in questions if q.question_id == a.question_id),
                    "",
                ),
            }
            for a in answers
        ]
        prompt = (
            template.replace("{user_intent}", user_intent)
            .replace(
                "{answers}",
                json.dumps(answers_payload, ensure_ascii=False),
            )
            .replace(
                "{scene_facts}",
                json.dumps(scene_facts.model_dump(by_alias=True), ensure_ascii=False),
            )
            .replace(
                "{aesthetic_draft}",
                json.dumps(aesthetic_draft.model_dump(by_alias=True), ensure_ascii=False),
            )
            .replace(
                "{conflicts}",
                json.dumps(
                    [c.model_dump(by_alias=True) for c in conflicts],
                    ensure_ascii=False,
                ),
            )
        )
        agent_out = self._client.generate(
            prompt=prompt,
            output_schema=PlanAndEditAgentOutput,
            image_paths=[],
        )
        return PlanAndEditInstruction(
            shooting_plan=agent_out.shooting_plan,
            coarse_guidance=agent_out.coarse_guidance,
            edit_instruction=agent_out.edit_instruction,
            scene_facts=scene_facts,
            aesthetic_draft=aesthetic_draft,
            reference_preview=agent_out.reference_preview,
            intent_resolution_notes=agent_out.intent_resolution_notes,
        )
