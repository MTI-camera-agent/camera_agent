"""Deterministic Settled-Evidence admission tests for issue #22.

These tests drive the public ``CoachingRuntime`` Interface (``submit`` /
``outputs`` / ``close``) constructed through ``build_runtime`` to prove the
deterministic frame-signal and Settled-Evidence admission behavior of issue
#22 against the S02–S05 and S11 scenarios in
``docs/CAMERA_AGENT_V2_EVALUATION.md`` §5.2:

- AC1 / S03: a hard camera-context or material visual/quality change
  immediately invalidates Evidence, overlays, queued work, and the
  authoritative run token; no VLM work is requested before count+dwell
  settling.
- AC2: a new Evidence identity is admitted only after at least two mutually
  equivalent post-change observations spanning at least the configured dwell.
- AC3 / S02: equivalent routine frames coalesce without a new Evidence
  identity or queued call.
- AC4 / S04: relative sharpness, luminance, clipping, decode-unavailable,
  and existing change facts may invalidate or request revalidation but never
  establish semantic achievement or Ready.
- AC5 / S05: decode failure yields unavailable quality data and a
  conservative fail-open change; no quality value is fabricated.
- S11: text may use a proven equivalent newest view while overlays remain
  bound to the exact analyzed observation.

Behavior is exercised only through the public runtime seam plus the private
``clock`` / ``signal_computer`` mechanical substitutions. The dormant v2 path
stays off the production composition root (the package remains ``DORMANT``).
"""

from __future__ import annotations

import asyncio
from uuid import uuid4

from camera_agent.v2 import (
    CriterionAssessment,
    CriterionClassification,
    GroundingFact,
    GroundingTag,
    InstructionFreshness,
    InstructionKind,
    RuntimeConfig,
    VisualGuidanceIntent,
    build_runtime,
)
from camera_agent.v2.contracts import (
    IntentionAcceptedEvent,
    ObservationReceivedEvent,
)
from camera_agent.v2.seams import (
    ProposedCriterion,
    StrategyProposal,
)
from tests.v2_controls import (
    CompletionDriver,
    ScriptedEditor,
    ScriptedFrameSignalComputer,
    ScriptedReasoner,
    ScriptedResponse,
    VirtualMonotonicClock,
    build_observation,
    decode_unavailable,
    default_camera_context,
    equivalent_no_change,
    material_change,
    non_equivalent_drift,
    quality_crossing,
)

# --- shared builders --------------------------------------------------------


def _action_proposal(
    *, action: str = "Step left", actor: str | None = "photographer",
) -> StrategyProposal:
    """A one-must-have proposal whose must-have is unmet -> ACTION Instruction."""
    return StrategyProposal(
        criteria=(
            ProposedCriterion(
                importance="must_have",
                priority=0,
                observable_target="subject centered in frame",
                candidate_actions=(action,),
                responsible_actor=actor,
            ),
        ),
        must_have_assessments=(
            CriterionAssessment(
                criterion_id=uuid4(),
                classification=CriterionClassification.INSUFFICIENT,
                confidence=0.6,
                grounding=(
                    GroundingFact(
                        text="subject is right of center",
                        tag=GroundingTag.CURRENT,
                    ),
                ),
            ),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )


def _build(
    *, signals: list | None = None, clock: VirtualMonotonicClock | None = None,
) -> tuple:
    """Build a runtime with a shared virtual clock and scripted signals.

    ``signals`` is the ordered queue of ``FrameSignals`` the scripted computer
    hands to each *post-change* observation that has a reference (the first
    post-change frame has no reference and is not measured). The computer and
    clock are private mechanical substitutions, not public Adapter seams.
    """
    clock = clock or VirtualMonotonicClock()
    driver = CompletionDriver(clock=clock)
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(_action_proposal())],
    )
    editor = ScriptedEditor(driver=driver)
    computer = ScriptedFrameSignalComputer(
        responses=list(signals) if signals else [equivalent_no_change()],
    )
    runtime = build_runtime(
        RuntimeConfig(),
        reasoner=reasoner,
        editor=editor,
        signal_computer=computer,
    )
    return runtime, driver, clock


async def _next(runtime):
    return await runtime.outputs().__anext__()


async def _pump(driver: CompletionDriver, *, max_pumps: int = 10000) -> None:
    """Pump the event loop until a scripted adapter call registers."""
    for _ in range(max_pumps):
        await asyncio.sleep(0)
        if driver.pending():
            return
    raise AssertionError("scripted adapter call never registered")


