"""Tests for the deterministic public-seam test controls (issue #19).

These tests prove the controls themselves: that they implement the approved
public Adapter seams as strict doubles, drive virtual time and deterministic
identities, hand out immutable fixtures, trace outputs and capture resource
high-water marks, expose reusable mandatory-invariant assertions, and stay off
the production composition root.

The controls are infrastructure for subsequent v2 behavior tickets (e.g. #21):
they do not drive a live ``CoachingRuntime`` here, because the runtime
implementation lands in a later ticket. They are exercised against synthetic
contract values and the scripted adapters in isolation so the control surface
is provably ready once the runtime lands.
"""

from __future__ import annotations

import asyncio
import hashlib
from uuid import UUID, uuid4

import pytest

import camera_agent.__main__ as production_main
import camera_agent.server as production_server
import tests.v2_controls as controls
from camera_agent.v2 import (
    ActionDisposition,
    ActionKind,
    ActionTarget,
    ActionTargetKind,
    Activity,
    ActivityKind,
    AvailableAction,
    CoachingPhase,
    CoachingReasoner,
    ContextImage,
    Criterion,
    CriterionAssessment,
    CriterionClassification,
    CriterionImportance,
    DORMANT,
    EvidenceIdentity,
    EvidenceSnapshot,
    GeneratedArtifact,
    GroundingFact,
    GroundingTag,
    IllustrationEditor,
    Instruction,
    InstructionDisposition,
    InstructionKind,
    OutputKind,
    Provenance,
    Readiness,
    ReadinessState,
    RemotePurpose,
    RuntimeConfig,
    ShotStrategy,
    Task,
    TypedFailure,
    VisualEntityKind,
    VisualGuidanceIntent,
    VisualGuidanceSidecar,
    VisualSidecarStatus,
    new_action_ordinal_uuid,
)
from camera_agent.v2.contracts import ActionResultOutput, CoachingProjection
from camera_agent.v2.seams import (
    AdapterFailure,
    AuthorizedIllustrationRequest,
    EditedIllustration,
    ProgressContextPack,
    ProposedCriterion,
    RevisionContextPack,
    StrategyContextPack,
    StrategyProposal,
)
from tests.v2_controls import (
    CompletionDriver,
    DeterministicIdentityFactory,
    ImageFixture,
    InvariantViolation,
    OutputTrace,
    PendingCall,
    RecordedIdentityMap,
    ResourceHighWater,
    ScriptedEditor,
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
    assert_visual_sidecar_isolated,
    default_preview_fixture,
    default_still_fixture,
    deterministic_session_salt,
)


# --- Shared builders -------------------------------------------------------


def _identity() -> UUID:
    # A distinct non-deterministic identity, mirroring production uuid4.
    return uuid4()


def _factory() -> DeterministicIdentityFactory:
    return DeterministicIdentityFactory()


def _clock() -> VirtualMonotonicClock:
    return VirtualMonotonicClock()


def _evidence(fid: DeterministicIdentityFactory) -> EvidenceIdentity:
    return EvidenceIdentity(
        evidence_id=fid.new_identity(),
        camera_context_id=fid.new_identity(),
        observation_id=1,
        source_bytes_hash="sha256:abc",
    )


def _image(fid: DeterministicIdentityFactory) -> ContextImage:
    return ContextImage(
        image_id=fid.new_identity(),
        bytes_hash="sha256:img",
        width=1920,
        height=1080,
    )


def _strategy_provenance(fid: DeterministicIdentityFactory) -> Provenance:
    return Provenance(
        purpose=RemotePurpose.STRATEGY,
        run_id=fid.new_identity(),
        identities={"task": fid.new_identity(), "evidence": fid.new_identity()},
    )


def _criterion(fid: DeterministicIdentityFactory) -> Criterion:
    return Criterion(
        criterion_id=fid.new_identity(),
        importance=CriterionImportance.MUST_HAVE,
        priority=0,
        observable_target="subject centered in frame",
    )


def _strategy(fid: DeterministicIdentityFactory) -> ShotStrategy:
    return ShotStrategy(
        strategy_id=fid.new_identity(),
        criteria=(_criterion(fid),),
        creation_reason="initial orientation",
    )


def _strategy_pack(fid: DeterministicIdentityFactory) -> StrategyContextPack:
    return StrategyContextPack(
        provenance=_strategy_provenance(fid),
        accepted_intention="portrait",
        journey="portrait",
        evidence=_evidence(fid),
        current_image=_image(fid),
        creation_reason="initial",
    )


