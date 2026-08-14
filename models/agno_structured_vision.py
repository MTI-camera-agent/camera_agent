from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, TypeVar

from agno.agent import Agent
from agno.media import Image
from pydantic import BaseModel, ValidationError

from models.openai_compatible_vlm import OpenAICompatibleVLMClient

T = TypeVar("T", bound=BaseModel)

# DeepSeek official Chat Completions currently rejects multimodal content parts
# (`unknown variant image_url, expected text`). Keep images off that wire format.
_TEXT_ONLY_PROVIDERS = frozenset({"agno.deepseek"})

_BRIDGE_DESCRIBE_PROMPT = (
    "You are assisting an image-editing planner. Describe each provided image "
    "factually and concisely for planning: subjects, pose/expression, camera angle, "
    "framing/composition, lighting, and background. If multiple images are provided, "
    "label them Image 1, Image 2, ... in order. Do not invent objects that are not visible."
)

_TIMEOUT_HINTS = (
    "timed out",
    "timeout",
    "api connection error",
)


class AgnoStructuredVisionClient:
    """Structured multimodal client backed by an Agno Agent.

    Supported ``provider`` values:
    - ``agno.google`` → Gemini (native images)
    - ``agno.deepseek`` → DeepSeek text API; images require ``vision_bridge`` (local VLM)
    - ``agno.openai_compatible`` → OpenAI-compatible Chat API (native images; e.g. MiniCPM)
    """

    def __init__(self, config: dict[str, Any]) -> None:
        model_id = config.get("model_id")
        if not model_id:
            raise ValueError("Model config requires model_id")

        self._provider = str(config.get("provider") or "")
        api_key = self._resolve_api_key(config)
        temperature = config.get("temperature")
        max_output_tokens = config.get("max_output_tokens")
        retries = int(config.get("retries", 1))
        self._use_json_mode = bool(config.get("use_json_mode", False))
        self._model = self._build_model(
            provider=self._provider,
            model_id=str(model_id),
            api_key=api_key,
            temperature=float(temperature) if temperature is not None else None,
            max_output_tokens=(
                int(max_output_tokens) if max_output_tokens is not None else None
            ),
            config=config,
        )
        self._retries = retries
        bridge_cfg = config.get("vision_bridge")
        self._vision_bridge: OpenAICompatibleVLMClient | None = None
        if isinstance(bridge_cfg, dict) and bridge_cfg:
            self._vision_bridge = OpenAICompatibleVLMClient(bridge_cfg)

    def generate(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        image_paths: list[Path],
    ) -> T:
        run_prompt, images = self._prepare_prompt_and_images(
            prompt=prompt, image_paths=image_paths
        )
        agent = Agent(
            model=self._model,
            output_schema=output_schema,
            use_json_mode=self._use_json_mode,
            markdown=False,
            retries=self._retries,
            telemetry=False,
        )
        response = agent.run(run_prompt, images=images or None)
        content = response.content
        if isinstance(content, output_schema):
            return content
        if isinstance(content, dict):
            return output_schema.model_validate(content)
        if isinstance(content, BaseModel):
            return output_schema.model_validate(content.model_dump())
        if isinstance(content, str):
            parsed = self._try_parse_schema_from_text(content, output_schema)
            if parsed is not None:
                return parsed
            self._raise_for_provider_string_error(content, output_schema)
        raise TypeError(
            f"Agno returned {type(content).__name__}, expected {output_schema.__name__}. "
            f"Content preview: {str(content)[:300]!r}"
        )

    @staticmethod
    def _try_parse_schema_from_text(content: str, output_schema: type[T]) -> T | None:
        """Best-effort JSON recovery when servers ignore ``response_format``.

        Only attempts extraction when the text clearly contains a ``{...}`` object.
        """
        text = content.strip()
        if "{" not in text or "}" not in text:
            return None
        # Prefer Agno's robust extractor when available.
        try:
            from agno.utils.string import parse_response_model_str

            parsed = parse_response_model_str(text, output_schema)
            if isinstance(parsed, output_schema):
                return parsed
        except Exception:  # noqa: BLE001 - fall through to local brace extract
            pass
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return None
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
        if not isinstance(data, dict):
            return None
        try:
            return output_schema.model_validate(data)
        except ValidationError:
            return None

    def _raise_for_provider_string_error(
        self, content: str, output_schema: type[BaseModel]
    ) -> None:
        lowered = content.lower()
        if any(hint in lowered for hint in _TIMEOUT_HINTS):
            if self._provider == "agno.deepseek":
                raise RuntimeError(
                    "DeepSeek planner API timed out or failed to connect "
                    f"(provider={self._provider!r}). "
                    "Check network reachability to https://api.deepseek.com, "
                    "DEEPSEEK_API_KEY, and structured_vision.timeout_seconds. "
                    f"Upstream detail: {content[:300]}"
                )
            raise RuntimeError(
                "OpenAI-compatible vision/evaluation API timed out "
                f"(provider={self._provider!r}). "
                "For local MiniCPM check `bash scripts/status_minicpm_server.sh` "
                "and structured_evaluation.timeout_seconds. "
                f"Upstream detail: {content[:300]}"
            )
        if (
            "lis_route_denied" in lowered
            or "无法根据 model 定位推理服务" in content
            or ("无法根据" in content and "model" in lowered)
        ):
            raise RuntimeError(
                "MiniCPM/OpenAI-compatible API could not route the configured model "
                f"(provider={self._provider!r}). "
                "For local :8001, confirm MiniCPM is up "
                "(`bash scripts/status_minicpm_server.sh`) and "
                "structured_evaluation.model_id matches GET /v1/models. "
                "For public ModelBest API, check MINICPM_API_KEY routing and run "
                "`python scripts/probe_minicpm_api.py --base-url https://api.modelbest.co/v1`. "
                f"Upstream detail: {content[:300]}"
            )
        raise RuntimeError(
            f"Model returned non-JSON text; expected {output_schema.__name__} "
            f"(provider={self._provider!r}). "
            "Local transformers serve ignores response_format; ensure the prompt "
            "requires a bare JSON object (see prompts/reflection.md). "
            f"Content preview: {content[:300]!r}"
        )

    def _prepare_prompt_and_images(
        self,
        *,
        prompt: str,
        image_paths: list[Path],
    ) -> tuple[str, list[Image]]:
        if not image_paths:
            return prompt, []

        if self._provider not in _TEXT_ONLY_PROVIDERS:
            return prompt, [Image(filepath=path) for path in image_paths]

        if self._vision_bridge is None:
            raise RuntimeError(
                "DeepSeek Chat API does not accept image_url content parts "
                "(text-only). Configure structured_vision.vision_bridge to a local "
                "OpenAI-compatible VLM (e.g. Qwen3-VL on http://127.0.0.1:8000), "
                "or switch structured_vision.provider to agno.google for native vision."
            )
        observation = self._vision_bridge.describe_images(
            image_paths=image_paths,
            prompt=_BRIDGE_DESCRIBE_PROMPT,
        )
        if not observation:
            raise RuntimeError("Vision bridge returned an empty image description")
        bridged_prompt = (
            f"{prompt}\n\n"
            "## Image observations (from local vision bridge)\n"
            f"{observation}\n"
        )
        return bridged_prompt, []

    @staticmethod
    def _build_model(
        *,
        provider: str,
        model_id: str,
        api_key: str | None,
        temperature: float | None,
        max_output_tokens: int | None,
        config: dict[str, Any],
    ) -> Any:
        timeout = config.get("timeout_seconds")
        timeout_f = float(timeout) if timeout is not None else None

        if provider == "agno.google":
            from agno.models.google import Gemini

            return Gemini(
                id=model_id,
                api_key=api_key,
                temperature=temperature,
                max_output_tokens=max_output_tokens,
            )

        if provider == "agno.deepseek":
            from agno.models.deepseek import DeepSeek

            kwargs = {
                "id": model_id,
                "api_key": api_key,
                "temperature": temperature,
                "max_tokens": max_output_tokens,
            }
            base_url = config.get("base_url")
            if base_url:
                kwargs["base_url"] = str(base_url)
            if "use_thinking" in config:
                kwargs["use_thinking"] = bool(config["use_thinking"])
            if timeout_f is not None:
                kwargs["timeout"] = timeout_f
            return DeepSeek(**kwargs)

        if provider == "agno.openai_compatible":
            from agno.models.openai.like import OpenAILike

            base_url = config.get("base_url")
            if not base_url:
                raise ValueError(
                    "agno.openai_compatible requires base_url "
                    "(e.g. https://api.modelbest.co/v1 or a local OpenAI-compatible VLM)"
                )
            # MiniCPM / many OpenAI-compatible VLMs support JSON mode but not
            # native json_schema structured outputs. Local transformers serve
            # also ignores response_format — prompt + parse fallback enforce JSON.
            # Local servers often ignore auth; OpenAI clients still expect a key.
            kwargs = {
                "id": model_id,
                "name": str(config.get("name") or "OpenAICompatible"),
                "api_key": api_key or "local-no-auth",
                "base_url": str(base_url),
                "temperature": temperature,
                "max_tokens": max_output_tokens,
                "supports_native_structured_outputs": False,
            }
            if timeout_f is not None:
                kwargs["timeout"] = timeout_f
            return OpenAILike(**kwargs)

        raise ValueError(
            f"Unsupported Agno structured vision provider {provider!r}. "
            "Available: agno.google, agno.deepseek, agno.openai_compatible"
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