async def _drain_pump(runtime, *, pumps: int = 50) -> int:
    """Pump the loop then return the output-queue size.

    Used to assert that no projection was emitted (stale / coalesced
    completions) without a real-time wait: a few event-loop turns are enough
    for any pending effect to drain back through the mailbox.
    """
    for _ in range(pumps):
        await asyncio.sleep(0)
    return runtime._output_queue.qsize()


async def _intend(runtime) -> None:
    """Accept an intention and consume the resulting orienting projection."""
    await _next(runtime)  # consume the construction (revision 0) projection
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=0, accepted_intention="portrait",
        )
    )
    await _next(runtime)  # consume the orienting projection


async def _settle(runtime, driver, clock) -> None:
    """Drive two mutually equivalent observations past the configured dwell.

    Leaves the runtime SETTLED with one Evidence identity admitted, the settle
    projection consumed, and exactly one orientation call pending. The scripted
    computer must hand ``equivalent_no_change()`` to the second observation.
    """
    # First post-change observation begins settling (suppressed projection).
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(), observation=build_observation(1, clock=clock),
        )
    )
    clock.advance(RuntimeConfig().settled.dwell_seconds)
    # Second mutually equivalent observation: count and dwell both met, so a
    # new Evidence identity is admitted and orientation is requested.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(), observation=build_observation(2, clock=clock),
        )
    )
    await _next(runtime)  # consume the settled projection
    await _pump(driver)


async def _intend_settle_and_complete(runtime, driver, clock):
    """Reach an admitted ACTION Instruction backed by current settled Evidence."""
    await _intend(runtime)
    await _settle(runtime, driver, clock)
    driver.complete_next()
    return await _next(runtime)  # the Instruction projection


# ===========================================================================
# AC2: a new Evidence identity requires count + dwell
# ===========================================================================


async def test_AC2_no_evidence_admitted_before_count_and_dwell_are_met() -> None:
    runtime, driver, clock = _build()
    await _intend(runtime)

    # First post-change observation begins settling. No Evidence yet, and the
    # reducer requests no VLM work before settling completes.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(), observation=build_observation(1, clock=clock),
        )
    )
    assert runtime._evidence is None
    assert runtime._evidence_state.value == "settling"
    assert driver.all_calls() == ()
    assert driver.pending() == ()

    # A second mutually equivalent observation with an insufficient dwell span
    # does NOT admit an Evidence identity.
    clock.advance(RuntimeConfig().settled.dwell_seconds / 2)
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(), observation=build_observation(2, clock=clock),
        )
    )
    assert runtime._evidence is None
    assert runtime._evidence_state.value == "settling"
    assert driver.all_calls() == ()

    # Only once count AND dwell are both met is an application-authored Evidence
    # identity admitted and orientation requested.
    clock.advance(RuntimeConfig().settled.dwell_seconds)
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(), observation=build_observation(3, clock=clock),
        )
    )
    assert runtime._evidence is not None
    assert runtime._evidence_state.value == "settled"
    await _pump(driver)
    assert len(driver.all_calls()) == 1
    await runtime.close()


async def test_AC2_first_post_change_frame_is_baseline_not_invalidation() -> None:
    runtime, driver, clock = _build()
    await _intend(runtime)

    # The very first post-change frame has no reference to compare against; it
    # is the baseline of a new settling period, not an invalidation, and it
    # admits no Evidence identity.
    receipt = await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(), observation=build_observation(1, clock=clock),
        )
    )
    assert receipt.disposition.value == "admitted"
    assert runtime._evidence is None
    assert runtime._evidence_state.value == "settling"
    assert runtime._settling_count == 1
    assert runtime._settling_baseline is not None
    assert driver.all_calls() == ()
    await runtime.close()


# ===========================================================================
# AC3 / S02: equivalent routine frames coalesce without a new identity or backlog
# ===========================================================================