def _progress_pack(fid: DeterministicIdentityFactory) -> ProgressContextPack:
    return ProgressContextPack(
        provenance=Provenance(
            purpose=RemotePurpose.PROGRESS,
            run_id=fid.new_identity(),
            identities={"task": fid.new_identity(), "evidence": fid.new_identity()},
        ),
        strategy=_strategy(fid),
        active_instruction_text="Step left",
        evidence=_evidence(fid),
        current_image=_image(fid),
    )


def _revision_pack(fid: DeterministicIdentityFactory) -> RevisionContextPack:
    return RevisionContextPack(
        provenance=Provenance(
            purpose=RemotePurpose.REVISION,
            run_id=fid.new_identity(),
            identities={"task": fid.new_identity(), "evidence": fid.new_identity()},
        ),
        affected_criterion_id=fid.new_identity(),
        evidence=_evidence(fid),
        current_image=_image(fid),
    )


def _edit_request(fid: DeterministicIdentityFactory) -> AuthorizedIllustrationRequest:
    return AuthorizedIllustrationRequest(
        provenance=Provenance(purpose=RemotePurpose.EDIT, run_id=fid.new_identity()),
        demonstrates="raise the camera",
        accepted_still=_image(fid),
    )


def _strategy_proposal(fid: DeterministicIdentityFactory) -> StrategyProposal:
    crit = ProposedCriterion(
        importance="must_have",
        priority=0,
        observable_target="centered",
        candidate_actions=("step left",),
    )
    return StrategyProposal(
        criteria=(crit,),
        must_have_assessments=(
            CriterionAssessment(
                criterion_id=fid.new_identity(),
                classification=CriterionClassification.ACHIEVED,
                confidence=0.9,
                grounding=(GroundingFact(text="centered", tag=GroundingTag.CURRENT),),
            ),
        ),
        visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
    )


def _edited_illustration(fid: DeterministicIdentityFactory) -> EditedIllustration:
    return EditedIllustration(
        image_id=fid.new_identity(),
        bytes_hash="sha256:edit",
        mime_type="image/jpeg",
        width=1024,
        height=1024,
    )


def _adapter_failure(purpose: RemotePurpose, fid: DeterministicIdentityFactory) -> AdapterFailure:
    return AdapterFailure(
        failure=TypedFailure.UNAVAILABLE,
        provenance=Provenance(
            purpose=purpose,
            run_id=fid.new_identity(),
            identities={"task": fid.new_identity(), "evidence": fid.new_identity()},
        )
        if purpose is not RemotePurpose.EDIT
        else Provenance(purpose=RemotePurpose.EDIT, run_id=fid.new_identity()),
    )


# ===========================================================================
# Criterion 4: controls are test-only and not a public semantic seam
# ===========================================================================


def test_v2_package_remains_dormant() -> None:
    assert DORMANT is True


def test_production_composition_root_does_not_import_test_controls() -> None:
    import inspect

    for module in (production_main, production_server):
        source = inspect.getsource(module)
        assert "v2_controls" not in source
        assert "from tests" not in source
        assert "import tests" not in source


def test_controls_do_not_export_public_seam_names() -> None:
    # The controls package must not invent reducer/scheduler/transport/visual
    # authority names that would become public semantic seams.
    forbidden = {
        "Reducer",
        "Scheduler",
        "Transport",
        "VisualWorkflow",
        "VisualWorkflowAuthority",
        "GenericTransport",
    }
    public = set(controls.__all__)
    assert not (forbidden & public)


# ===========================================================================
# Virtual monotonic clock
# ===========================================================================


def test_clock_starts_at_origin_and_advances_deterministically() -> None:
    clock = VirtualMonotonicClock()
    assert clock.now() == 0.0
    clock.advance(2.5)
    assert clock.now() == 2.5
    clock.advance(0.5)
    assert clock.now() == 3.0


def test_clock_rejects_backward_motion() -> None:
    clock = VirtualMonotonicClock(origin=10.0)
    assert clock.now() == 10.0
    with pytest.raises(ValueError):
        clock.advance(-1.0)


