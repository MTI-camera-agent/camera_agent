"""Strict scripted ``CoachingReasoner`` and ``IllustrationEditor`` doubles.

These are the deterministic Adapter implementations the replay harness drives
through the public seams. They support the full set of mechanical controls the
evaluation contract requires (§3):

- controlled *success* with a declared ``StrategyProposal`` / ``ProgressEvidence``
  / ``RevisionProposal`` / ``EditedIllustration``;
- controlled *typed failure* with a declared ``AdapterFailure``
  (``deadline_exceeded | unavailable | throttled | rejected | invalid_output |
  misconfigured``);
- *timeout*, where a call never self-completes and the test enforces the
  runtime deadline through the completion driver;
- *cancellable* versus *non-cancellable* physical calls — a non-cancellable
  call may be logically abandoned (its result will be discarded) but still
  occupies a physical slot until it physically completes; and
- *explicit completion order* — the test, not the adapter, decides which pending
  call matures next.

These doubles implement the already-approved public Adapter Protocols. They are
**not** a new seam and add no scheduling, retry, freshness, or visual-job
policy: the runtime owns all of that. The doubles only let a test drive the
public seam deterministically.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Union

from camera_agent.v2.identity import Provenance, RemotePurpose
from camera_agent.v2.seams import (
    AdapterFailure,
    AuthorizedIllustrationRequest,
    ContextPack,
    EditedIllustration,
    ProgressContextPack,
    ProgressEvidence,
    ReasonerOutcome,
    RevisionContextPack,
    RevisionProposal,
    StrategyContextPack,
    StrategyProposal,
)
from camera_agent.v2.values import TypedFailure

from .tracing import CallTrace, RecordedCall, ResourceHighWater


class CallLifecycle(StrEnum):
    """Terminal lifecycle of a scripted Adapter call."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    LOGICALLY_ABANDONED = "logically_abandoned"


@dataclass(frozen=True, slots=True)
class ScriptedResponse:
    """How a scripted call is configured to mature when the test triggers it.

    Exactly one of ``success`` / ``failure`` is set, or ``timeout`` is true. The
    test still controls *when* the call matures through the
    ``CompletionDriver``; this response only describes the terminal behavior.
    """

    success: Any | None = None
    failure: AdapterFailure | None = None
    timeout: bool = False
    cancellable: bool = True

    def __post_init__(self) -> None:
        flags = (self.success is not None, self.failure is not None, self.timeout)
        if sum(flags) != 1:
            raise ValueError(
                "a scripted response needs exactly one of success/failure/timeout"
            )

    # --- constructors ------------------------------------------------------

    @classmethod
    def success_for(cls, outcome: Any, *, cancellable: bool = True) -> "ScriptedResponse":
        return cls(success=outcome, cancellable=cancellable)

    @classmethod
    def failure_for(
        cls,
        failure: TypedFailure,
        *,
        provenance: Provenance,
        throttle_delay_seconds: float | None = None,
        cancellable: bool = True,
    ) -> "ScriptedResponse":
        return cls(
            failure=AdapterFailure(
                failure=failure,
                provenance=provenance,
                throttle_delay_seconds=throttle_delay_seconds,
            ),
            cancellable=cancellable,
        )

    @classmethod
    def timeout_for(cls, *, cancellable: bool = True) -> "ScriptedResponse":
        return cls(timeout=True, cancellable=cancellable)


ScriptedOutcome = Union[StrategyProposal, ProgressEvidence, RevisionProposal, EditedIllustration, AdapterFailure]
"""The union of outcomes a scripted call may resolve with."""


class _CancelledOutcome:
    """Sentinel marking a cancellable call that the runtime cancelled."""

    __slots__ = ()


_CANCELLED = _CancelledOutcome()


