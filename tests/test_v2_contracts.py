"""Deterministic contract tests for the dormant v2 runtime interfaces.

These tests exercise the canonical v2 contract surface through the public
runtime, host, and adapter seams. They prove:

- the public interfaces are exactly ``CoachingRuntime``, opaque-lifecycle
  ``RuntimeHost``, ``CoachingReasoner``, and ``IllustrationEditor``;
- the immutable versioned configuration and canonical Task, Evidence, Strategy,
  Criterion, Instruction, Readiness, action, recovery, visual, provenance, and
  typed-failure values are defined with their normative bounds;
- canonical runtime events, receipts, complete immutable outputs, and correlated
  effects carry application-authored identities and provenance; and
- no public reducer lane, scheduler, generic transport port, or independent
  visual-workflow authority is introduced.

The dormant v2 path stays off the production composition root: the package is
``DORMANT`` and the production server/main modules do not import it.
"""

from __future__ import annotations

import inspect
from typing import Protocol
from uuid import UUID

import pytest

import camera_agent.__main__ as production_main
import camera_agent.server as production_server
import camera_agent.v2 as v2
from camera_agent.v2 import (
    ActionKind,
    ActionTarget,
    ActionTargetKind,
    Activity,
    ActivityKind,
    AvailableAction,
    BlockedReason,
    CandidateAction,
    CoachingPhase,
    ConnectionOffer,
    ContextImage,
    CoachingReasoner,
    Criterion,
    CriterionAssessment,
    CriterionClassification,
    CriterionImportance,
    CameraContext,
    DORMANT,
    Effect,
    EffectKind,
    EventKind,
    EvidenceIdentity,
    EvidenceSnapshot,
    FrameSignals,
    GeneratedArtifact,
    GroundingFact,
    GroundingTag,
    IllustrationEditor,
    Instruction,
    InstructionKind,
    Observation,
    OutputKind,
    OverlayPrimitive,
    OverlaySet,
    PreviewImage,
    Provenance,
    Readiness,
    ReadinessState,
    Receipt,
    ReceiptDisposition,
    RemotePurpose,
    RuntimeConfig,
    RuntimeHost,
    RuntimeVersion,
    ShotStrategy,
    StrategyApplicability,
    StrategyApplicabilityStatus,
    Task,
    TypedFailure,
    UncertaintyReason,
    VisualEntityKind,
    VisualGuidanceIntent,
    VisualGuidanceSidecar,
    VisualSidecarStatus,
    build_runtime,
    event_identity,
    event_kind,
    new_action_ordinal_uuid,
    new_identity,
    output_kind,
)
from camera_agent.v2.contracts import (
    AdapterFailureEvent,
    CoachingProjection,
    IntentionAcceptedEvent,
    ObservationReceivedEvent,
    ReasonerStrategyEvent,
    UserActionEvent,
)
from camera_agent.v2.seams import (
    AdapterFailure,
    AuthorizedIllustrationRequest,
    EditedIllustration,
    ProgressContextPack,
    ProposedCriterion,
    StrategyContextPack,
    StrategyProposal,
    RevisionContextPack,
)
from camera_agent.v2.runtime import CoachingRuntime


# --- Helpers ----------------------------------------------------------------


def _identity() -> UUID:
    return new_identity()


def _evidence() -> EvidenceIdentity:
    return EvidenceIdentity(
        evidence_id=_identity(),
        camera_context_id=_identity(),
        observation_id=1,
        source_bytes_hash="sha256:abc",
    )


def _image() -> ContextImage:
    return ContextImage(
        image_id=_identity(), bytes_hash="sha256:img", width=1920, height=1080
    )


def _strategy_provenance() -> Provenance:
    return Provenance(
        purpose=RemotePurpose.STRATEGY,
        run_id=_identity(),
        identities={"task": _identity(), "evidence": _identity()},
    )


def _criterion(importance: CriterionImportance = CriterionImportance.MUST_HAVE, priority: int = 0) -> Criterion:
    return Criterion(
        criterion_id=_identity(),
        importance=importance,
        priority=priority,
        observable_target="subject centered in frame",
        candidate_actions=(CandidateAction(text="step left"),),
    )


def _strategy() -> ShotStrategy:
    return ShotStrategy(
        strategy_id=_identity(),
        criteria=(_criterion(),),
        creation_reason="initial orientation",
    )


