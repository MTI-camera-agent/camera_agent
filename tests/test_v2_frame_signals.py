"""Production ``PILFrameSignalComputer`` coverage and the S04 invariant.

Issue #22 admits settled Evidence using CPU-cheap deterministic frame signals.
The reducer's settling / invalidation / coalescing policy is exercised through
the scripted computer in ``test_v2_evidence_settling.py``; this module gives
the *production* Pillow-based computer direct coverage and locks in the S04
guarantee (``docs/CAMERA_AGENT_V2_EVALUATION.md`` §5.2): a calibrated relative
sharpness / luminance / clipping crossing may request revalidation only and
MUST NOT itself be a material invalidation.

The production computer is a private mechanical measurement, not a public seam:
these tests construct real ``PreviewImage`` bytes with Pillow so the
thumbnail / d-hash / translation-tolerant MAE / sharpness / clipping paths run
for real.
"""

from __future__ import annotations

import asyncio
import io
from uuid import uuid4

from PIL import Image, ImageDraw, ImageFilter

from camera_agent.v2 import (
    InstructionFreshness,
    InstructionKind,
    RuntimeConfig,
    build_runtime,
)
from camera_agent.v2._signals import PILFrameSignalComputer
from camera_agent.v2.config import FrameSignalPolicy
from camera_agent.v2.contracts import (
    IntentionAcceptedEvent,
    ObservationReceivedEvent,
)
from camera_agent.v2.values import (
    CameraContext,
    Observation,
    PreviewImage,
)
from tests.v2_controls import (
    CompletionDriver,
    ScriptedEditor,
    ScriptedReasoner,
    ScriptedResponse,
    VirtualMonotonicClock,
)
from tests.test_v2_evidence_settling import _action_proposal

# --- real-image helpers -----------------------------------------------------

_SIZE = 256