class PendingCall:
    """One in-flight scripted Adapter call awaiting test-driven completion.

    A call occupies a physical slot from creation until its slot is released
    (``complete`` / ``fail`` always release; ``cancel`` / ``time_out`` release
    only for *cancellable* calls — a non-cancellable call stays physically
    in-flight until it matures, modelling a provider call the runtime cannot
    physically abort).
    """

    def __init__(
        self,
        call_id: int,
        purpose: RemotePurpose,
        payload: ContextPack | AuthorizedIllustrationRequest,
        response: ScriptedResponse,
        started_at: float,
        future: asyncio.Future,
    ) -> None:
        self.call_id = call_id
        self.purpose = purpose
        self.payload = payload
        self.response = response
        self.started_at = started_at
        self.completed_at: float | None = None
        self.lifecycle = CallLifecycle.PENDING
        self._future = future
        self._outcome: Any = None
        self.slot_released = False

    @property
    def cancellable(self) -> bool:
        return self.response.cancellable

    @property
    def outcome(self) -> Any:
        return self._outcome

    @property
    def done(self) -> bool:
        """Physically terminal: the slot is released and the call cannot mature."""
        return self.lifecycle in {
            CallLifecycle.COMPLETED,
            CallLifecycle.FAILED,
            CallLifecycle.CANCELLED,
            CallLifecycle.TIMED_OUT,
        }

    @property
    def logically_abandoned(self) -> bool:
        return self.lifecycle is CallLifecycle.LOGICALLY_ABANDONED

    @property
    def matureable(self) -> bool:
        """The call can still be physically matured (completed/failed).

        A non-cancellable call that has been logically abandoned is still
        physically in-flight: it occupies a slot and must still mature.
        """
        return self.lifecycle in {CallLifecycle.PENDING, CallLifecycle.LOGICALLY_ABANDONED}

    async def await_completion(self) -> Any:
        """Await the call. Returns the resolved outcome or raises CancelledError."""
        result = await self._future
        if result is _CANCELLED:
            raise asyncio.CancelledError()
        return result

    def _terminate(self, lifecycle: CallLifecycle, completed_at: float, outcome: Any) -> None:
        self.lifecycle = lifecycle
        self.completed_at = completed_at
        self._outcome = outcome

    def _abandon(self, completed_at: float) -> None:
        # Logical abandonment: the call is no longer authoritative but a
        # non-cancellable physical call keeps its slot until it matures.
        self.lifecycle = CallLifecycle.LOGICALLY_ABANDONED
        self.completed_at = completed_at


