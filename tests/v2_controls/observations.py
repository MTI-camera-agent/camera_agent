"""Observation builders and a scripted frame-signal computer for v2 replay.

The runtime owns deterministic frame measurement as an internal responsibility.
For deterministic replay a test substitutes a *scripted* signal computer
through ``build_runtime(signal_computer=...)`` — a private mechanical
substitution, not a public Adapter seam (it owns no scheduling, settling,
invalidation, Instruction, Readiness, or visual-job policy). The scripted
computer only lets a test declaratively control the ``FrameSignals`` each
observation produces so the settling, invalidation, and coalescing *policy*
(owned by the reducer) is exercised deterministically.

These controls hand out immutable ``Observation`` values built from the stable
``ImageFixture`` bytes, so a test can assert byte provenance and correlation
without depending on live capture or real image decoding.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from camera_agent.v2.values import (
    CameraContext,
    FrameSignals,
    Observation,
    PreviewImage,
)

from .clock import VirtualMonotonicClock
from .fixtures import default_preview_fixture


def default_camera_context(**overrides: object) -> CameraContext:
    """A stable camera context for general composition scenarios.

    Keyword overrides replace individual metadata keys. Changing a hard key
    (``lensID``/``orientation``/``frameWidth``/``frameHeight``) models a hard
    camera-context change; changing a soft key models routine shimmer.
    """

    base: dict[str, object] = {
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
    base.update(overrides)
    return CameraContext(metadata=base)


def build_observation(
    observation_id: int,
    *,
    camera: CameraContext | None = None,
    preview: PreviewImage | None = None,
    arrival: float | None = None,
    clock: VirtualMonotonicClock | None = None,
    reason: str = "stream",
) -> Observation:
    """Build one immutable observation from stable fixtures.

    ``arrival`` is the desktop-monotonic arrival time. When a virtual clock is
    supplied without an explicit arrival, the clock's current virtual time is
    used so Settled dwell is deterministic.
    """

    if preview is None:
        fixture = default_preview_fixture()
        preview = PreviewImage(
            bytes_=fixture.bytes_,
            mime_type=fixture.mime_type,
            width=fixture.width,
            height=fixture.height,
            bytes_hash=fixture.bytes_hash,
        )
    if camera is None:
        camera = default_camera_context()
    if arrival is None:
        arrival = clock.now() if clock is not None else 0.0
    return Observation(
        observation_id=observation_id,
        camera=camera,
        preview=preview,
        arrival_monotonic_seconds=arrival,
        reason=reason,
    )


# --- Scripted frame-signal computer -----------------------------------------


def equivalent_no_change() -> FrameSignals:
    """A routine frame that coalesces without a new Evidence identity."""

    return FrameSignals(
        decode_available=True,
        material_change=False,
        equivalent_to_reference=True,
    )


def material_change(*reasons: str) -> FrameSignals:
    """A hard/material visual or quality change that immediately invalidates."""

    return FrameSignals(
        decode_available=True,
        material_change=True,
        equivalent_to_reference=False,
        material_reasons=reasons or ("visual_global",),
    )


def decode_unavailable() -> FrameSignals:
    """Decode failure: unavailable quality data, conservative fail-open change."""

    return FrameSignals(
        decode_available=False,
        material_change=True,
        equivalent_to_reference=False,
    )


def quality_crossing(*, sharpness_regression: bool = False) -> FrameSignals:
    """A calibrated quality crossing that may request revalidation only.

    It is not a material invalidation (the Evidence identity is retained) and it
    never establishes semantic achievement or Ready.
    """

    return FrameSignals(
        decode_available=True,
        material_change=False,
        equivalent_to_reference=True,
        quality_crossing=True,
        sharpness_regression=sharpness_regression,
    )


def non_equivalent_drift() -> FrameSignals:
    """A non-equivalent, non-material drift that restarts settling softly."""

    return FrameSignals(
        decode_available=True,
        material_change=False,
        equivalent_to_reference=False,
    )


@dataclass(slots=True)
class ScriptedFrameSignalComputer:
    """A strict scripted deterministic frame-signal substitution.

    Each call pops the next declared ``FrameSignals`` from the queue. When the
    queue is empty it returns ``equivalent_no_change()`` so a settling scenario
    that only declares the material/quality changes completes deterministically.

    The computer is a mechanical substitution only: it never allocates Evidence
    identities, never mutates runtime state, and never decides invalidation or
    coalescing policy. The reducer owns all of that.
    """

    responses: list[FrameSignals] = field(default_factory=list)
    _seen: int = 0

    def __call__(self, reference: Observation | None, candidate: Observation) -> FrameSignals:
        self._seen += 1
        if self.responses:
            return self.responses.pop(0)
        return equivalent_no_change()

    @property
    def calls_seen(self) -> int:
        return self._seen


__all__ = [
    "default_camera_context",
    "build_observation",
    "ScriptedFrameSignalComputer",
    "equivalent_no_change",
    "material_change",
    "decode_unavailable",
    "quality_crossing",
    "non_equivalent_drift",
]