async def test_S02_equivalent_routine_frames_coalesce_without_new_identity_or_call() -> None:
    runtime, driver, clock = _build()
    await _intend(runtime)
    await _settle(runtime, driver, clock)

    settled_evidence_id = runtime._evidence.evidence_id
    settled_observation = runtime._settled_observation
    pending_before = len(driver.pending())

    # A third equivalent routine frame coalesces: no new Evidence identity and
    # no queued call. The projection is suppressed (no inference backlog).
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    assert runtime._evidence.evidence_id == settled_evidence_id
    assert runtime._settled_observation is settled_observation  # overlay anchor unchanged
    assert runtime._evidence_state.value == "settled"
    assert len(driver.pending()) == pending_before  # no second call queued
    assert len(driver.all_calls()) == 1
    # No new projection was emitted (duplicate-suppressed coalescing).
    assert await _drain_pump(runtime) == 0
    await runtime.close()


async def test_S11_overlay_stays_on_exact_analyzed_observation_while_latest_view_advances() -> None:
    # S11: text may use a proven equivalent newest view while overlays remain
    # bound to the exact analyzed observation. The runtime keeps the exact
    # settled observation as the overlay/analysis anchor and only advances the
    # newest equivalent view, which text may be projected against.
    runtime, driver, clock = _build()
    await _intend(runtime)
    await _settle(runtime, driver, clock)

    overlay_anchor = runtime._settled_observation.observation_id
    assert runtime._latest_observation.observation_id == 2  # last settled view

    # An equivalent routine frame advances the latest view only.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(4, clock=clock),
        )
    )
    assert runtime._settled_observation.observation_id == overlay_anchor
    assert runtime._latest_observation.observation_id == 4
    await runtime.close()


# ===========================================================================
# AC1 / S03: material camera or visual change immediately invalidates
# ===========================================================================


async def test_S03_material_visual_change_immediately_invalidates_evidence_run_overlay() -> None:
    runtime, driver, clock = _build(signals=[equivalent_no_change(), material_change()])
    await _intend(runtime)
    await _settle(runtime, driver, clock)

    assert runtime._evidence is not None
    assert runtime._authoritative_run is not None
    assert runtime._settled_observation is not None

    # A material visual change immediately invalidates Evidence, the
    # authoritative run token, and the overlay-bound observation, and starts a
    # fresh settling period. No VLM work is requested before count+dwell.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    assert runtime._last_signals.material_change is True
    assert runtime._evidence is None
    assert runtime._authoritative_run is None
    assert runtime._settled_observation is None
    assert runtime._evidence_state.value == "settling"
    # No new strategy call was requested: the original call is now stale and
    # the reducer must re-settle before any fresh VLM work.
    assert len(driver.all_calls()) == 1
    await runtime.close()


async def test_S03_hard_camera_context_change_invalidates_with_recorded_reason() -> None:
    runtime, driver, clock = _build(
        signals=[equivalent_no_change(), material_change("camera:lensID")],
    )
    await _intend(runtime)
    await _settle(runtime, driver, clock)

    # A hard camera-context change (lens/orientation/frame dimensions) is the
    # canonical material invalidation. The scripted computer reports it.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(
                3,
                clock=clock,
                camera=default_camera_context(lensID="tele-camera"),
            ),
        )
    )
    assert "camera:lensID" in runtime._last_signals.material_reasons
    assert runtime._evidence is None
    assert runtime._authoritative_run is None
    assert runtime._evidence_state.value == "settling"
    await runtime.close()


async def test_S03_stale_completion_after_invalidation_is_a_harmless_discard() -> None:
    runtime, driver, clock = _build(signals=[equivalent_no_change(), material_change()])
    await _intend(runtime)
    await _settle(runtime, driver, clock)

    # The pending orientation call belongs to the now-invalidated run. Letting
    # it mature after a material change must not admit a Strategy/Instruction.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    assert runtime._authoritative_run is None
    await _next(runtime)  # consume the invalidation projection

    driver.complete_next()
    # Let the stale completion's effect drain back through the mailbox; it must
    # produce no projection and admit no Strategy/Instruction.
    assert await _drain_pump(runtime) == 0
    assert runtime._strategy is None
    assert runtime._instruction is None
    await runtime.close()


# ===========================================================================
# AC4 / S04: quality signals may request revalidation only, never Ready
# ===========================================================================