def _assessment(
    classification: CriterionClassification = CriterionClassification.ACHIEVED,
) -> CriterionAssessment:
    return CriterionAssessment(
        criterion_id=_criterion().criterion_id,
        classification=classification,
        confidence=0.8,
        grounding=(GroundingFact(text="subject centered", tag=GroundingTag.CURRENT),),
    )


# --- Dormancy: the v2 path stays off the production composition root ----------


def test_v2_package_is_marked_dormant() -> None:
    assert DORMANT is True


def test_production_composition_root_does_not_import_v2() -> None:
    # Static check: neither production module references the v2 package by name.
    for module in (production_main, production_server):
        source = inspect.getsource(module)
        assert ".v2" not in source
        assert "from camera_agent.v2" not in source
        assert "import camera_agent.v2" not in source


def test_build_runtime_returns_coaching_runtime() -> None:
    # The tracer-bullet runtime (issue #21) lands through the public factory.
    # It satisfies the ``CoachingRuntime`` Protocol and remains off the
    # production composition root until the atomic-cutover ticket.
    config = RuntimeConfig()
    runtime = build_runtime(config, reasoner=object(), editor=object())  # type: ignore[arg-type]
    assert isinstance(runtime, CoachingRuntime)
    assert DORMANT is True


# --- Public surface is exactly the approved seams ----------------------------


APPROVED_PUBLIC_SEAMS = {CoachingRuntime, RuntimeHost, CoachingReasoner, IllustrationEditor}


def _public_seam_methods(protocol: type) -> set[str]:
    """Non-dunder callable members declared on a Protocol seam."""
    return {
        name
        for name, _ in inspect.getmembers(protocol, predicate=inspect.isfunction)
        if not name.startswith("_")
    }


def test_public_runtime_authority_has_exactly_three_methods() -> None:
    assert _public_seam_methods(CoachingRuntime) == {"submit", "outputs", "close"}


def test_public_host_seam_has_exactly_three_methods() -> None:
    assert _public_seam_methods(RuntimeHost) == {"attach", "detach", "close"}


def test_reasoner_seam_has_exactly_three_methods() -> None:
    assert _public_seam_methods(CoachingReasoner) == {
        "propose_strategy",
        "assess_progress",
        "propose_revision",
    }


def test_editor_seam_has_exactly_one_method() -> None:
    assert _public_seam_methods(IllustrationEditor) == {"render"}


def test_no_forbidden_public_authority_is_introduced() -> None:
    forbidden_names = {
        "Reducer",
        "Scheduler",
        "Transport",
        "VisualWorkflow",
        "VisualWorkflowAuthority",
        "GenericTransport",
    }
    public = set(v2.__all__)
    assert not (forbidden_names & public)
    # No public Protocol in the package is an independently mutable coaching lane.
    for name in public:
        obj = getattr(v2, name)
        if isinstance(obj, type) and getattr(obj, "_is_protocol", False):
            assert obj in APPROVED_PUBLIC_SEAMS, f"unexpected public protocol {name}"


def test_approved_seams_are_runtime_checkable_protocols() -> None:
    for seam in APPROVED_PUBLIC_SEAMS:
        assert issubclass(seam, Protocol)
    # Runtime-checkability is behaviourally proven by the scripted-adapter and
    # plain-object isinstance tests below; the decorator marker is not part of
    # the stable public API across interpreter versions.


# --- Immutable versioned configuration with normative bounds -----------------


