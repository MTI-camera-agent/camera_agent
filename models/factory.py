from __future__ import annotations

from typing import Any, Callable

from models.agno_structured_vision import AgnoStructuredVisionClient
from models.image_generation import OpenAICompatibleImageClient
from models.protocols import ImageGenerationClient, StructuredVisionClient

StructuredProvider = Callable[[dict[str, Any]], StructuredVisionClient]
ImageProvider = Callable[[dict[str, Any]], ImageGenerationClient]

_STRUCTURED_PROVIDERS: dict[str, StructuredProvider] = {
    "agno.google": AgnoStructuredVisionClient,
}

_IMAGE_PROVIDERS: dict[str, ImageProvider] = {
    "openai_compatible": OpenAICompatibleImageClient,
}


def build_structured_vision_client(config: dict[str, Any]) -> StructuredVisionClient:
    provider = _require_provider(config)
    try:
        factory = _STRUCTURED_PROVIDERS[provider]
    except KeyError as exc:
        available = ", ".join(sorted(_STRUCTURED_PROVIDERS))
        raise ValueError(f"Unknown structured vision provider {provider!r}. Available: {available}") from exc
    return factory(config)


def build_image_generator(config: dict[str, Any]) -> ImageGenerationClient:
    provider = _require_provider(config)
    try:
        factory = _IMAGE_PROVIDERS[provider]
    except KeyError as exc:
        available = ", ".join(sorted(_IMAGE_PROVIDERS))
        raise ValueError(f"Unknown image provider {provider!r}. Available: {available}") from exc
    return factory(config)


def _require_provider(config: dict[str, Any]) -> str:
    provider = config.get("provider")
    if not provider:
        raise ValueError("Provider config requires a provider field")
    return str(provider)
