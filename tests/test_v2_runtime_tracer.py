"""Deterministic behavior tests for the v2 ``CoachingRuntime`` tracer bullet.

These tests drive the public ``CoachingRuntime`` Interface (``submit`` /
``outputs`` / ``close``) constructed through ``build_runtime`` to prove the
first coaching tracer bullet (issue #21):

- T01: no intention produces ``needs_intention``, truthful waiting Activity, no
  reasoning, and a complete immutable projection;
- T02: a changed/explicitly-updated intention invalidates old authority,
  allocates application-owned Task provenance, and immediately projects
  truthful Orienting Activity;
- T03: a scripted Strategy completion is admitted atomically and produces one
  actionable Instruction (app-authored IDs) without a second call;
- T04: a same-Evidence Strategy proposal with every must-have achieved derives
  immediate Ready without a second call;
- T11 (applicable initial): the phase-precedence projections covered by this
  bullet — ``needs_intention`` → ``orienting`` → ``coaching`` / ``ready`` —
  with the visual sidecar never changing phase;
- U12 (applicable initial): ``close`` invalidates authority immediately, late
  outcomes cannot act or emit, and output iteration terminates; and
- the mailbox-ordering criteria: concurrent submissions receive one
  authoritative order, state commits precede effects/outputs, and stale
  completions are harmless.

Behavior is exercised only through the public runtime seam and the strict
scripted Adapter doubles. The dormant v2 path stays off the production
composition root (the package remains ``DORMANT``).
"""

from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

from camera_agent.v2 import (
    DORMANT,
    ActivityKind,
    CoachingPhase,
    CoachingReasoner,
    CriterionAssessment,
    CriterionClassification,
    EvidenceIdentity,
    GroundingFact,
    GroundingTag,
    InstructionKind,
    Provenance,
    RemotePurpose,
    RuntimeConfig,
    VisualGuidanceIntent,
    build_runtime,
)
from camera_agent.v2.contracts import (
    EvidenceSettledEvent,
    IntentionAcceptedEvent,
    ReasonerStrategyEvent,
)
from camera_agent.v2.seams import (
    ProposedCriterion,
    StrategyProposal,
)
from tests.v2_controls import (
    CompletionDriver,
    ScriptedEditor,
    ScriptedReasoner,
    ScriptedResponse,
    VirtualMonotonicClock,
    assert_at_most_one_active_instruction,
    assert_coaching_projection_well_formed,
    assert_no_obsolete_current_output,
    assert_output_order_is_committed,
    assert_ready_cites_current_evidence,
    assert_truthful_activity_when_no_instruction,
)


# --- shared builders --------------------------------------------------------


def _evidence() -> EvidenceIdentity:
    return EvidenceIdentity(
        evidence_id=uuid4(),
        camera_context_id=uuid4(),
        observation_id=1,
        source_bytes_hash="sha256:abc",
    )


def _action_proposal(*, action: str = "Step left", actor: str | None = "photographer") -> StrategyProposal:
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


def _ready_proposal() -> StrategyProposal:
    """A one-must-have proposal whose must-have is achieved -> immediate Ready."""
    return StrategyProposal(
        criteria=(
            ProposedCriterion(
                importance="must_have",
                priority=0,
                observable_target="subject centered in frame",
                candidate_actions=("Hold still",),
            ),
        ),
        must_have_assessments=(
            CriterionAssessment(
                criterion_id=uuid4(),
                classification=CriterionClassification.ACHIEVED,
                confidence=0.9,
                grounding=(
                    GroundingFact(text="subject is centered", tag=GroundingTag.CURRENT),
                ),
            ),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )


def _runtime_with_strategy(proposal: StrategyProposal):
    """Build a runtime whose reasoner will return ``proposal`` on first call."""
    driver = CompletionDriver(clock=VirtualMonotonicClock())
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(proposal)],
    )
    editor = ScriptedEditor(driver=driver)
    runtime = build_runtime(RuntimeConfig(), reasoner=reasoner, editor=editor)
    return runtime, driver


async def _pump_until_pending(driver: CompletionDriver, *, max_pumps: int = 10000) -> None:
    """Pump the event loop until the scripted adapter has a registered call.

    ``submit`` returns before the background strategy effect has registered its
    adapter call, so a deterministic test pumps until the call exists before
    driving its completion.
    """
    for _ in range(max_pumps):
        await asyncio.sleep(0)
        if driver.pending():
            return
    raise AssertionError("scripted adapter call never registered")


