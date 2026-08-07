"""Deterministic progress-assessment tests for issue #23.

These tests drive the public ``CoachingRuntime`` Interface (``submit`` /
``outputs`` / ``close``) constructed through ``build_runtime`` to prove the
progress-assessment and trustworthy-Instruction/Readiness behavior of issue
#23 against the T05–T08, P01, P02, and P05 scenarios in
``docs/CAMERA_AGENT_V2_EVALUATION.md`` §5.1 / §5.3:

- T05 (Hold while improving): an accepted Settled ``improving`` assessment
  preserves the exact Instruction identity and text; only freshness may change.
- T06 (Achievement and advance): the active Instruction closes ``achieved``
  exactly once and the runtime advances to one new action for the
  highest-priority unmet Must-have.
- T07 (All must-haves achieved): Ready is derived from one current compatible
  Evidence Snapshot; Nice-to-haves may remain unmet.
- T08 (Regression after Ready): motion and capture mark Ready for revalidation
  without revoking it; reconfirmation preserves the ready Instruction identity;
  accepted regression may replace it with one corrective action Instruction.
- P01 (Every must-have reassessed): one Evidence Snapshot covers every
  Must-have from the same view with bounded grounding, finite or null
  confidence, and bounded typed uncertainty; incomplete or malformed progress
  is rejected atomically and prior guidance is preserved.
- P02 (Nice-to-have unmet): Ready is immediate; v2 emits no Nice-to-have
  Instruction before or after Ready.
- P05 (Deviating criterion): a regressed higher-priority Must-have may preempt
  the current action Instruction with one corrective Instruction; no stacked
  instructions.

Behavior is exercised only through the public runtime seam plus the strict
scripted Adapter doubles and the private ``clock`` / ``signal_computer``
mechanical substitutions. The dormant v2 path stays off the production
composition root (the package remains ``DORMANT``).
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest

from camera_agent.v2 import (
    DORMANT,
    CriterionAssessment,
    CriterionClassification,
    CriterionImportance,
    GroundingFact,
    GroundingTag,
    InstructionDisposition,
    InstructionFreshness,
    InstructionKind,
    ReadinessState,
    RuntimeConfig,
    StrategyApplicability,
    StrategyApplicabilityStatus,
    UncertaintyReason,
    VisualGuidanceIntent,
    build_runtime,
)
from camera_agent.v2.contracts import (
    IntentionAcceptedEvent,
    ObservationReceivedEvent,
    ReasonerProgressEvent,
    UserCaptureEvent,
)
from camera_agent.v2.seams import (
    ProgressEvidence,
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
    assert_at_most_one_active_instruction,
    assert_coaching_projection_well_formed,
    assert_instruction_immutable_for_identity,
    assert_no_obsolete_current_output,
    assert_output_order_is_committed,
    assert_ready_cites_current_evidence,
    assert_single_terminal_disposition,
    assert_truthful_activity_when_no_instruction,
    build_observation,
    equivalent_no_change,
    material_change,
)


# --- shared builders --------------------------------------------------------


def _criterion(
    *,
    importance: str = "must_have",
    priority: int,
    target: str,
    action: str,
    actor: str | None = "photographer",
) -> ProposedCriterion:
    return ProposedCriterion(
        importance=importance,
        priority=priority,
        observable_target=target,
        candidate_actions=(action,),
        responsible_actor=actor,
    )


def _achieved(cid: UUID, *, confidence: float = 0.9) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=cid,
        classification=CriterionClassification.ACHIEVED,
        confidence=confidence,
        grounding=(
            GroundingFact(
                text="criterion met in current view", tag=GroundingTag.CURRENT
            ),
        ),
    )


def _improving(cid: UUID, *, confidence: float = 0.6) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=cid,
        classification=CriterionClassification.IMPROVING,
        confidence=confidence,
        grounding=(
            GroundingFact(text="moving toward the target", tag=GroundingTag.CURRENT),
        ),
    )


def _insufficient(cid: UUID, *, confidence: float = 0.5) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=cid,
        classification=CriterionClassification.INSUFFICIENT,
        confidence=confidence,
        grounding=(
            GroundingFact(text="criterion not yet met", tag=GroundingTag.CURRENT),
        ),
    )


def _deviating(cid: UUID, *, confidence: float = 0.7) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=cid,
        classification=CriterionClassification.DEVIATING,
        confidence=confidence,
        grounding=(
            GroundingFact(
                text="criterion regressed from achieved", tag=GroundingTag.CURRENT
            ),
        ),
    )


def _applicable() -> StrategyApplicability:
    return StrategyApplicability(
        status=StrategyApplicabilityStatus.APPLICABLE,
        confidence=0.9,
        grounding=(
            GroundingFact(
                text="strategy still applies to the view", tag=GroundingTag.CURRENT
            ),
        ),
    )


def _progress(
    must_assessments: tuple[CriterionAssessment, ...],
    *,
    nice_assessments: tuple[CriterionAssessment, ...] = (),
    applicability: StrategyApplicability | None = None,
) -> ProgressEvidence:
    return ProgressEvidence(
        must_have_assessments=must_assessments,
        applicability=applicability or _applicable(),
        nice_to_have_assessments=nice_assessments,
    )


def _runtime(
    *,
    strategy_responses: list[ScriptedResponse],
    progress_responses: list[ScriptedResponse],
    signals: list | None = None,
) -> tuple:
    clock = VirtualMonotonicClock()
    driver = CompletionDriver(clock=clock)
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=strategy_responses,
        progress_responses=progress_responses,
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
    return runtime, driver, clock, reasoner


async def _next(runtime, *, timeout: float = 2.0):
    return await asyncio.wait_for(runtime.outputs().__anext__(), timeout=timeout)


async def _drain(runtime, *, timeout: float = 0.05) -> list:
    """Collect every currently-buffered projection without blocking the test.

    A short timeout per item means a blocked reader stops as soon as the queue
    is empty rather than hanging the run.
    """
    items: list = []
    while True:
        try:
            items.append(await _next(runtime, timeout=timeout))
        except (asyncio.TimeoutError, StopAsyncIteration):
            return items


async def _pump_until_pending(
    driver: CompletionDriver, *, max_pumps: int = 10000
) -> None:
    for _ in range(max_pumps):
        await asyncio.sleep(0)
        if driver.pending():
            return
    raise AssertionError("scripted adapter call never registered")


async def _intend(runtime) -> None:
    await _next(runtime)  # consume the construction (revision 0) projection
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(),
            task_epoch=0,
            accepted_intention="portrait",
        )
    )
    await _next(runtime)  # consume the orienting projection


async def _first_settle(runtime, driver, clock) -> None:
    """Drive two mutually equivalent observations past the configured dwell.

    Leaves the runtime SETTLED with one Evidence identity admitted and exactly
    one orientation (strategy) call pending.
    """
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(1, clock=clock),
        )
    )
    clock.advance(RuntimeConfig().settled.dwell_seconds)
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(2, clock=clock),
        )
    )
    await _next(runtime)  # consume the settled projection
    await _pump_until_pending(driver)


async def _reach_coaching(runtime, driver, clock) -> None:
    """Reach the point where a strategy completion is pending, then complete it.

    Consumes the construction, orienting, and settled projections and drives the
    strategy completion; the *coaching* projection is left buffered for the caller
    to read through the public ``outputs`` seam.
    """
    await _intend(runtime)
    await _first_settle(runtime, driver, clock)
    driver.complete_next()  # strategy completion -> coaching projection buffered


async def _resettle_and_drive_progress(runtime, driver, clock) -> list:
    """Invalidate via a material change, re-settle, and drive one progress call.

    Returns the buffered invalidation/settling projections plus the final
    progress projection as the last element.
    """
    # A material visual change immediately invalidates Evidence/run/overlay and
    # begins a fresh settling period. The scripted computer reports it.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    clock.advance(RuntimeConfig().settled.dwell_seconds)
    # A second mutually equivalent observation settles and admits a fresh Evidence
    # identity, which requests a material progress evaluation.
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(4, clock=clock),
        )
    )
    buffered = await _drain(runtime)  # invalidation + settle projections
    await _pump_until_pending(driver)
    driver.complete_next()  # progress completion
    progress_projection = await _next(runtime)
    return [*buffered, progress_projection]


def _must_have_ids(runtime) -> tuple[UUID, ...]:
    return tuple(
        c.criterion_id
        for c in runtime._strategy.criteria
        if c.importance is CriterionImportance.MUST_HAVE
    )


def _nice_ids(runtime) -> tuple[UUID, ...]:
    return tuple(
        c.criterion_id
        for c in runtime._strategy.criteria
        if c.importance is CriterionImportance.NICE_TO_HAVE
    )


def _action_text(runtime, criterion_id: UUID) -> str:
    for c in runtime._strategy.criteria:
        if c.criterion_id == criterion_id:
            return c.candidate_actions[0].text
    raise AssertionError("criterion not found")


def _assert_invariants(trace: list) -> None:
    assert_no_obsolete_current_output(trace)
    assert_output_order_is_committed(trace)
    for projection in trace:
        assert_coaching_projection_well_formed(projection)
        assert_at_most_one_active_instruction(projection)
        assert_truthful_activity_when_no_instruction(projection)


# ===========================================================================
# Dormancy guard
# ===========================================================================


def test_progress_path_remains_dormant_off_production_root() -> None:
    assert DORMANT is True


# ===========================================================================
# T05: Hold while improving — exact identity/text preserved
# ===========================================================================


async def test_T05_improving_preserves_exact_instruction_identity_and_text() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_insufficient(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)  # consume the (already-emitted) coaching proj
    # The coaching projection carries exactly one actionable Instruction.
    assert coaching.instruction is not None
    assert coaching.instruction.kind is InstructionKind.ACTION
    assert coaching.instruction.text == "Step left"
    assert coaching.instruction.freshness is InstructionFreshness.CURRENT
    held_id = coaching.instruction.instruction_id
    active_criterion = runtime._instruction_criterion_id
    assert active_criterion is not None

    # A fresh Settled Evidence after a material change requests progress. The
    # scripted reasoner returns an ``improving`` assessment for the active
    # Must-have.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_improving(active_criterion),)))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    progress = trace[-1]

    # T05: the exact Instruction identity and text are preserved; only freshness
    # may change. The trajectory coalesces — no new Instruction identity.
    assert progress.instruction is not None
    assert progress.instruction.instruction_id == held_id
    assert progress.instruction.text == "Step left"
    assert progress.instruction.freshness is InstructionFreshness.CURRENT
    assert runtime._instruction_criterion_id == active_criterion
    assert runtime._readiness is None  # improving never establishes Ready
    _assert_invariants(trace)
    await runtime.close()


# ===========================================================================
# T06: Achievement and advance — close once, advance to next unmet
# ===========================================================================


async def test_T06_achievement_closes_once_and_advances_to_next_unmet() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
            _criterion(priority=1, target="horizon level", action="Level the camera"),
        ),
        must_have_assessments=(
            _insufficient(uuid4()),
            _insufficient(uuid4()),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    assert coaching.instruction is not None
    assert coaching.instruction.text == "Step left"  # highest-priority unmet
    first_instruction_id = coaching.instruction.instruction_id

    c0, c1 = _must_have_ids(runtime)
    assert runtime._instruction_criterion_id == c0

    # Progress: the active Must-have is achieved; the other remains unmet.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_achieved(c0), _insufficient(c1))))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    advance = trace[-1]

    # T06: the prior Instruction closes ``achieved`` exactly once and the runtime
    # advances to one new action for the highest-priority unmet Must-have.
    assert advance.instruction is not None
    assert advance.instruction.kind is InstructionKind.ACTION
    assert advance.instruction.text == "Level the camera"
    assert advance.instruction.instruction_id != first_instruction_id
    assert runtime._instruction_criterion_id == c1
    dispositions = runtime._instruction_dispositions
    assert dispositions[first_instruction_id] is InstructionDisposition.ACHIEVED
    assert_single_terminal_disposition([dispositions[first_instruction_id]])
    assert advance.readiness is None  # not every must-have achieved yet
    _assert_invariants(trace)
    await runtime.close()


# ===========================================================================
# T07: All must-haves achieved — Ready derived; nice-to-haves may remain unmet
# ===========================================================================


async def test_T07_all_must_haves_achieved_derives_ready_with_nice_to_have_unmet() -> (
    None
):
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
            _criterion(
                importance="nice_to_have",
                priority=1,
                target="tidy background",
                action="Tidy the background",
            ),
        ),
        must_have_assessments=(_insufficient(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    assert coaching.instruction is not None
    assert coaching.instruction.kind is InstructionKind.ACTION
    must_ids = _must_have_ids(runtime)
    nice_ids = _nice_ids(runtime)
    assert len(must_ids) == 1 and len(nice_ids) == 1
    c0 = must_ids[0]
    n0 = nice_ids[0]

    # Progress: the Must-have is achieved; the Nice-to-have remains unmet. Ready
    # is derived from the Must-have assessment only (Nice-to-haves never block).
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(
            _progress(
                (_achieved(c0),),
                nice_assessments=(_insufficient(n0),),
            )
        )
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    ready = trace[-1]

    # T07: Ready is derived from one current compatible Evidence Snapshot.
    assert ready.instruction is not None
    assert ready.instruction.kind is InstructionKind.READY
    assert ready.readiness is not None
    assert ready.readiness.state is ReadinessState.READY
    assert ready.readiness.supporting_evidence_id == runtime._evidence.evidence_id
    assert ready.readiness.evidence_snapshot_id == runtime._last_snapshot.snapshot_id
    # The Nice-to-have remained unmet yet did not block Ready.
    n0_assessment = next(
        a
        for a in runtime._last_snapshot.nice_to_have_assessments
        if a.criterion_id == n0
    )
    assert n0_assessment.classification is CriterionClassification.INSUFFICIENT
    assert_ready_cites_current_evidence(ready, runtime._last_snapshot, RuntimeConfig())
    _assert_invariants(trace)
    await runtime.close()


# ===========================================================================
# P02: Nice-to-have unmet — Ready immediate; no Nice-to-have Instruction
# ===========================================================================


async def test_P02_nice_to_have_never_instructs_or_blocks_ready() -> None:
    # Initial Strategy: the single Must-have is achieved at strategy time, so
    # Ready is derived immediately even though a Nice-to-have is unmet (no
    # assessment for it yet). v2 emits no Nice-to-have Instruction.
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
            _criterion(
                importance="nice_to_have",
                priority=1,
                target="tidy background",
                action="Tidy the background",
            ),
        ),
        must_have_assessments=(_achieved(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _next(runtime)  # construction projection
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(),
            task_epoch=0,
            accepted_intention="portrait",
        )
    )
    orienting = await _next(runtime)
    assert orienting.instruction is None  # no Nice-to-have Instruction before Ready
    await _first_settle(runtime, driver, clock)
    driver.complete_next()  # strategy
    ready0 = await _next(runtime)
    # P02: Ready is immediate; no Nice-to-have Instruction before or after Ready.
    assert ready0.instruction is not None
    assert ready0.instruction.kind is InstructionKind.READY
    assert ready0.readiness is not None
    assert ready0.readiness.state is ReadinessState.READY
    ready_instruction_id = ready0.instruction.instruction_id
    must_ids = _must_have_ids(runtime)
    nice_ids = _nice_ids(runtime)
    c0 = must_ids[0]
    n0 = nice_ids[0]

    # After Ready, a progress assessment reports the Must-have achieved and the
    # Nice-to-have insufficient. Ready is reconfirmed; no Nice-to-have Instruction
    # is ever emitted.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(
            _progress(
                (_achieved(c0),),
                nice_assessments=(_insufficient(n0),),
            )
        )
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    reconfirmed = trace[-1]
    assert reconfirmed.instruction is not None
    assert reconfirmed.instruction.kind is InstructionKind.READY
    # No Nice-to-have Instruction was ever emitted: the ready Instruction is
    # preserved (P02 + T08 reconfirmation).
    assert reconfirmed.instruction.instruction_id == ready_instruction_id
    assert reconfirmed.readiness is not None
    assert reconfirmed.readiness.state is ReadinessState.READY
    _assert_invariants([ready0, reconfirmed])
    await runtime.close()


# ===========================================================================
# T08: Regression after Ready — revalidation, reconfirmation, replacement
# ===========================================================================


async def _reach_ready(runtime, driver, clock) -> None:
    """Reach the point where a strategy completion is pending, then complete it.

    The *ready* projection is left buffered for the caller to read.
    """
    await _intend(runtime)
    await _first_settle(runtime, driver, clock)
    driver.complete_next()  # strategy -> Ready projection buffered


async def _ready_progress(runtime, driver, clock, reasoner, must_assessment) -> list:
    reasoner.progress_responses.append(
        ScriptedResponse.success_for(_progress((must_assessment,)))
    )
    return await _resettle_and_drive_progress(runtime, driver, clock)


async def test_T08_motion_marks_ready_for_revalidation_without_revoking() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_achieved(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_ready(runtime, driver, clock)
    ready0 = await _next(runtime)
    assert ready0.readiness is not None
    assert ready0.readiness.state is ReadinessState.READY
    ready_instruction_id = ready0.instruction.instruction_id
    c0 = _must_have_ids(runtime)[0]

    # T08: motion marks Ready for revalidation without revoking it. The material
    # change invalidates Evidence and marks the ready Instruction
    # ``needs_revalidation`` (identity preserved, not revoked).
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    revalidation = await _next(runtime)
    assert revalidation.instruction is not None
    assert revalidation.instruction.instruction_id == ready_instruction_id
    assert revalidation.instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    assert revalidation.readiness is not None
    assert revalidation.readiness.state is ReadinessState.NEEDS_REVALIDATION
    assert runtime._evidence is None  # Evidence invalidated

    # Reconfirmation: fresh accepted Evidence with the Must-have still achieved
    # preserves the exact ready Instruction identity. The progress response
    # is appended before the settling frame so the progress effect task finds
    # it when it runs.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_achieved(c0),)))
    )
    clock.advance(RuntimeConfig().settled.dwell_seconds)
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(4, clock=clock),
        )
    )
    await _drain(runtime)  # settle projection
    await _pump_until_pending(driver)
    driver.complete_next()
    reconfirmed = await _next(runtime)
    assert reconfirmed.instruction is not None
    assert reconfirmed.instruction.instruction_id == ready_instruction_id
    assert reconfirmed.instruction.freshness is InstructionFreshness.CURRENT
    assert reconfirmed.readiness is not None
    assert reconfirmed.readiness.state is ReadinessState.READY
    assert_ready_cites_current_evidence(
        reconfirmed,
        runtime._last_snapshot,
        RuntimeConfig(),
    )
    _assert_invariants([ready0, revalidation, reconfirmed])
    await runtime.close()


async def test_T08_capture_marks_ready_for_revalidation_without_revoking() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_achieved(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        # The capture itself invalidates Evidence; the reconfirmation re-settles
        # on an equivalent routine frame (no second material change needed).
        signals=[equivalent_no_change(), equivalent_no_change()],
    )
    await _reach_ready(runtime, driver, clock)
    ready0 = await _next(runtime)
    ready_instruction_id = ready0.instruction.instruction_id
    c0 = _must_have_ids(runtime)[0]

    # T08: a local user capture marks Ready for revalidation without revoking it
    # and requires fresh live Evidence (the prior evaluation is invalidated).
    await runtime.submit(
        UserCaptureEvent(
            event_id=uuid4(),
            task_id=runtime._task.task_id,
        )
    )
    after_capture = await _next(runtime)
    assert after_capture.instruction is not None
    assert after_capture.instruction.instruction_id == ready_instruction_id
    assert (
        after_capture.instruction.freshness is InstructionFreshness.NEEDS_REVALIDATION
    )
    assert after_capture.readiness is not None
    assert after_capture.readiness.state is ReadinessState.NEEDS_REVALIDATION
    assert runtime._evidence is None  # fresh Evidence required

    # Fresh Settled Evidence reconfirms Ready (identity preserved). The
    # progress response is appended before the settling frame so the progress
    # effect task finds it when it runs.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_achieved(c0),)))
    )
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(3, clock=clock),
        )
    )
    clock.advance(RuntimeConfig().settled.dwell_seconds)
    await runtime.submit(
        ObservationReceivedEvent(
            event_id=uuid4(),
            observation=build_observation(4, clock=clock),
        )
    )
    await _drain(runtime)
    await _pump_until_pending(driver)
    driver.complete_next()
    reconfirmed = await _next(runtime)
    assert reconfirmed.instruction is not None
    assert reconfirmed.instruction.instruction_id == ready_instruction_id
    assert reconfirmed.readiness is not None
    assert reconfirmed.readiness.state is ReadinessState.READY
    _assert_invariants([ready0, after_capture, reconfirmed])
    await runtime.close()


async def test_T08_accepted_regression_replaces_ready_with_one_corrective_instruction() -> (
    None
):
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_achieved(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_ready(runtime, driver, clock)
    ready0 = await _next(runtime)
    ready_instruction_id = ready0.instruction.instruction_id
    c0 = _must_have_ids(runtime)[0]

    # Accepted regression: fresh accepted Evidence reports the Must-have
    # deviating. The ready Instruction is replaced by one corrective action
    # Instruction for the regressed Must-have.
    trace = await _ready_progress(runtime, driver, clock, reasoner, _deviating(c0))
    replaced = trace[-1]
    assert replaced.instruction is not None
    assert replaced.instruction.kind is InstructionKind.ACTION
    assert replaced.instruction.text == "Step left"
    assert replaced.instruction.instruction_id != ready_instruction_id
    assert replaced.readiness is None  # Ready replaced
    # The ready Instruction recorded exactly one terminal disposition.
    dispositions = runtime._instruction_dispositions
    assert dispositions[ready_instruction_id] is InstructionDisposition.SUPERSEDED
    assert_single_terminal_disposition([dispositions[ready_instruction_id]])
    assert runtime._instruction_criterion_id == c0  # corrective targets the regress
    _assert_invariants([ready0, *trace])
    await runtime.close()


# ===========================================================================
# P05: Deviating criterion — regressed higher-priority Must-have preempts
# ===========================================================================


async def test_P05_higher_priority_deviating_must_have_preempts_without_stacking() -> (
    None
):
    # C0 (priority 0, higher) is achieved at strategy time; C1 (priority 1) is
    # unmet, so the runtime coaches C1. A later progress assessment reports C0
    # deviating (regressed) — the higher-priority Must-have preempts C1.
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="horizon level", action="Level the camera"),
            _criterion(priority=1, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(
            _achieved(uuid4()),
            _insufficient(uuid4()),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    assert coaching.instruction is not None
    assert coaching.instruction.text == "Step left"  # C1 is the unmet Must-have
    c1_instruction_id = coaching.instruction.instruction_id
    c0, c1 = _must_have_ids(runtime)
    assert runtime._instruction_criterion_id == c1

    # Progress: C0 (higher priority) deviates; C1 remains unmet. C0 preempts C1.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_deviating(c0), _insufficient(c1))))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    preempted = trace[-1]

    # P05: the regressed higher-priority Must-have preempts the current action
    # Instruction with one corrective Instruction; no stacked instructions.
    assert preempted.instruction is not None
    assert preempted.instruction.kind is InstructionKind.ACTION
    assert preempted.instruction.text == "Level the camera"  # corrective for C0
    assert preempted.instruction.instruction_id != c1_instruction_id
    assert runtime._instruction_criterion_id == c0  # focus moved to C0
    dispositions = runtime._instruction_dispositions
    assert dispositions[c1_instruction_id] is InstructionDisposition.SUPERSEDED
    assert_single_terminal_disposition([dispositions[c1_instruction_id]])
    _assert_invariants([coaching, *trace])
    await runtime.close()


# ===========================================================================
# P01: Every Must-have reassessed; malformed rejected atomically
# ===========================================================================


async def test_P01_valid_progress_assesses_every_must_have_once_with_bounds() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
            _criterion(priority=1, target="horizon level", action="Level the camera"),
        ),
        must_have_assessments=(
            _insufficient(uuid4()),
            _insufficient(uuid4()),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    await _next(runtime)  # coaching projection
    c0, c1 = _must_have_ids(runtime)

    # P01: every Must-have is assessed exactly once against the same Evidence
    # with 1–4 bounded grounding facts, finite [0,1] or null confidence, and
    # bounded typed uncertainty.
    bounded = CriterionAssessment(
        criterion_id=c0,
        classification=CriterionClassification.IMPROVING,
        confidence=0.62,
        grounding=(
            GroundingFact(
                text="subject drifting toward center", tag=GroundingTag.CURRENT
            ),
            GroundingFact(text="earlier off-center", tag=GroundingTag.PREVIOUS),
        ),
        uncertainty_reasons=(UncertaintyReason.BLURRED,),
    )
    null_conf = CriterionAssessment(
        criterion_id=c1,
        classification=CriterionClassification.INSUFFICIENT,
        confidence=None,
        grounding=(
            GroundingFact(text="horizon not yet level", tag=GroundingTag.CURRENT),
        ),
        uncertainty_reasons=(UncertaintyReason.POOR_LIGHTING,),
    )
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((bounded, null_conf)))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    admitted = trace[-1]

    snapshot = runtime._last_snapshot
    assert snapshot is not None
    assert {a.criterion_id for a in snapshot.must_have_assessments} == {c0, c1}
    assert len(snapshot.must_have_assessments) == 2  # exactly once each
    a0 = next(a for a in snapshot.must_have_assessments if a.criterion_id == c0)
    assert a0.confidence == 0.62
    assert len(a0.grounding) == 2
    assert UncertaintyReason.BLURRED in a0.uncertainty_reasons
    a1 = next(a for a in snapshot.must_have_assessments if a.criterion_id == c1)
    assert a1.confidence is None  # finite or null confidence
    # The active Instruction is preserved (improving / still-insufficient).
    assert admitted.instruction is not None
    assert admitted.instruction.kind is InstructionKind.ACTION
    _assert_invariants(trace)
    await runtime.close()


async def test_P01_progress_missing_a_must_have_is_rejected_atomically() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
            _criterion(priority=1, target="horizon level", action="Level the camera"),
        ),
        must_have_assessments=(
            _insufficient(uuid4()),
            _insufficient(uuid4()),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    c0, c1 = _must_have_ids(runtime)
    held_id = coaching.instruction.instruction_id  # type: ignore[union-attr]
    held_text = coaching.instruction.text  # type: ignore[union-attr]

    # Malformed: only one of two Must-haves is assessed. Rejected atomically.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_insufficient(c0),)))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    rejected = trace[-1]
    # Prior guidance is preserved: the active Instruction is unchanged.
    assert rejected.instruction is not None
    assert rejected.instruction.instruction_id == held_id
    assert rejected.instruction.text == held_text
    # The malformed snapshot was not admitted: the material change cleared
    # the prior snapshot, and the rejected progress did not allocate a new one.
    assert runtime._last_snapshot is None
    _assert_invariants(trace)
    await runtime.close()


async def test_P01_progress_with_duplicate_or_unknown_refs_is_rejected() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
            _criterion(priority=1, target="horizon level", action="Level the camera"),
        ),
        must_have_assessments=(
            _insufficient(uuid4()),
            _insufficient(uuid4()),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[
            equivalent_no_change(),
            material_change(),
            equivalent_no_change(),
            material_change(),
            equivalent_no_change(),
        ],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    c0, c1 = _must_have_ids(runtime)
    held_id = coaching.instruction.instruction_id  # type: ignore[union-attr]

    # Duplicate Must-have criterion references cannot reach the runtime: the
    # ``ProgressEvidence`` contract enforces unique references at the seam
    # boundary, so a strict Adapter can never construct one. The runtime's
    # own coverage/uniqueness admission is exercised by the missing- and
    # unknown-reference cases below and in the dedicated test.
    with pytest.raises(ValueError):
        _progress((_insufficient(c0), _insufficient(c0)))

    # Unknown criterion reference (a bogus id presented as a Must-have) is
    # rejected atomically; prior guidance is preserved.
    bogus = uuid4()
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(
            _progress((_insufficient(c0), _insufficient(bogus)))
        )
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    rejected = trace[-1]
    assert rejected.instruction.instruction_id == held_id  # prior guidance preserved
    assert runtime._last_snapshot is None  # malformed snapshot not admitted
    _assert_invariants(trace)
    await runtime.close()


async def test_P01_progress_missing_current_grounding_is_rejected() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_insufficient(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    c0 = _must_have_ids(runtime)[0]
    held_id = coaching.instruction.instruction_id  # type: ignore[union-attr]

    # A Must-have assessment with no current grounding fact is malformed.
    no_current = CriterionAssessment(
        criterion_id=c0,
        classification=CriterionClassification.INSUFFICIENT,
        confidence=0.4,
        grounding=(GroundingFact(text="earlier view", tag=GroundingTag.PREVIOUS),),
    )
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((no_current,)))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    rejected = trace[-1]
    assert rejected.instruction.instruction_id == held_id  # prior guidance preserved
    _assert_invariants(trace)
    await runtime.close()


async def test_P01_stale_progress_completion_is_a_harmless_discard() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_insufficient(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    held_id = coaching.instruction.instruction_id  # type: ignore[union-attr]
    c0 = _must_have_ids(runtime)[0]

    # A progress completion with the wrong provenance is a harmless stale discard.
    from camera_agent.v2.identity import Provenance, RemotePurpose

    stale_receipt = await runtime.submit(
        ReasonerProgressEvent(
            event_id=uuid4(),
            provenance=Provenance(
                purpose=RemotePurpose.PROGRESS,
                run_id=uuid4(),
                identities={
                    "task": runtime._task.task_id,
                    "evidence": uuid4(),
                    "strategy": runtime._strategy.strategy_id,
                },
            ),
            evidence=_progress((_improving(c0),)),
        )
    )
    assert stale_receipt.disposition.value == "stale"
    assert runtime._output_queue.empty()
    # The active Instruction is unchanged.
    assert runtime._instruction is not None
    assert runtime._instruction.instruction_id == held_id

    # The current-token progress completion still admits the snapshot.
    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_improving(c0),)))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    admitted = trace[-1]
    assert admitted.instruction.instruction_id == held_id  # improving preserves
    _assert_invariants(trace)
    await runtime.close()


# ===========================================================================
# Regression: immutable Instruction semantics across progress
# ===========================================================================


async def test_progress_preserves_instruction_immutability_for_identity() -> None:
    proposal = StrategyProposal(
        criteria=(
            _criterion(priority=0, target="subject centered", action="Step left"),
        ),
        must_have_assessments=(_insufficient(uuid4()),),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )
    runtime, driver, clock, reasoner = _runtime(
        strategy_responses=[ScriptedResponse.success_for(proposal)],
        progress_responses=[],
        signals=[equivalent_no_change(), material_change(), equivalent_no_change()],
    )
    await _reach_coaching(runtime, driver, clock)
    coaching = await _next(runtime)
    c0 = _must_have_ids(runtime)[0]
    held = coaching.instruction  # type: ignore[assignment]

    reasoner.progress_responses.append(  # type: ignore[attr-defined]
        ScriptedResponse.success_for(_progress((_improving(c0),)))
    )
    trace = await _resettle_and_drive_progress(runtime, driver, clock)
    progress = trace[-1]
    # The improving assessment preserved the exact identity AND content tuple;
    # only freshness was allowed to change.
    assert_instruction_immutable_for_identity(held, progress.instruction)  # type: ignore[arg-type]
    await runtime.close()