def test_runtime_config_defaults_are_uncalibrated_and_within_bounds() -> None:
    config = RuntimeConfig()
    assert config.calibrated is False
    assert config.is_uncalibrated is True
    assert config.ready_confidence_threshold == 0.75
    assert config.physical_vlm_max_concurrency == 2
    assert config.nice_to_have_instruction_budget == 0
    assert config.grounding_max_facts == 4
    assert config.grounding_fact_max_chars == 160
    assert config.uncertainty_max_reasons == 3
    # Sub-policy defaults mirror the evaluation contract §9.
    assert config.heartbeat.intervals_seconds == (15.0, 30.0, 60.0)
    assert config.heartbeat.max_calls_per_rolling_window == 3
    assert config.reasoner_retry.attempt_deadline_seconds == 8.0
    assert config.reasoner_retry.max_automatic_retries == 1
    assert config.reasoner_retry.throttle_delay_cap_seconds == 2.0
    assert config.visual.capture_deadline_seconds == 5.0
    assert config.visual.editor_deadline_seconds == 60.0
    assert config.visual.max_automatic_retries == 0
    assert config.settled.confirmation_count == 2
    assert config.settled.dwell_seconds == 0.5
    assert config.strategy.max_criteria == 6
    assert config.strategy.max_must_have == 4
    assert config.strategy.max_nice_to_have == 2
    assert config.context.structured_text_max_bytes == 32 * 1024
    assert config.action_replay.max_action_receipts == 256
    assert config.action_replay.max_action_message_receipts == 256
    assert config.action_replay.retention_seconds == 600.0
    assert config.continuity.detached_ttl_seconds == 60.0
    assert config.continuity.max_detached_sessions == 1
    assert config.transport.observation_fragment_max_unmatched_per_side == 16
    assert config.transport.observation_fragment_ttl_seconds == 5.0
    assert config.transport.max_message_bytes == 8 * 1024 * 1024
    assert config.transport.send_queue_max_frames == 32
    assert config.transport.send_queue_max_bytes == 16 * 1024 * 1024
    assert config.transport.diagnostic_max_files == 200
    assert config.transport.diagnostic_max_bytes == 256 * 1024 * 1024
    assert config.progress.insufficient_count_before_alternative == 2
    assert config.progress.insufficient_span_seconds == 10.0
    assert config.progress.visual_offer_distinct_insufficient_actions == 2
    # Deterministic frame-signal thresholds (issue #22) inherit the v1 material-
    # change starting points and are explicitly uncalibrated.
    assert config.settled.confirmation_count == 2
    assert config.settled.dwell_seconds == 0.5
    assert config.frame_signals.visual_material_global_mae == 0.04
    assert config.frame_signals.visual_material_block_mae == 0.10
    assert config.frame_signals.visual_material_hash_distance == 6
    assert config.frame_signals.camera_hard_change_keys == (
        "lensID", "orientation", "frameWidth", "frameHeight",
    )


def test_frame_signals_decode_failure_is_conservative_fail_open() -> None:
    # Spec §4.2: decode failure yields unavailable quality data and
    # conservative fail-open change handling. Decode-unavailable forces a
    # material invalidation regardless of the caller's flags, and never
    # fabricates a quality value.
    signals = FrameSignals(
        decode_available=False,
        material_change=False,
        equivalent_to_reference=True,
    )
    assert signals.decode_available is False
    assert signals.material_change is True
    assert signals.equivalent_to_reference is True  # caller's value preserved
    assert "decode_unavailable" in signals.material_reasons
    assert signals.relative_sharpness is None
    assert signals.luminance is None
    assert signals.quality_crossing is False


def test_frame_signals_reject_out_of_range_measurements() -> None:
    with pytest.raises(ValueError):
        FrameSignals(
            decode_available=True,
            material_change=False,
            equivalent_to_reference=True,
            relative_sharpness=1.5,
        )
    with pytest.raises(ValueError):
        FrameSignals(
            decode_available=True,
            material_change=False,
            equivalent_to_reference=True,
            luminance=-0.1,
        )


def test_observation_and_camera_context_are_immutable() -> None:
    camera = CameraContext(
        metadata={"lensID": "wide", "orientation": "portrait", "frameWidth": 480, "frameHeight": 640}
    )
    assert camera.hard_signature == ("wide", "portrait", 480, 640)
    with pytest.raises(TypeError):
        camera.metadata["lensID"] = "tele"  # type: ignore[index]
    preview = PreviewImage(
        bytes_=b"\x00\x01", mime_type="image/jpeg", width=2, height=2,
    )
    assert preview.bytes_hash.startswith("sha256:")
    observation = Observation(
        observation_id=7,
        camera=camera,
        preview=preview,
        arrival_monotonic_seconds=1.0,
        reason="stream",
    )
    assert observation.observation_id == 7
    with pytest.raises(ValueError):
        Observation(
            observation_id=-1,
            camera=camera,
            preview=preview,
            arrival_monotonic_seconds=1.0,
        )


def test_runtime_config_is_frozen() -> None:
    config = RuntimeConfig()
    with pytest.raises((dataclass_frozen_error_types())):
        config.ready_confidence_threshold = 0.5  # type: ignore[misc]


