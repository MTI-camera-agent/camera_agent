from __future__ import annotations

import time
import uuid
from io import BytesIO
from pathlib import Path

from PIL import Image

from camera_agent.domain import (
    ImageData,
    ObservationContext,
    PlanStep,
    PlanningDecision,
    ShotPlan,
    VerificationDecision,
    VerificationOutcome,
)


def _fixture_jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (32, 32), (80, 110, 140)).save(output, format="JPEG")
    return output.getvalue()


JPEG = _fixture_jpeg()


def fixture(name: str) -> bytes:
    return (Path(__file__).parent / "fixtures" / "plant" / name).read_bytes()


def camera() -> dict:
    return {
        "lensID": "wide-camera",
        "lensName": "Back Camera",
        "zoomFactor": 1,
        "focalLength35mm": 24,
        "focusPoint": None,
        "exposurePoint": None,
        "exposureBias": 0,
        "iso": 50,
        "exposureDurationSeconds": 0.01,
        "whiteBalanceRedGain": 2,
        "whiteBalanceGreenGain": 1,
        "whiteBalanceBlueGain": 1.8,
        "flashMode": "off",
        "orientation": "portrait",
        "frameWidth": 480,
        "frameHeight": 640,
        "cropAspectRatio": 0.75,
        "rollRadians": 0,
        "pitchRadians": 0,
    }


def observation_message(
    observation_id: int = 1,
    *,
    reason: str = "stream",
    intention: str = "A confident portrait",
    image_message_id: str | None = None,
) -> dict:
    return {
        "type": "observation",
        "version": 1,
        "messageId": str(uuid.uuid4()),
        "observationId": observation_id,
        "timestampMs": 1000 + observation_id,
        "reason": reason,
        "intention": intention,
        "camera": camera(),
        "imageMessageId": image_message_id or str(uuid.uuid4()),
    }


def preview_header(observation: dict, *, width: int = 480, height: int = 640) -> dict:
    return {
        "type": "preview_image",
        "version": 1,
        "messageId": observation["imageMessageId"],
        "observationId": observation["observationId"],
        "requestId": None,
        "timestampMs": observation["timestampMs"],
        "mimeType": "image/jpeg",
        "width": width,
        "height": height,
        "initiation": None,
    }


def context(
    observation_id: int = 1,
    *,
    reason: str = "stream",
    intention: str = "A confident portrait",
    image: bytes = JPEG,
) -> ObservationContext:
    return ObservationContext(
        observation_id=observation_id,
        timestamp_ms=1000 + observation_id,
        reason=reason,
        intention=intention,
        camera=camera(),
        image_message_id=str(uuid.uuid4()),
        image=ImageData(image, "image/jpeg", 480, 640),
        received_monotonic=time.monotonic(),
    )


def shot_plan(*criteria: str) -> ShotPlan:
    values = criteria or ("Place the subject on the left third",)
    return ShotPlan(
        tuple(
            PlanStep(f"step-{index}", "composition", criterion)
            for index, criterion in enumerate(values)
        )
    )


def planning(
    instruction: str | None = "Move the subject slightly left.",
    *,
    plan: ShotPlan | None = None,
    ready: bool = False,
    sample_instruction: str | None = None,
) -> PlanningDecision:
    return PlanningDecision(
        assessment="Current view assessed.",
        plan=plan or shot_plan(),
        ready=ready,
        instruction=instruction,
        sample_instruction=sample_instruction,
    )


def verification(
    outcome: VerificationOutcome = VerificationOutcome.HOLD,
    *,
    instruction: str | None = None,
    step_index: int | None = None,
) -> VerificationDecision:
    return VerificationDecision(
        outcome=outcome,
        assessment="Compared fixed step with current view.",
        instruction=instruction,
        step_index=step_index,
    )