class CompletionDriver:
    """Drives scripted calls to maturity in a test-declared order.

    The driver owns the deterministic call-id space, the call trace, and the
    resource high-water counters. It never inspects runtime state and never
    schedules reasoning, heartbeat, or visual work; it only resolves the futures
    the scripted adapters are awaiting, in the order a test declares.
    """

    def __init__(
        self,
        *,
        clock: Any,
        trace: CallTrace | None = None,
        high_water: ResourceHighWater | None = None,
    ) -> None:
        self._clock = clock
        self._trace = trace or CallTrace()
        self._high_water = high_water or ResourceHighWater()
        self._next_call_id = 0
        self._pending: list[PendingCall] = []
        self._all: list[PendingCall] = []
        self._in_flight = 0

    # --- internal ----------------------------------------------------------

    def _new_future(self) -> asyncio.Future:
        loop = asyncio.get_running_loop()
        return loop.create_future()

    def register(
        self,
        purpose: RemotePurpose,
        payload: ContextPack | AuthorizedIllustrationRequest,
        response: ScriptedResponse,
    ) -> PendingCall:
        call = PendingCall(
            call_id=self._next_call_id,
            purpose=purpose,
            payload=payload,
            response=response,
            started_at=self._clock.now(),
            future=self._new_future(),
        )
        self._next_call_id += 1
        self._pending.append(call)
        self._all.append(call)
        self._in_flight += 1
        self._high_water.observe_concurrent(self._in_flight)
        self._high_water.observe_pending(len(self._pending))
        self._trace.record(
            RecordedCall(
                call_id=call.call_id,
                purpose=purpose.value,
                payload_kind=type(payload).__name__,
                started_at=call.started_at,
                completed_at=None,
                outcome_kind="pending",
            )
        )
        return call

    # --- query -------------------------------------------------------------

    @property
    def trace(self) -> CallTrace:
        return self._trace

    @property
    def high_water(self) -> ResourceHighWater:
        return self._high_water

    def pending(self) -> tuple[PendingCall, ...]:
        return tuple(c for c in self._pending if not c.done)

    def in_flight_count(self) -> int:
        return self._in_flight

    def all_calls(self) -> tuple[PendingCall, ...]:
        return tuple(self._all)

    # --- termination -------------------------------------------------------

    def _release_slot(self, call: PendingCall) -> None:
        if not call.slot_released:
            self._in_flight -= 1
            call.slot_released = True

    def _record_outcome(self, call: PendingCall, outcome_kind: str) -> None:
        # Patch this call's trace row with its terminal fields.
        for index in range(len(self._trace) - 1, -1, -1):
            row = self._trace[index]
            if row.call_id == call.call_id:
                row.completed_at = call.completed_at
                row.outcome_kind = outcome_kind
                break

    def complete(
        self,
        call: PendingCall,
        *,
        outcome_override: Any | None = None,
        completed_at: float | None = None,
    ) -> None:
        if not call.matureable:
            raise ValueError(f"call {call.call_id} is already terminal")
        if call.response.timeout and outcome_override is None:
            raise ValueError(
                "a timeout call never succeeds; time_out() it or override the outcome"
            )
        outcome = outcome_override if outcome_override is not None else call.response.success
        if outcome is None:
            raise ValueError("no scripted success outcome to complete with")
        ts = completed_at if completed_at is not None else self._clock.now()
        call._terminate(CallLifecycle.COMPLETED, ts, outcome)
        if not call._future.done():
            call._future.set_result(outcome)
        self._release_slot(call)
        self._record_outcome(call, "success")

    def fail(
        self,
        call: PendingCall,
        *,
        failure_override: AdapterFailure | None = None,
        completed_at: float | None = None,
    ) -> None:
        if not call.matureable:
            raise ValueError(f"call {call.call_id} is already terminal")
        failure = failure_override or call.response.failure
        if failure is None:
            raise ValueError("no scripted failure to fail with")
        ts = completed_at if completed_at is not None else self._clock.now()
        call._terminate(CallLifecycle.FAILED, ts, failure)
        if not call._future.done():
            call._future.set_result(failure)
        self._release_slot(call)
        self._record_outcome(call, "failure")

    def cancel(self, call: PendingCall, *, completed_at: float | None = None) -> None:
        """Logically cancel a call.

        A *cancellable* call is resolved immediately (its awaiter raises
        ``CancelledError``) and its physical slot is freed. A *non-cancellable*
        call is marked logically abandoned; its physical slot is retained until
        the test matures it with ``complete``/``fail``.
        """
        if not call.matureable:
            raise ValueError(f"call {call.call_id} is already terminal")
        ts = completed_at if completed_at is not None else self._clock.now()
        if call.cancellable:
            call._terminate(CallLifecycle.CANCELLED, ts, _CANCELLED)
            if not call._future.done():
                call._future.set_result(_CANCELLED)
            self._release_slot(call)
            self._record_outcome(call, "cancelled")
        else:
            call._abandon(ts)
            self._record_outcome(call, "logically_abandoned")

    def time_out(self, call: PendingCall, *, completed_at: float | None = None) -> None:
        """Enforce the runtime deadline against a call.

        For a *cancellable* call this resolves it (its awaiter raises
        ``CancelledError``) and frees the slot. For a *non-cancellable* call the
        deadline cannot physically abort it; the call is logically abandoned and
        retains its slot until it physically matures.
        """
        if not call.matureable:
            raise ValueError(f"call {call.call_id} is already terminal")
        ts = completed_at if completed_at is not None else self._clock.now()
        if call.cancellable:
            call._terminate(CallLifecycle.TIMED_OUT, ts, _CANCELLED)
            if not call._future.done():
                call._future.set_result(_CANCELLED)
            self._release_slot(call)
            self._record_outcome(call, "timed_out")
        else:
            call._abandon(ts)
            self._record_outcome(call, "deadline_ignored_non_cancellable")

    # --- explicit-order helpers ------------------------------------------

    def complete_next(self, *, outcome_override: Any | None = None) -> PendingCall:
        call = self._oldest_pending()
        self.complete(call, outcome_override=outcome_override)
        return call

    def fail_next(self, *, failure_override: AdapterFailure | None = None) -> PendingCall:
        call = self._oldest_pending()
        self.fail(call, failure_override=failure_override)
        return call

    def cancel_next(self) -> PendingCall:
        call = self._oldest_pending()
        self.cancel(call)
        return call

    def time_out_next(self) -> PendingCall:
        call = self._oldest_pending()
        self.time_out(call)
        return call

    def complete_in_order(self, call_ids: list[int]) -> None:
        by_id = {c.call_id: c for c in self._pending}
        for call_id in call_ids:
            call = by_id[call_id]
            self.complete(call)

    def _oldest_pending(self) -> PendingCall:
        for call in self._pending:
            if not call.done:
                return call
        raise LookupError("no pending calls to mature")


