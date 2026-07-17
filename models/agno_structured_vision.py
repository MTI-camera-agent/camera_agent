from __future__ import annotations

import os
from pathlib import Path
from typing import Any, TypeVar

from agno.agent import Agent
from agno.media import Image
from agno.models.google import Gemini
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class AgnoStructuredVisionClient:
    """Structured multimodal client backed by an Agno Agent."""

    def __init__(self, config: dict[str, Any]) -> None:
        model_id = config.get("model_id")
        if not model_id:
            raise ValueError("Model config requires model_id")

        api_key = self._resolve_api_key(config)
        temperature = config.get("temperature")
        max_output_tokens = config.get("max_output_tokens")
        retries = int(config.get("retries", 1))
        self._use_json_mode = bool(config.get("use_json_mode", False))

        self._model = Gemini(
            id=str(model_id),
            api_key=api_key,
            temperature=float(temperature) if temperature is not None else None,
            max_output_tokens=int(max_output_tokens) if max_output_tokens is not None else None,
        )
        self._retries = retries

    def generate(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        image_paths: list[Path],
    ) -> T:
        agent = Agent(
            model=self._model,
            output_schema=output_schema,
            use_json_mode=self._use_json_mode,
            markdown=False,
            retries=self._retries,
            telemetry=False,
        )
        images = [Image(filepath=path) for path in image_paths]
        response = agent.run(prompt, images=images)
        content = response.content
        if isinstance(content, output_schema):
            return content
        if isinstance(content, dict):
            return output_schema.model_validate(content)
        if isinstance(content, BaseModel):
            return output_schema.model_validate(content.model_dump())
        raise TypeError(
            f"Agno returned {type(content).__name__}, expected {output_schema.__name__}"
        )

    @staticmethod
    def _resolve_api_key(config: dict[str, Any]) -> str | None:
        env_name = config.get("api_key_env")
        if not env_name:
            return None
        api_key = os.environ.get(str(env_name))
        if not api_key:
            raise RuntimeError(
                f"Required API key environment variable is not set: {env_name}"
            )
        return api_key
