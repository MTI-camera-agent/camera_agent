"""Runtime configuration with conservative development defaults."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True, slots=True)
class ChangeDetectionConfig:
    """Thresholds for deciding whether a routine frame deserves VLM analysis.

    Increasing any delta, distance, MAE, or hash threshold makes detection less
    sensitive and reduces model calls. Decreasing it makes detection more
    sensitive.
    """

    zoom_relative_delta: float = 0.01
    focus_point_distance: float = 0.03
    exposure_point_distance: float = 0.03
    exposure_bias_delta_ev: float = 0.10
    crop_aspect_ratio_delta: float = 0.001
    attitude_delta_degrees: float = 2.0
    visual_global_mae: float = 0.04
    visual_block_mae: float = 0.10
    visual_hash_distance: int = 6
    visual_thumbnail_size: int = 64
    visual_blur_radius: float = 1.0
    visual_alignment_radius: int = 2
    routine_change_confirmations: int = 2
    inference_stale_global_mae: float = 0.12
    inference_stale_block_mae: float = 0.24

    def __post_init__(self) -> None:
        positive = {
            "zoom_relative_delta": self.zoom_relative_delta,
            "focus_point_distance": self.focus_point_distance,
            "exposure_point_distance": self.exposure_point_distance,
            "exposure_bias_delta_ev": self.exposure_bias_delta_ev,
            "crop_aspect_ratio_delta": self.crop_aspect_ratio_delta,
            "attitude_delta_degrees": self.attitude_delta_degrees,
            "visual_global_mae": self.visual_global_mae,
            "visual_block_mae": self.visual_block_mae,
            "inference_stale_global_mae": self.inference_stale_global_mae,
            "inference_stale_block_mae": self.inference_stale_block_mae,
        }
        for name, value in positive.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.visual_hash_distance <= 0:
            raise ValueError("visual_hash_distance must be positive")
        if self.visual_thumbnail_size < 8 or self.visual_thumbnail_size % 4:
            raise ValueError("visual_thumbnail_size must be >= 8 and divisible by 4")
        if self.visual_blur_radius < 0:
            raise ValueError("visual_blur_radius must not be negative")
        if self.visual_alignment_radius < 0:
            raise ValueError("visual_alignment_radius must not be negative")
        if self.routine_change_confirmations < 1:
            raise ValueError("routine_change_confirmations must be at least 1")


@dataclass(frozen=True, slots=True)
class HarnessConfig:
    host: str = "0.0.0.0"
    port: int = 8765
    model: str = DEFAULT_MODEL
    editor_url: str = "http://127.0.0.1:8000/edit"
    assembler_ttl_seconds: float = 5.0
    still_timeout_seconds: float = 5.0
    editor_timeout_seconds: float = 180.0
    max_message_bytes: int = 8 * 1024 * 1024
    max_output_tokens: int = 1200
    debug_artifacts: Path | None = None
    change_detection: ChangeDetectionConfig = field(default_factory=ChangeDetectionConfig)