async def _drain(runtime, *, max_items: int = 64, timeout: float = 1.0) -> list:
    """Collect every currently-buffered output through the public ``outputs``.

    After ``close`` the iterator drains committed-then-close outputs and
    terminates, so this returns exactly the buffered projections without ever
    blocking the test indefinitely.
    """
    collected: list = []

    async def collect() -> None:
        async for output in runtime.outputs():
            collected.append(output)
            if len(collected) >= max_items:
                break

    await asyncio.wait_for(collect(), timeout=timeout)
    return collected


async def _next(runtime):
    """Pull the next committed projection through the public ``outputs`` seam."""
    return await runtime.outputs().__anext__()


async def _intend_and_settle(runtime, driver, *, intention: str = "portrait"):
    """Submit an intention then a settled Evidence view; return (p1, p2, evidence)."""
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=0, accepted_intention=intention,
        )
    )
    p1 = await _next(runtime)
    evidence = _evidence()
    await runtime.submit(
        EvidenceSettledEvent(
            event_id=uuid4(), evidence=evidence, task_id=p1.task.task_id,
        )
    )
    p2 = await _next(runtime)
    await _pump_until_pending(driver)
    return p1, p2, evidence


def _assert_invariants(trace: list) -> None:
    """Apply the mandatory invariants covered by the tracer bullet."""
    assert_no_obsolete_current_output(trace)
    assert_output_order_is_committed(trace)
    for projection in trace:
        assert_coaching_projection_well_formed(projection)
        assert_at_most_one_active_instruction(projection)
        assert_truthful_activity_when_no_instruction(projection)


# ===========================================================================
# Dormancy: the tracer bullet stays off the production composition root
# ===========================================================================


def test_tracer_bullet_keeps_v2_dormant_off_production_root() -> None:
    assert DORMANT is True


def test_build_runtime_returns_a_coaching_runtime() -> None:
    runtime, _ = _runtime_with_strategy(_action_proposal())
    # The concrete runtime satisfies the CoachingRuntime Protocol structurally
    # (submit/outputs/close) and is not the reasoner seam.
    assert hasattr(runtime, "submit")
    assert hasattr(runtime, "outputs")
    assert hasattr(runtime, "close")
    assert not isinstance(runtime, CoachingReasoner)


# ===========================================================================
# T01: no intention
# ===========================================================================


async def test_T01_no_intention_projects_needs_intention_with_no_reasoning() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    projection = await _next(runtime)

    assert projection.task is None
    assert projection.instruction is None
    assert projection.readiness is None
    assert projection.phase == CoachingPhase.NEEDS_INTENTION
    assert projection.activity is not None
    assert projection.activity.kind is ActivityKind.WAITING
    assert projection.activity.text.strip()
    assert projection.state_revision == 0
    # No reasoning has been launched.
    assert driver.pending() == ()
    assert len(driver.trace) == 0
    _assert_invariants([projection])
    await runtime.close()


# ===========================================================================
# T02: new/changed intention invalidates old authority and orients
# ===========================================================================


async def test_T02_new_intention_allocates_task_and_projects_orienting() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    initial = await _next(runtime)

    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=0, accepted_intention="portrait",
        )
    )
    orienting = await _next(runtime)

    assert orienting.task is not None
    assert orienting.task.accepted_intention == "portrait"
    assert orienting.task.task_epoch == 0
    # Application-owned provenance: real UUID identities, not model-authored.
    assert isinstance(orienting.task.task_id, UUID)
    assert isinstance(orienting.task.strategy_revision, UUID)
    # Post-intention: no Instruction, no Strategy, no evidence yet.
    assert orienting.instruction is None
    assert orienting.readiness is None
    assert orienting.phase == CoachingPhase.ORIENTING
    assert orienting.activity is not None
    assert orienting.activity.kind is ActivityKind.WORKING
    # Revisions strictly increase through the committed projection stream.
    assert orienting.state_revision == initial.state_revision + 1
    # No reasoning yet — Settled Evidence is required before any VLM work.
    assert driver.pending() == ()
    assert len(driver.trace) == 0
    _assert_invariants([initial, orienting])
    await runtime.close()


async def test_T02_changed_intention_invalidates_old_authority() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    await _next(runtime)
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=0, accepted_intention="first",
        )
    )
    first = await _next(runtime)
    first_task_id = first.task.task_id

    # A changed intention replaces the task immediately.
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=1, accepted_intention="second",
        )
    )
    second = await _next(runtime)
    assert second.task.accepted_intention == "second"
    assert second.task.task_id != first_task_id
    assert second.task.task_epoch == first.task.task_epoch + 1
    # Old authority cleared: no instruction, no readiness, orienting again.
    assert second.instruction is None
    assert second.readiness is None
    assert second.phase == CoachingPhase.ORIENTING
    _assert_invariants([first, second])
    await runtime.close()


