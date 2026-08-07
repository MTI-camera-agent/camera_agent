"""The sole v2 runtime authority and the opaque-lifecycle host seam.

One deep, mailbox-style ``CoachingRuntime`` Module is the sole semantic authority
for a live coaching session. A composition-root ``RuntimeHost`` Module owns only
cross-connection lifecycle without becoming a second coaching authority: it
atomically attaches one fresh or matching retained runtime, rejects a second
active connection, detains and retains for 60 seconds, and closes expired or
evicted runtimes. It treats runtime state as opaque.

These are the final public Interfaces. Construction receives immutable versioned
configuration and the selected ``CoachingReasoner`` and ``IllustrationEditor``
Adapters—the only public semantic Adapter seams inside the runtime.

No public reducer lane, scheduler, generic transport port, or independent
visual-workflow authority is introduced here. The internal pure transition
``current state + one semantic event -> next state + declarative effects`` and all
scheduling, memory, and visual-job policy remain behind the ``CoachingRuntime``
Interface.

This module is dormant v2 contract code. It is not imported by the production
composition root (``camera_agent.server`` / ``camera_agent.__main__``) until the
atomic-cutover ticket.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import AsyncIterator, Callable, Protocol, runtime_checkable
from uuid import UUID

from .config import RuntimeConfig
from .contracts import RuntimeEvent, RuntimeOutput, Receipt
from .seams import CoachingReasoner, IllustrationEditor
from .values import FrameSignals, Observation


class AttachDecision(StrEnum):
    """The atomic ``RuntimeHost.attach`` decision for one connection offer."""

    FRESH = "fresh"
    RESUMED = "resumed"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class ConnectionOffer:
    """A validated protocol offer presented to ``RuntimeHost.attach``.

    A Protocol Adapter validates hello/offer framing and translates it into this
    canonical offer. ``resume_session_id`` is the memory-only continuity handle
    carried by ``protocol_v2_offer``; ``None`` starts a fresh session.
    """

    offered_capabilities: tuple[str, ...]
    resume_session_id: UUID | None = None

    def __post_init__(self) -> None:
        if not self.offered_capabilities:
            raise ValueError("a connection offer must carry capabilities")
        if "camera_agent_interaction_v2" not in self.offered_capabilities:
            raise ValueError(
                "camera_agent_interaction_v2 is mandatory in every offer"
            )


@dataclass(frozen=True, slots=True)
class RuntimeLease:
    """A lease bound to exactly one runtime and one connection.

    ``attach`` returns this. ``detach`` submits the semantic connection-loss event
    to the bound runtime, invalidates the lease, and begins retention. The host
    treats retained runtime state as opaque and cannot inspect or mutate task,
    Evidence, Instruction, Readiness, or visual state.
    """

    lease_id: UUID
    session_id: UUID
    runtime: "CoachingRuntime"
    decision: AttachDecision


@runtime_checkable
class CoachingRuntime(Protocol):
    """The sole session authority for one live coaching session.

    Construction supplies immutable versioned configuration and the selected
    ``CoachingReasoner`` and ``IllustrationEditor`` Adapters.

    Guarantees:

    - ``submit`` acknowledges admission without waiting for remote work;
    - concurrent submissions receive one authoritative mailbox order;
    - state is committed before effects launch or outputs become deliverable;
    - async work never mutates state or writes to a phone directly; every
      completion re-enters the same mailbox as a correlated semantic event;
    - ``outputs`` yields complete immutable projections or correlated phone-bound
      requests in committed order; and
    - ``close`` immediately invalidates outstanding authority and releases bounded
      retained images without depending on physical cancellation.

    Callers and tests use the same Interface. No caller receives writable state
    lanes, coordinates reducer steps, or bypasses completion admission.
    """

    async def submit(self, event: RuntimeEvent) -> Receipt: ...

    def outputs(self) -> AsyncIterator[RuntimeOutput]: ...

    async def close(self) -> None: ...


@runtime_checkable
class RuntimeHost(Protocol):
    """The composition-root cross-connection lifecycle Module.

    Owns at most one active or detached ``CoachingRuntime``, the 60-second detached
    retention timer, active-connection rejection, matching resume attachment versus
    fresh-runtime creation, and closing expired or evicted runtimes. ``attach``
    performs that choice atomically and returns a lease bound to exactly one
    runtime and connection. ``detach`` submits the semantic connection-loss event
    to that runtime, invalidates the connection lease, and begins retention.

    The host treats retained runtime state as opaque and cannot inspect or mutate
    task, Evidence, Instruction, Readiness, or visual state. A Protocol Adapter
    only translates a validated offer into ``attach``, binds the returned
    ``RuntimeLease``, and translates wire input/output; it makes no continuity
    decision.
    """

    async def attach(self, offer: ConnectionOffer) -> RuntimeLease: ...

    async def detach(self, lease_id: UUID) -> None: ...

    async def close(self) -> None: ...


def build_runtime(
    config: RuntimeConfig,
    reasoner: CoachingReasoner,
    editor: IllustrationEditor,
    *,
    signal_computer: "Callable[[Observation | None, Observation], FrameSignals] | None" = None,
) -> CoachingRuntime:
    """Construct a ``CoachingRuntime`` from immutable config and the two Adapters.

    This factory is the sole composition entry point so that the production
    composition root never wires a second coaching authority. It returns the
    concrete tracer-bullet runtime (issue #21) extended with deterministic
    frame-signal measurement and asymmetric Settled hysteresis (issue #22):
    ordered admission from no intention through Task creation, observation
    settling, and initial Strategy completion to one persistent Instruction or
    immediate evidence-backed Ready.

    ``signal_computer`` is a private mechanical substitution, not a public
    Adapter seam: production decodes previews with Pillow; deterministic tests
    substitute a scripted signal computer through the same keyword argument. It
    never owns scheduling, settling policy, invalidation, Instruction,
    Readiness, or visual-job policy. Settled dwell is measured in the
    transport-recorded ``Observation.arrival_monotonic_seconds`` space, so no
    runtime-owned clock is required here.

    The returned runtime implements the v2 coaching surface; subsequent v2
    tickets extend the same public Interface. The package remains dormant and
    off the production composition root until the atomic-cutover ticket, so
    production never calls this factory yet.
    """

    from ._runtime_impl import _CoachingRuntime

    if signal_computer is None:
        from ._signals import PILFrameSignalComputer

        signal_computer = PILFrameSignalComputer(config.frame_signals).compute

    return _CoachingRuntime(
        config, reasoner, editor, signal_computer=signal_computer,
    )  # type: ignore[arg-type]


class RuntimeContractPending(RuntimeError):
    """Reserved for v2 factories whose implementation lands in a later ticket.

    The dormant v2 contract surface is complete; ``build_runtime`` now returns
    the tracer-bullet runtime. This exception is retained for any future
    not-yet-landed factory so the staged v2 migration can keep a single public
    surface marker. It is part of the approved public surface and is not raised
    by ``build_runtime``.
    """


__all__ = [
    "AttachDecision",
    "ConnectionOffer",
    "RuntimeLease",
    "CoachingRuntime",
    "RuntimeHost",
    "RuntimeContractPending",
    "build_runtime",
]