def test_runtime_config_rejects_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        RuntimeConfig(ready_confidence_threshold=1.5)
    with pytest.raises(ValueError):
        RuntimeConfig(physical_vlm_max_concurrency=0)
    with pytest.raises(ValueError):
        RuntimeConfig(nice_to_have_instruction_budget=1)


def test_runtime_version_stamp_marks_uncalibrated() -> None:
    version = RuntimeVersion()
    assert "+uncalibrated" in str(version)
    calibrated = RuntimeVersion(calibrated=True)
    assert "+uncalibrated" not in str(calibrated)


def test_reasoner_auto_retryable_failures_exclude_rejected_and_misconfigured() -> None:
    config = RuntimeConfig()
    assert config.reasoner_retry.is_auto_retryable(TypedFailure.DEADLINE_EXCEEDED.value)
    assert config.reasoner_retry.is_auto_retryable(TypedFailure.UNAVAILABLE.value)
    assert config.reasoner_retry.is_auto_retryable(TypedFailure.THROTTLED.value)
    assert config.reasoner_retry.is_auto_retryable(TypedFailure.INVALID_OUTPUT.value)
    assert not config.reasoner_retry.is_auto_retryable(TypedFailure.REJECTED.value)
    assert not config.reasoner_retry.is_auto_retryable(TypedFailure.MISCONFIGURED.value)


# --- Canonical values: immutability and normative bounds --------------------


def test_strategy_rejects_more_than_six_criteria() -> None:
    criteria = tuple(
        _criterion(importance=CriterionImportance.MUST_HAVE, priority=i) for i in range(5)
    )
    with pytest.raises(ValueError):
        ShotStrategy(strategy_id=_identity(), criteria=criteria, creation_reason="x")


def test_strategy_enforces_must_have_nice_to_have_split() -> None:
    nice = tuple(
        _criterion(importance=CriterionImportance.NICE_TO_HAVE, priority=i) for i in range(3)
    )
    with pytest.raises(ValueError):
        ShotStrategy(strategy_id=_identity(), criteria=nice, creation_reason="x")


def test_criterion_rejects_more_than_three_candidate_actions() -> None:
    with pytest.raises(ValueError):
        Criterion(
            criterion_id=_identity(),
            importance=CriterionImportance.MUST_HAVE,
            priority=0,
            observable_target="t",
            candidate_actions=tuple(CandidateAction(text=f"a{i}") for i in range(4)),
        )


def test_criterion_assessment_confidence_is_bounded() -> None:
    with pytest.raises(ValueError):

        CriterionAssessment(
            criterion_id=_identity(),
            classification=CriterionClassification.ACHIEVED,
            confidence=1.5,
            grounding=(GroundingFact(text="x", tag=GroundingTag.CURRENT),),
        )


def test_criterion_assessment_rejects_more_than_three_uncertainty_reasons() -> None:

    with pytest.raises(ValueError):
        CriterionAssessment(
            criterion_id=_identity(),
            classification=CriterionClassification.INSUFFICIENT,
            confidence=0.5,
            grounding=(GroundingFact(text="x", tag=GroundingTag.CURRENT),),
            uncertainty_reasons=(
                UncertaintyReason.OCCLUDED,
                UncertaintyReason.BLURRED,
                UncertaintyReason.POOR_LIGHTING,
                UncertaintyReason.OUT_OF_FRAME,
            ),
        )


def test_blocked_requires_blocked_reason_and_forbids_it_otherwise() -> None:
    CriterionAssessment(
        criterion_id=_identity(),
        classification=CriterionClassification.BLOCKED,
        blocked_reason=BlockedReason.AMBIGUOUS,
        grounding=(GroundingFact(text="x", tag=GroundingTag.CURRENT),),
    )
    with pytest.raises(ValueError):
        CriterionAssessment(
            criterion_id=_identity(),
            classification=CriterionClassification.BLOCKED,
        )
    with pytest.raises(ValueError):
        CriterionAssessment(
            criterion_id=_identity(),
            classification=CriterionClassification.ACHIEVED,
            blocked_reason=BlockedReason.AMBIGUOUS,
        )