# ===========================================================================
# T03: initial strategy and first action
# ===========================================================================


async def test_T03_strategy_completion_produces_one_actionable_instruction() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal(action="Step left"))
    initial = await _next(runtime)
    p1, p2, evidence = await _intend_and_settle(runtime, driver)

    # Pre-completion: orienting, analysis requested, exactly one strategy call.
    assert p2.phase == CoachingPhase.ORIENTING
    assert p2.instruction is None
    assert len(driver.trace) == 1
    assert driver.trace[0].purpose == RemotePurpose.STRATEGY.value

    driver.complete_next()
    p3 = await _next(runtime)

    # One actionable Instruction; no second call.
    assert p3.instruction is not None
    assert p3.instruction.kind is InstructionKind.ACTION
    assert p3.instruction.text == "Step left"
    assert p3.instruction.addressee is not None  # mapped from "photographer"
    assert p3.phase == CoachingPhase.COACHING
    assert p3.readiness is None
    # Application-authored IDs: the Strategy and its Criteria carry real UUIDs.
    strategy = runtime._strategy
    assert strategy is not None
    assert isinstance(strategy.strategy_id, UUID)
    assert all(isinstance(c.criterion_id, UUID) for c in strategy.criteria)
    # The Task's strategy_revision now references the admitted Strategy.
    assert p3.task.strategy_revision == strategy.strategy_id
    # Only one Reasoner call occurred (no second assess_progress call).
    assert len(driver.trace) == 1
    _assert_invariants([initial, p1, p2, p3])
    await runtime.close()


async def test_T03_instruction_provenance_cites_admitted_snapshot() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    await _next(runtime)
    _, _, evidence = await _intend_and_settle(runtime, driver)
    driver.complete_next()
    p3 = await _next(runtime)
    snapshot = runtime._last_snapshot
    assert snapshot is not None
    assert snapshot.evidence.evidence_id == evidence.evidence_id
    assert snapshot.strategy_id == runtime._strategy.strategy_id
    # The Instruction's identity is application-authored (real UUID).
    assert isinstance(p3.instruction.instruction_id, UUID)
    await runtime.close()


# ===========================================================================
# T04: immediate Ready without a second call
# ===========================================================================


async def test_T04_immediate_ready_without_second_call() -> None:
    runtime, driver = _runtime_with_strategy(_ready_proposal())
    initial = await _next(runtime)
    p1, p2, evidence = await _intend_and_settle(runtime, driver)
    driver.complete_next()
    p3 = await _next(runtime)

    assert p3.instruction is not None
    assert p3.instruction.kind is InstructionKind.READY
    assert p3.instruction.text == "Ready—take the shot."
    assert p3.instruction.source_evidence_id == evidence.evidence_id
    assert p3.readiness is not None
    assert p3.readiness.state.value == "ready"
    assert p3.readiness.supporting_evidence_id == evidence.evidence_id
    assert p3.readiness.evidence_snapshot_id == runtime._last_snapshot.snapshot_id
    assert p3.phase == CoachingPhase.READY
    # Deterministic Ready derived from the single Strategy proposal — no
    # second (assess_progress) call.
    assert len(driver.trace) == 1
    assert_ready_cites_current_evidence(p3, runtime._last_snapshot, RuntimeConfig())
    _assert_invariants([initial, p1, p2, p3])
    await runtime.close()


# ===========================================================================
# T11 (applicable initial): phase-precedence projections
# ===========================================================================


async def test_T11_phase_precedence_needs_intention_then_orienting_then_coaching() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    p0 = await _next(runtime)
    assert p0.phase == CoachingPhase.NEEDS_INTENTION  # no task -> needs_intention

    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=0, accepted_intention="portrait",
        )
    )
    p1 = await _next(runtime)
    # Task exists but no Strategy/Instruction -> orienting (not coaching).
    assert p1.phase == CoachingPhase.ORIENTING

    await runtime.submit(
        EvidenceSettledEvent(
            event_id=uuid4(), evidence=_evidence(), task_id=p1.task.task_id,
        )
    )
    p2 = await _next(runtime)
    await _pump_until_pending(driver)
    # Still orienting while orientation analysis is requested (not evaluating).
    assert p2.phase == CoachingPhase.ORIENTING

    driver.complete_next()
    p3 = await _next(runtime)
    assert p3.phase == CoachingPhase.COACHING  # action Instruction -> coaching
    _assert_invariants([p0, p1, p2, p3])
    await runtime.close()