def _checkerboard(*, cell: int = 8, contrast: int = 255, base: int = 128) -> bytes:
    """A deterministic high-frequency PNG preview for sharpness measurements."""
    img = Image.new("L", (_SIZE, _SIZE), base)
    draw = ImageDraw.Draw(img)
    for y in range(0, _SIZE, cell):
        for x in range(0, _SIZE, cell):
            if (x // cell + y // cell) % 2 == 0:
                draw.rectangle([x, y, x + cell - 1, y + cell - 1], fill=base - contrast)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _blurred_checkerboard(radius: float = 0.8) -> bytes:
    """A mildly blurred checkerboard: lower high-frequency energy, same mean."""
    img = Image.new("L", (_SIZE, _SIZE), 128)
    draw = ImageDraw.Draw(img)
    for y in range(0, _SIZE, 8):
        for x in range(0, _SIZE, 8):
            if (x // 8 + y // 8) % 2 == 0:
                draw.rectangle([x, y, x + 7, y + 7], fill=0)
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    buf = io.BytesIO()
    blurred.save(buf, format="PNG")
    return buf.getvalue()


def _png_observation(
    bytes_: bytes, *, oid: int, arrival: float, lens: str = "wide-camera",
) -> Observation:
    return Observation(
        observation_id=oid,
        camera=CameraContext(
            metadata={
                "lensID": lens,
                "orientation": "portrait",
                "frameWidth": _SIZE,
                "frameHeight": _SIZE,
            }
        ),
        preview=PreviewImage(
            bytes_=bytes_, mime_type="image/png", width=_SIZE, height=_SIZE,
        ),
        arrival_monotonic_seconds=arrival,
    )


def _default_computer() -> PILFrameSignalComputer:
    return PILFrameSignalComputer(RuntimeConfig().frame_signals)


# ===========================================================================
# Production measurement coverage
# ===========================================================================


def test_pil_identical_frames_are_equivalent_with_no_material_change() -> None:
    ref = _png_observation(_checkerboard(), oid=1, arrival=0.0)
    signals = _default_computer().compute(ref, ref)
    assert signals.decode_available is True
    assert signals.material_change is False
    assert signals.equivalent_to_reference is True
    assert signals.material_reasons == ()
    assert signals.quality_crossing is False
    # Quality diagnostics are populated, not fabricated-none, on a real decode.
    assert signals.relative_sharpness is not None
    assert signals.luminance is not None


def test_pil_hard_camera_context_change_is_a_material_invalidation() -> None:
    ref = _png_observation(_checkerboard(), oid=1, arrival=0.0, lens="wide-camera")
    cand = _png_observation(
        _checkerboard(), oid=2, arrival=0.5, lens="tele-camera",
    )
    signals = _default_computer().compute(ref, cand)
    assert signals.material_change is True
    assert signals.equivalent_to_reference is False
    assert "camera:lensID" in signals.material_reasons


def test_pil_decode_failure_is_conservative_fail_open_with_no_fabricated_value() -> None:
    ref = _png_observation(_checkerboard(), oid=1, arrival=0.0)
    bad = _png_observation(b"not actually an image", oid=2, arrival=0.5)
    signals = _default_computer().compute(ref, bad)
    assert signals.decode_available is False
    assert signals.material_change is True  # conservative fail-open
    assert "decode_unavailable" in signals.material_reasons
    # No quality value is fabricated on a failed decode.
    assert signals.relative_sharpness is None
    assert signals.luminance is None
    assert signals.quality_crossing is False


# ===========================================================================
# S04 invariant: a quality crossing is revalidation-only, never material
# ===========================================================================


def test_pil_quality_crossing_is_revalidation_only_and_never_material() -> None:
    # A mildly blurred checkerboard preserves the global structure (no material
    # visual delta) but loses high-frequency energy (a relative blur regression).
    # With a sensitive sharpness-regression threshold the production computer
    # reports a quality crossing that is NOT a material change and is equivalent
    # to the reference — exactly the S04 "revalidation only" signal.
    ref = _png_observation(_checkerboard(), oid=1, arrival=0.0)
    cand = _png_observation(_blurred_checkerboard(), oid=2, arrival=0.5)
    policy = FrameSignalPolicy(sharpness_regression_threshold=0.001)
    signals = PILFrameSignalComputer(policy).compute(ref, cand)

    assert signals.decode_available is True
    assert signals.quality_crossing is True
    assert signals.sharpness_regression is True
    # S04: a quality crossing must NOT itself be a material invalidation.
    assert signals.material_change is False
    assert signals.equivalent_to_reference is True
    assert "quality_crossing" not in signals.material_reasons
    assert signals.material_reasons == ()


def test_pil_material_change_is_driven_only_by_material_reasons() -> None:
    # The S04 invariant holds across constructed pairs: ``material_change`` is
    # exactly ``bool(material_reasons)``, and ``material_reasons`` never carries
    # ``"quality_crossing"``. Quality crossings ride the separate flags only.
    ref = _png_observation(_checkerboard(), oid=1, arrival=0.0)
    pairs = [
        ref,  # identical
        _png_observation(_checkerboard(), oid=2, arrival=0.5, lens="tele"),
        _png_observation(_blurred_checkerboard(), oid=3, arrival=0.5),
        _png_observation(b"bad bytes", oid=4, arrival=0.5),
    ]
    computer = _default_computer()
    sensitive = PILFrameSignalComputer(
        FrameSignalPolicy(sharpness_regression_threshold=0.001),
    )
    for cand in pairs:
        for c in (computer, sensitive):
            signals = c.compute(ref, cand)
            assert signals.material_change is bool(signals.material_reasons)
            assert "quality_crossing" not in signals.material_reasons


# ===========================================================================
# End-to-end: the production computer through the public runtime seam
# ===========================================================================


async def test_production_quality_crossing_marks_revalidation_not_invalidation() -> None:
    # Wire the production Pillow computer into the real runtime with a sensitive
    # sharpness-regression threshold so a real mild-blur frame is a quality
    # crossing. Settle two identical frames, admit an Instruction, then send the
    # blurred frame: the Instruction is marked NEEDS_REVALIDATION (revalidation
    # only), the Evidence identity is retained, and no second VLM call is queued.
    config = RuntimeConfig(
        frame_signals=FrameSignalPolicy(sharpness_regression_threshold=0.001),
    )
    driver = CompletionDriver(clock=VirtualMonotonicClock())  # adapter trace timestamps
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(_action_proposal())],
    )
    editor = ScriptedEditor(driver=driver)
    runtime = build_runtime(
        config, reasoner=reasoner, editor=editor,
        signal_computer=PILFrameSignalComputer(config.frame_signals).compute,
    )

    async def _next():
        return await runtime.outputs().__anext__()

    await _next()  # consume the construction projection
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=0, accepted_intention="portrait",
        )
    )
    await _next()  # consume the orienting projection

    sharp = _checkerboard()
    # First post-change observation begins settling; second identical frame
    # settles after the configured dwell.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=_png_observation(sharp, oid=1, arrival=0.0),
        )
    )
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=_png_observation(sharp, oid=2, arrival=config.settled.dwell_seconds),
        )
    )
    await _next()  # consume the settled projection
    for _ in range(100):
        await asyncio.sleep(0)
        if driver.pending():
            break
    assert runtime._evidence is not None
    evidence_before = runtime._evidence.evidence_id

    driver.complete_next()
    instruction_projection = await _next()
    assert instruction_projection.instruction is not None
    assert instruction_projection.instruction.kind is InstructionKind.ACTION
    assert instruction_projection.instruction.freshness is InstructionFreshness.CURRENT

    # A real mild-blur frame is a quality crossing (revalidation only): the
    # Instruction is marked needing revalidation, the Evidence identity is
    # retained, and no second call is queued.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=_png_observation(
                _blurred_checkerboard(), oid=3, arrival=config.settled.dwell_seconds * 2,
            ),
        )
    )
    assert runtime._last_signals.quality_crossing is True
    assert runtime._last_signals.material_change is False
    assert runtime._evidence.evidence_id == evidence_before  # identity retained
    assert runtime._instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    assert runtime._readiness is None  # never establishes Ready
    assert len(driver.all_calls()) == 1  # no second VLM call queued
    revalidation = await _next()
    assert revalidation.instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    await runtime.close()