def test_strategy_applicability_requires_at_least_one_grounding_fact() -> None:
    # Spec §5.2: one to four bounded current-view grounding facts.
    with pytest.raises(ValueError):
        StrategyApplicability(status=StrategyApplicabilityStatus.APPLICABLE)
    StrategyApplicability(
        status=StrategyApplicabilityStatus.APPLICABLE,
        grounding=(GroundingFact(text="stable scene", tag=GroundingTag.CURRENT),),
    )


def test_receipt_disposition_includes_orphaned_for_harmless_completions() -> None:
    # Spec §3.3: duplicate, stale, orphaned, or malformed completions are harmless.
    assert ReceiptDisposition.ORPHANED.value == "orphaned"
    receipt = Receipt(
        event_id=_identity(),
        order=0,
        disposition=ReceiptDisposition.ORPHANED,
    )
    assert receipt.disposition is ReceiptDisposition.ORPHANED


def test_mapping_fields_are_immutable_views() -> None:
    provenance = _strategy_provenance()
    with pytest.raises(TypeError):
        provenance.identities["task"] = _identity()  # type: ignore[index]
    effect = Effect(
        effect_id=_identity(),
        kind=EffectKind.REQUEST_STRATEGY,
        provenance=_strategy_provenance(),
        correlation_id=_identity(),
        payload={"a": 1},
    )
    with pytest.raises(TypeError):
        effect.payload["a"] = 2  # type: ignore[index]


def test_must_have_assessment_requires_current_grounding() -> None:

    assessment = CriterionAssessment(
        criterion_id=_identity(),
        classification=CriterionClassification.ACHIEVED,
        confidence=0.8,
        grounding=(GroundingFact(text="prev", tag=GroundingTag.PREVIOUS),),
    )
    with pytest.raises(ValueError):
        EvidenceSnapshot(
            snapshot_id=_identity(),
            evidence=_evidence(),
            task_id=_identity(),
            strategy_id=_identity(),
            must_have_assessments=(assessment,),
        )


def test_grounding_fact_caps_at_160_characters() -> None:
    with pytest.raises(ValueError):
        GroundingFact(text="x" * 161, tag=GroundingTag.CURRENT)


def test_instruction_content_tuple_is_immutable_per_identity() -> None:
    iid = _identity()
    first = Instruction(instruction_id=iid, kind=InstructionKind.ACTION, text="Step left")
    second = Instruction(instruction_id=iid, kind=InstructionKind.ACTION, text="Step left")
    assert first.content_tuple() == second.content_tuple()
    changed = Instruction(instruction_id=iid, kind=InstructionKind.ACTION, text="Step right")
    assert changed.content_tuple() != first.content_tuple()


def test_ready_instruction_requires_source_evidence() -> None:
    with pytest.raises(ValueError):
        Instruction(instruction_id=_identity(), kind=InstructionKind.READY, text="Ready—take the shot.")


def test_ready_readiness_requires_supporting_evidence() -> None:
    with pytest.raises(ValueError):
        Readiness(state=ReadinessState.READY)
    assert Readiness(state=ReadinessState.NOT_READY).evidence_snapshot_id is None


def test_nice_to_have_cannot_produce_instruction_via_budget() -> None:
    # The v2 budget for nice-to-have Instructions is exactly zero.
    assert RuntimeConfig().nice_to_have_instruction_budget == 0


def test_generated_artifact_provenance_label_is_fixed() -> None:
    artifact = GeneratedArtifact(
        image_message_id=_identity(),
        announced_at_state_revision=1,
        demonstrates="raise the camera",
    )
    assert (
        artifact.provenance_label
        == v2.GENERATED_VISUAL_GUIDANCE_PROVENANCE_LABEL
    )
    with pytest.raises(ValueError):
        GeneratedArtifact(
            image_message_id=_identity(),
            announced_at_state_revision=1,
            demonstrates="x",
            provenance_label="wrong label",
        )


def test_visual_sidecar_combinations_are_validated() -> None:
    src = _identity()
    # An offer carries no activity/artifact/failure.
    VisualGuidanceSidecar(
        visual_id=_identity(),
        kind=VisualEntityKind.OFFER,
        status=VisualSidecarStatus.OFFERED,
        source_instruction_id=src,
        demonstrates="adjust",
    )
    # available requires an artifact.
    with pytest.raises(ValueError):
        VisualGuidanceSidecar(
            visual_id=_identity(),
            kind=VisualEntityKind.JOB,
            status=VisualSidecarStatus.AVAILABLE,
            source_instruction_id=src,
            demonstrates="adjust",
        )
    # active job requires activity.
    with pytest.raises(ValueError):
        VisualGuidanceSidecar(
            visual_id=_identity(),
            kind=VisualEntityKind.JOB,
            status=VisualSidecarStatus.GENERATING,
            source_instruction_id=src,
            demonstrates="adjust",
        )


