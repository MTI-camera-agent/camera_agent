from __future__ import annotations

from typing import Any, Callable

from models.protocols import ImageGenerationClient, StructuredVisionClient

StructuredProvider = Callable[[dict[str, Any]], StructuredVisionClient]
ImageProvider = Callable[[dict[str, Any]], ImageGenerationClient]


def build_structured_vision_client(config: dict[str, Any]) -> StructuredVisionClient:
    provider = _require_provider(config)
    factory = _structured_provider(provider)
    return factory(config)


def build_image_generator(config: dict[str, Any]) -> ImageGenerationClient:
    provider = _require_provider(config)
    factory = _image_provider(provider)
    return factory(config)


def _require_provider(config: dict[str, Any]) -> str:
    provider = config.get("provider")
    if not provider:
        raise ValueError("Provider config requires a provider field")
    return str(provider)


def _structured_provider(provider: str) -> StructuredProvider:
    if provider in {"agno.google", "agno.deepseek", "agno.openai_compatible"}:
        from models.agno_structured_vision import AgnoStructuredVisionClient

        return AgnoStructuredVisionClient
    available = "agno.google, agno.deepseek, agno.openai_compatible"
    raise ValueError(f"Unknown structured vision provider {provider!r}. Available: {available}")


def _image_provider(provider: str) -> ImageProvider:
    if provider == "comfyui":
        from models.comfyui_image import ComfyUIImageEditClient

        return ComfyUIImageEditClient
    if provider == "openai_compatible":
        from models.image_generation import OpenAICompatibleImageClient

        return OpenAICompatibleImageClient
    available = "comfyui, openai_compatible"
    raise ValueError(f"Unknown image provider {provider!r}. Available: {available}")
