"""Canonical v2 runtime events, receipts, outputs, and correlated effects.

The ``CoachingRuntime`` mailbox admits immutable ``RuntimeEvent`` values through
``submit`` and yields complete immutable ``RuntimeOutput`` values through
``outputs``. Async work never mutates state or writes to a phone directly; every
completion re-enters the same mailbox as a correlated ``RuntimeEvent`` carrying an
out-of-band provenance envelope.

``Effect`` is the declarative correlated-effect type the runtime owns and launches.
Its completions become correlated ``RuntimeEvent`` values through the same
mailbox. It is a canonical contract value (it carries application-authored
identities and provenance) but is **not** a public seam callers or tests drive:
callers observe ``RuntimeOutput`` and the public ``CoachingRuntime`` Interface
only. There is no public reducer lane, scheduler, generic transport port, or
independent visual-workflow authority here.

Every value carries application-authored identities and provenance. Provider/model
output never authors or alters those identities.

This module is dormant v2 contract code and is not on the production composition
root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping, Union
from uuid import UUID

from .identity import Provenance, RemotePurpose
from .values import (
    ActionDisposition,
    ActionKind,
    ActionTarget,
    Activity,
    AvailableAction,
    EvidenceIdentity,
    GeneratedArtifact,
    Instruction,
    OverlaySet,
    Readiness,
    Task,
    TypedFailure,
    VisualGuidanceSidecar,
    validate_throttle_delay,
)


class EventKind(StrEnum):
    """Discriminating kind for canonical ``RuntimeEvent`` values."""

    INTENTION_ACCEPTED = "intention_accepted"
    EVIDENCE_SETTLED = "evidence_settled"
    USER_ACTION = "user_action"
    USER_CAPTURE = "user_capture"
    PAUSE_COACHING = "pause_coaching"
    RESUME_COACHING = "resume_coaching"
    CONNECTION_LOST = "connection_lost"
    CONNECTION_RESUMED = "connection_resumed"
    REASONER_STRATEGY = "reasoner_strategy"
    REASONER_PROGRESS = "reasoner_progress"
    REASONER_REVISION = "reasoner_revision"
    HIGH_RESOLUTION_CAPTURE = "high_resolution_capture"
    EDITOR_RENDER = "editor_render"
    ADAPTER_FAILURE = "adapter_failure"
    TASK_ENDED = "task_ended"


class ReceiptDisposition(StrEnum):
    """Admission disposition for a submitted event.

    Concurrent submissions receive one authoritative mailbox order. ``submit``
    acknowledges admission without waiting for remote work. Duplicate, stale,
    orphaned, or malformed submissions are harmless no-ops.
    """

    ADMITTED = "admitted"
    DUPLICATE = "duplicate"
    STALE = "stale"
    ORPHANED = "orphaned"
    MALFORMED = "malformed"


class OutputKind(StrEnum):
    """Discriminating kind for canonical ``RuntimeOutput`` values."""

    COACHING_PROJECTION = "coaching_projection"
    ACTION_RESULT = "action_result"
    VISUAL_GUIDANCE_IMAGE = "visual_guidance_image"
    HIGH_RESOLUTION_CAPTURE_REQUEST = "high_resolution_capture_request"
    PROTOCOL_ERROR = "protocol_error"


class EffectKind(StrEnum):
    """Declarative effect kind owned and launched by the runtime.

    This is runtime-internal. Effects are not a public seam: callers and tests do
    not coordinate reducer steps or scheduler lanes. A completion always re-enters
    the same mailbox as a correlated ``RuntimeEvent``.
    """

    REQUEST_STRATEGY = "request_strategy"
    REQUEST_PROGRESS = "request_progress"
    REQUEST_REVISION = "request_revision"
    REQUEST_OFFER_DECISION = "request_offer_decision"
    REQUEST_HIGH_RESOLUTION_CAPTURE = "request_high_resolution_capture"
    REQUEST_EDIT = "request_edit"
    CANCEL_REMOTE = "cancel_remote"
    RETAIN_DETACHED = "retain_detached"
    EVICT_DETACHED = "evict_detached"
    RELEASE_RETAINED_IMAGES = "release_retained_images"


@dataclass(frozen=True, slots=True)
class Receipt:
    """Acknowledgement of admission for one submitted event.

    Carries the application-authored event identity, the authoritative mailbox
    order, and the admission disposition. ``submit`` returns this before any
    remote work runs.
    """

    event_id: UUID
    order: int
    disposition: ReceiptDisposition

    def __post_init__(self) -> None:
        if self.order < 0:
            raise ValueError("mailbox order must not be negative")


# --- Canonical RuntimeEvent values -------------------------------------------
# Each event is an immutable, discriminated value. The runtime is the sole
# authority that allocates event identities and mailbox order; provider
# completions carry provenance envelopes but never author identities.


@dataclass(frozen=True, slots=True)
class IntentionAcceptedEvent:
    """A new or changed accepted intention, repeated by unchanged v1 observation.

    An accepted intention/``intention_updated`` text that explicitly requests an
    edited example is interpreted through typed grounded Strategy output, not a
    phrase allowlist. This event replaces the prior task immediately.
    """

    event_id: UUID
    task_epoch: int
    accepted_intention: str
    explicit_visual_request: bool = False


@dataclass(frozen=True, slots=True)
class EvidenceSettledEvent:
    """One accepted settled Evidence view admitted to the mailbox."""

    event_id: UUID
    evidence: EvidenceIdentity
    task_id: UUID


@dataclass(frozen=True, slots=True)
class UserActionEvent:
    """A one-use action invocation.

    ``action_id`` identifies the semantic opportunity; ``action_message_id``
    identifies this transmission. Globally one-use within a session.
    """

    event_id: UUID
    action_id: UUID
    action_message_id: UUID
    action_kind: ActionKind
    target: ActionTarget


@dataclass(frozen=True, slots=True)
class UserCaptureEvent:
    """A local user capture, neutrally acknowledged.

    A capture MUST proceed locally. It is neutrally acknowledged, invalidates
    analysis tied to an older view, and requires fresh live Evidence. It MUST NOT
    be interpreted as achievement, rejection, refusal, or "too soon."
    """

    event_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class PauseCoachingEvent:
    """Pause immediately invalidates pending/running reasoning, overlays,
    reminders, and visual jobs."""

    event_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class ResumeCoachingEvent:
    """Resume requires post-Resume fresh settled Evidence before retained
    guidance becomes current again."""

    event_id: UUID
    task_id: UUID


@dataclass(frozen=True, slots=True)
class ConnectionLostEvent:
    """Connection loss immediately invalidates async work in the runtime."""

    event_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class ConnectionResumedEvent:
    """A matching sole detached session resumed within the 60-second TTL."""

    event_id: UUID
    session_id: UUID


@dataclass(frozen=True, slots=True)
class ReasonerStrategyEvent:
    """A correlated ``propose_strategy`` completion.

    Carries provenance. May affect state only if its run remains authoritative and
    every applicable token is current; otherwise it is a harmless discard.
    """

    event_id: UUID
    provenance: Provenance
    proposal: Any  # ``StrategyProposal`` is defined in ``seams``; stored opaquely.


@dataclass(frozen=True, slots=True)
class ReasonerProgressEvent:
    """A correlated ``assess_progress`` completion."""

    event_id: UUID
    provenance: Provenance
    evidence: Any  # ``ProgressEvidence``; stored opaquely.


@dataclass(frozen=True, slots=True)
class ReasonerRevisionEvent:
    """A correlated ``propose_revision`` completion, limited to one Criterion."""

    event_id: UUID
    provenance: Provenance
    proposal: Any  # ``RevisionProposal``; stored opaquely.


@dataclass(frozen=True, slots=True)
class HighResolutionCaptureEvent:
    """A correlated v1 high-resolution still completion bound to a visual job."""

    event_id: UUID
    provenance: Provenance
    still_bytes_hash: str
    media_metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class EditorRenderEvent:
    """A correlated ``IllustrationEditor.render`` completion."""

    event_id: UUID
    provenance: Provenance
    illustration: Any  # ``EditedIllustration``; stored opaquely.


@dataclass(frozen=True, slots=True)
class AdapterFailureEvent:
    """A typed dependency failure carrying invocation identity.

    ``deadline_exceeded | unavailable | throttled | rejected | invalid_output |
    misconfigured``. Provider exceptions, HTTP codes, raw error text, SDK types,
    model names, prompts, and provider schemas remain inside Adapters.
    """

    event_id: UUID
    provenance: Provenance
    failure: TypedFailure
    throttle_delay_seconds: float | None = None

    def __post_init__(self) -> None:
        validate_throttle_delay(self.failure, self.throttle_delay_seconds)


@dataclass(frozen=True, slots=True)
class TaskEndedEvent:
    """The current task has ended; its active Instruction closes ``task_ended``."""

    event_id: UUID
    task_id: UUID


RuntimeEvent = Union[
    IntentionAcceptedEvent,
    EvidenceSettledEvent,
    UserActionEvent,
    UserCaptureEvent,
    PauseCoachingEvent,
    ResumeCoachingEvent,
    ConnectionLostEvent,
    ConnectionResumedEvent,
    ReasonerStrategyEvent,
    ReasonerProgressEvent,
    ReasonerRevisionEvent,
    HighResolutionCaptureEvent,
    EditorRenderEvent,
    AdapterFailureEvent,
    TaskEndedEvent,
]


def event_kind(event: RuntimeEvent) -> EventKind:
    """Return the discriminating kind for a ``RuntimeEvent``."""

    mapping: dict[type, EventKind] = {
        IntentionAcceptedEvent: EventKind.INTENTION_ACCEPTED,
        EvidenceSettledEvent: EventKind.EVIDENCE_SETTLED,
        UserActionEvent: EventKind.USER_ACTION,
        UserCaptureEvent: EventKind.USER_CAPTURE,
        PauseCoachingEvent: EventKind.PAUSE_COACHING,
        ResumeCoachingEvent: EventKind.RESUME_COACHING,
        ConnectionLostEvent: EventKind.CONNECTION_LOST,
        ConnectionResumedEvent: EventKind.CONNECTION_RESUMED,
        ReasonerStrategyEvent: EventKind.REASONER_STRATEGY,
        ReasonerProgressEvent: EventKind.REASONER_PROGRESS,
        ReasonerRevisionEvent: EventKind.REASONER_REVISION,
        HighResolutionCaptureEvent: EventKind.HIGH_RESOLUTION_CAPTURE,
        EditorRenderEvent: EventKind.EDITOR_RENDER,
        AdapterFailureEvent: EventKind.ADAPTER_FAILURE,
        TaskEndedEvent: EventKind.TASK_ENDED,
    }
    return mapping[type(event)]


def event_identity(event: RuntimeEvent) -> UUID:
    """Return the application-authored identity of any ``RuntimeEvent``."""

    return event.event_id  # type: ignore[union-attr]


# --- Canonical RuntimeOutput values ------------------------------------------


@dataclass(frozen=True, slots=True)
class CoachingProjection:
    """The complete immutable user-visible coaching projection.

    Emitted in committed order after the reducer commits next state. Async workers
    MUST NOT allocate revisions or write messages; the serialized runtime commits
    state, assigns the next revision, and enqueues output.
    """

    session_id: UUID
    state_revision: int
    task: Task | None
    phase: str
    instruction: Instruction | None
    activity: Activity | None
    overlays: OverlaySet | None
    available_actions: tuple[AvailableAction, ...] = ()
    visual_guidance: VisualGuidanceSidecar | None = None
    readiness: Readiness | None = None

    def __post_init__(self) -> None:
        if self.state_revision < 0:
            raise ValueError("state revision must not be negative")
        if self.task is None and self.instruction is not None:
            raise ValueError("an Instruction requires a Task")
        ids = [a.action_id for a in self.available_actions]
        if len(set(ids)) != len(ids):
            raise ValueError("available action ids must be unique in a projection")


@dataclass(frozen=True, slots=True)
class ActionResultOutput:
    """Immediate idempotent acknowledgement of a one-use action.

    Enqueued before any state snapshot caused by the disposition and before slow
    reasoning, capture, or editing. The subsequent full state is authoritative UI
    state.
    """

    session_id: UUID
    action_id: UUID
    action_message_id: UUID
    disposition: ActionDisposition
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class VisualGuidanceImageOutput:
    """A correlated phone-bound Generated Visual Guidance byte transfer.

    Announced in a committed full state first; the bytes follow. The phone accepts
    bytes only while its current state references the exact session, job, image ID,
    and first-announcement revision.
    """

    session_id: UUID
    artifact: GeneratedArtifact
    visual_job_id: UUID
    image_bytes: bytes

    def __post_init__(self) -> None:
        if not self.image_bytes:
            raise ValueError("visual guidance image bytes must be nonempty")


@dataclass(frozen=True, slots=True)
class HighResolutionCaptureRequest:
    """A correlated v1 high-resolution capture request bound to a visual job."""

    session_id: UUID
    request_id: UUID
    visual_job_id: UUID


@dataclass(frozen=True, slots=True)
class ProtocolErrorOutput:
    """A scoped extension fault that MUST NOT clear the last valid state."""

    session_id: UUID | None
    code: str
    related_message_id: UUID | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not self.code.strip():
            raise ValueError("protocol error code must be nonempty")


RuntimeOutput = Union[
    CoachingProjection,
    ActionResultOutput,
    VisualGuidanceImageOutput,
    HighResolutionCaptureRequest,
    ProtocolErrorOutput,
]


def output_kind(output: RuntimeOutput) -> OutputKind:
    """Return the discriminating kind for a ``RuntimeOutput``."""

    mapping: dict[type, OutputKind] = {
        CoachingProjection: OutputKind.COACHING_PROJECTION,
        ActionResultOutput: OutputKind.ACTION_RESULT,
        VisualGuidanceImageOutput: OutputKind.VISUAL_GUIDANCE_IMAGE,
        HighResolutionCaptureRequest: OutputKind.HIGH_RESOLUTION_CAPTURE_REQUEST,
        ProtocolErrorOutput: OutputKind.PROTOCOL_ERROR,
    }
    return mapping[type(output)]


# --- Declarative correlated Effect (runtime-internal, not a public seam) -----


@dataclass(frozen=True, slots=True)
class Effect:
    """A declarative effect owned and launched by the runtime.

    The runtime owns effect execution. Starting, succeeding, failing, timing out,
    or logically cancelling an effect always produces a correlated ``RuntimeEvent``
    through the same mailbox. Effects are **not** a public seam: callers and tests
    observe ``RuntimeOutput`` and the public ``CoachingRuntime`` Interface only.
    """

    effect_id: UUID
    kind: EffectKind
    provenance: Provenance
    correlation_id: UUID
    payload: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind is EffectKind.REQUEST_EDIT:
            if self.provenance.purpose is not RemotePurpose.EDIT:
                raise ValueError("edit effects must carry an edit provenance")
        object.__setattr__(self, "payload", MappingProxyType(dict(self.payload)))


__all__ = [
    "EventKind",
    "ReceiptDisposition",
    "OutputKind",
    "EffectKind",
    "Receipt",
    "IntentionAcceptedEvent",
    "EvidenceSettledEvent",
    "UserActionEvent",
    "UserCaptureEvent",
    "PauseCoachingEvent",
    "ResumeCoachingEvent",
    "ConnectionLostEvent",
    "ConnectionResumedEvent",
    "ReasonerStrategyEvent",
    "ReasonerProgressEvent",
    "ReasonerRevisionEvent",
    "HighResolutionCaptureEvent",
    "EditorRenderEvent",
    "AdapterFailureEvent",
    "TaskEndedEvent",
    "RuntimeEvent",
    "event_kind",
    "event_identity",
    "CoachingProjection",
    "ActionResultOutput",
    "VisualGuidanceImageOutput",
    "HighResolutionCaptureRequest",
    "ProtocolErrorOutput",
    "RuntimeOutput",
    "output_kind",
    "Effect",
]
