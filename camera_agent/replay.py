"""Replay observation manifests through the real coaching-loop interface."""

from __future__ import annotations

import json
import time
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from .coaching import CoachingLoop
from .config import HarnessConfig
from .domain import CoachingEvent, ImageData, ObservationContext
from .ports import Reasoner
from .protocol import validate_message


async def replay_manifest(
    path: Path,
    reasoner: Reasoner,
    config: HarnessConfig,
) -> None:
    async def print_event(event: CoachingEvent) -> None:
        print(
            json.dumps(
                {
                    "kind": event.kind.value,
                    "taskId": event.task_id,
                    "observationId": event.context.observation_id,
                    "intention": event.intention,
                    "stepId": event.step_id,
                    "instruction": event.instruction,
                },
                ensure_ascii=False,
            )
        )

    loop = CoachingLoop(reasoner, config.change_detection, print_event)
    await loop.start()
    try:
        manifest = path.expanduser().resolve()
        for line_number, raw_line in enumerate(
            manifest.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not raw_line.strip() or raw_line.lstrip().startswith("#"):
                continue
            value: dict[str, Any] = json.loads(raw_line)
            observation = validate_message(value["observation"])
            image_path = (manifest.parent / value["imagePath"]).resolve()
            image_bytes = image_path.read_bytes()
            with Image.open(BytesIO(image_bytes)) as decoded:
                width, height = decoded.size
                image_format = (decoded.format or "").upper()
            mime_type = {"JPEG": "image/jpeg", "PNG": "image/png"}.get(
                image_format
            )
            if mime_type is None:
                raise ValueError(
                    f"line {line_number}: unsupported image format {image_format}"
                )
            await loop.submit(
                ObservationContext(
                    observation_id=int(observation["observationId"]),
                    timestamp_ms=int(observation["timestampMs"]),
                    reason=str(observation["reason"]),
                    intention=str(observation["intention"]),
                    camera=dict(observation["camera"]),
                    image_message_id=str(observation["imageMessageId"]),
                    image=ImageData(
                        image_bytes,
                        mime_type,
                        width,
                        height,
                    ),
                    received_monotonic=time.monotonic(),
                )
            )
            await loop.flush()
    finally:
        await loop.close()
