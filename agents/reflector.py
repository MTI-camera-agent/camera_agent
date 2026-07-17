from __future__ import annotations

from pathlib import Path

from agents.prompt_loader import PromptLoader
from models.protocols import StructuredVisionClient
from schemas.state import EvaluationReport


class ReflectorAgent:
    def __init__(self, client: StructuredVisionClient, prompt_loader: PromptLoader) -> None:
        self._client = client
        self._prompt_loader = prompt_loader

    def evaluate(
        self,
        *,
        original_image: Path,
        current_image: Path,
        user_prompt: str,
        state_summary: str,
    ) -> EvaluationReport:
        template = self._prompt_loader.load("reflection.md")
        prompt = (
            template.replace("{user_prompt}", user_prompt)
            .replace("{state_summary}", state_summary)
        )
        return self._client.generate(
            prompt=prompt,
            output_schema=EvaluationReport,
            image_paths=[original_image, current_image],
        )