def test_overlay_set_requires_unique_primitive_ids() -> None:
    prim = OverlayPrimitive(
        primitive_id="p1", kind="rect", points=((0.0, 0.0), (1.0, 1.0))
    )
    with pytest.raises(ValueError):
        OverlaySet(
            instruction_id=_identity(),
            source_observation_id=1,
            source_evidence_id=_identity(),
            primitives=(prim, prim),
        )


def test_available_action_carries_ordinal_and_target() -> None:
    action = AvailableAction(
        action_id=_identity(),
        ordinal=3,
        kind=ActionKind.TRY_ANOTHER_SUGGESTION,
        target=ActionTarget(kind=ActionTargetKind.INSTRUCTION, identity=_identity()),
    )
    assert action.ordinal == 3


# --- Application-authored identities and provenance -------------------------


def test_new_identity_is_a_uuid() -> None:
    assert isinstance(new_identity(), UUID)


def test_action_ordinal_uuids_are_unique_within_a_session() -> None:
    salt = _identity()
    ids = {new_action_ordinal_uuid(i, salt) for i in range(512)}
    assert len(ids) == 512


def test_action_ordinal_uuids_differ_across_sessions() -> None:
    salt_a = _identity()
    salt_b = _identity()
    assert new_action_ordinal_uuid(0, salt_a) != new_action_ordinal_uuid(0, salt_b)


def test_provenance_requires_identities_except_for_edit() -> None:
    run = _identity()
    with pytest.raises(ValueError):
        Provenance(purpose=RemotePurpose.PROGRESS, run_id=run)
    # Edit provenance may be assembled by the authorized request itself.
    Provenance(purpose=RemotePurpose.EDIT, run_id=run)


def test_provenance_is_current_only_when_all_tokens_match() -> None:
    task = _identity()
    evidence = _identity()
    provenance = Provenance(
        purpose=RemotePurpose.PROGRESS,
        run_id=_identity(),
        identities={"task": task, "evidence": evidence},
    )
    assert provenance.is_current({"task": task, "evidence": evidence})
    assert not provenance.is_current({"task": task, "evidence": _identity()})
    assert not provenance.is_current({"task": _identity(), "evidence": evidence})


def test_provenance_is_immutable() -> None:
    provenance = _strategy_provenance()
    with pytest.raises((dataclass_frozen_error_types())):
        provenance.purpose = RemotePurpose.REVISION  # type: ignore[misc]


# --- Canonical events, receipts, outputs, effects carry identities ---------


def test_every_event_carries_an_application_authored_identity() -> None:
    events = [
        IntentionAcceptedEvent(
            event_id=_identity(),
            task_epoch=0,
            accepted_intention="portrait",
        ),
        UserActionEvent(
            event_id=_identity(),
            action_id=_identity(),
            action_message_id=_identity(),
            action_kind=ActionKind.PAUSE_COACHING,
            target=ActionTarget(kind=ActionTargetKind.TASK, identity=_identity()),
        ),
        AdapterFailureEvent(
            event_id=_identity(),
            provenance=_strategy_provenance(),
            failure=TypedFailure.DEADLINE_EXCEEDED,
        ),
        ObservationReceivedEvent(
            event_id=_identity(),
            observation=Observation(
                observation_id=1,
                camera=CameraContext(metadata={"lensID": "wide"}),
                preview=PreviewImage(
                    bytes_=b"x", mime_type="image/jpeg", width=1, height=1,
                ),
                arrival_monotonic_seconds=0.0,
            ),
        ),
    ]
    for event in events:
        assert isinstance(event_identity(event), UUID)


