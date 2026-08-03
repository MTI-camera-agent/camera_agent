from __future__ import annotations

import pytest

from camera_agent.__main__ import build_parser, config_from_args
from camera_agent.config import ChangeDetectionConfig
from camera_agent.domain import explicit_sample_permission


def test_tuning_defaults_are_centralized() -> None:
    args = build_parser().parse_args([])
    assert config_from_args(args).model == "gemini-3.5-flash-lite"
    change = ChangeDetectionConfig()
    assert change.zoom_relative_delta == 0.01
    assert change.focus_point_distance == 0.03
    assert change.exposure_bias_delta_ev == 0.10
    assert change.attitude_delta_degrees == 2.0
    assert change.visual_blur_radius == 1.0
    assert change.visual_alignment_radius == 2
    assert change.routine_change_confirmations == 2
    assert change.inference_stale_global_mae == 0.12
    assert change.inference_stale_block_mae == 0.24


def test_cli_overrides_tuning_values() -> None:
    args = build_parser().parse_args(
        [
            "--zoom-relative-delta",
            "0.025",
            "--focus-point-distance",
            "0.05",
            "--routine-change-confirmations",
            "3",
            "--visual-blur-radius",
            "1.5",
            "--visual-alignment-radius",
            "3",
            "--inference-stale-global-mae",
            "0.15",
            "--inference-stale-block-mae",
            "0.3",
        ]
    )
    config = config_from_args(args)
    assert config.change_detection.zoom_relative_delta == 0.025
    assert config.change_detection.focus_point_distance == 0.05
    assert config.change_detection.visual_blur_radius == 1.5
    assert config.change_detection.visual_alignment_radius == 3
    assert config.change_detection.routine_change_confirmations == 3
    assert config.change_detection.inference_stale_global_mae == 0.15
    assert config.change_detection.inference_stale_block_mae == 0.3


def test_invalid_tuning_values_fail_fast() -> None:
    with pytest.raises(ValueError):
        ChangeDetectionConfig(zoom_relative_delta=0)
    with pytest.raises(ValueError):
        ChangeDetectionConfig(routine_change_confirmations=0)
    with pytest.raises(ValueError):
        ChangeDetectionConfig(visual_blur_radius=-1)
    with pytest.raises(ValueError):
        ChangeDetectionConfig(visual_alignment_radius=-1)


def test_reference_image_wording_is_explicit_permission() -> None:
    assert explicit_sample_permission(
        "A close view of the shirt with a reference image"
    )