def test_clock_fires_timers_in_time_then_insertion_order() -> None:
    clock = VirtualMonotonicClock()
    fired: list[str] = []
    # Schedule two timers at the same instant: insertion order breaks ties.
    clock.schedule(5.0, lambda: fired.append("second"), label="b")
    clock.schedule(5.0, lambda: fired.append("first"), label="a")
    clock.schedule(3.0, lambda: fired.append("early"), label="c")
    matured = clock.advance(5.0)
    assert fired == ["early", "second", "first"]
    assert [t.label for t in matured] == ["c", "b", "a"]
    assert clock.now() == 5.0


def test_clock_cancel_and_pending() -> None:
    clock = VirtualMonotonicClock()
    called = []
    timer = clock.schedule(4.0, lambda: called.append("x"), label="x")
    assert len(clock.pending_timers()) == 1
    clock.cancel(timer)
    assert len(clock.pending_timers()) == 0
    clock.advance(10.0)
    assert called == []


# ===========================================================================
# Deterministic identities and recorded identity mappings
# ===========================================================================


def test_deterministic_identity_factory_is_reproducible_and_disjoint() -> None:
    a = DeterministicIdentityFactory()
    b = DeterministicIdentityFactory()
    seq_a = [a.new_identity() for _ in range(8)]
    seq_b = [b.new_identity() for _ in range(8)]
    assert seq_a == seq_b
    # Distinct seed => disjoint stream.
    from uuid import uuid5, NAMESPACE_DNS

    other = DeterministicIdentityFactory(seed=uuid5(NAMESPACE_DNS, "other"))
    assert other.new_identity() not in seq_a
    # All are real UUIDs.
    assert all(isinstance(x, UUID) for x in seq_a)


def test_deterministic_identity_factory_reset_replays_sequence() -> None:
    factory = DeterministicIdentityFactory()
    first_run = [factory.new_identity() for _ in range(4)]
    factory.reset()
    second_run = [factory.new_identity() for _ in range(4)]
    assert first_run == second_run


def test_recorded_identity_map_is_immutable_view_and_stable() -> None:
    mapping = RecordedIdentityMap()
    task = _identity()
    evidence = _identity()
    mapping.record("task", task)
    mapping.record("evidence", evidence)
    with pytest.raises(ValueError):
        mapping.record("task", _identity())
    table = mapping.as_token_table()
    with pytest.raises(TypeError):
        table["task"] = _identity()  # type: ignore[index]
    assert mapping.require("evidence") == evidence
    with pytest.raises(KeyError):
        mapping.require("run")
    # Deterministic session salt makes action ordinals reproducible.
    salt = deterministic_session_salt()
    assert new_action_ordinal_uuid(0, salt) == new_action_ordinal_uuid(0, salt)


# ===========================================================================
# Immutable image fixtures
# ===========================================================================


def test_image_fixture_hash_is_sha256_of_bytes() -> None:
    import hashlib

    fixture = default_preview_fixture()
    expected = "sha256:" + hashlib.sha256(fixture.bytes_).hexdigest()
    assert fixture.bytes_hash == expected
    assert (fixture.width, fixture.height) == (480, 640)
    still = default_still_fixture()
    assert still.bytes_hash != fixture.bytes_hash


def test_image_fixture_is_immutable_and_validates_hash() -> None:
    fixture = default_still_fixture()
    with pytest.raises(ValueError):
        ImageFixture(
            bytes_=fixture.bytes_,
            bytes_hash="sha256:wrong",
            width=fixture.width,
            height=fixture.height,
            mime_type="image/jpeg",
        )
    with pytest.raises(ValueError):
        ImageFixture(
            bytes_=b"",
            bytes_hash="sha256:" + "0" * 64,
            width=1,
            height=1,
            mime_type="image/jpeg",
        )
    with pytest.raises(ValueError):
        ImageFixture(
            bytes_=b"x",
            bytes_hash="sha256:" + hashlib.sha256(b"x").hexdigest(),
            width=0,
            height=1,
            mime_type="image/jpeg",
        )


def test_image_fixture_produces_context_image_with_factory_identity() -> None:
    fid = _factory()
    fixture = default_preview_fixture()
    ctx = fixture.to_context_image_with_factory(fid)
    assert isinstance(ctx, ContextImage)
    assert ctx.bytes_hash == fixture.bytes_hash
    assert (ctx.width, ctx.height) == (fixture.width, fixture.height)


# ===========================================================================
# Strict scripted adapters: protocol satisfaction
# ===========================================================================


