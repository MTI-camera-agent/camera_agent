"""External semantic Adapter seams for the dormant v2 runtime.

The only public semantic Adapter seams inside the runtime are
``CoachingReasoner`` and ``IllustrationEditor``. Production Gemini and strict
scripted implementations are Adapters at these seams.

The runtime owns IDs, scheduling, retry, freshness, validation, admission,
strategy revision, Instruction identity, and Readiness. Provider output is inert
until a current-token completion passes atomic admission. The Adapter Interfaces
contain domain proposals and Evidence, not provider prompts, SDK objects, model
names, HTTP errors, or authoritative runtime state.

Both seams return typed dependency outcomes carrying invocation identity:
``deadline_exceeded | unavailable | throttled | rejected | invalid_output |
misconfigured``. Adapters do not retry or decide semantic retryability; the runtime
owns the approved bounds.

This module is dormant v2 contract code and is not on the production composition
root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Protocol, Union, runtime_checkable
from uuid import UUID

from .identity import Provenance, RemotePurpose
from .values import (
    CriterionAssessment,
    EvidenceIdentity,
    ShotStrategy,
    StrategyApplicability,
    VisualGuidanceIntent,
    TypedFailure,
    validate_throttle_delay,
)


# --- Context Packs -----------------------------------------------------------
# Every remote call receives an immutable, allowlisted, provenance-tokened pack.
# Mandatory content MUST NOT be dropped. Structured text is capped at 32 KiB
# UTF-8 excluding image bytes. Image counts are purpose-specific.


@dataclass(frozen=True, slots=True)
class ContextImage:
    """One immutable image reference carried by a Context Pack.

    The runtime pins exact bytes only for a run's lifetime. ``bytes_hash`` is the
    authoritative source-byte hash recorded for diagnostics.
    """

    image_id: UUID
    bytes_hash: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("image dimensions must be positive")
        if not self.bytes_hash.strip():
            raise ValueError("image bytes hash must be nonempty")


@dataclass(frozen=True, slots=True)
class StrategyContextPack:
    """Context Pack for ``propose_strategy``.

    Contains intention, current settled Evidence/image, camera facts, journey,
    creation/rebuild reason, surviving constraints, and whether this accepted
    intention explicitly requests an edited example. Receives at most one current
    preview.
    """

    provenance: Provenance
    accepted_intention: str
    journey: str
    evidence: EvidenceIdentity
    current_image: ContextImage
    creation_reason: str
    surviving_constraints: tuple[str, ...] = ()
    explicit_visual_request: bool = False
    structured_text_bytes: int = 0

    def __post_init__(self) -> None:
        if self.provenance.purpose is not RemotePurpose.STRATEGY:
            raise ValueError("strategy pack must carry a strategy provenance")
        if not self.accepted_intention.strip():
            raise ValueError("accepted intention must be nonempty")
        if not self.journey.strip():
            raise ValueError("journey must be nonempty")
        if not self.creation_reason.strip():
            raise ValueError("creation reason must be nonempty")
        if self.structured_text_bytes > 32 * 1024:
            raise ValueError("context structured text exceeds 32 KiB")


@dataclass(frozen=True, slots=True)
class ProgressContextPack:
    """Context Pack for ``assess_progress``.

    Contains current Strategy and every must-have, active Instruction, current
    Evidence/image, one previous compatible summary, relevant trajectory counters,
    and cheap deterministic signals. Receives at most one current plus one previous
    compatible preview.
    """

    provenance: Provenance
    strategy: ShotStrategy
    active_instruction_text: str | None
    evidence: EvidenceIdentity
    current_image: ContextImage
    previous_image: ContextImage | None = None
    trajectory_counters: dict[str, int] = field(default_factory=dict)
    deterministic_signals: dict[str, float] = field(default_factory=dict)
    structured_text_bytes: int = 0

    def __post_init__(self) -> None:
        if self.provenance.purpose is not RemotePurpose.PROGRESS:
            raise ValueError("progress pack must carry a progress provenance")
        if self.structured_text_bytes > 32 * 1024:
            raise ValueError("context structured text exceeds 32 KiB")
        object.__setattr__(self, "trajectory_counters", MappingProxyType(dict(self.trajectory_counters)))
        object.__setattr__(
            self, "deterministic_signals", MappingProxyType(dict(self.deterministic_signals))
        )


@dataclass(frozen=True, slots=True)
class RevisionContextPack:
    """Context Pack for ``propose_revision``.

    Contains one affected Criterion, current/rejected action, relevant Evidence,
    bounded attempts, and constraints. Receives at most one current preview.
    Limited to an alternative for one Criterion or a one-Criterion patch.
    """

    provenance: Provenance
    affected_criterion_id: UUID
    evidence: EvidenceIdentity
    current_image: ContextImage
    rejected_action_text: str | None = None
    attempt_count: int = 0
    constraints: tuple[str, ...] = ()
    structured_text_bytes: int = 0

    def __post_init__(self) -> None:
        if self.provenance.purpose is not RemotePurpose.REVISION:
            raise ValueError("revision pack must carry a revision provenance")
        if self.attempt_count < 0:
            raise ValueError("attempt count must not be negative")
        if self.structured_text_bytes > 32 * 1024:
            raise ValueError("context structured text exceeds 32 KiB")


@dataclass(frozen=True, slots=True)
class OfferDecisionContextPack:
    """Context Pack for a proactive visual-guidance offer decision."""

    provenance: Provenance
    evidence: EvidenceIdentity
    source_instruction_id: UUID
    criterion_id: UUID
    suppression_choices: tuple[str, ...] = ()
    structured_text_bytes: int = 0

    def __post_init__(self) -> None:
        if self.provenance.purpose is not RemotePurpose.OFFER_DECISION:
            raise ValueError("offer-decision pack must carry an offer provenance")
        if self.structured_text_bytes > 32 * 1024:
            raise ValueError("context structured text exceeds 32 KiB")


@dataclass(frozen=True, slots=True)
class AuthorizedIllustrationRequest:
    """Authorized request for ``IllustrationEditor.render``.

    Only an accepted Generate, Retry, or Another example action plus a fresh
    compatible still permits construction. The request binds all task, Instruction,
    Criterion, Evidence, camera, visual-job/attempt, action, capture, and
    source-image identities; contains one demonstrated adjustment and fixed
    preservation/media constraints; and excludes the coaching transcript. Edit
    receives exactly one accepted still.
    """

    provenance: Provenance
    demonstrates: str
    accepted_still: ContextImage
    preservation_constraints: tuple[str, ...] = ()
    media_limits: dict[str, int] = field(default_factory=dict)
    structured_text_bytes: int = 0

    def __post_init__(self) -> None:
        if self.provenance.purpose is not RemotePurpose.EDIT:
            raise ValueError("edit request must carry an edit provenance")
        if not self.demonstrates.strip():
            raise ValueError("demonstrates must be nonempty")
        if self.structured_text_bytes > 32 * 1024:
            raise ValueError("context structured text exceeds 32 KiB")
        object.__setattr__(self, "media_limits", MappingProxyType(dict(self.media_limits)))


@dataclass(frozen=True, slots=True)
class RetryContextPack:
    """A newly assembled pack from current authoritative memory, not replay.

    Every retry uses a freshly assembled Context Pack of the appropriate purpose
    and runs only while the semantic purpose remains current.
    """

    provenance: Provenance
    structured_text_bytes: int = 0

    def __post_init__(self) -> None:
        if self.provenance.purpose is not RemotePurpose.RETRY:
            raise ValueError("retry pack must carry a retry provenance")
        if self.structured_text_bytes > 32 * 1024:
            raise ValueError("context structured text exceeds 32 KiB")


ContextPack = Union[
    StrategyContextPack,
    ProgressContextPack,
    RevisionContextPack,
    OfferDecisionContextPack,
    AuthorizedIllustrationRequest,
    RetryContextPack,
]


# --- Reasoner proposals and progress evidence --------------------------------


@dataclass(frozen=True, slots=True)
class ProposedCriterion:
    """A Criterion proposed by the Reasoner (ids assigned by the runtime)."""

    importance: str
    priority: int
    observable_target: str
    candidate_actions: tuple[str, ...]
    responsible_actor: str | None = None
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.importance not in {"must_have", "nice_to_have"}:
            raise ValueError("proposed importance must be must_have or nice_to_have")
        if not self.observable_target.strip():
            raise ValueError("proposed target must be nonempty")
        if not self.candidate_actions:
            raise ValueError("a proposed criterion needs at least one action")
        if len(self.candidate_actions) > 3:
            raise ValueError("a proposed criterion has at most three actions")


@dataclass(frozen=True, slots=True)
class StrategyProposal:
    """Output of ``propose_strategy``.

    Supplies proposed Criteria, grounded current-view assessments for every
    proposed must-have, feasible actions, at most one candidate first action, and a
    typed ``VisualGuidanceIntent`` grounded in the accepted intention text and
    current Criterion suitability. Deterministic admission assigns IDs and may
    derive immediate Ready without a second call.

    The Reasoner MUST NOT author Ready, authoritative IDs, state transitions,
    Activity, retry policy, consent, or final Strategy/Instruction state.
    """

    criteria: tuple[ProposedCriterion, ...]
    must_have_assessments: tuple[CriterionAssessment, ...]
    visual_guidance_intent: VisualGuidanceIntent
    candidate_first_action: str | None = None

    def __post_init__(self) -> None:
        if not self.criteria:
            raise ValueError("a proposal needs at least one criterion")
        if len(self.criteria) > 6:
            raise ValueError("a proposal has at most six criteria")
        must_haves = [c for c in self.criteria if c.importance == "must_have"]
        if len(must_haves) > 4:
            raise ValueError("a proposal has at most four must-haves")
        if len(must_haves) != len(self.must_have_assessments):
            raise ValueError(
                "must-have assessments must cover every proposed must-have"
            )


@dataclass(frozen=True, slots=True)
class ProgressEvidence:
    """Output of ``assess_progress``.

    Covers every current must-have once against the same Evidence, returns one
    bounded ``StrategyApplicability`` record, and may include at most one candidate
    action. Only an admitted high-confidence ``broad_discontinuity`` may request a
    full rebuild.
    """

    must_have_assessments: tuple[CriterionAssessment, ...]
    applicability: StrategyApplicability
    nice_to_have_assessments: tuple[CriterionAssessment, ...] = ()
    candidate_action: str | None = None

    def __post_init__(self) -> None:
        if not self.must_have_assessments:
            raise ValueError("progress evidence must assess every must-have")
        ids = [a.criterion_id for a in self.must_have_assessments]
        if len(set(ids)) != len(ids):
            raise ValueError("must-have criterion references must be unique")


@dataclass(frozen=True, slots=True)
class RevisionProposal:
    """Output of ``propose_revision``, limited to one Criterion.

    Either an alternative action for one Criterion or a one-Criterion patch.
    """

    affected_criterion_id: UUID
    alternative_action: str | None = None
    patched_target: str | None = None
    constraints: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.alternative_action is None and self.patched_target is None:
            raise ValueError("a revision proposes an action or a patch")
        if self.alternative_action is not None and not self.alternative_action.strip():
            raise ValueError("alternative action must be nonempty")
        if self.patched_target is not None and not self.patched_target.strip():
            raise ValueError("patched target must be nonempty")


# --- Editor output and typed failure ----------------------------------------


@dataclass(frozen=True, slots=True)
class EditedIllustration:
    """Validated edited illustration output from ``IllustrationEditor.render``.

    The Adapter validates media bytes, type, dimensions, decode integrity, and
    bounds. V2 performs no additional runtime VLM inspection of edited output.
    Generated output never enters live Evidence.
    """

    image_id: UUID
    bytes_hash: str
    mime_type: str
    width: int
    height: int

    def __post_init__(self) -> None:
        if not self.bytes_hash.strip():
            raise ValueError("illustration bytes hash must be nonempty")
        if self.mime_type not in {"image/jpeg", "image/png"}:
            raise ValueError("edited illustration must be JPEG or PNG")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("illustration dimensions must be positive")


@dataclass(frozen=True, slots=True)
class AdapterFailure:
    """Typed dependency outcome carrying invocation identity.

    Provider exceptions, HTTP codes, raw error text, SDK types, model names,
    prompts, and provider schemas remain inside Adapters. Adapters MUST NOT retry
    or decide semantic retryability. ``throttled`` MAY include a provider delay.
    """

    failure: TypedFailure
    provenance: Provenance
    throttle_delay_seconds: float | None = None

    def __post_init__(self) -> None:
        validate_throttle_delay(self.failure, self.throttle_delay_seconds)


ReasonerOutcome = Union[StrategyProposal, ProgressEvidence, RevisionProposal, AdapterFailure]
EditorOutcome = Union[EditedIllustration, AdapterFailure]


# --- Public Adapter seams ----------------------------------------------------


@runtime_checkable
class CoachingReasoner(Protocol):
    """The sole external reasoning seam.

    The VLM supplies semantic Evidence and proposals. It MAY propose Criteria,
    priorities, actors, feasible actions, grounded assessments, uncertainty, one
    candidate action/overlay, or one explicitly scoped revision. It MUST NOT author
    Ready, authoritative IDs, state transitions, Activity, retry policy, consent,
    or final Strategy/Instruction state.
    """

    async def propose_strategy(
        self, context: StrategyContextPack
    ) -> ReasonerOutcome: ...

    async def assess_progress(
        self, context: ProgressContextPack
    ) -> ReasonerOutcome: ...

    async def propose_revision(
        self, context: RevisionContextPack
    ) -> ReasonerOutcome: ...


@runtime_checkable
class IllustrationEditor(Protocol):
    """The sole external illustration-editing seam.

    Only the runtime may construct an authorized request after identified consent
    and fresh compatible capture. The editor cannot choose whether to offer,
    request capture, select an adjustment, change coaching state, or create
    Evidence. Production HTTP/editor and strict scripted implementations are
    Adapters at this seam.
    """

    async def render(
        self, request: AuthorizedIllustrationRequest
    ) -> EditorOutcome: ...


__all__ = [
    "ContextImage",
    "StrategyContextPack",
    "ProgressContextPack",
    "RevisionContextPack",
    "OfferDecisionContextPack",
    "AuthorizedIllustrationRequest",
    "RetryContextPack",
    "ContextPack",
    "ProposedCriterion",
    "StrategyProposal",
    "ProgressEvidence",
    "RevisionProposal",
    "EditedIllustration",
    "AdapterFailure",
    "ReasonerOutcome",
    "EditorOutcome",
    "CoachingReasoner",
    "IllustrationEditor",
]
