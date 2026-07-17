from __future__ import annotations

import os
import subprocess
import json
from pathlib import Path

import httpx
import pytest

from agents import PlannerAgent, ReflectorAgent
from agents.prompt_loader import PromptLoader
from models import build_image_generator, build_structured_vision_client
from schemas.state import ExecutionState
from tools import create_default_tool_registry
from tools.base import ExecutionOptions
from workflow import ImageLoop, PlanCompiler, StateManager, ToolExecutor


pytestmark = pytest.mark.integration


def _live_enabled() -> bool:
    return os.environ.get("RUN_LIVE_AGENT_TESTS") == "1"


def _ensure_gemini_key() -> bool:
    if os.environ.get("GEMINI_API_KEY"):
        return True
    command = ["bash", "-ic", 'printf %s "$GEMINI_API_KEY"']
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    key = result.stdout.strip()
    if not key:
        return False
    os.environ["GEMINI_API_KEY"] = key
    return True


def _flux_service_available() -> bool:
    try:
        response = httpx.get("http://127.0.0.1:8010/health", timeout=5)
    except httpx.HTTPError:
        return False
    return response.status_code == 200


def test_live_gemini_planner_loop_resize(tmp_path: Path) -> None:
    if not _live_enabled():
        pytest.skip("Set RUN_LIVE_AGENT_TESTS=1 to run live provider checks")
    if not _ensure_gemini_key():
        pytest.skip("GEMINI_API_KEY is required for the live Agno planner check")

    registry = create_default_tool_registry()
    client = build_structured_vision_client(
        {
            "provider": "agno.google",
            "model_id": "gemini-2.5-flash",
            "api_key_env": "GEMINI_API_KEY",
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "use_json_mode": True,
        }
    )
    prompt_loader = PromptLoader(Path("prompts"))
    planner = PlannerAgent(client, prompt_loader, registry.specs_markdown())
    reflector = ReflectorAgent(client, prompt_loader)
    loop = ImageLoop(
        planner=planner,
        reflector=reflector,
        compiler=PlanCompiler(registry),
        executor=ToolExecutor(output_dir=tmp_path / "images", mask_dir=tmp_path / "masks"),
        state_manager=StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans"),
        max_iterations=1,
    )

    result = loop.run(
        image_path=Path("test_img/stand_female_0.jpg"),
        user_prompt="Resize the image to exactly 64 pixels wide and 64 pixels tall. Use the resize tool.",
    )

    assert result.final_image.exists()
    assert isinstance(result.state, ExecutionState)
    assert result.state.evaluations


def test_live_image_generator_health() -> None:
    if not _live_enabled():
        pytest.skip("Set RUN_LIVE_AGENT_TESTS=1 to run live provider checks")
    if not _flux_service_available():
        pytest.skip("Image generation service did not return healthy status")

    generator = build_image_generator(
        {
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:8010",
            "timeout_seconds": None,
            "guidance_scale": 1.0,
            "num_inference_steps": 4,
            "seed": 0,
        }
    )

    assert generator.healthcheck()


def test_live_gemini_flux_background_edit_loop(tmp_path: Path) -> None:
    if not _live_enabled():
        pytest.skip("Set RUN_LIVE_AGENT_TESTS=1 to run live provider checks")
    if not _ensure_gemini_key():
        pytest.skip("GEMINI_API_KEY is required for the live Agno planner check")
    if not _flux_service_available():
        pytest.skip("Image generation service did not return healthy status")

    registry = create_default_tool_registry()
    vision_client = build_structured_vision_client(
        {
            "provider": "agno.google",
            "model_id": "gemini-2.5-flash",
            "api_key_env": "GEMINI_API_KEY",
            "temperature": 0.0,
            "max_output_tokens": 4096,
            "use_json_mode": True,
        }
    )
    image_generator = build_image_generator(
        {
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:8010",
            "timeout_seconds": None,
            "guidance_scale": 1.0,
            "num_inference_steps": 4,
            "seed": 0,
        }
    )
    prompt_loader = PromptLoader(Path("prompts"))
    loop = ImageLoop(
        planner=PlannerAgent(vision_client, prompt_loader, registry.specs_markdown()),
        reflector=ReflectorAgent(vision_client, prompt_loader),
        compiler=PlanCompiler(registry),
        executor=ToolExecutor(
            output_dir=tmp_path / "images",
            mask_dir=tmp_path / "masks",
            services={"image_generator": image_generator},
        ),
        state_manager=StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans"),
        max_iterations=1,
    )

    result = loop.run(
        image_path=Path("test_img/stand_female_0.jpg"),
        user_prompt=(
            "Use the replace_background tool exactly once to change the background "
            "to a sunny beach while preserving the person, pose, clothing, and camera perspective."
        ),
    )

    assert result.final_image.exists()
    assert result.final_image.parent == tmp_path / "images"
    assert any(
        entry.action.action in {"replace_background", "edit_image"}
        for entry in result.state.history
    )
    assert result.state.evaluations


def test_live_gemini_flux_replans_after_debug_weak_background_pass(tmp_path: Path) -> None:
    if not _live_enabled():
        pytest.skip("Set RUN_LIVE_AGENT_TESTS=1 to run live provider checks")
    if not _ensure_gemini_key():
        pytest.skip("GEMINI_API_KEY is required for the live Agno planner check")
    if not _flux_service_available():
        pytest.skip("Image generation service did not return healthy status")

    registry = create_default_tool_registry()
    vision_client = build_structured_vision_client(
        {
            "provider": "agno.google",
            "model_id": "gemini-2.5-flash",
            "api_key_env": "GEMINI_API_KEY",
            "temperature": 0.0,
            "max_output_tokens": 4096,
            "use_json_mode": True,
        }
    )
    image_generator = build_image_generator(
        {
            "provider": "openai_compatible",
            "base_url": "http://127.0.0.1:8010",
            "timeout_seconds": None,
            "guidance_scale": 1.0,
            "num_inference_steps": 4,
            "seed": 0,
        }
    )
    prompt_loader = PromptLoader(Path("prompts"))
    loop = ImageLoop(
        planner=PlannerAgent(vision_client, prompt_loader, registry.specs_markdown()),
        reflector=ReflectorAgent(vision_client, prompt_loader),
        compiler=PlanCompiler(registry),
        executor=ToolExecutor(
            output_dir=tmp_path / "images",
            mask_dir=tmp_path / "masks",
            services={"image_generator": image_generator},
            execution_options=ExecutionOptions(
                replace_background_refine_disabled_iterations={0}
            ),
        ),
        state_manager=StateManager(log_dir=tmp_path / "logs", plan_dir=tmp_path / "plans"),
        max_iterations=2,
    )

    result = loop.run(
        image_path=Path("test_img/stand_female_1.jpg"),
        user_prompt="Change the background to a sunny beach.",
    )

    assert len(result.state.evaluations) >= 2
    assert result.state.evaluations[0].satisfied is False
    first_state = json.loads((tmp_path / "logs" / "state_iter_00.json").read_text())
    assert any(
        artifact["data"].get("refine_disabled_reason")
        == "debug_disable_refine_first_iteration"
        for artifact in first_state["artifacts"].values()
    )