def test_scripted_adapters_satisfy_the_public_seam_protocols() -> None:
    driver = CompletionDriver(clock=_clock())
    reasoner = ScriptedReasoner(driver=driver)
    editor = ScriptedEditor(driver=driver)
    assert isinstance(reasoner, CoachingReasoner)
    assert isinstance(editor, IllustrationEditor)


def test_a_plain_object_does_not_satisfy_the_seam_protocols() -> None:
    assert not isinstance(object(), CoachingReasoner)
    assert not isinstance(object(), IllustrationEditor)


# ===========================================================================
# Controlled success, typed failure, timeout, completion order
# ===========================================================================


async def test_scripted_reasoner_returns_controlled_success() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    proposal = _strategy_proposal(fid)
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(proposal)],
    )
    task = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
    await asyncio.sleep(0)  # let the call register
    assert driver.in_flight_count() == 1
    driver.complete_next()
    result = await task
    assert result is proposal
    assert driver.in_flight_count() == 0
    assert driver.high_water.peak_concurrent == 1


async def test_scripted_reasoner_returns_controlled_typed_failure() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    failure = _adapter_failure(RemotePurpose.STRATEGY, fid)
    reasoner = ScriptedReasoner(
        driver=driver,
        progress_responses=[ScriptedResponse.failure_for(
            TypedFailure.UNAVAILABLE,
            provenance=Provenance(
                purpose=RemotePurpose.PROGRESS,
                run_id=fid.new_identity(),
                identities={"task": fid.new_identity(), "evidence": fid.new_identity()},
            ),
        )],
    )
    # Override the success/failure wiring: use a failure response directly.
    reasoner.progress_responses = [ScriptedResponse(
        failure=failure, cancellable=True
    )]
    task = asyncio.create_task(reasoner.assess_progress(_progress_pack(fid)))
    await asyncio.sleep(0)
    driver.fail_next()
    result = await task
    assert isinstance(result, AdapterFailure)
    assert result.failure is TypedFailure.UNAVAILABLE


async def test_scripted_editor_returns_controlled_success() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    illustration = _edited_illustration(fid)
    editor = ScriptedEditor(
        driver=driver,
        render_responses=[ScriptedResponse.success_for(illustration)],
    )
    task = asyncio.create_task(editor.render(_edit_request(fid)))
    await asyncio.sleep(0)
    driver.complete_next()
    result = await task
    assert result is illustration


async def test_explicit_completion_order_is_test_driven() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[
            ScriptedResponse.success_for(_strategy_proposal(fid)),
            ScriptedResponse.success_for(_strategy_proposal(fid)),
        ],
    )
    # Start two strategy calls out of order and complete the second first.
    t1 = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
    t2 = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
    await asyncio.sleep(0)
    pending = driver.pending()
    assert len(pending) == 2
    second = pending[1]
    first = pending[0]
    driver.complete(second)
    driver.complete(first)
    r2 = await t2
    r1 = await t1
    assert r2 is not None and r1 is not None
    # The high-water of two concurrent in-flight calls was captured.
    assert driver.high_water.peak_concurrent == 2


async def test_timeout_call_never_self_completes_and_deadline_resolves_it() -> None:
    fid = _factory()
    clock = _clock()
    driver = CompletionDriver(clock=clock)
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.timeout_for()],
    )
    task = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
    await asyncio.sleep(0)
    pending = driver.pending()
    assert len(pending) == 1
    call = pending[0]
    assert call.response.timeout is True
    # A timeout call cannot be completed via complete_next.
    with pytest.raises(ValueError):
        driver.complete_next()
    # Advancing the clock alone does not mature the call (the runtime, not the
    # adapter, owns the deadline).
    clock.advance(8.0)
    assert len(driver.pending()) == 1
    # The runtime enforces its deadline through the driver.
    driver.time_out_next()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert driver.in_flight_count() == 0


async def test_cancellable_call_frees_slot_on_cancel() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.timeout_for(cancellable=True)],
    )
    task = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
    await asyncio.sleep(0)
    call = driver.pending()[0]
    assert call.cancellable is True
    driver.cancel(call)
    with pytest.raises(asyncio.CancelledError):
        await task
    assert driver.in_flight_count() == 0


