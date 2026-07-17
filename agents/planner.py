from __future__ import annotations

from pathlib import Path

from agents.prompt_loader import PromptLoader
from models.protocols import StructuredVisionClient
from schemas.plan import Plan


class PlannerAgent:
    def __init__(
        self,
        client: StructuredVisionClient,
        prompt_loader: PromptLoader,
        tool_catalog: str,
    ) -> None:
        self._client = client
        self._prompt_loader = prompt_loader
        self._tool_catalog = tool_catalog

    def plan(
        self,
        *,
        image_path: Path,
        user_prompt: str,
        state_summary: str,
        feedback: str | None = None,
    ) -> Plan:
        template = self._prompt_loader.load("planner.md")
        prompt = (
            template.replace("{user_prompt}", user_prompt)
            .replace("{tool_catalog}", self._tool_catalog)
            .replace("{state_summary}", state_summary)
            .replace("{feedback}", feedback or "None")
        )
        return self._client.generate(
            prompt=prompt,
            output_schema=Plan,
            image_paths=[image_path],
        )