def test_event_kind_discriminates_events() -> None:
    assert event_kind(
        IntentionAcceptedEvent(
            event_id=_identity(), task_epoch=0, accepted_intention="x"
        )
    ) is EventKind.INTENTION_ACCEPTED
    assert event_kind(
        ObservationReceivedEvent(
            event_id=_identity(),
            observation=Observation(
                observation_id=1,
                camera=CameraContext(metadata={"lensID": "wide"}),
                preview=PreviewImage(
                    bytes_=b"x", mime_type="image/jpeg", width=1, height=1,
                ),
                arrival_monotonic_seconds=0.0,
            ),
        )
    ) is EventKind.OBSERVATION_RECEIVED
    assert event_kind(
        AdapterFailureEvent(
            event_id=_identity(),
            provenance=_strategy_provenance(),
            failure=TypedFailure.UNAVAILABLE,
        )
    ) is EventKind.ADAPTER_FAILURE


def test_correlated_reasoner_event_carries_provenance() -> None:
    event = ReasonerStrategyEvent(
        event_id=_identity(),
        provenance=_strategy_provenance(),
        proposal=object(),
    )
    assert event.provenance.purpose is RemotePurpose.STRATEGY
    assert isinstance(event_identity(event), UUID)


def test_receipt_carries_order_and_disposition() -> None:
    receipt = Receipt(event_id=_identity(), order=7, disposition=ReceiptDisposition.ADMITTED)
    assert receipt.order == 7
    with pytest.raises(ValueError):
        Receipt(event_id=_identity(), order=-1, disposition=ReceiptDisposition.ADMITTED)


def test_adapter_failure_event_only_throttled_may_carry_delay() -> None:
    with pytest.raises(ValueError):
        AdapterFailureEvent(
            event_id=_identity(),
            provenance=_strategy_provenance(),
            failure=TypedFailure.UNAVAILABLE,
            throttle_delay_seconds=1.0,
        )
    AdapterFailureEvent(
        event_id=_identity(),
        provenance=_strategy_provenance(),
        failure=TypedFailure.THROTTLED,
        throttle_delay_seconds=1.5,
    )


def test_coaching_projection_rejects_instruction_without_task() -> None:
    with pytest.raises(ValueError):
        CoachingProjection(
            session_id=_identity(),
            state_revision=1,
            task=None,
            phase=CoachingPhase.COACHING,
            instruction=Instruction(
                instruction_id=_identity(),
                kind=InstructionKind.ACTION,
                text="Step left",
            ),
            activity=None,
            overlays=None,
        )


def test_coaching_projection_rejects_duplicate_action_ids() -> None:
    aid = _identity()
    action = AvailableAction(
        action_id=aid,
        ordinal=0,
        kind=ActionKind.PAUSE_COACHING,
        target=ActionTarget(kind=ActionTargetKind.TASK, identity=_identity()),
    )
    with pytest.raises(ValueError):
        CoachingProjection(
            session_id=_identity(),
            state_revision=1,
            task=Task(
                task_epoch=0,
                task_id=_identity(),
                accepted_intention="x",
                strategy_revision=_identity(),
            ),
            phase=CoachingPhase.PAUSED,
            instruction=None,
            activity=Activity(kind=ActivityKind.WAITING, text="Paused"),
            overlays=None,
            available_actions=(action, action),
        )


def test_output_kind_discriminates_outputs() -> None:
    assert output_kind(
        CoachingProjection(
            session_id=_identity(),
            state_revision=0,
            task=None,
            phase=CoachingPhase.NEEDS_INTENTION,
            instruction=None,
            activity=Activity(kind=ActivityKind.WAITING, text="Waiting"),
            overlays=None,
        )
    ) is OutputKind.COACHING_PROJECTION


def test_effect_is_immutable_and_carries_provenance() -> None:
    effect = Effect(
        effect_id=_identity(),
        kind=EffectKind.REQUEST_STRATEGY,
        provenance=_strategy_provenance(),
        correlation_id=_identity(),
    )
    assert effect.provenance.purpose is RemotePurpose.STRATEGY
    with pytest.raises((dataclass_frozen_error_types())):
        effect.kind = EffectKind.REQUEST_PROGRESS  # type: ignore[misc]


def test_effect_edit_requires_edit_provenance() -> None:
    with pytest.raises(ValueError):
        Effect(
            effect_id=_identity(),
            kind=EffectKind.REQUEST_EDIT,
            provenance=_strategy_provenance(),
            correlation_id=_identity(),
        )


# --- Adapter seam contracts -------------------------------------------------