async def test_non_cancellable_call_retains_slot_until_physical_completion() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    proposal = _strategy_proposal(fid)
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(proposal, cancellable=False)],
    )
    task = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
    await asyncio.sleep(0)
    call = driver.pending()[0]
    assert call.cancellable is False
    # Logical cancellation marks the call abandoned but does NOT free the slot.
    driver.cancel(call)
    assert call.logically_abandoned is True
    assert driver.in_flight_count() == 1, "non-cancellable call still occupies a slot"
    # A deadline cannot physically abort a non-cancellable call either.
    call2 = driver.pending()[0]
    driver.time_out(call2)
    assert driver.in_flight_count() == 1
    # The call only frees its slot when it physically matures.
    driver.complete(call2)
    assert driver.in_flight_count() == 0
    # The awaiter receives the (stale, to-be-discarded) outcome.
    result = await task
    assert result is proposal


async def test_non_cancellable_abandoned_then_failed_records_stale_outcome() -> None:
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    failure = _adapter_failure(RemotePurpose.PROGRESS, fid)
    reasoner = ScriptedReasoner(
        driver=driver,
        progress_responses=[ScriptedResponse(failure=failure, cancellable=False)],
    )
    task = asyncio.create_task(reasoner.assess_progress(_progress_pack(fid)))
    await asyncio.sleep(0)
    call = driver.pending()[0]
    driver.cancel(call)
    assert call.logically_abandoned
    driver.fail(call)
    result = await task
    assert isinstance(result, AdapterFailure)
    # The trace records the stale/abandoned lifecycle.
    row = driver.trace[-1]
    assert row.outcome_kind == "failure"


# ===========================================================================
# Output/effect tracing and resource high-water capture
# ===========================================================================


def test_output_trace_records_ordered_outputs_and_revisions() -> None:
    fid = _factory()
    trace = OutputTrace()
    p1 = CoachingProjection(
        session_id=fid.new_identity(),
        state_revision=0,
        task=None,
        phase=CoachingPhase.NEEDS_INTENTION,
        instruction=None,
        activity=Activity(kind=ActivityKind.WAITING, text="Waiting for intention"),
        overlays=None,
    )
    p2 = CoachingProjection(
        session_id=p1.session_id,
        state_revision=1,
        task=Task(
            task_epoch=0,
            task_id=fid.new_identity(),
            accepted_intention="portrait",
            strategy_revision=fid.new_identity(),
        ),
        phase=CoachingPhase.ORIENTING,
        instruction=None,
        activity=Activity(kind=ActivityKind.WORKING, text="Orienting"),
        overlays=None,
    )
    trace.append(p1)
    trace.append(p2)
    assert trace.kinds() == (OutputKind.COACHING_PROJECTION, OutputKind.COACHING_PROJECTION)
    assert trace.state_revisions() == (0, 1)


def test_call_trace_records_purpose_order() -> None:
    fid = _factory()
    clock = _clock()
    driver = CompletionDriver(clock=clock)
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(_strategy_proposal(fid))],
        progress_responses=[ScriptedResponse.success_for(_strategy_proposal(fid))],
    )

    async def drive() -> None:
        t1 = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
        await asyncio.sleep(0)
        driver.complete_next()
        await t1
        t2 = asyncio.create_task(reasoner.assess_progress(_progress_pack(fid)))
        await asyncio.sleep(0)
        driver.complete_next()
        await t2

    asyncio.run(drive())
    assert driver.trace.purposes_in_order() == ("strategy", "progress")
    assert driver.trace[0].outcome_kind == "success"
    assert driver.trace[1].completed_at is not None


def test_resource_high_water_captures_peaks() -> None:
    hw = ResourceHighWater()
    hw.observe_concurrent(1)
    hw.observe_concurrent(2)
    hw.observe_concurrent(1)
    hw.observe_pending(3)
    hw.observe_pending(1)
    hw.observe_retained_images(2)
    hw.observe_send_queue(10, 1024)
    snap = hw.snapshot()
    assert snap["peak_concurrent"] == 2
    assert snap["peak_pending"] == 3
    assert snap["peak_retained_images"] == 2
    assert snap["peak_send_queue_frames"] == 10


# ===========================================================================
# Reusable mandatory-invariant assertions
# ===========================================================================


