"""Cheap, deterministic gating for routine camera observations."""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Mapping

from PIL import Image, ImageFilter, ImageStat

from .config import ChangeDetectionConfig
from .domain import ObservationContext

LOGGER = logging.getLogger("camera_agent.change_detection")


@dataclass(frozen=True, slots=True)
class ChangeAssessment:
    significant: bool
    reasons: tuple[str, ...]
    visual_global_mae: float = 0.0
    visual_block_mae: float = 0.0
    visual_hash_distance: int = 0


@dataclass(frozen=True, slots=True)
class _VisualSignature:
    values: tuple[float, ...]
    difference_hash: tuple[bool, ...]


class ObservationChangeDetector:
    """Compare a candidate with the last observation actually analyzed."""

    def __init__(self, config: ChangeDetectionConfig) -> None:
        self._config = config
        self._reference_cache: tuple[str, _VisualSignature] | None = None
        self._candidate_cache: tuple[str, _VisualSignature] | None = None

    def assess(
        self,
        reference: ObservationContext | None,
        candidate: ObservationContext,
    ) -> ChangeAssessment:
        if reference is None:
            return ChangeAssessment(True, ("first_analysis",))

        reasons = self._metadata_reasons(reference.camera, candidate.camera)
        try:
            global_mae, block_mae, hash_distance = self._visual_scores(
                reference, candidate
            )
        except (OSError, ValueError) as error:
            LOGGER.warning(
                "visual change decoding failed reference=%s candidate=%s error=%s",
                reference.observation_id,
                candidate.observation_id,
                error,
            )
            return ChangeAssessment(True, (*reasons, "visual_decode_failed"))

        if global_mae >= self._config.visual_global_mae:
            reasons.append("visual_global")
        if block_mae >= self._config.visual_block_mae:
            reasons.append("visual_local")
        hash_has_visual_support = (
            global_mae >= self._config.visual_global_mae / 2
            or block_mae >= self._config.visual_block_mae / 2
        )
        if (
            hash_distance >= self._config.visual_hash_distance
            and hash_has_visual_support
        ):
            reasons.append("visual_hash")
        assessment = ChangeAssessment(
            significant=bool(reasons),
            reasons=tuple(reasons),
            visual_global_mae=global_mae,
            visual_block_mae=block_mae,
            visual_hash_distance=hash_distance,
        )
        LOGGER.debug(
            "change reference=%s candidate=%s significant=%s reasons=%s "
            "global_mae=%.4f/%.4f block_mae=%.4f/%.4f hash=%s/%s",
            reference.observation_id,
            candidate.observation_id,
            assessment.significant,
            ",".join(assessment.reasons) or "none",
            global_mae,
            self._config.visual_global_mae,
            block_mae,
            self._config.visual_block_mae,
            hash_distance,
            self._config.visual_hash_distance,
        )
        return assessment

    def _metadata_reasons(
        self,
        reference: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> list[str]:
        reasons: list[str] = []
        for key in ("lensID", "orientation", "frameWidth", "frameHeight"):
            if reference.get(key) != candidate.get(key):
                reasons.append(key)

        if self._relative_delta(reference.get("zoomFactor"), candidate.get("zoomFactor")) >= (
            self._config.zoom_relative_delta
        ):
            reasons.append("zoom")
        if self._absolute_delta(
            reference.get("exposureBias"), candidate.get("exposureBias")
        ) >= self._config.exposure_bias_delta_ev:
            reasons.append("exposure_bias")
        if self._absolute_delta(
            reference.get("cropAspectRatio"), candidate.get("cropAspectRatio")
        ) >= self._config.crop_aspect_ratio_delta:
            reasons.append("crop")

        if self._point_distance(
            reference.get("focusPoint"), candidate.get("focusPoint")
        ) >= self._config.focus_point_distance:
            reasons.append("focus_point")
        if self._point_distance(
            reference.get("exposurePoint"), candidate.get("exposurePoint")
        ) >= self._config.exposure_point_distance:
            reasons.append("exposure_point")

        for key in ("rollRadians", "pitchRadians"):
            if self._angle_delta_degrees(reference.get(key), candidate.get(key)) >= (
                self._config.attitude_delta_degrees
            ):
                reasons.append(key.removesuffix("Radians"))
        return reasons

    def _visual_scores(
        self,
        reference: ObservationContext,
        candidate: ObservationContext,
    ) -> tuple[float, float, int]:
        size = self._config.visual_thumbnail_size
        reference_signature = self._reference_signature(reference, size)
        candidate_signature = self._build_signature(candidate, size)
        self._candidate_cache = (candidate.image_message_id, candidate_signature)
        global_mae, block_mae = self._translation_tolerant_mae(
            reference_signature.values,
            candidate_signature.values,
            size,
            self._config.visual_alignment_radius,
        )
        hash_distance = sum(
            left != right
            for left, right in zip(
                reference_signature.difference_hash,
                candidate_signature.difference_hash,
                strict=True,
            )
        )
        return global_mae, block_mae, hash_distance

    @staticmethod
    def _translation_tolerant_mae(
        reference: tuple[float, ...],
        candidate: tuple[float, ...],
        size: int,
        radius: int,
    ) -> tuple[float, float]:
        """Find the lowest-error small translation and ignore uncovered edges."""
        best: tuple[float, float] | None = None
        block_size = size // 4
        for delta_y in range(-radius, radius + 1):
            y_start = max(0, -delta_y)
            y_stop = min(size, size - delta_y)
            for delta_x in range(-radius, radius + 1):
                x_start = max(0, -delta_x)
                x_stop = min(size, size - delta_x)
                total = 0.0
                count = 0
                block_totals = [0.0] * 16
                block_counts = [0] * 16
                for y in range(y_start, y_stop):
                    reference_row = y * size
                    candidate_row = (y + delta_y) * size
                    for x in range(x_start, x_stop):
                        difference = abs(
                            reference[reference_row + x]
                            - candidate[candidate_row + x + delta_x]
                        )
                        total += difference
                        count += 1
                        block = (y // block_size) * 4 + (x // block_size)
                        block_totals[block] += difference
                        block_counts[block] += 1
                global_mae = total / (count * 255)
                block_mae = max(
                    total / (count * 255)
                    for total, count in zip(
                        block_totals,
                        block_counts,
                        strict=True,
                    )
                    if count
                )
                score = (global_mae, block_mae)
                if best is None or score < best:
                    best = score
        if best is None:
            raise ValueError("visual alignment produced no overlapping pixels")
        return best

    def _reference_signature(
        self,
        context: ObservationContext,
        size: int,
    ) -> _VisualSignature:
        if (
            self._reference_cache is not None
            and self._reference_cache[0] == context.image_message_id
        ):
            return self._reference_cache[1]
        if (
            self._candidate_cache is not None
            and self._candidate_cache[0] == context.image_message_id
        ):
            signature = self._candidate_cache[1]
        else:
            signature = self._build_signature(context, size)
        self._reference_cache = (context.image_message_id, signature)
        return signature

    def _build_signature(
        self,
        context: ObservationContext,
        size: int,
    ) -> _VisualSignature:
        with Image.open(BytesIO(context.image.data)) as image:
            grayscale = image.convert("L")
            thumbnail = grayscale.resize((size, size)).filter(
                ImageFilter.GaussianBlur(self._config.visual_blur_radius)
            )
            hash_image = grayscale.resize((9, 8))
        return _VisualSignature(
            values=tuple(self._mean_centered(thumbnail)),
            difference_hash=self._difference_hash(hash_image),
        )

    @staticmethod
    def _mean_centered(image: Image.Image) -> list[float]:
        values = list(image.tobytes())
        mean = ImageStat.Stat(image).mean[0]
        return [max(0.0, min(255.0, value - mean + 128.0)) for value in values]

    @staticmethod
    def _difference_hash(image: Image.Image) -> tuple[bool, ...]:
        values = list(image.tobytes())
        return tuple(
            values[y * 9 + x] > values[y * 9 + x + 1]
            for y in range(8)
            for x in range(8)
        )

    @staticmethod
    def _relative_delta(left: Any, right: Any) -> float:
        if left is None or right is None:
            return 0.0 if left is right else math.inf
        left_value, right_value = float(left), float(right)
        return abs(left_value - right_value) / max(abs(left_value), abs(right_value), 1e-9)

    @staticmethod
    def _absolute_delta(left: Any, right: Any) -> float:
        if left is None or right is None:
            return 0.0 if left is right else math.inf
        return abs(float(left) - float(right))

    @staticmethod
    def _point_distance(left: Any, right: Any) -> float:
        if left is None or right is None:
            return 0.0 if left is right else math.inf
        return math.hypot(
            float(left["x"]) - float(right["x"]),
            float(left["y"]) - float(right["y"]),
        )

    @staticmethod
    def _angle_delta_degrees(left: Any, right: Any) -> float:
        if left is None or right is None:
            return 0.0 if left is right else math.inf
        delta = float(right) - float(left)
        wrapped = math.atan2(math.sin(delta), math.cos(delta))
        return abs(math.degrees(wrapped))
