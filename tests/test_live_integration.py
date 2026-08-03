from __future__ import annotations

import os
from pathlib import Path

import pytest
from PIL import Image

from camera_agent.adapters import GeminiReasoner, HttpImageEditor
from camera_agent.domain import ImageData, PlanningRequest
from tests.helpers import camera

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_LIVE_AGENT_TESTS") != "1",
    reason="set RUN_LIVE_AGENT_TESTS=1 to call the real model adapters",
)

IMAGE_PATH = Path("models/test_img/stand_female_0.jpg")


def load_image() -> ImageData:
    data = IMAGE_PATH.read_bytes()
    with Image.open(IMAGE_PATH) as decoded:
        width, height = decoded.size
    return ImageData(data, "image/jpeg", width, height)


@pytest.mark.asyncio
async def test_real_gemini_structured_decision() -> None:
    reasoner = GeminiReasoner(max_output_tokens=1200)
    decision = await reasoner.create_plan(
        PlanningRequest(
            intention="A confident full-body portrait. Show me a pose reference.",
            sample_allowed=True,
            camera=camera(),
            observation_reason="intention_updated",
            current_image=load_image(),
        )
    )
    assert decision.ready or 1 <= len(decision.plan.steps) <= 5
    assert decision.assessment
    assert decision.sample_instruction


@pytest.mark.asyncio
async def test_real_editor_returns_protocol_supported_image() -> None:
    editor = HttpImageEditor(timeout_seconds=180)
    edited = await editor.edit(
        load_image(),
        (
            "Change the main subject's pose from standing to sitting. Preserve identity, "
            "clothing, background, lighting, and framing."
        ),
    )
    assert edited.image.mime_type in {"image/jpeg", "image/png"}
    assert edited.image.width > 0
    assert edited.image.height > 0
    assert edited.image.data
