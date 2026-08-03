"""Exercise fixed-plan photographic semantics on controlled plant frames."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from camera_agent.adapters.gemini import GeminiReasoner
from camera_agent.domain import (
    ImageData,
    PlanStep,
    PlanningRequest,
    ShotPlan,
    VerificationRequest,
)

FIXTURES = Path("tests/fixtures/plant")
INTENTION = "A close shot of the green plant"
CAMERA = {
    "lensID": "wide-camera",
    "zoomFactor": 1.0,
    "focusPoint": None,
    "exposurePoint": None,
    "exposureBias": 0.0,
    "orientation": "portrait",
    "frameWidth": 480,
    "frameHeight": 640,
    "cropAspectRatio": 0.75,
    "rollRadians": 0.0,
    "pitchRadians": 0.0,
}


def image(name: str) -> ImageData:
    return image_path(FIXTURES / name)


def image_path(path: Path) -> ImageData:
    return ImageData(path.read_bytes(), "image/jpeg", 480, 640)


async def evaluate(
    good_close_path: Path | None = None,
    overcropped_path: Path | None = None,
) -> None:
    reasoner = GeminiReasoner(max_output_tokens=1200)
    edge = await reasoner.create_plan(
        PlanningRequest(
            intention=INTENTION,
            sample_allowed=False,
            camera=CAMERA,
            observation_reason="intention_updated",
            current_image=image("plant-at-right-edge.jpg"),
        )
    )
    scale_plan = ShotPlan(
        (PlanStep("close-scale", "composition", "Plant dominates the frame"),)
    )
    close = await reasoner.verify_step(
        VerificationRequest(
            intention=INTENTION,
            sample_allowed=False,
            plan=scale_plan,
            active_step_index=0,
            current_instruction="Move slightly closer.",
            was_ready=False,
            camera=CAMERA,
            observation_reason="stream",
            baseline_image=image("plant-medium-centered.jpg"),
            current_image=image("plant-close-filled.jpg"),
        )
    )
    focus_plan = ShotPlan(
        (PlanStep("focus", "exposure_focus", "Plant is clearly focused"),)
    )
    focus = await reasoner.verify_step(
        VerificationRequest(
            intention=INTENTION,
            sample_allowed=False,
            plan=focus_plan,
            active_step_index=0,
            current_instruction="Tap the plant to focus.",
            was_ready=False,
            camera={**CAMERA, "focusPoint": {"x": 0.5, "y": 0.42}},
            observation_reason="focus_changed",
            baseline_image=image("plant-close-blurry.jpg"),
            current_image=image("plant-close-filled.jpg"),
        )
    )

    print("edge:", edge.instruction, edge.assessment)
    print("close:", close.outcome.value, close.instruction, close.assessment)
    print("focus:", focus.outcome.value, focus.instruction, focus.assessment)
    edge_text = (edge.instruction or "").lower()
    if good_close_path is not None and overcropped_path is not None:
        intention = "A close view of the entire shirt"
        good_close = await reasoner.create_plan(
            PlanningRequest(
                intention=intention,
                sample_allowed=False,
                camera=CAMERA,
                observation_reason="intention_updated",
                current_image=image_path(good_close_path),
            )
        )
        overcropped = await reasoner.create_plan(
            PlanningRequest(
                intention=intention,
                sample_allowed=False,
                camera=CAMERA,
                observation_reason="intention_updated",
                current_image=image_path(overcropped_path),
            )
        )
        print("good-close:", good_close.ready, good_close.instruction)
        print("overcropped:", overcropped.ready, overcropped.instruction)
        good_text = (good_close.instruction or "").lower()
        assert "closer" not in good_text and "zoom in" not in good_text
        overcropped_text = (overcropped.instruction or "").lower()
        assert any(
            phrase in overcropped_text
            for phrase in ("wider", "move back", "further away", "zoom out")
        ), overcropped.instruction
    assert "right" in edge_text and "left" not in edge_text, edge.instruction
    assert close.outcome.value == "ready"
    assert focus.outcome.value == "ready"


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--good-close", type=Path)
    parser.add_argument("--overcropped", type=Path)
    arguments = parser.parse_args()
    if (arguments.good_close is None) != (arguments.overcropped is None):
        parser.error("--good-close and --overcropped must be provided together")
    asyncio.run(evaluate(arguments.good_close, arguments.overcropped))
