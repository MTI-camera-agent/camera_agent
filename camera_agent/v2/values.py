"""Canonical v2 runtime values with normative bounds.

Immutable value objects for Task, Strategy, Criterion, Evidence, Evidence Snapshot,
Instruction, Readiness, Activity, overlays, one-use actions, recovery, the Visual
Guidance Sidecar, and typed revisions. Each carries stable application-authored
identities and obeys the normative size and freshness bounds from
``docs/CAMERA_AGENT_V2_SPEC.md``.

These are pure value contracts. The runtime reducer, scheduler, memory, and
visual-job policy live behind the ``CoachingRuntime`` Interface and are not public
seams here. Provider/model output never authors or alters these identities.

This module is dormant v2 contract code and is not on the production composition
root.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping
from uuid import UUID

from .identity import new_identity


# --- Coaching projection enums -----------------------------------------------


class CoachingPhase(StrEnum):
    """Derived coaching phase (first matching rule wins)."""

    NEEDS_INTENTION = "needs_intention"
    ORIENTING = "orienting"
    COACHING = "coaching"
    EVALUATING = "evaluating"
    READY = "ready"
    RECOVERING = "recovering"
    PAUSED = "paused"


class ActivityKind(StrEnum):
    """Transient coaching or visual Activity kind."""

    WORKING = "working"
    WAITING = "waiting"
    RECOVERING = "recovering"


class Mode(StrEnum):
    """Runtime mode."""

    ACTIVE = "active"
    PAUSED = "paused"


class ConnectionState(StrEnum):
    """Connection authority state."""

    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    CONNECTED_NEEDS_FRESH_EVIDENCE = "connected_needs_fresh_evidence"


class EvidenceState(StrEnum):
    """Evidence settling state."""

    MISSING = "missing"
    MOVING = "moving"
    SETTLING = "settling"
    SETTLED = "settled"


class InstructionKind(StrEnum):
    """Persistent Instruction kind."""

    ACTION = "action"
    READY = "ready"


class InstructionFreshness(StrEnum):
    """Instruction freshness projection."""

    CURRENT = "current"
    NEEDS_REVALIDATION = "needs_revalidation"
    MAY_BE_OUTDATED = "may_be_outdated"


class InstructionDisposition(StrEnum):
    """Exactly one terminal disposition recorded when an Instruction closes."""

    ACHIEVED = "achieved"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    IRRELEVANT = "irrelevant"
    TASK_ENDED = "task_ended"


class Addressee(StrEnum):
    """Recipient named by an Instruction when responsibility could be ambiguous."""

    PHOTOGRAPHER = "photographer"
    SUBJECT = "subject"


class ReadinessState(StrEnum):
    """Readiness assessment."""

    NOT_READY = "not_ready"
    READY = "ready"
    NEEDS_REVALIDATION = "needs_revalidation"


class AnalysisState(StrEnum):
    """Authoritative reasoning run state."""

    IDLE = "idle"
    REQUESTED = "requested"
    RUNNING = "running"


# --- Strategy and progress enums ---------------------------------------------


class CriterionImportance(StrEnum):
    """Criterion importance. Nice-to-haves never produce a v2 Instruction."""

    MUST_HAVE = "must_have"
    NICE_TO_HAVE = "nice_to_have"


class CriterionClassification(StrEnum):
    """Exactly one classification for every assessed Criterion."""

    ACHIEVED = "achieved"
    IMPROVING = "improving"
    INSUFFICIENT = "insufficient"
    DEVIATING = "deviating"
    BLOCKED = "blocked"


class UncertaintyReason(StrEnum):
    """Bounded typed uncertainty reasons."""

    OCCLUDED = "occluded"
    BLURRED = "blurred"
    POOR_LIGHTING = "poor_lighting"
    OUT_OF_FRAME = "out_of_frame"
    AMBIGUOUS_SUBJECT = "ambiguous_subject"
    INSUFFICIENT_CHANGE = "insufficient_change"
    CONFLICTING_CUES = "conflicting_cues"
    OTHER = "other"


class BlockedReason(StrEnum):
    """Required only when a Criterion classification is ``blocked``."""

    NOT_OBSERVABLE = "not_observable"
    TEMPORARILY_INFEASIBLE = "temporarily_infeasible"
    ACTION_INFEASIBLE = "action_infeasible"
    AMBIGUOUS = "ambiguous"


class StrategyApplicabilityStatus(StrEnum):
    """Whether the current Strategy still applies to the current view."""

    APPLICABLE = "applicable"
    BROAD_DISCONTINUITY = "broad_discontinuity"
    UNKNOWN = "unknown"


class VisualGuidanceIntent(StrEnum):
    """Typed, grounded Strategy output about an edited example."""

    REQUESTED = "requested"
    NOT_REQUESTED = "not_requested"
    UNSUITABLE = "unsuitable"


class RevisionScope(StrEnum):
    """The three Strategy revision scopes."""

    INSTRUCTION_REFINEMENT = "instruction_refinement"
    LOCAL_STRATEGY_PATCH = "local_strategy_patch"
    FULL_STRATEGY_REBUILD = "full_strategy_rebuild"


class GroundingTag(StrEnum):
    """Tag for a grounding observable-fact record."""

    CURRENT = "current"
    PREVIOUS = "previous"


# --- Recovery, action, and visual enums --------------------------------------


class RecoveryScope(StrEnum):
    """Independently scoped recovery lanes."""

    COACHING = "coaching"
    CONNECTION = "connection"
    CAPTURE = "capture"
    REASONER = "reasoner"
    EDITOR = "editor"


class ActionTargetKind(StrEnum):
    """Typed target of a one-use protocol action."""

    INSTRUCTION = "instruction"
    TASK = "task"
    VISUAL_OFFER = "visual_offer"
    VISUAL_JOB = "visual_job"


class ActionKind(StrEnum):
    """Server-minted one-use action kinds."""

    TRY_ANOTHER_SUGGESTION = "try_another_suggestion"
    PAUSE_COACHING = "pause_coaching"
    RESUME_COACHING = "resume_coaching"
    GENERATE_VISUAL_GUIDANCE = "generate_visual_guidance"
    DECLINE_VISUAL_GUIDANCE = "decline_visual_guidance"
    CANCEL_VISUAL_GUIDANCE = "cancel_visual_guidance"
    RETRY_VISUAL_GUIDANCE = "retry_visual_guidance"
    DISMISS_VISUAL_GUIDANCE = "dismiss_visual_guidance"
    ANOTHER_VISUAL_EXAMPLE = "another_visual_example"


class ActionDisposition(StrEnum):
    """One-use action acknowledgement disposition."""

    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    STALE = "stale"
    UNAVAILABLE = "unavailable"


class VisualEntityKind(StrEnum):
    """Visual Guidance Sidecar entity kind."""

    OFFER = "offer"
    JOB = "job"


class VisualSidecarStatus(StrEnum):
    """Visual Guidance Sidecar status."""

    IDLE = "idle"
    OFFERED = "offered"
    WAITING_FOR_SETTLE = "waiting_for_settle"
    CAPTURING = "capturing"
    GENERATING = "generating"
    AVAILABLE = "available"
    FAILED = "failed"


class TypedFailure(StrEnum):
    """Typed dependency outcome returned by both Adapter seams."""

    DEADLINE_EXCEEDED = "deadline_exceeded"
    UNAVAILABLE = "unavailable"
    THROTTLED = "throttled"
    REJECTED = "rejected"
    INVALID_OUTPUT = "invalid_output"
    MISCONFIGURED = "misconfigured"


def validate_throttle_delay(failure: TypedFailure, throttle_delay_seconds: float | None) -> None:
    """Shared bound check: only ``throttled`` may carry a provider delay.

    ``throttled`` MAY include a provider delay; all other typed failures carry
    ``None``. Provider exceptions, HTTP codes, raw error text, SDK types, model
    names, prompts, and provider schemas remain inside Adapters.
    """

    if failure is TypedFailure.THROTTLED:
        if throttle_delay_seconds is not None and throttle_delay_seconds < 0:
            raise ValueError("throttle delay must not be negative")
    elif throttle_delay_seconds is not None:
        raise ValueError("only throttled may carry a provider delay")


# Canonical fixed provenance label for a Generated Visual Guidance artifact.
GENERATED_VISUAL_GUIDANCE_PROVENANCE_LABEL = (
    "Edited illustration based on an earlier still — not the live preview."
)


# --- Canonical value objects -------------------------------------------------


@dataclass(frozen=True, slots=True)
class Activity:
    """Transient coaching or visual Activity.

    Reports what is happening or what the user can do; it MUST NOT expose model or
    provider names, queues, hidden reasoning, or invented confidence percentages.
    Activity never silently mutates the persistent Instruction.
    """

    kind: ActivityKind
    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("activity text must be nonempty")


@dataclass(frozen=True, slots=True)
class Task:
    """The accepted intention and its current strategy revision.

    ``task_epoch`` orders the task against other tasks for the same session;
    ``task_id`` is its stable application-authored identity. A new or changed
    accepted intention replaces the prior task immediately.
    """

    task_epoch: int
    task_id: UUID
    accepted_intention: str
    strategy_revision: UUID

    def __post_init__(self) -> None:
        if self.task_epoch < 0:
            raise ValueError("task epoch must not be negative")
        if not self.accepted_intention.strip():
            raise ValueError("accepted intention must be nonempty")


@dataclass(frozen=True, slots=True)
class CandidateAction:
    """One feasible incremental action for a Criterion."""

    text: str
    responsible_actor: Addressee | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("candidate action text must be nonempty")


@dataclass(frozen=True, slots=True)
class Criterion:
    """One observable condition in a Shot Strategy.

    A Criterion has a stable application-authored identity, an observable target,
    ``must_have | nice_to_have`` importance, a priority, and at most three
    candidate actions. Nice-to-haves are diagnostic context only: they MUST NOT
    produce a v2 Instruction, delay Ready, or replace Ready.
    """

    criterion_id: UUID
    importance: CriterionImportance
    priority: int
    observable_target: str
    candidate_actions: tuple[CandidateAction, ...] = ()
    responsible_actor: Addressee | None = None
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.observable_target.strip():
            raise ValueError("criterion observable target must be nonempty")
        if len(self.candidate_actions) > 3:
            raise ValueError("a criterion has at most three candidate actions")
        if self.priority < 0:
            raise ValueError("criterion priority must not be negative")
        for action in self.candidate_actions:
            if not isinstance(action, CandidateAction):
                raise TypeError("candidate_actions must be CandidateAction values")


@dataclass(frozen=True, slots=True)
class ShotStrategy:
    """A priority-ordered set of at most six observable Criteria.

    At most four must-haves and two nice-to-haves. The strategy and every Criterion
    have stable application-authored identities. ``strategy_id`` identifies this
    revision; a rebuild allocates a new identity while preserving surviving
    constraints.
    """

    strategy_id: UUID
    criteria: tuple[Criterion, ...]
    creation_reason: str
    surviving_constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("a strategy must contain at least one criterion")
        if len(self.criteria) > 6:
            raise ValueError("a strategy has at most six criteria")
        must_haves = [c for c in self.criteria if c.importance is CriterionImportance.MUST_HAVE]
        nice_to_haves = [
            c for c in self.criteria if c.importance is CriterionImportance.NICE_TO_HAVE
        ]
        if len(must_haves) > 4:
            raise ValueError("a strategy has at most four must-have criteria")
        if len(nice_to_haves) > 2:
            raise ValueError("a strategy has at most two nice-to-have criteria")
        if not must_haves:
            raise ValueError("a strategy must contain at least one must-have")
        ids = [c.criterion_id for c in self.criteria]
        if len(set(ids)) != len(ids):
            raise ValueError("criterion identities must be unique within a strategy")
        priorities = [c.priority for c in self.criteria]
        if len(set(priorities)) != len(priorities):
            raise ValueError("criterion priorities must be unique within a strategy")
        if not self.creation_reason.strip():
            raise ValueError("strategy creation reason must be nonempty")


@dataclass(frozen=True, slots=True)
class GroundingFact:
    """One bounded observable-fact grounding record.

    At most 160 characters, tagged ``current`` or ``previous``. Chain-of-thought
    and hidden reasoning are prohibited.
    """

    text: str
    tag: GroundingTag

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("grounding fact text must be nonempty")
        if len(self.text) > 160:
            raise ValueError("grounding fact must be at most 160 characters")


@dataclass(frozen=True, slots=True)
class CriterionAssessment:
    """One Criterion assessment against one current compatible Evidence view.

    ``confidence`` is a finite number in ``[0, 1]`` or ``null`` when unknown;
    ``null`` confidence cannot support Ready. ``uncertainty_reasons`` holds zero to
    three typed values. ``blocked_reason`` is required only for ``blocked``.
    Every must-have assessment MUST contain at least one ``current`` grounding fact.
    """

    criterion_id: UUID
    classification: CriterionClassification
    confidence: float | None = None
    grounding: tuple[GroundingFact, ...] = ()
    uncertainty_reasons: tuple[UncertaintyReason, ...] = ()
    blocked_reason: BlockedReason | None = None

    def __post_init__(self) -> None:
        if len(self.grounding) > 4:
            raise ValueError("an assessment has at most four grounding facts")
        if len(self.uncertainty_reasons) > 3:
            raise ValueError("an assessment has at most three uncertainty reasons")
        if len(set(self.uncertainty_reasons)) != len(self.uncertainty_reasons):
            raise ValueError("uncertainty reasons must be unique")
        if self.classification is CriterionClassification.BLOCKED:
            if self.blocked_reason is None:
                raise ValueError("blocked requires a blocked_reason")
        elif self.blocked_reason is not None:
            raise ValueError("blocked_reason is only permitted for blocked")
        if self.confidence is not None:
            if not (0.0 <= self.confidence <= 1.0):
                raise ValueError("confidence must be a finite number in [0, 1]")
            if self.confidence != self.confidence:  # NaN guard
                raise ValueError("confidence must be finite")

    def has_current_grounding(self) -> bool:
        return any(f.tag is GroundingTag.CURRENT for f in self.grounding)


@dataclass(frozen=True, slots=True)
class StrategyApplicability:
    """Whether the current Strategy still applies to the current view.

    ``status: applicable | broad_discontinuity | unknown``. Only an admitted
    high-confidence ``broad_discontinuity`` may request a full rebuild; ``unknown``
    requests clearer fresh Evidence and scoped recovery and does not rebuild.
    Deterministic frame signals may request this semantic check but cannot author
    its result.
    """

    status: StrategyApplicabilityStatus
    confidence: float | None = None
    grounding: tuple[GroundingFact, ...] = ()

    def __post_init__(self) -> None:
        if not self.grounding:
            raise ValueError("applicability requires one to four grounding facts")
        if len(self.grounding) > 4:
            raise ValueError("applicability has at most four grounding facts")
        if self.confidence is not None and not (0.0 <= self.confidence <= 1.0):
            raise ValueError("applicability confidence must be in [0, 1]")


@dataclass(frozen=True, slots=True)
class EvidenceIdentity:
    """Identity bundle for one accepted settled Evidence view.

    Settled state identifies evidence, camera context, source observation, and
    exact source bytes. Observation identity remains the v1 positive process-local
    ``observationId``.
    """

    evidence_id: UUID
    camera_context_id: UUID
    observation_id: int
    source_bytes_hash: str

    def __post_init__(self) -> None:
        if self.observation_id < 0:
            raise ValueError("observation id must be a non-negative v1 local value")
        if not self.source_bytes_hash.strip():
            raise ValueError("source bytes hash must be nonempty")


@dataclass(frozen=True, slots=True)
class EvidenceSnapshot:
    """A strategy-indexed Evidence Snapshot for one accepted settled view.

    Contains one grounded assessment for every must-have against the same view,
    relevant nice-to-have assessments, task-relevant observable facts and cheap
    deterministic signals, the observed response to the active Instruction, and
    bounded confidence, uncertainty, and blocked-condition records.
    """

    snapshot_id: UUID
    evidence: EvidenceIdentity
    task_id: UUID
    strategy_id: UUID
    must_have_assessments: tuple[CriterionAssessment, ...]
    nice_to_have_assessments: tuple[CriterionAssessment, ...] = ()
    applicability: StrategyApplicability | None = None
    deterministic_signals: Mapping[str, Any] = field(default_factory=dict)
    observed_instruction_response: str | None = None

    def __post_init__(self) -> None:
        if not self.must_have_assessments:
            raise ValueError("a snapshot must assess every must-have")
        for assessment in self.must_have_assessments:
            if not assessment.has_current_grounding():
                raise ValueError(
                    "every must-have assessment must contain at least one "
                    "current grounding fact"
                )
        ids = [a.criterion_id for a in self.must_have_assessments]
        if len(set(ids)) != len(ids):
            raise ValueError("must-have criterion references must be unique")
        object.__setattr__(self, "deterministic_signals", MappingProxyType(dict(self.deterministic_signals)))


@dataclass(frozen=True, slots=True)
class Instruction:
    """The single persistent primary actionable direction.

    ``kind``, ``text``, and ``addressee`` are immutable for one ``instruction_id``;
    changing any of them creates a new identity. ``freshness`` may change without
    replacing the Instruction. ``kind=ready`` is permitted only for evidence-backed
    Readiness. ``Ready—take the shot.`` is an Instruction with ``kind=ready`` and a
    separate Readiness record.
    """

    instruction_id: UUID
    kind: InstructionKind
    text: str
    addressee: Addressee | None = None
    freshness: InstructionFreshness = InstructionFreshness.CURRENT
    source_evidence_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("instruction text must be nonempty")
        if self.kind is InstructionKind.READY and self.source_evidence_id is None:
            raise ValueError("a ready Instruction must cite its source Evidence")

    def content_tuple(self) -> tuple[InstructionKind, str, Addressee | None]:
        """The immutable content tuple keyed by identity.

        Two Instructions with the same ``instruction_id`` MUST share this tuple;
        any change requires a new identity.
        """

        return (self.kind, self.text, self.addressee)


@dataclass(frozen=True, slots=True)
class Readiness:
    """An evidence-backed satisficing Readiness assessment.

    Ready is derived only when every must-have is ``achieved`` with non-null
    confidence at or above the configured threshold in one current compatible
    Evidence Snapshot. Motion and user capture mark its support as needing
    revalidation but do not revoke or flicker Ready.
    """

    state: ReadinessState
    evidence_snapshot_id: UUID | None = None
    supporting_evidence_id: UUID | None = None

    def __post_init__(self) -> None:
        if self.state is ReadinessState.READY:
            if self.evidence_snapshot_id is None or self.supporting_evidence_id is None:
                raise ValueError(
                    "ready requires a supporting Evidence Snapshot and Evidence"
                )
        elif self.evidence_snapshot_id is not None:
            raise ValueError(
                "non-ready Readiness must not carry a supporting snapshot"
            )


@dataclass(frozen=True, slots=True)
class OverlayPrimitive:
    """One v1-compatible overlay primitive bound to one Instruction and Evidence."""

    primitive_id: str
    kind: str
    points: tuple[tuple[float, float], ...]
    text: str | None = None
    color: str | None = None
    line_width: float | None = None
    expires_ms: int = 1800

    def __post_init__(self) -> None:
        if not self.primitive_id.strip():
            raise ValueError("overlay primitive id must be nonempty")
        if not self.points:
            raise ValueError("an overlay primitive needs at least one point")
        if self.expires_ms <= 0:
            raise ValueError("overlay expiry must be positive")


@dataclass(frozen=True, slots=True)
class OverlaySet:
    """One complete observation-bound overlay set.

    Names the current ``instruction_id``, exact ``source_observation_id``, and one
    or more primitives. Spatial overlays remain bound to the exact analyzed
    observation and must pass protocol freshness checks; they are independently
    suppressible without changing the Instruction.
    """

    instruction_id: UUID
    source_observation_id: int
    source_evidence_id: UUID
    primitives: tuple[OverlayPrimitive, ...]

    def __post_init__(self) -> None:
        if not self.primitives:
            raise ValueError("an overlay set needs at least one primitive")
        ids = [p.primitive_id for p in self.primitives]
        if len(set(ids)) != len(ids):
            raise ValueError("overlay primitive ids must be unique within a set")
        if self.source_observation_id < 0:
            raise ValueError("source observation id must be non-negative")


@dataclass(frozen=True, slots=True)
class ActionTarget:
    """Typed target of a one-use protocol action."""

    kind: ActionTargetKind
    identity: UUID

    def __post_init__(self) -> None:
        # ``task`` targets use the task id; ``instruction``/``visual_offer``/
        # ``visual_job`` use the corresponding stable identity. Validated against
        # the current snapshot by the runtime, not here.
        if self.kind not in ActionTargetKind:
            raise ValueError("unknown action target kind")


@dataclass(frozen=True, slots=True)
class AvailableAction:
    """A server-minted one-use action opportunity.

    ``action_id`` is globally one-use within a session and derived from a
    session-scoped monotonic ordinal so non-reuse does not require unbounded
    history. An ID persists unchanged while available but MUST NOT change meaning,
    reappear after retirement, or reappear after consumption.
    """

    action_id: UUID
    ordinal: int
    kind: ActionKind
    target: ActionTarget

    def __post_init__(self) -> None:
        if self.ordinal < 0:
            raise ValueError("action ordinal must not be negative")


@dataclass(frozen=True, slots=True)
class Recovery:
    """An independently scoped recovery record with one concrete next action."""

    scope: RecoveryScope
    activity: Activity
    next_action: str | None = None

    def __post_init__(self) -> None:
        if self.scope is RecoveryScope.COACHING and not self.next_action:
            raise ValueError("coaching recovery needs a concrete next action")


@dataclass(frozen=True, slots=True)
class GeneratedArtifact:
    """A delivered Generated Visual Guidance artifact.

    Only its delivered edited-image artifact is Generated Visual Guidance. It
    carries the exact demonstrated action and the fixed protocol provenance label.
    """

    image_message_id: UUID
    announced_at_state_revision: int
    demonstrates: str
    provenance_label: str = GENERATED_VISUAL_GUIDANCE_PROVENANCE_LABEL

    def __post_init__(self) -> None:
        if not self.demonstrates.strip():
            raise ValueError("artifact demonstrates must be nonempty")
        if self.provenance_label != GENERATED_VISUAL_GUIDANCE_PROVENANCE_LABEL:
            raise ValueError("generated artifact provenance label is fixed")
        if self.announced_at_state_revision < 0:
            raise ValueError("state revision must not be negative")


@dataclass(frozen=True, slots=True)
class VisualGuidanceSidecar:
    """The concurrent Visual Guidance Sidecar.

    ``idle | offered | waiting_for_settle | capturing | generating | available |
    failed``. The sidecar never changes coaching phase. Only its delivered
    edited-image artifact is Generated Visual Guidance.
    """

    visual_id: UUID
    kind: VisualEntityKind
    status: VisualSidecarStatus
    source_instruction_id: UUID
    demonstrates: str
    activity: Activity | None = None
    artifact: GeneratedArtifact | None = None
    failure: str | None = None

    def __post_init__(self) -> None:
        if not self.demonstrates.strip():
            raise ValueError("visual sidecar demonstrates must be nonempty")
        if self.status is VisualSidecarStatus.OFFERED:
            if self.kind is not VisualEntityKind.OFFER:
                raise ValueError("offered status requires an offer entity")
            if self.activity is not None or self.artifact is not None or self.failure is not None:
                raise ValueError("an offer carries no activity, artifact, or failure")
        if self.status is VisualSidecarStatus.AVAILABLE:
            if self.artifact is None or self.activity is not None or self.failure is not None:
                raise ValueError("available requires an artifact and no activity/failure")
        if self.status is VisualSidecarStatus.FAILED:
            if self.failure is None or self.artifact is not None or self.activity is not None:
                raise ValueError("failed requires failure text and no artifact/activity")
        if self.status in {
            VisualSidecarStatus.WAITING_FOR_SETTLE,
            VisualSidecarStatus.CAPTURING,
            VisualSidecarStatus.GENERATING,
        }:
            if self.activity is None or self.artifact is not None:
                raise ValueError("active job status requires activity and no artifact")
            if self.kind is not VisualEntityKind.JOB:
                raise ValueError("active job status requires a job entity")


# --- Observation, camera context, and deterministic frame signals ----------


@dataclass(frozen=True, slots=True)
class CameraContext:
    """Immutable camera-context metadata for one complete observation.

    Carries the exact camera metadata that arrived with a preview. A hard
    camera-context change (lens, orientation, frame dimensions) immediately
    invalidates settled Evidence. Automatic exposure and white-balance shimmer
    is ignored unless a calibrated quality signal shows a meaningful change.
    The metadata mapping is frozen as an immutable view.
    """

    metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not isinstance(self.metadata, Mapping):
            raise TypeError("camera context metadata must be a mapping")
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))

    @property
    def hard_signature(self) -> tuple[Any, ...]:
        """The keys whose change is a hard camera-context change.

        Lens identity, orientation, and frame dimensions changing is a hard
        invalidation: the runtime cannot treat the new view as equivalent to the
        prior settled Evidence.
        """

        m = self.metadata
        return (
            m.get("lensID"),
            m.get("orientation"),
            m.get("frameWidth"),
            m.get("frameHeight"),
        )


@dataclass(frozen=True, slots=True)
class PreviewImage:
    """One immutable preview image carried by a complete observation.

    ``bytes_hash`` is ``sha256:<hex>`` of ``bytes_`` and is the authoritative
    source-byte identity recorded in Evidence and diagnostics. Dimensions are
    positive integers; the mime type is JPEG or PNG.
    """

    bytes_: bytes
    mime_type: str
    width: int
    height: int
    bytes_hash: str = ""

    def __post_init__(self) -> None:
        if not self.bytes_:
            raise ValueError("preview bytes must be nonempty")
        if self.mime_type not in {"image/jpeg", "image/png"}:
            raise ValueError("preview mime type must be JPEG or PNG")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("preview dimensions must be positive")
        expected = "sha256:" + hashlib.sha256(self.bytes_).hexdigest()
        if self.bytes_hash and self.bytes_hash != expected:
            raise ValueError("preview bytes_hash must be sha256 of bytes_")
        if not self.bytes_hash:
            object.__setattr__(self, "bytes_hash", expected)


@dataclass(frozen=True, slots=True)
class Observation:
    """One complete immutable observation context admitted to the mailbox.

    The transport-edge ``ObservationAssembler`` correlates observation metadata
    and preview bytes using both ``imageMessageId`` and ``observationId`` and
    emits exactly one complete context per joined observation. ``observation_id``
    is the v1 positive process-local ``observationId``; ``arrival_monotonic_seconds``
    is the desktop-monotonic arrival time used for Settled dwell.
    """

    observation_id: int
    camera: CameraContext
    preview: PreviewImage
    arrival_monotonic_seconds: float
    reason: str = "stream"

    def __post_init__(self) -> None:
        if self.observation_id < 0:
            raise ValueError("observation id must be a non-negative v1 local value")
        if self.arrival_monotonic_seconds < 0:
            raise ValueError("arrival monotonic seconds must not be negative")
        if not self.reason.strip():
            raise ValueError("observation reason must be nonempty")


@dataclass(frozen=True, slots=True)
class FrameSignals:
    """Cheap deterministic signals assessed for one complete preview.

    Every complete preview is assessed with CPU-cheap deterministic signals
    (spec §4.2): compatible camera-context metadata deltas, existing thumbnail /
    global / local difference and hash-supported change signals, mutual
    equivalence of post-change frames, relative sharpness/blur regression, and
    luminance and highlight/shadow clipping measurements.

    Deterministic signals MAY invalidate Evidence, influence Settled, request
    reasoning, or enter a Context Pack. They MUST NOT establish semantic
    achievement, subject presence, framing correctness, or Readiness. Ready is
    derived only from admitted ``CriterionAssessment`` values; these signals never
    author that result.

    ``decode_available`` is ``False`` when the preview could not be decoded;
    decode failure yields unavailable quality data and conservative fail-open
    change handling (the runtime treats it as a material invalidation).
    ``material_change`` is ``True`` for a hard camera-context change, a material
    preview/metadata delta, or decode-unavailable fail-open — these immediately
    invalidate settled Evidence (spec §4.3 / issue #22 AC1). A relative
    sharpness/luminance/clipping *configured crossing* is reported via
    ``quality_crossing`` and ``sharpness_regression`` and requests revalidation
    only; it MUST NOT itself be a material invalidation or establish semantic
    achievement or Ready (S04 / issue #22 AC4). ``equivalent_to_reference``
    is ``True`` for a routine frame that coalesces without a new Evidence identity
    (a frame may be both equivalent and quality-crossing). The numeric
    measurements are diagnostic and never establish Ready.
    """

    decode_available: bool
    material_change: bool
    equivalent_to_reference: bool
    material_reasons: tuple[str, ...] = ()
    relative_sharpness: float | None = None
    luminance: float | None = None
    highlight_clipping: float | None = None
    shadow_clipping: float | None = None
    sharpness_regression: bool = False
    quality_crossing: bool = False

    def __post_init__(self) -> None:
        if not self.decode_available:
            # Decode failure: quality data is unavailable and the runtime treats
            # the frame as a conservative fail-open change regardless of the
            # caller's ``material_change`` flag.
            object.__setattr__(self, "material_change", True)
            if not self.material_reasons:
                object.__setattr__(self, "material_reasons", ("decode_unavailable",))
        for name, value in {
            "relative_sharpness": self.relative_sharpness,
            "luminance": self.luminance,
            "highlight_clipping": self.highlight_clipping,
            "shadow_clipping": self.shadow_clipping,
        }.items():
            if value is not None:
                if value != value:  # NaN guard
                    raise ValueError(f"{name} must be finite")
                if not (0.0 <= value <= 1.0):
                    raise ValueError(f"{name} must be in [0, 1]")
        if not isinstance(self.material_reasons, tuple):
            raise TypeError("material_reasons must be a tuple")


def new_action_ordinal_uuid(ordinal: int, session_salt: UUID) -> UUID:
    """Derive a stable action UUID from a session-scoped monotonic ordinal.

    Action UUIDs are derived from a session-scoped monotonic ordinal so non-reuse
    does not require unbounded history. The salt binds the derivation to one
    session; the same ordinal in a different session yields a different identity.
    """

    if ordinal < 0:
        raise ValueError("action ordinal must not be negative")
    # Deterministic name-based derivation. The runtime is the sole allocator; this
    # keeps the contract testable without a live UUID source while preserving
    # non-reuse within a session.
    from uuid import uuid5

    return uuid5(session_salt, f"action:{ordinal}")


__all__ = [
    "GENERATED_VISUAL_GUIDANCE_PROVENANCE_LABEL",
    "new_identity",
    "new_action_ordinal_uuid",
    "CoachingPhase",
    "ActivityKind",
    "Mode",
    "ConnectionState",
    "EvidenceState",
    "InstructionKind",
    "InstructionFreshness",
    "InstructionDisposition",
    "Addressee",
    "ReadinessState",
    "AnalysisState",
    "CriterionImportance",
    "CriterionClassification",
    "UncertaintyReason",
    "BlockedReason",
    "StrategyApplicabilityStatus",
    "VisualGuidanceIntent",
    "RevisionScope",
    "GroundingTag",
    "RecoveryScope",
    "ActionTargetKind",
    "ActionKind",
    "ActionDisposition",
    "VisualEntityKind",
    "VisualSidecarStatus",
    "TypedFailure",
    "validate_throttle_delay",
    "Activity",
    "Task",
    "CandidateAction",
    "Criterion",
    "ShotStrategy",
    "GroundingFact",
    "CriterionAssessment",
    "StrategyApplicability",
    "EvidenceIdentity",
    "EvidenceSnapshot",
    "Instruction",
    "Readiness",
    "OverlayPrimitive",
    "OverlaySet",
    "ActionTarget",
    "AvailableAction",
    "Recovery",
    "GeneratedArtifact",
    "VisualGuidanceSidecar",
    # observation & deterministic frame signals
    "CameraContext",
    "PreviewImage",
    "Observation",
    "FrameSignals",
]
