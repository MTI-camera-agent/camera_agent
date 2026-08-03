"""Opt-in, bounded recording of exact VLM inputs and outcomes."""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from pathlib import Path
from typing import Any

from .domain import (
    ObservationContext,
    PlanningDecision,
    VerificationDecision,
)


class ArtifactRecorder:
    def __init__(self, root: Path, *, max_files: int = 200) -> None:
        stamp = f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"
        self.directory = root.expanduser().resolve() / stamp
        self.directory.mkdir(parents=True, exist_ok=False)
        self._max_files = max_files
        self._sequence = 0

    def record_attempt(
        self,
        *,
        phase: str,
        task_id: str,
        intention: str,
        context: ObservationContext,
        baseline_image_message_id: str | None,
        disposition: str,
        result: PlanningDecision | VerificationDecision | None,
        error: str | None = None,
    ) -> None:
        if self._sequence * 2 >= self._max_files:
            return
        self._sequence += 1
        prefix = (
            f"{self._sequence:04d}-{phase}-observation-{context.observation_id}"
        )
        suffix = ".jpg" if context.image.mime_type == "image/jpeg" else ".png"
        (self.directory / f"{prefix}{suffix}").write_bytes(context.image.data)
        payload: dict[str, Any] = {
            "phase": phase,
            "taskId": task_id,
            "intention": intention,
            "disposition": disposition,
            "observationId": context.observation_id,
            "imageMessageId": context.image_message_id,
            "imageSha256": hashlib.sha256(context.image.data).hexdigest(),
            "baselineImageMessageId": baseline_image_message_id,
            "timestampMs": context.timestamp_ms,
            "reason": context.reason,
            "camera": dict(context.camera),
            "error": error,
            "result": self._serialize_result(result),
        }
        (self.directory / f"{prefix}.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    @staticmethod
    def _serialize_result(
        result: PlanningDecision | VerificationDecision | None,
    ) -> dict[str, Any] | None:
        if result is None:
            return None
        if isinstance(result, PlanningDecision):
            return {
                "assessment": result.assessment,
                "ready": result.ready,
                "plan": result.plan.to_prompt(),
                "instruction": result.instruction,
                "overlays": [overlay.to_wire() for overlay in result.overlays],
                "sampleInstruction": result.sample_instruction,
            }
        return {
            "assessment": result.assessment,
            "outcome": result.outcome.value,
            "stepIndex": result.step_index,
            "instruction": result.instruction,
            "overlays": [overlay.to_wire() for overlay in result.overlays],
            "sampleInstruction": result.sample_instruction,
        }