def _projection(
    fid: DeterministicIdentityFactory,
    *,
    state_revision: int = 0,
    task: Task | None = None,
    instruction: Instruction | None = None,
    activity: Activity | None = None,
    readiness: Readiness | None = None,
    visual: VisualGuidanceSidecar | None = None,
    actions: tuple[AvailableAction, ...] = (),
) -> CoachingProjection:
    return CoachingProjection(
        session_id=fid.new_identity(),
        state_revision=state_revision,
        task=task,
        phase=CoachingPhase.COACHING,
        instruction=instruction,
        activity=activity,
        overlays=None,
        available_actions=actions,
        readiness=readiness,
        visual_guidance=visual,
    )


def test_invariant_at_most_one_active_instruction_passes() -> None:
    fid = _factory()
    instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.ACTION,
        text="Step left",
    )
    task = Task(
        task_epoch=0,
        task_id=fid.new_identity(),
        accepted_intention="portrait",
        strategy_revision=fid.new_identity(),
    )
    action = AvailableAction(
        action_id=fid.new_identity(),
        ordinal=0,
        kind=ActionKind.TRY_ANOTHER_SUGGESTION,
        target=ActionTarget(
            kind=ActionTargetKind.INSTRUCTION,
            identity=instruction.instruction_id,
        ),
    )
    projection = _projection(
        fid, task=task, instruction=instruction,
        activity=Activity(kind=ActivityKind.WORKING, text="Coaching"),
        actions=(action,),
    )
    assert_at_most_one_active_instruction(projection)


def test_invariant_at_most_one_active_instruction_rejects_other_target() -> None:
    fid = _factory()
    instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.ACTION,
        text="Step left",
    )
    task = Task(
        task_epoch=0,
        task_id=fid.new_identity(),
        accepted_intention="portrait",
        strategy_revision=fid.new_identity(),
    )
    wrong = AvailableAction(
        action_id=fid.new_identity(),
        ordinal=0,
        kind=ActionKind.TRY_ANOTHER_SUGGESTION,
        target=ActionTarget(
            kind=ActionTargetKind.INSTRUCTION,
            identity=fid.new_identity(),  # a different instruction id
        ),
    )
    projection = _projection(
        fid, task=task, instruction=instruction,
        activity=Activity(kind=ActivityKind.WORKING, text="Coaching"),
        actions=(wrong,),
    )
    with pytest.raises(InvariantViolation):
        assert_at_most_one_active_instruction(projection)


def test_invariant_immutable_identity_preserved_on_hold() -> None:
    fid = _factory()
    iid = fid.new_identity()
    first = Instruction(instruction_id=iid, kind=InstructionKind.ACTION, text="Step left")
    held = Instruction(instruction_id=iid, kind=InstructionKind.ACTION, text="Step left")
    assert_instruction_immutable_for_identity(first, held)
    changed = Instruction(instruction_id=iid, kind=InstructionKind.ACTION, text="Step right")
    with pytest.raises(InvariantViolation):
        assert_instruction_immutable_for_identity(first, changed)


def test_invariant_truthful_activity_when_no_instruction() -> None:
    fid = _factory()
    good = _projection(
        fid, activity=Activity(kind=ActivityKind.WAITING, text="Waiting for intention")
    )
    assert_truthful_activity_when_no_instruction(good)
    blank = _projection(fid, activity=None)
    with pytest.raises(InvariantViolation):
        assert_truthful_activity_when_no_instruction(blank)


def test_invariant_no_obsolete_current_output_rejects_regression() -> None:
    fid = _factory()
    p0 = _projection(fid, state_revision=0, activity=Activity(kind=ActivityKind.WAITING, text="w"))
    p1 = _projection(fid, state_revision=1, activity=Activity(kind=ActivityKind.WORKING, text="x"))
    p_stale = _projection(fid, state_revision=1, activity=Activity(kind=ActivityKind.WORKING, text="y"))
    assert_no_obsolete_current_output([p0, p1])
    with pytest.raises(InvariantViolation):
        assert_no_obsolete_current_output([p0, p1, p_stale])


