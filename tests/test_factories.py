from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from models.agno_structured_vision import AgnoStructuredVisionClient
from models.comfyui_image import ComfyUIImageEditClient
from models.factory import build_image_generator, build_structured_vision_client

REPO = Path(__file__).resolve().parents[1]
QWEN2511_WORKFLOW = REPO / "assets/comfyui/qwen2511/workflow.api.json"
QWEN2511_SCHEMA = REPO / "assets/comfyui/qwen2511/schema.json"


def test_structured_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown structured vision provider"):
        build_structured_vision_client({"provider": "missing"})


def test_structured_factory_builds_deepseek_client() -> None:
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
        client = build_structured_vision_client(
            {
                "provider": "agno.deepseek",
                "model_id": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "use_json_mode": True,
                "use_thinking": False,
            }
        )
    assert isinstance(client, AgnoStructuredVisionClient)


def test_deepseek_client_requires_api_key_env() -> None:
    env = {k: v for k, v in os.environ.items() if k != "DEEPSEEK_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="DEEPSEEK_API_KEY"):
            build_structured_vision_client(
                {
                    "provider": "agno.deepseek",
                    "model_id": "deepseek-v4-flash",
                    "api_key_env": "DEEPSEEK_API_KEY",
                }
            )


def test_deepseek_requires_vision_bridge_when_images_present(
    tmp_path: Path,
) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n")
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
        client = build_structured_vision_client(
            {
                "provider": "agno.deepseek",
                "model_id": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "use_json_mode": True,
                "use_thinking": False,
            }
        )
    with pytest.raises(RuntimeError, match="vision_bridge"):
        client._prepare_prompt_and_images(prompt="plan", image_paths=[image])


def test_structured_factory_builds_openai_compatible_minicpm() -> None:
    client = build_structured_vision_client(
        {
            "provider": "agno.openai_compatible",
            "model_id": "MiniCPM-V-4.6",
            "base_url": "http://127.0.0.1:8001/v1",
            "use_json_mode": True,
        }
    )
    assert isinstance(client, AgnoStructuredVisionClient)
    assert client._provider == "agno.openai_compatible"


def test_openai_compatible_local_allows_missing_api_key() -> None:
    env = {k: v for k, v in os.environ.items() if k != "MINICPM_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        client = build_structured_vision_client(
            {
                "provider": "agno.openai_compatible",
                "model_id": "MiniCPM-V-4.6",
                "base_url": "http://127.0.0.1:8001/v1",
                "use_json_mode": True,
            }
        )
    assert isinstance(client, AgnoStructuredVisionClient)


def test_openai_compatible_requires_api_key_when_env_configured() -> None:
    env = {k: v for k, v in os.environ.items() if k != "MINICPM_API_KEY"}
    with patch.dict(os.environ, env, clear=True):
        with pytest.raises(RuntimeError, match="MINICPM_API_KEY"):
            build_structured_vision_client(
                {
                    "provider": "agno.openai_compatible",
                    "model_id": "MiniCPM-V-4.6-Instruct",
                    "api_key_env": "MINICPM_API_KEY",
                    "base_url": "https://api.modelbest.co/v1",
                }
            )


def test_openai_compatible_requires_base_url() -> None:
    with pytest.raises(ValueError, match="base_url"):
        build_structured_vision_client(
            {
                "provider": "agno.openai_compatible",
                "model_id": "MiniCPM-V-4.6",
                "use_json_mode": True,
            }
        )


def test_openai_compatible_passes_native_images(tmp_path: Path) -> None:
    image_a = tmp_path / "a.jpg"
    image_b = tmp_path / "b.jpg"
    image_a.write_bytes(b"fake-a")
    image_b.write_bytes(b"fake-b")
    client = build_structured_vision_client(
        {
            "provider": "agno.openai_compatible",
            "model_id": "MiniCPM-V-4.6",
            "base_url": "http://127.0.0.1:8001/v1",
            "use_json_mode": True,
        }
    )
    prompt, images = client._prepare_prompt_and_images(
        prompt="Judge original vs current.",
        image_paths=[image_a, image_b],
    )
    assert prompt == "Judge original vs current."
    assert len(images) == 2


def test_config_yaml_splits_planner_and_evaluation() -> None:
    import yaml

    raw = yaml.safe_load((REPO / "config.yaml").read_text(encoding="utf-8"))
    assert raw["structured_vision"]["provider"] == "agno.deepseek"
    assert raw["structured_evaluation"]["provider"] == "agno.openai_compatible"
    assert raw["structured_evaluation"]["model_id"] == "MiniCPM-V-4.6"
    assert raw["structured_evaluation"]["base_url"] == "http://127.0.0.1:8001/v1"
    assert not raw["structured_evaluation"].get("api_key_env")


def test_deepseek_bridges_images_to_text(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake-jpeg")
    with patch.dict(os.environ, {"DEEPSEEK_API_KEY": "test-key"}, clear=False):
        client = build_structured_vision_client(
            {
                "provider": "agno.deepseek",
                "model_id": "deepseek-v4-flash",
                "api_key_env": "DEEPSEEK_API_KEY",
                "use_json_mode": True,
                "use_thinking": False,
                "vision_bridge": {"base_url": "http://127.0.0.1:8000"},
            }
        )
    assert client._vision_bridge is not None
    with patch.object(
        client._vision_bridge,
        "describe_images",
        return_value="A person facing slightly left.",
    ) as describe:
        prompt, images = client._prepare_prompt_and_images(
            prompt="Adjust camera angle.",
            image_paths=[image],
        )
    describe.assert_called_once()
    assert images == []
    assert "Image observations" in prompt
    assert "A person facing slightly left." in prompt


def test_image_factory_rejects_unknown_provider() -> None:
    with pytest.raises(ValueError, match="Unknown image provider"):
        build_image_generator({"provider": "missing"})


def test_image_factory_builds_comfyui_client() -> None:
    client = build_image_generator(
        {
            "provider": "comfyui",
            "base_url": "http://127.0.0.1:8188",
            "workflow_api_path": str(QWEN2511_WORKFLOW),
            "schema_path": str(QWEN2511_SCHEMA),
        }
    )
    assert isinstance(client, ComfyUIImageEditClient)


def test_comfyui_generate_is_edit_only() -> None:
    client = ComfyUIImageEditClient(
        {
            "base_url": "http://127.0.0.1:8188",
            "workflow_api_path": str(QWEN2511_WORKFLOW),
            "schema_path": str(QWEN2511_SCHEMA),
        }
    )
    with pytest.raises(RuntimeError, match="image-edit only"):
        client.generate(prompt="x", output_path=REPO / "outputs" / "x.png")


def test_comfyui_inject_params_sets_image_and_prompt() -> None:
    client = ComfyUIImageEditClient(
        {
            "base_url": "http://127.0.0.1:8188",
            "workflow_api_path": str(QWEN2511_WORKFLOW),
            "schema_path": str(QWEN2511_SCHEMA),
        }
    )
    workflow = client._inject_params(uploaded_name="frame.png", prompt="调整构图")
    assert workflow["78"]["inputs"]["image"] == "frame.png"
    assert workflow["435"]["inputs"]["value"] == "调整构图"


def test_qwen2511_workflow_uses_lightning8_and_long_side_512() -> None:
    workflow = json.loads(QWEN2511_WORKFLOW.read_text(encoding="utf-8"))
    schema = json.loads(QWEN2511_SCHEMA.read_text(encoding="utf-8"))

    assert "nodes" not in workflow
    assert workflow["78"]["class_type"] == "LoadImage"
    assert (
        workflow["433:89"]["inputs"]["lora_name"]
        == "Qwen-Image-Edit-2511-Lightning-8steps-V1.0-bf16.safetensors"
    )
    assert workflow["433:3"]["inputs"]["steps"] == 8
    assert workflow["433:117"]["class_type"] == "ImageScaleToMaxDimension"
    assert workflow["433:117"]["inputs"]["largest_size"] == 512
    assert schema["parameters"]["steps_433_3"]["default"] == 8
    assert schema["parameters"]["image"]["node_id"] == "78"
    assert schema["parameters"]["prompt"]["node_id"] == "435"