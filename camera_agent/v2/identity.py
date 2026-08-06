"""Application-authored identities and provenance envelopes for the v2 runtime.

The runtime owns application-authored UUIDs for task, strategy revision, Criterion,
Instruction, Evidence, camera context, reasoning run, visual offer/job/attempt,
capture request, action opportunity, and generated transfer. Observation identity
remains the v1 positive process-local ``observationId``. Action UUIDs are derived
from a session-scoped monotonic ordinal.

Every remote invocation and completion carries an out-of-band provenance envelope
containing its purpose and all applicable identities. Model-controlled output MUST
NOT author or alter those identities. A completion may affect state only if its
run remains authoritative and every applicable token is current.

This module is dormant v2 contract code and is not on the production composition
root.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping
from uuid import UUID, uuid4


class RemotePurpose(StrEnum):
    """Purpose of a remote Reasoner/Editor invocation, carried in provenance."""

    STRATEGY = "strategy"
    PROGRESS = "progress"
    REVISION = "revision"
    OFFER_DECISION = "offer_decision"
    EDIT = "edit"
    RETRY = "retry"


class AnalysisPurpose(StrEnum):
    """Coaching analysis purpose for an authoritative reasoning run.

    These are distinct from ``RemotePurpose``: the runtime derives the analysis
    purpose that motivates a Reasoner call (orient/evaluate/replan) and maps it
    onto the appropriate Reasoner method.
    """

    ORIENT = "orient"
    EVALUATE = "evaluate"
    REPLAN = "replan"


@dataclass(frozen=True, slots=True)
class RuntimeVersion:
    """Versioned configuration stamp recorded in every evidence output.

    ``calibrated`` records whether threshold-bearing values have been promoted by
    a documented calibration run. Initial values are explicitly **uncalibrated**.
    """

    major: int = 1
    minor: int = 0
    patch: int = 0
    calibrated: bool = False

    def __post_init__(self) -> None:
        if self.major < 0 or self.minor < 0 or self.patch < 0:
            raise ValueError("runtime version components must not be negative")

    def __str__(self) -> str:
        suffix = "" if self.calibrated else "+uncalibrated"
        return f"v2.{self.major}.{self.minor}.{self.patch}{suffix}"


def new_identity() -> UUID:
    """Allocate a fresh application-authored identity UUID.

    The runtime is the sole allocator of application-authored identities. Provider
    output is inert until a current-token completion passes admission; it never
    authors or alters these identities.
    """

    return uuid4()


@dataclass(frozen=True, slots=True)
class Provenance:
    """Out-of-band provenance envelope for one remote invocation or completion.

    Carries the invocation purpose and every applicable identity. Duplicate, late,
    stale, orphaned, physically uncancelled, or malformed completions are harmless
    dispositions: a completion may affect state only if its run remains
    authoritative and every applicable token is current.

    ``identities`` is an immutable mapping of identity-kind to UUID. Identity kinds
    are not enumerated here so that the runtime can attach whichever of task,
    strategy revision, Criterion, Instruction, Evidence, camera context, reasoning
    run, visual offer/job/attempt, capture request, action opportunity, and
    generated transfer apply to the purpose.
    """

    purpose: RemotePurpose
    run_id: UUID
    identities: Mapping[str, UUID] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.identities and self.purpose is not RemotePurpose.EDIT:
            # Every non-edit remote call is bound to at least the task and Evidence
            # it reasons about. ``EDIT`` carries its own authorized-still identity
            # set validated by ``AuthorizedIllustrationRequest``.
            raise ValueError("provenance must carry at least one identity")
        # Freeze as an immutable mapping view so callers cannot mutate identities.
        object.__setattr__(self, "identities", MappingProxyType(dict(self.identities)))

    def token(self, kind: str) -> UUID | None:
        return self.identities.get(kind)

    def is_current(self, current: Mapping[str, UUID]) -> bool:
        """Return ``True`` only if every applicable identity is still current.

        A completion whose run is no longer authoritative, or whose task,
        strategy revision, Evidence, camera context, or other token has been
        replaced, is harmless and MUST NOT act.
        """

        for kind, value in self.identities.items():
            if current.get(kind) != value:
                return False
        return True