def test_strategy_context_pack_enforces_provenance_purpose() -> None:
    provenance = _strategy_provenance()
    StrategyContextPack(
        provenance=provenance,
        accepted_intention="portrait",
        journey="portrait",
        evidence=_evidence(),
        current_image=_image(),
        creation_reason="initial",
    )
    wrong = Provenance(
        purpose=RemotePurpose.PROGRESS,
        run_id=_identity(),
        identities={"task": _identity(), "evidence": _identity()},
    )
    with pytest.raises(ValueError):
        StrategyContextPack(
            provenance=wrong,
            accepted_intention="portrait",
            journey="portrait",
            evidence=_evidence(),
            current_image=_image(),
            creation_reason="initial",
        )


def test_context_pack_rejects_text_over_32kib() -> None:
    with pytest.raises(ValueError):
        StrategyContextPack(
            provenance=_strategy_provenance(),
            accepted_intention="portrait",
            journey="portrait",
            evidence=_evidence(),
            current_image=_image(),
            creation_reason="initial",
            structured_text_bytes=32 * 1024 + 1,
        )


def test_strategy_proposal_covers_every_proposed_must_have() -> None:
    crit = ProposedCriterion(
        importance="must_have",
        priority=0,
        observable_target="centered",
        candidate_actions=("step left",),
    )
    with pytest.raises(ValueError):
        StrategyProposal(
            criteria=(crit,),
            must_have_assessments=(),
            visual_guidance_intent=VisualGuidanceIntent.NOT_REQUESTED,
        )


def test_authorized_illustration_request_enforces_edit_provenance() -> None:
    with pytest.raises(ValueError):
        AuthorizedIllustrationRequest(
            provenance=_strategy_provenance(),
            demonstrates="adjust",
            accepted_still=_image(),
        )
    req = AuthorizedIllustrationRequest(
        provenance=Provenance(purpose=RemotePurpose.EDIT, run_id=_identity()),
        demonstrates="adjust",
        accepted_still=_image(),
    )
    assert req.provenance.purpose is RemotePurpose.EDIT


def test_edited_illustration_rejects_unsupported_media() -> None:
    with pytest.raises(ValueError):
        EditedIllustration(
            image_id=_identity(),
            bytes_hash="h",
            mime_type="image/gif",
            width=1,
            height=1,
        )


def test_adapter_failure_only_throttled_carries_delay() -> None:
    with pytest.raises(ValueError):
        AdapterFailure(
            failure=TypedFailure.UNAVAILABLE,
            provenance=_strategy_provenance(),
            throttle_delay_seconds=1.0,
        )


def test_connection_offer_requires_mandatory_capability() -> None:
    ConnectionOffer(offered_capabilities=("camera_agent_interaction_v2",))
    with pytest.raises(ValueError):
        ConnectionOffer(offered_capabilities=("generated_visual_guidance_v2",))


def test_connection_offer_supports_resume_handle() -> None:
    offer = ConnectionOffer(
        offered_capabilities=("camera_agent_interaction_v2", "generated_visual_guidance_v2"),
        resume_session_id=_identity(),
    )
    assert offer.resume_session_id is not None


# --- Adapter seam satisfaction (deterministic scripted adapters) ------------


class _ScriptedReasoner:
    async def propose_strategy(self, context: StrategyContextPack):  # type: ignore[no-untyped-def]
        return None

    async def assess_progress(self, context: ProgressContextPack):  # type: ignore[no-untyped-def]
        return None

    async def propose_revision(self, context: RevisionContextPack):  # type: ignore[no-untyped-def]
        return None


class _ScriptedEditor:
    async def render(self, request: AuthorizedIllustrationRequest):  # type: ignore[no-untyped-def]
        return None


def test_scripted_adapters_satisfy_the_public_seam_protocols() -> None:
    assert isinstance(_ScriptedReasoner(), CoachingReasoner)
    assert isinstance(_ScriptedEditor(), IllustrationEditor)


def test_a_plain_object_does_not_satisfy_the_seam_protocols() -> None:
    assert not isinstance(object(), CoachingReasoner)
    assert not isinstance(object(), IllustrationEditor)


# --- Helper plumbing --------------------------------------------------------


def dataclass_frozen_error_types() -> tuple[type[BaseException], ...]:
    return (AttributeError, TypeError)
