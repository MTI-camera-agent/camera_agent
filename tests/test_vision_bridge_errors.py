from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from models.openai_compatible_vlm import OpenAICompatibleVLMClient


def test_vision_bridge_engine_dead_raises_patch_guidance(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake-jpeg")
    client = OpenAICompatibleVLMClient(
        {"base_url": "http://127.0.0.1:8000", "model_id": "Qwen3-VL-8B-Photography_FP8"}
    )
    request = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
    response = httpx.Response(
        500,
        request=request,
        text=(
            '{"error":{"message":"EngineCore encountered an issue. '
            "ValueError: Requested more deepstack tokens than available in buffer\","
            '"type":"InternalServerError"}}'
        ),
    )
    with patch("models.openai_compatible_vlm.httpx.post", return_value=response):
        with pytest.raises(RuntimeError, match="patch_vllm_qwen3vl_deepstack"):
            client.describe_images(image_paths=[image], prompt="describe")


def test_vision_bridge_generic_4xx_keeps_simple_message(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake-jpeg")
    client = OpenAICompatibleVLMClient(
        {"base_url": "http://127.0.0.1:8000", "model_id": "Qwen3-VL-8B-Photography_FP8"}
    )
    request = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
    response = httpx.Response(400, request=request, text='{"error":"bad request"}')
    with patch("models.openai_compatible_vlm.httpx.post", return_value=response):
        with pytest.raises(RuntimeError, match="Vision bridge chat failed HTTP 400"):
            client.describe_images(image_paths=[image], prompt="describe")


def test_http_error_helper_detects_enginedead_without_deepstack_word() -> None:
    client = OpenAICompatibleVLMClient({"base_url": "http://127.0.0.1:8000"})
    request = httpx.Request("POST", "http://127.0.0.1:8000/v1/chat/completions")
    response = httpx.Response(
        500,
        request=request,
        text='{"error":{"message":"EngineDeadError: EngineCore encountered an issue."}}',
    )
    err = client._http_error(response)
    assert "restart_required_services" in str(err)
    assert "patch_vllm_qwen3vl_deepstack" in str(err)
