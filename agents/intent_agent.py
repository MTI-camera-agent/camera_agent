from __future__ import annotations

import json

from agents.prompt_loader import PromptLoader
from models.protocols import StructuredVisionClient
from schemas.shooting import (
    AestheticInstructionDraft,
    IntentAgentOutput,
    IntentPhaseResult,
    SceneFacts,
)


class IntentAgent:
    """Main-agent Questions from userIntent + Qwen scene/aesthetic evidence (text only)."""

    def __init__(
        self,
        client: StructuredVisionClient,
        prompt_loader: PromptLoader,
    ) -> None:
        self._client = client
        self._prompt_loader = prompt_loader

    def analyze(
        self,
        *,
        user_intent: str,
        scene_facts: SceneFacts,
        aesthetic_draft: AestheticInstructionDraft,
    ) -> IntentPhaseResult:
        template = self._prompt_loader.load("intent.md")
        prompt = (
            template.replace("{user_intent}", user_intent)
            .replace(
                "{scene_facts}",
                json.dumps(scene_facts.model_dump(by_alias=True), ensure_ascii=False),
            )
            .replace(
                "{aesthetic_draft}",
                json.dumps(aesthetic_draft.model_dump(by_alias=True), ensure_ascii=False),
            )
        )
        agent_out = self._client.generate(
            prompt=prompt,
            output_schema=IntentAgentOutput,
            image_paths=[],
        )
        return IntentPhaseResult(
            draft_goal=agent_out.draft_goal,
            questions=agent_out.questions,
            conflicts=agent_out.conflicts,
            scene_facts=scene_facts,
            aesthetic_draft=aesthetic_draft,
        )