def test_invariant_ready_cites_current_evidence() -> None:
    fid = _factory()
    evidence = _evidence(fid)
    strategy = _strategy(fid)
    assessment = CriterionAssessment(
        criterion_id=strategy.criteria[0].criterion_id,
        classification=CriterionClassification.ACHIEVED,
        confidence=0.9,
        grounding=(GroundingFact(text="centered", tag=GroundingTag.CURRENT),),
    )
    snapshot = EvidenceSnapshot(
        snapshot_id=fid.new_identity(),
        evidence=evidence,
        task_id=fid.new_identity(),
        strategy_id=strategy.strategy_id,
        must_have_assessments=(assessment,),
    )
    task = Task(
        task_epoch=0,
        task_id=fid.new_identity(),
        accepted_intention="portrait",
        strategy_revision=strategy.strategy_id,
    )
    instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.READY,
        text="Ready—take the shot.",
        source_evidence_id=evidence.evidence_id,
    )
    readiness = Readiness(
        state=ReadinessState.READY,
        evidence_snapshot_id=snapshot.snapshot_id,
        supporting_evidence_id=evidence.evidence_id,
    )
    projection = _projection(
        fid, state_revision=1, task=task, instruction=instruction,
        activity=Activity(kind=ActivityKind.WORKING, text="Ready"),
        readiness=readiness,
    )
    assert_ready_cites_current_evidence(projection, snapshot, RuntimeConfig())


def test_invariant_ready_rejects_low_confidence() -> None:
    fid = _factory()
    evidence = _evidence(fid)
    strategy = _strategy(fid)
    assessment = CriterionAssessment(
        criterion_id=strategy.criteria[0].criterion_id,
        classification=CriterionClassification.ACHIEVED,
        confidence=0.5,  # below the 0.75 threshold
        grounding=(GroundingFact(text="centered", tag=GroundingTag.CURRENT),),
    )
    snapshot = EvidenceSnapshot(
        snapshot_id=fid.new_identity(),
        evidence=evidence,
        task_id=fid.new_identity(),
        strategy_id=strategy.strategy_id,
        must_have_assessments=(assessment,),
    )
    task = Task(
        task_epoch=0,
        task_id=fid.new_identity(),
        accepted_intention="portrait",
        strategy_revision=strategy.strategy_id,
    )
    instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.READY,
        text="Ready—take the shot.",
        source_evidence_id=evidence.evidence_id,
    )
    readiness = Readiness(
        state=ReadinessState.READY,
        evidence_snapshot_id=snapshot.snapshot_id,
        supporting_evidence_id=evidence.evidence_id,
    )
    projection = _projection(
        fid, state_revision=1, task=task, instruction=instruction,
        activity=Activity(kind=ActivityKind.WORKING, text="Ready"),
        readiness=readiness,
    )
    with pytest.raises(InvariantViolation):
        assert_ready_cites_current_evidence(projection, snapshot, RuntimeConfig())


def test_invariant_visual_sidecar_isolation() -> None:
    fid = _factory()
    instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.ACTION,
        text="Step left",
    )
    task = Task(
        task_epoch=0,
        task_id=fid.new_identity(),
        accepted_intention="portrait",
        strategy_revision=fid.new_identity(),
    )
    artifact = GeneratedArtifact(
        image_message_id=fid.new_identity(),
        announced_at_state_revision=2,
        demonstrates="raise the camera",
    )
    sidecar = VisualGuidanceSidecar(
        visual_id=fid.new_identity(),
        kind=VisualEntityKind.JOB,
        status=VisualSidecarStatus.AVAILABLE,
        source_instruction_id=instruction.instruction_id,
        demonstrates="raise the camera",
        artifact=artifact,
    )
    # A delivered artifact alongside an Instruction is fine (sidecar is concurrent).
    assert_visual_sidecar_isolated(
        _projection(
            fid, task=task, instruction=instruction,
            activity=Activity(kind=ActivityKind.WORKING, text="Coaching"),
            visual=sidecar,
        )
    )
    # A delivered artifact may coexist with Ready: the sidecar must not be the
    # Ready evidence, but coexistence alone is not an isolation violation
    # (the generated-image-is-not-Ready-evidence check lives in
    # assert_ready_cites_current_evidence).
    evidence = _evidence(fid)
    ready_instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.READY,
        text="Ready—take the shot.",
        source_evidence_id=evidence.evidence_id,
    )
    readiness = Readiness(
        state=ReadinessState.READY,
        evidence_snapshot_id=fid.new_identity(),
        supporting_evidence_id=evidence.evidence_id,
    )
    assert_visual_sidecar_isolated(
        _projection(
            fid, task=task, instruction=ready_instruction,
            activity=Activity(kind=ActivityKind.WORKING, text="Ready"),
            readiness=readiness,
            visual=sidecar,
        )
    )
    # But an artifact with no Instruction is an isolation violation.
    with pytest.raises(InvariantViolation):
        assert_visual_sidecar_isolated(
            _projection(fid, visual=sidecar)
        )