async def test_S04_quality_crossing_requests_revalidation_only_and_never_establishes_ready() -> None:
    runtime, driver, clock = _build(
        signals=[equivalent_no_change(), quality_crossing()],
    )
    p3 = await _intend_settle_and_complete(runtime, driver, clock)

    # An active ACTION Instruction backed by current settled Evidence.
    assert p3.instruction is not None
    assert p3.instruction.kind is InstructionKind.ACTION
    assert p3.instruction.freshness is InstructionFreshness.CURRENT
    assert p3.readiness is None  # no Ready from a deterministic signal
    evidence_before = runtime._evidence.evidence_id

    # An equivalent routine frame carrying a calibrated quality crossing (a
    # relative blur / luminance / clipping regression) requests revalidation only:
    # it marks the Instruction as needing revalidation while retaining the same
    # Evidence identity, queues no new VLM call, and never produces Ready.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(5, clock=clock),
        )
    )
    assert runtime._evidence.evidence_id == evidence_before  # identity retained
    assert runtime._instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    assert runtime._readiness is None  # never establishes Ready
    assert len(driver.all_calls()) == 1  # no second call queued
    # The revalidation request is projected (freshness changed), not suppressed.
    revalidation = await _next(runtime)
    assert revalidation.instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    assert revalidation.readiness is None
    await runtime.close()


async def test_S04_material_quality_change_invalidates_without_establishing_readiness() -> None:
    # A material quality change invalidates Evidence/run/overlay outright; it
    # never derives Ready or admits a fresh Instruction by itself. The
    # persistent Instruction is retained as needing revalidation (no flicker),
    # never revoked by a deterministic signal alone.
    runtime, driver, clock = _build(
        signals=[equivalent_no_change(), material_change("quality_crossing")],
    )
    p3 = await _intend_settle_and_complete(runtime, driver, clock)
    assert p3.instruction is not None

    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(5, clock=clock),
        )
    )
    assert runtime._evidence is None  # Evidence invalidated
    assert runtime._authoritative_run is None  # run authority invalidated
    assert runtime._settled_observation is None  # overlay invalidated
    assert runtime._instruction is not None  # guidance retained, not revoked
    assert runtime._instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    assert runtime._readiness is None  # never establishes Ready
    await runtime.close()


# ===========================================================================
# AC5 / S05: decode failure is a conservative fail-open change
# ===========================================================================


async def test_S05_decode_failure_is_conservative_fail_open_change_with_no_fabricated_value() -> None:
    runtime, driver, clock = _build(
        signals=[equivalent_no_change(), decode_unavailable()],
    )
    await _intend(runtime)
    await _settle(runtime, driver, clock)

    # Decode failure yields unavailable quality data and conservative fail-open
    # change handling: the runtime treats it as a material invalidation, and no
    # quality value is fabricated.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    signals = runtime._last_signals
    assert signals.decode_available is False
    assert signals.material_change is True
    assert "decode_unavailable" in signals.material_reasons
    assert signals.relative_sharpness is None  # no fabricated sharpness
    assert signals.luminance is None  # no fabricated luminance
    assert signals.highlight_clipping is None
    assert signals.shadow_clipping is None
    assert signals.quality_crossing is False
    # And it actually invalidated the settled Evidence and run authority.
    assert runtime._evidence is None
    assert runtime._authoritative_run is None
    assert runtime._evidence_state.value == "settling"
    await runtime.close()


# ===========================================================================
# Non-equivalent drift: soft settling restart without identity revocation
# ===========================================================================


async def test_non_equivalent_drift_restarts_settling_and_marks_guidance_outdated() -> None:
    runtime, driver, clock = _build(
        signals=[equivalent_no_change(), non_equivalent_drift()],
    )
    p3 = await _intend_settle_and_complete(runtime, driver, clock)
    assert p3.instruction is not None
    assert p3.instruction.freshness is InstructionFreshness.CURRENT

    # A non-equivalent, non-material drift does not immediately invalidate the
    # Evidence identity (only material/hard/quality crossings do); it restarts
    # settling and marks the retained guidance as possibly outdated so it does
    # not flicker or revoke.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(5, clock=clock),
        )
    )
    assert runtime._last_signals.material_change is False
    assert runtime._last_signals.equivalent_to_reference is False
    # The identity is retained (not invalidated) but guidance is marked outdated.
    assert runtime._evidence is not None
    assert runtime._evidence_state.value == "settling"
    assert runtime._instruction.freshness is InstructionFreshness.MAY_BE_OUTDATED
    await runtime.close()


# ===========================================================================
# Dormancy guard
# ===========================================================================


async def test_evidence_settling_path_remains_dormant_off_production_root() -> None:
    from camera_agent.v2 import DORMANT

    assert DORMANT is True