@dataclass(slots=True)
class ScriptedReasoner:
    """A strict scripted ``CoachingReasoner`` double.

    Each method consults a per-purpose deque of scripted responses. When the
    deque is empty the adapter raises, so a test must declare every outcome it
    expects to drive. The adapter never authors Ready, identities, state
    transitions, Activity, retry policy, or consent.
    """

    driver: CompletionDriver
    strategy_responses: list[ScriptedResponse] = field(default_factory=list)
    progress_responses: list[ScriptedResponse] = field(default_factory=list)
    revision_responses: list[ScriptedResponse] = field(default_factory=list)

    def _next_response(
        self, responses: list[ScriptedResponse], purpose: RemotePurpose
    ) -> ScriptedResponse:
        if not responses:
            raise RuntimeError(f"scripted reasoner has no remaining {purpose.value} response")
        return responses.pop(0)

    async def propose_strategy(self, context: StrategyContextPack) -> ReasonerOutcome:
        response = self._next_response(self.strategy_responses, RemotePurpose.STRATEGY)
        call = self.driver.register(RemotePurpose.STRATEGY, context, response)
        return await call.await_completion()  # type: ignore[return-value]

    async def assess_progress(self, context: ProgressContextPack) -> ReasonerOutcome:
        response = self._next_response(self.progress_responses, RemotePurpose.PROGRESS)
        call = self.driver.register(RemotePurpose.PROGRESS, context, response)
        return await call.await_completion()  # type: ignore[return-value]

    async def propose_revision(self, context: RevisionContextPack) -> ReasonerOutcome:
        response = self._next_response(self.revision_responses, RemotePurpose.REVISION)
        call = self.driver.register(RemotePurpose.REVISION, context, response)
        return await call.await_completion()  # type: ignore[return-value]


@dataclass(slots=True)
class ScriptedEditor:
    """A strict scripted ``IllustrationEditor`` double."""

    driver: CompletionDriver
    render_responses: list[ScriptedResponse] = field(default_factory=list)

    async def render(self, request: AuthorizedIllustrationRequest) -> Any:  # EditorOutcome
        if not self.render_responses:
            raise RuntimeError("scripted editor has no remaining render response")
        response = self.render_responses.pop(0)
        call = self.driver.register(RemotePurpose.EDIT, request, response)
        return await call.await_completion()


__all__ = [
    "CallLifecycle",
    "ScriptedResponse",
    "ScriptedOutcome",
    "PendingCall",
    "CompletionDriver",
    "ScriptedReasoner",
    "ScriptedEditor",
]