async def test_T11_ready_precedence_over_orienting() -> None:
    runtime, driver = _runtime_with_strategy(_ready_proposal())
    p0 = await _next(runtime)
    assert p0.phase == CoachingPhase.NEEDS_INTENTION
    _, _, _ = await _intend_and_settle(runtime, driver)
    driver.complete_next()
    p3 = await _next(runtime)
    # A ready Instruction takes precedence over the orienting that preceded it.
    assert p3.phase == CoachingPhase.READY
    assert p3.instruction.kind is InstructionKind.READY
    await runtime.close()


async def test_T11_visual_sidecar_never_changes_coaching_phase() -> None:
    # The tracer bullet never produces a visual sidecar; the invariant holds
    # trivially but is asserted to lock the precedence rule for future tickets.
    runtime, driver = _runtime_with_strategy(_action_proposal())
    p0 = await _next(runtime)
    assert p0.visual_guidance is None
    assert p0.phase == CoachingPhase.NEEDS_INTENTION
    await runtime.close()


# ===========================================================================
# U12 (applicable initial): runtime close
# ===========================================================================


async def test_U12_close_terminates_output_iteration() -> None:
    runtime, _ = _runtime_with_strategy(_action_proposal())
    initial = await _next(runtime)
    await runtime.close()
    # The public outputs() iterator terminates deterministically after close
    # with no buffered projections left to yield.
    assert await _drain(runtime) == []
    _assert_invariants([initial])


async def test_U12_close_invalidates_authority_late_outcomes_cannot_act() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    await _next(runtime)
    await _intend_and_settle(runtime, driver)  # strategy request in flight
    assert len(driver.pending()) == 1

    await runtime.close()  # immediately invalidates outstanding authority

    # Driving the now-cancelled effect cannot emit a projection.
    driver.complete_next()
    assert await _drain(runtime) == []
    assert runtime._strategy is None  # no strategy was admitted

    # A late completion submitted directly is a harmless stale discard: no
    # state mutation, no output.
    receipt = await runtime.submit(
        ReasonerStrategyEvent(
            event_id=uuid4(),
            provenance=Provenance(
                purpose=RemotePurpose.STRATEGY,
                run_id=uuid4(),
                identities={"task": uuid4(), "evidence": uuid4()},
            ),
            proposal=_action_proposal(),
        )
    )
    assert receipt.disposition.value == "stale"
    assert runtime._strategy is None
    assert await _drain(runtime) == []


# ===========================================================================
# Mailbox ordering: concurrent submissions and stale completions
# ===========================================================================


async def test_concurrent_submissions_receive_one_authoritative_order() -> None:
    runtime, _ = _runtime_with_strategy(_action_proposal())
    initial = await _next(runtime)
    e1 = IntentionAcceptedEvent(
        event_id=uuid4(), task_epoch=0, accepted_intention="first",
    )
    e2 = IntentionAcceptedEvent(
        event_id=uuid4(), task_epoch=1, accepted_intention="second",
    )
    r1, r2 = await asyncio.gather(runtime.submit(e1), runtime.submit(e2))
    # One authoritative mailbox order: distinct, sequential orders.
    assert r1.order != r2.order
    assert {r1.order, r2.order} == {0, 1}
    assert r1.disposition.value == "admitted"
    assert r2.disposition.value == "admitted"
    # State commits precede outputs: both orienting projections are enqueued in
    # committed order with strictly increasing revisions.
    p_a = await _next(runtime)
    p_b = await _next(runtime)
    assert p_a.state_revision < p_b.state_revision
    assert {p_a.task.accepted_intention, p_b.task.accepted_intention} == {"first", "second"}
    _assert_invariants([initial, p_a, p_b])
    await runtime.close()


async def test_duplicate_event_id_is_a_harmless_no_op() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    await _next(runtime)
    event = IntentionAcceptedEvent(
        event_id=uuid4(), task_epoch=0, accepted_intention="portrait",
    )
    first = await runtime.submit(event)
    await _next(runtime)
    duplicate = await runtime.submit(event)
    assert first.disposition.value == "admitted"
    assert duplicate.disposition.value == "duplicate"
    assert duplicate.order > first.order  # it consumed an order slot
    # No extra output for the duplicate.
    assert runtime._output_queue.empty()
    await runtime.close()


