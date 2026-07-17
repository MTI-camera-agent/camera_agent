from __future__ import annotations

from pathlib import Path

from agents.prompt_loader import PromptLoader
from models.protocols import StructuredVisionClient
from schemas.perception import PerceptionReport


class PerceptionAgent:
    def __init__(self, client: StructuredVisionClient, prompt_loader: PromptLoader) -> None:
        self._client = client
        self._prompt_loader = prompt_loader

    def perceive(self, *, image_path: Path, user_prompt: str) -> PerceptionReport:
        template = self._prompt_loader.load("perception.md")
        prompt = template.replace("{user_prompt}", user_prompt)
        return self._client.generate(
            prompt=prompt,
            output_schema=PerceptionReport,
            image_paths=[image_path],
        )
