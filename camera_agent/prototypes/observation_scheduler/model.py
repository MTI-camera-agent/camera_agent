"""PROTOTYPE — pure reducer for observation gating and VLM scheduling.

Question: can latest-only coalescing, asymmetric settling, heartbeat checks, and a
bounded-overlap inference lane remain responsive without allowing stale model
work to change the active Instruction or Readiness?
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum


class EvidenceStatus(str, Enum):
    MISSING = "missing"
    SETTLING = "settling"
    SETTLED = "settled"


class InstructionFreshness(str, Enum):
    CURRENT = "current"
    NEEDS_REVALIDATION = "needs-revalidation"


class Purpose(str, Enum):
    ORIENT = "orient"
    EVALUATE = "evaluate"
    REPLAN = "replan"


class Trigger(str, Enum):
    FRESH_TASK = "fresh-task"
    MATERIAL_CHANGE = "material-change"
    CHEAP_PROBE = "cheap-probe"
    EXPLICIT_REPLAN = "explicit-replan"
    HEARTBEAT = "heartbeat"
    RETRY = "retry"


class Action(str, Enum):
    TICK = "tick"
    QUIET_FRAME = "quiet-frame"
    MATERIAL_FRAME = "material-frame"
    HARD_CAMERA_CHANGE = "hard-camera-change"
    PROBE_CHANGE = "probe-change"
    NEW_INTENTION = "new-intention"
    EXPLICIT_REPLAN = "explicit-replan"


class CompletionOutcome(str, Enum):
    HOLD = "hold"
    REVISE = "revise"
    READY = "ready"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Completion:
    """Adapter completion carrying the run identity it actually belongs to."""

    run_id: int
    outcome: CompletionOutcome


@dataclass(frozen=True, slots=True)
class Request:
    purpose: Purpose
    trigger: Trigger
    priority: int
    task_epoch: int
    strategy_revision: int
    instruction_id: int | None
    evidence_id: int
    camera_context: int
    source_observation_id: int


@dataclass(frozen=True, slots=True)
class Run:
    run_id: int
    request: Request


@dataclass(frozen=True, slots=True)
class State:
    tick: int = 0
    task_epoch: int = 1
    strategy_revision: int = 1
    instruction_id: int | None = 1
    instruction_strategy_revision: int | None = 1
    instruction_freshness: InstructionFreshness | None = InstructionFreshness.CURRENT
    ready: bool = False
    next_instruction_id: int = 2
    latest_observation_id: int = 1
    camera_context: int = 1
    evidence_status: EvidenceStatus = EvidenceStatus.SETTLED
    evidence_id: int | None = 1
    next_evidence_id: int = 2
    evidence_source_observation_id: int | None = 1
    quiet_streak: int = 2
    material_pending: bool = False
    material_trigger: Trigger | None = None
    replan_requested: bool = False
    recovery: str | None = None
    heartbeat_tier: int = 1
    heartbeat_due: int | None = 4
    pending: Request | None = None
    active: Run | None = None
    orphans: tuple[Run, ...] = ()
    next_run_id: int = 1
    effects: tuple[str, ...] = (
        "Initial demo state: Instruction 1 is backed by settled Evidence 1.",
    )


@dataclass(frozen=True, slots=True)
class Transition:
    state: State


def reduce(state: State, event: Action | Completion) -> Transition:
    state = replace(state, effects=())
    if isinstance(event, Completion):
        return Transition(_complete(state, event))

    if event is Action.TICK:
        state = replace(state, tick=state.tick + 1)
        if state.heartbeat_due is not None and state.tick >= state.heartbeat_due:
            if state.evidence_status is not EvidenceStatus.SETTLED:
                state = _effect(state, "Heartbeat/retry waits for fresh settled evidence.")
            elif state.active is not None or state.pending is not None:
                state = replace(state, heartbeat_due=state.tick + 1)
                state = _effect(state, "Heartbeat deferred behind active or pending work.")
            elif state.instruction_id is None:
                state = _enqueue(state, Purpose.ORIENT, Trigger.RETRY, priority=3)
                state = replace(state, heartbeat_due=None)
            elif state.replan_requested:
                state = _enqueue(state, Purpose.REPLAN, Trigger.RETRY, priority=3)
                state = replace(state, heartbeat_due=None)
            else:
                state = _enqueue(state, Purpose.EVALUATE, Trigger.HEARTBEAT, priority=1)
                state = replace(state, heartbeat_due=None)
        return Transition(_dispatch(state))

    if event is Action.NEW_INTENTION:
        state = _invalidate_active(state, "new intention")
        state = replace(
            state,
            task_epoch=state.task_epoch + 1,
            strategy_revision=1,
            instruction_id=None,
            instruction_strategy_revision=None,
            instruction_freshness=None,
            ready=False,
            evidence_status=EvidenceStatus.MISSING,
            evidence_id=None,
            evidence_source_observation_id=None,
            quiet_streak=0,
            material_pending=False,
            material_trigger=None,
            replan_requested=False,
            recovery=None,
            heartbeat_tier=1,
            heartbeat_due=None,
            pending=None,
        )
        state = _effect(state, "New task token: wait for two post-intention equivalent frames.")
        return Transition(state)

    if event is Action.EXPLICIT_REPLAN:
        if state.instruction_id is None:
            if state.active is not None and state.active.request.purpose is Purpose.ORIENT:
                state = _effect(state, "No Instruction exists; the active orientation already owns this need.")
                return Transition(state)
            state = replace(state, replan_requested=False)
            if state.evidence_status is EvidenceStatus.SETTLED:
                state = _enqueue(state, Purpose.ORIENT, Trigger.EXPLICIT_REPLAN, priority=3)
            else:
                state = _effect(state, "No Instruction exists; orientation waits for settled evidence.")
            return Transition(_dispatch(state))

        state = _invalidate_active(state, "explicit replan")
        state = replace(
            state,
            replan_requested=True,
            pending=None,
            heartbeat_tier=1,
            heartbeat_due=None,
        )
        if state.evidence_status is EvidenceStatus.SETTLED:
            state = _enqueue(state, Purpose.REPLAN, Trigger.EXPLICIT_REPLAN, priority=3)
        else:
            state = _effect(state, "Replan intent retained until evidence settles.")
        return Transition(_dispatch(state))

    if event in {
        Action.MATERIAL_FRAME,
        Action.HARD_CAMERA_CHANGE,
        Action.PROBE_CHANGE,
    }:
        trigger = Trigger.CHEAP_PROBE if event is Action.PROBE_CHANGE else Trigger.MATERIAL_CHANGE
        label = {
            Action.MATERIAL_FRAME: "preview/metadata delta",
            Action.HARD_CAMERA_CHANGE: "hard camera-context change",
            Action.PROBE_CHANGE: "cheap probe confidence crossing",
        }[event]
        state = _invalidate_active(state, label)
        state = replace(
            state,
            latest_observation_id=state.latest_observation_id + 1,
            camera_context=(
                state.camera_context + 1
                if event is Action.HARD_CAMERA_CHANGE
                else state.camera_context
            ),
            evidence_status=EvidenceStatus.SETTLING,
            evidence_id=None,
            evidence_source_observation_id=None,
            quiet_streak=1,
            material_pending=True,
            material_trigger=trigger,
            instruction_freshness=(
                InstructionFreshness.NEEDS_REVALIDATION
                if state.instruction_id is not None
                else None
            ),
            pending=None,
            heartbeat_tier=1,
            heartbeat_due=None,
        )
        state = _effect(
            state,
            f"{label} invalidates evidence immediately; this frame starts a settling candidate.",
        )
        return Transition(state)

    if event is Action.QUIET_FRAME:
        observation_id = state.latest_observation_id + 1
        state = replace(state, latest_observation_id=observation_id)
        if state.evidence_status is EvidenceStatus.SETTLED:
            state = _effect(
                state,
                "Equivalent frame coalesced as latest view; Evidence identity stays stable.",
            )
            return Transition(_dispatch(state))

        streak = state.quiet_streak + 1
        state = replace(state, quiet_streak=streak)
        if streak < 2:
            state = replace(state, evidence_status=EvidenceStatus.SETTLING)
            state = _effect(state, "First quiet candidate retained; one equivalent frame still required.")
            return Transition(state)

        evidence_id = state.next_evidence_id
        state = replace(
            state,
            evidence_status=EvidenceStatus.SETTLED,
            evidence_id=evidence_id,
            next_evidence_id=evidence_id + 1,
            evidence_source_observation_id=observation_id,
        )
        state = _effect(
            state,
            f"Evidence {evidence_id} settled from immutable Observation {observation_id}.",
        )
        if state.instruction_id is None:
            state = _enqueue(state, Purpose.ORIENT, Trigger.FRESH_TASK, priority=3)
        elif state.replan_requested:
            state = _enqueue(state, Purpose.REPLAN, Trigger.EXPLICIT_REPLAN, priority=3)
        elif state.material_pending:
            state = _enqueue(
                state,
                Purpose.EVALUATE,
                state.material_trigger or Trigger.MATERIAL_CHANGE,
                priority=2,
            )
        return Transition(_dispatch(state))

    raise AssertionError(f"unhandled action: {event}")


def _complete(state: State, completion: Completion) -> State:
    if state.active is None or completion.run_id != state.active.run_id:
        orphan = next((run for run in state.orphans if run.run_id == completion.run_id), None)
        if orphan is None:
            return _effect(state, f"Unknown Run {completion.run_id} completion discarded.")
        state = replace(
            state,
            orphans=tuple(run for run in state.orphans if run.run_id != completion.run_id),
        )
        state = _effect(
            state,
            f"Late Run {completion.run_id} completed after logical cancellation; its own token discards it.",
        )
        return _dispatch(state)

    run = state.active
    state = replace(state, active=None)
    if not _fresh(state, run.request):
        state = _effect(state, f"Run {run.run_id} failed token freshness; result discarded.")
        return _dispatch(state)

    if completion.outcome is CompletionOutcome.FAILED:
        state = replace(
            state,
            recovery="reasoner unavailable; retry scheduled",
            heartbeat_tier=1,
            heartbeat_due=state.tick + _heartbeat_interval(1),
        )
        return _effect(state, f"Run {run.run_id} failed; current Instruction/Ready remains unchanged.")

    strategy_revision = state.strategy_revision
    instruction_id = state.instruction_id
    next_instruction_id = state.next_instruction_id
    ready = state.ready
    creates_instruction = (
        run.request.purpose in {Purpose.ORIENT, Purpose.REPLAN}
        or completion.outcome in {CompletionOutcome.REVISE, CompletionOutcome.READY}
    )
    if run.request.purpose is Purpose.REPLAN:
        strategy_revision += 1
    if creates_instruction:
        instruction_id = next_instruction_id
        next_instruction_id += 1
    if completion.outcome is CompletionOutcome.READY:
        ready = True
    elif creates_instruction:
        ready = False

    is_hold = not creates_instruction
    next_tier = min(3, state.heartbeat_tier + 1) if is_hold else 1
    state = replace(
        state,
        strategy_revision=strategy_revision,
        instruction_id=instruction_id,
        instruction_strategy_revision=(
            strategy_revision if instruction_id is not None else None
        ),
        instruction_freshness=(
            InstructionFreshness.CURRENT if instruction_id is not None else None
        ),
        ready=ready,
        next_instruction_id=next_instruction_id,
        material_pending=False,
        material_trigger=None,
        replan_requested=False,
        recovery=None,
        heartbeat_tier=next_tier,
        heartbeat_due=state.tick + _heartbeat_interval(next_tier),
    )
    outcome = "hold/backoff" if is_hold else f"new Instruction {instruction_id}"
    state = _effect(
        state,
        f"Run {run.run_id} accepted ({outcome}) for Evidence {run.request.evidence_id}; "
        f"text may act on the latest equivalent view, overlays remain anchored to "
        f"Observation {run.request.source_observation_id}.",
    )
    return _dispatch(state)


def _enqueue(
    state: State,
    purpose: Purpose,
    trigger: Trigger,
    *,
    priority: int,
) -> State:
    if (
        state.evidence_status is not EvidenceStatus.SETTLED
        or state.evidence_id is None
        or state.evidence_source_observation_id is None
    ):
        return _effect(state, f"{purpose.value} request waits: no settled evidence.")
    request = Request(
        purpose=purpose,
        trigger=trigger,
        priority=priority,
        task_epoch=state.task_epoch,
        strategy_revision=state.strategy_revision,
        instruction_id=state.instruction_id,
        evidence_id=state.evidence_id,
        camera_context=state.camera_context,
        source_observation_id=state.evidence_source_observation_id,
    )
    pending = state.pending
    if pending is not None and pending.priority > request.priority:
        return _effect(
            state,
            f"Dropped {trigger.value}: pending {pending.trigger.value} has higher priority.",
        )
    state = replace(state, pending=request)
    return _effect(
        state,
        f"Latest-only queue now holds {purpose.value}/{trigger.value} for Evidence {request.evidence_id}.",
    )


def _dispatch(state: State) -> State:
    if state.active is not None or state.pending is None:
        return state
    # Hard budget: at most two physical VLM calls total, including orphans.
    if len(state.orphans) >= 2:
        return _effect(
            state,
            "Two non-cancellable orphan calls consume the physical cap; keep only the latest pending request.",
        )
    request = state.pending
    if not _fresh(state, request):
        return _effect(replace(state, pending=None), "Pending request became stale before dispatch.")
    run = Run(run_id=state.next_run_id, request=request)
    return _effect(
        replace(
            state,
            active=run,
            pending=None,
            next_run_id=state.next_run_id + 1,
        ),
        f"Started authoritative Run {run.run_id}; total physical VLM calls are capped at two.",
    )


def _invalidate_active(state: State, reason: str) -> State:
    if state.active is None:
        return state
    run = state.active
    state = replace(state, active=None, orphans=(*state.orphans, run))
    return _effect(
        state,
        f"Run {run.run_id} logically cancelled by {reason}; issue best-effort adapter cancellation.",
    )


def _fresh(state: State, request: Request) -> bool:
    return (
        state.evidence_status is EvidenceStatus.SETTLED
        and request.task_epoch == state.task_epoch
        and request.strategy_revision == state.strategy_revision
        and request.instruction_id == state.instruction_id
        and request.evidence_id == state.evidence_id
        and request.camera_context == state.camera_context
    )


def _heartbeat_interval(tier: int) -> int:
    # Demo ticks only. The specification should name measured budgets, not copy these.
    return {1: 4, 2: 6, 3: 9}[tier]


def _effect(state: State, message: str) -> State:
    return replace(state, effects=(*state.effects, message))