async def test_stale_strategy_completion_is_harmless_and_does_not_corrupt_state() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    initial = await _next(runtime)
    p1, p2, _ = await _intend_and_settle(runtime, driver)
    trace_before = [initial, p1, p2]

    # A stale completion (wrong provenance) is discarded without state mutation.
    stale_receipt = await runtime.submit(
        ReasonerStrategyEvent(
            event_id=uuid4(),
            provenance=Provenance(
                purpose=RemotePurpose.STRATEGY,
                run_id=uuid4(),
                identities={"task": uuid4(), "evidence": uuid4()},
            ),
            proposal=_action_proposal(),
        )
    )
    assert stale_receipt.disposition.value == "stale"
    assert runtime._output_queue.empty()
    assert runtime._strategy is None  # not admitted
    assert runtime._instruction is None

    # The real, current-token completion still admits the strategy.
    driver.complete_next()
    p3 = await _next(runtime)
    assert p3.instruction is not None
    assert p3.instruction.kind is InstructionKind.ACTION
    assert p3.phase == CoachingPhase.COACHING
    _assert_invariants([*trace_before, p3])
    await runtime.close()


async def test_stale_strategy_completion_after_replacement_is_harmless() -> None:
    runtime, driver = _runtime_with_strategy(_action_proposal())
    await _next(runtime)
    await _intend_and_settle(runtime, driver)  # strategy request #1 in flight

    # A new intention invalidates the first task and its authoritative run.
    await runtime.submit(
        IntentionAcceptedEvent(
            event_id=uuid4(), task_epoch=1, accepted_intention="second",
        )
    )
    await _next(runtime)  # orienting for the new task
    # The first strategy effect is still awaiting; if it completes now its
    # provenance no longer matches the current task -> stale discard.
    driver.complete_next()
    # Pump the loop so the (stale) completion re-enters the mailbox.
    for _ in range(50):
        await asyncio.sleep(0)
    assert runtime._strategy is None  # stale completion did not admit a strategy
    await runtime.close()


# ===========================================================================
# Regression: current-token failure and task-end emit a committed projection
# (the effect/output tuple ordering must not drop the projection).
# ===========================================================================


def _runtime_with_failing_strategy():
    from tests.v2_controls import ScriptedResponse
    from camera_agent.v2.seams import AdapterFailure
    from camera_agent.v2 import TypedFailure
    driver = CompletionDriver(clock=VirtualMonotonicClock())
    failure = AdapterFailure(
        failure=TypedFailure.UNAVAILABLE,
        provenance=Provenance(
            purpose=RemotePurpose.STRATEGY,
            run_id=uuid4(),
            identities={"task": uuid4(), "evidence": uuid4()},
        ),
    )
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse(failure=failure, cancellable=True)],
    )
    editor = ScriptedEditor(driver=driver)
    runtime = build_runtime(RuntimeConfig(), reasoner=reasoner, editor=editor)
    return runtime, driver


async def test_current_strategy_failure_emits_projection_and_clears_run() -> None:
    runtime, driver = _runtime_with_failing_strategy()
    initial = await _next(runtime)
    await _intend_and_settle(runtime, driver)  # strategy request in flight
    await _pump_until_pending(driver)
    # The reasoner returns a typed failure; the runtime re-enters the mailbox
    # with an AdapterFailureEvent. Because the failure's provenance was minted
    # by the runtime for the current run, it is current and must clear the
    # authoritative run and emit a committed projection (not crash/drop it).
    driver.fail_next()
    p_fail = await _next(runtime)
    assert runtime._authoritative_run is None
    assert runtime._strategy is None
    # No Instruction was admitted; coaching guidance stays truthfully orienting.
    assert p_fail.phase == CoachingPhase.ORIENTING
    assert p_fail.instruction is None
    assert p_fail.state_revision > initial.state_revision
    _assert_invariants([initial, p_fail])
    await runtime.close()


async def test_task_ended_clears_task_and_projects_needs_intention() -> None:
    from camera_agent.v2.contracts import TaskEndedEvent
    runtime, driver = _runtime_with_strategy(_action_proposal())
    await _next(runtime)
    _, _, _ = await _intend_and_settle(runtime, driver)
    driver.complete_next()
    coaching = await _next(runtime)
    assert coaching.phase == CoachingPhase.COACHING

    await runtime.submit(
        TaskEndedEvent(event_id=uuid4(), task_id=coaching.task.task_id),
    )
    ended = await _next(runtime)
    assert ended.task is None
    assert ended.instruction is None
    assert ended.readiness is None
    assert ended.phase == CoachingPhase.NEEDS_INTENTION
    assert ended.state_revision > coaching.state_revision
    await runtime.close()
