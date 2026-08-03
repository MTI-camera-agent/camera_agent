from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance

from camera_agent.change_detection import ObservationChangeDetector
from camera_agent.config import ChangeDetectionConfig
from tests.helpers import context


def _jpeg(image: Image.Image, quality: int = 70) -> bytes:
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=quality)
    return output.getvalue()


def _fixture(name: str) -> Image.Image:
    with Image.open(Path("models/test_img") / name) as image:
        return image.copy()


def test_same_scene_and_exposure_only_variation_are_suppressed() -> None:
    detector = ObservationChangeDetector(ChangeDetectionConfig())
    base = _fixture("stand_female_0.jpg")
    reference = context(1, image=_jpeg(base, quality=60))
    same_recompressed = context(2, image=_jpeg(base, quality=85))
    brighter = context(
        3,
        image=_jpeg(ImageEnhance.Brightness(base).enhance(1.10), quality=60),
    )
    assert not detector.assess(reference, same_recompressed).significant
    assert not detector.assess(reference, brighter).significant


def test_pose_change_is_significant() -> None:
    detector = ObservationChangeDetector(ChangeDetectionConfig())
    reference = context(1, image=_jpeg(_fixture("stand_female_0.jpg")))
    candidate = context(2, image=_jpeg(_fixture("sit_female_0.jpg")))
    assessment = detector.assess(reference, candidate)
    assert assessment.significant
    assert any(reason.startswith("visual_") for reason in assessment.reasons)


def test_tiny_persistent_handheld_translation_is_suppressed() -> None:
    detector = ObservationChangeDetector(ChangeDetectionConfig())
    base = _fixture("stand_female_0.jpg")
    reference = context(1, image=_jpeg(base))
    shifted = context(2, image=_jpeg(ImageChops.offset(base, 5, 5)))
    assert not detector.assess(reference, shifted).significant


def test_camera_thresholds_are_centralized_and_auto_iso_is_ignored() -> None:
    config = ChangeDetectionConfig(zoom_relative_delta=0.02)
    detector = ObservationChangeDetector(config)
    reference = context(1)

    small_zoom = replace(
        context(2),
        camera={**reference.camera, "zoomFactor": 1.01},
    )
    large_zoom = replace(
        context(3),
        camera={**reference.camera, "zoomFactor": 1.03},
    )
    iso_only = replace(
        context(4),
        camera={**reference.camera, "iso": 400},
    )
    assert not detector.assess(reference, small_zoom).significant
    assert "zoom" in detector.assess(reference, large_zoom).reasons
    assert not detector.assess(reference, iso_only).significant


def test_focus_exposure_and_attitude_thresholds() -> None:
    detector = ObservationChangeDetector(ChangeDetectionConfig())
    reference = context(1)
    cases = {
        "focus_point": {
            "focusPoint": {"x": 0.10, "y": 0.10},
        },
        "exposure_point": {
            "exposurePoint": {"x": 0.10, "y": 0.10},
        },
        "exposure_bias": {
            "exposureBias": 0.2,
        },
        "roll": {
            "rollRadians": 0.05,
        },
    }
    for expected_reason, updates in cases.items():
        candidate = replace(
            context(2),
            camera={**reference.camera, **updates},
        )
        assert expected_reason in detector.assess(reference, candidate).reasons