def test_invariant_well_formed_ready_requires_readiness() -> None:
    fid = _factory()
    task = Task(
        task_epoch=0,
        task_id=fid.new_identity(),
        accepted_intention="portrait",
        strategy_revision=fid.new_identity(),
    )
    instruction = Instruction(
        instruction_id=fid.new_identity(),
        kind=InstructionKind.READY,
        text="Ready—take the shot.",
        source_evidence_id=fid.new_identity(),
    )
    projection = _projection(
        fid, task=task, instruction=instruction,
        activity=Activity(kind=ActivityKind.WORKING, text="Ready"),
        readiness=None,  # missing
    )
    with pytest.raises(InvariantViolation):
        assert_coaching_projection_well_formed(projection)


def test_invariant_single_terminal_disposition_enforces_exactly_one() -> None:
    # §4.3: a closed Instruction records exactly one terminal disposition.
    assert_single_terminal_disposition([InstructionDisposition.ACHIEVED])
    with pytest.raises(InvariantViolation):
        assert_single_terminal_disposition([])
    with pytest.raises(InvariantViolation):
        assert_single_terminal_disposition(
            [InstructionDisposition.ACHIEVED, InstructionDisposition.REJECTED]
        )


def test_invariant_output_order_rejects_duplicate_action_acknowledgement() -> None:
    # §4.15: an explicit action id is one-use; a duplicate transmission MUST
    # NOT execute a second acknowledgement.
    fid = _factory()
    session = fid.new_identity()
    action_id = fid.new_identity()
    message_id = fid.new_identity()
    ack = ActionResultOutput(
        session_id=session,
        action_id=action_id,
        action_message_id=message_id,
        disposition=ActionDisposition.ACCEPTED,
    )
    duplicate = ActionResultOutput(
        session_id=session,
        action_id=action_id,
        action_message_id=message_id,  # same transmission
        disposition=ActionDisposition.DUPLICATE,
    )
    # A duplicate transmission is a no-op: the first acknowledgement stands.
    assert_output_order_is_committed([ack, duplicate])
    # But two distinct acknowledged transmissions of the same message id is a
    # committed-order violation.
    with pytest.raises(InvariantViolation):
        assert_output_order_is_committed(
            [
                ActionResultOutput(
                    session_id=session,
                    action_id=action_id,
                    action_message_id=message_id,
                    disposition=ActionDisposition.ACCEPTED,
                ),
                ActionResultOutput(
                    session_id=session,
                    action_id=action_id,
                    action_message_id=message_id,
                    disposition=ActionDisposition.ACCEPTED,
                ),
            ]
        )


# ===========================================================================
# The controls do not expose writable runtime state
# ===========================================================================


def test_scripted_adapters_do_not_allocate_revisions_or_state() -> None:
    # The scripted adapters expose no writable runtime-state attributes: they
    # only hold response queues and a completion-driver handle. There is no state
    # revision, no reducer, no mailbox on them.
    driver = CompletionDriver(clock=_clock())
    reasoner = ScriptedReasoner(driver=driver)
    editor = ScriptedEditor(driver=driver)
    forbidden_attrs = {"state_revision", "reducer", "mailbox", "current_state", "strategy"}
    for obj in (reasoner, editor, driver):
        for attr in forbidden_attrs:
            assert not hasattr(obj, attr), f"{type(obj).__name__} must not expose {attr}"


def test_pending_call_outcome_is_not_writable_runtime_state() -> None:
    # A pending call exposes its scripted response and lifecycle, but no
    # writable runtime state lane and no authority to allocate revisions.
    fid = _factory()
    driver = CompletionDriver(clock=_clock())
    reasoner = ScriptedReasoner(
        driver=driver,
        strategy_responses=[ScriptedResponse.success_for(_strategy_proposal(fid))],
    )

    async def drive() -> PendingCall:
        task = asyncio.create_task(reasoner.propose_strategy(_strategy_pack(fid)))
        await asyncio.sleep(0)
        call = driver.pending()[0]
        driver.complete_next()
        await task
        return call

    call = asyncio.run(drive())
    assert call.outcome is not None
    # The call records terminal fields but no runtime authority.
    for attr in ("state_revision", "reducer", "mailbox", "current_state"):
        assert not hasattr(call, attr)
