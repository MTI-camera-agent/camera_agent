"""PROTOTYPE — Generated Visual Guidance offer and job policy.

This pure reducer explores when unsuccessful text coaching should produce one
non-nagging visual offer and how an accepted offer remains explicitly consented,
freshness-bound, cancellable, provenance-labelled, and separate from live-shot
progress. It is a decision artifact, not production harness code.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum


class Progress(StrEnum):
    ACHIEVED = "achieved"
    IMPROVING = "improving"
    INSUFFICIENT = "insufficient"
    DEVIATING = "deviating"
    BLOCKED = "blocked"


class VisualStatus(StrEnum):
    IDLE = "idle"
    OFFERED = "offered"
    WAITING_FOR_SETTLE = "waiting_for_settle"
    CAPTURING = "capturing"
    GENERATING = "generating"
    AVAILABLE = "available"
    FAILED = "failed"


class FailureStage(StrEnum):
    CAPTURE = "capture"
    EDIT = "edit"


@dataclass(frozen=True, slots=True)
class Instruction:
    id: str
    criterion_id: str
    text: str
    visualizable: bool = True


@dataclass(frozen=True, slots=True)
class VisualGuidance:
    status: VisualStatus = VisualStatus.IDLE
    id: str | None = None
    source_task_id: str | None = None
    source_instruction_id: str | None = None
    source_criterion_id: str | None = None
    source_scene_revision: int | None = None
    source_evidence_revision: int | None = None
    capture_sequence: int = 0
    capture_request_id: str | None = None
    still_id: str | None = None
    demonstrated_action: str | None = None
    failure_stage: FailureStage | None = None
    provenance: str | None = None


@dataclass(frozen=True, slots=True)
class State:
    task_id: str = "task-1"
    scene_revision: int = 1
    evidence_revision: int = 1
    settled: bool = True
    instruction_sequence: int = 1
    visual_sequence: int = 0
    instruction: Instruction = field(
        default_factory=lambda: Instruction(
            id="instruction-1",
            criterion_id="pose-shoulders",
            text="Subject: turn your shoulders slightly toward the window.",
        )
    )
    failed_actions: tuple[str, ...] = ()
    no_progress_streak: int = 0
    suppressed_offer_keys: frozenset[tuple[str, str, int]] = frozenset()
    improved_since_offer: bool = False
    visual: VisualGuidance = field(default_factory=VisualGuidance)
    last_event: str = "initial"


@dataclass(frozen=True, slots=True)
class ProgressEvaluated:
    progress: Progress
    instruction_id: str
    scene_revision: int
    evidence_revision: int


@dataclass(frozen=True, slots=True)
class ReplaceInstruction:
    text: str
    visualizable: bool = True


@dataclass(frozen=True, slots=True)
class UserAskedForVisual:
    pass


@dataclass(frozen=True, slots=True)
class AcceptOffer:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class DeclineOffer:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class MotionObserved:
    material: bool = False


@dataclass(frozen=True, slots=True)
class SettledObserved:
    pass


@dataclass(frozen=True, slots=True)
class StillCaptured:
    visual_id: str | None
    capture_request_id: str | None


@dataclass(frozen=True, slots=True)
class GenerationCompleted:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class JobFailed:
    visual_id: str | None
    stage: FailureStage


@dataclass(frozen=True, slots=True)
class RetryJob:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class CancelJob:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class DismissImage:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class AnotherExample:
    visual_id: str | None


Event = (
    ProgressEvaluated
    | ReplaceInstruction
    | UserAskedForVisual
    | AcceptOffer
    | DeclineOffer
    | MotionObserved
    | SettledObserved
    | StillCaptured
    | GenerationCompleted
    | JobFailed
    | RetryJob
    | CancelJob
    | DismissImage
    | AnotherExample
)


@dataclass(frozen=True, slots=True)
class Transition:
    state: State
    effects: tuple[str, ...] = ()


# Illustrative only. The release-gate ticket must derive the real no-progress
# budget from replay and live measurements.
PROACTIVE_FAILED_ACTION_BUDGET = 2


def initial_state() -> State:
    return State()


def evolve(state: State, event: Event) -> Transition:
    if isinstance(event, ProgressEvaluated):
        return _progress_evaluated(state, event)
    if isinstance(event, ReplaceInstruction):
        return _replace_instruction(state, event)
    if isinstance(event, UserAskedForVisual):
        if not state.instruction.visualizable:
            return _unchanged(state, event, "This instruction cannot be usefully illustrated.")
        if _has_live_job(state):
            return _unchanged(state, event, "Visual guidance is already active.")
        return _offer(state, event, "user_requested")
    if isinstance(event, AcceptOffer):
        if not _matches(state, event.visual_id, VisualStatus.OFFERED):
            return _unchanged(state, event, "Ignored stale or duplicate Generate action.")
        if state.settled:
            return _start_capture(state, event, "Generate authorizes one fresh transient still.")
        return Transition(
            replace(
                state,
                visual=replace(state.visual, status=VisualStatus.WAITING_FOR_SETTLE),
                last_event=type(event).__name__,
            ),
            ("Wait for compatible settled evidence; show ‘Hold still for the visual example…’.",),
        )
    if isinstance(event, DeclineOffer):
        if not _matches(state, event.visual_id, VisualStatus.OFFERED):
            return _unchanged(state, event, "Ignored stale or duplicate Not now action.")
        return _clear_and_suppress(state, event, "Suppress this offer for the same Instruction and scene.")
    if isinstance(event, MotionObserved):
        if event.material:
            effects = ()
            if _has_live_job(state):
                effects = ("Invalidate the visual-job token; discard any late still or image.",)
            return Transition(
                replace(
                    state,
                    scene_revision=state.scene_revision + 1,
                    settled=False,
                    failed_actions=(),
                    no_progress_streak=0,
                    improved_since_offer=False,
                    visual=VisualGuidance(),
                    last_event=type(event).__name__,
                ),
                effects,
            )
        visual = state.visual
        effects: tuple[str, ...] = ()
        if visual.status == VisualStatus.CAPTURING:
            visual = replace(
                visual,
                status=VisualStatus.WAITING_FOR_SETTLE,
                capture_request_id=None,
            )
            effects = ("Invalidate the in-motion capture request; wait for settled evidence and use a new request ID.",)
        return Transition(
            replace(state, settled=False, visual=visual, last_event=type(event).__name__),
            effects,
        )
    if isinstance(event, SettledObserved):
        settled_state = replace(
            state,
            evidence_revision=state.evidence_revision + 1,
            settled=True,
        )
        if state.visual.status == VisualStatus.WAITING_FOR_SETTLE:
            return _start_capture(settled_state, event, "Settled evidence authorizes the accepted job's fresh still.")
        return Transition(replace(settled_state, last_event=type(event).__name__))
    if isinstance(event, StillCaptured):
        if (
            not _matches(state, event.visual_id, VisualStatus.CAPTURING)
            or state.visual.capture_request_id != event.capture_request_id
        ):
            return _unchanged(state, event, "Discarded unmatched, in-motion, or late high-resolution still.")
        still_id = f"still-{state.visual.id}-{state.visual.capture_sequence}"
        return Transition(
            replace(
                state,
                visual=replace(
                    state.visual,
                    status=VisualStatus.GENERATING,
                    capture_request_id=None,
                    still_id=still_id,
                ),
                last_event=type(event).__name__,
            ),
            ("Edit only this accepted still to demonstrate the one source Instruction.",),
        )
    if isinstance(event, GenerationCompleted):
        if not _matches(state, event.visual_id, VisualStatus.GENERATING):
            return _unchanged(state, event, "Discarded stale or cancelled generated image.")
        return Transition(
            replace(
                state,
                visual=replace(
                    state.visual,
                    status=VisualStatus.AVAILABLE,
                    provenance="Edited illustration based on an earlier still — not the live preview.",
                ),
                last_event=type(event).__name__,
            ),
            ("Display in a separate visual-guidance area; do not change Strategy, Instruction, or Readiness.",),
        )
    if isinstance(event, JobFailed):
        if state.visual.id != event.visual_id or state.visual.status not in {
            VisualStatus.CAPTURING,
            VisualStatus.GENERATING,
        }:
            return _unchanged(state, event, "Ignored stale visual-job failure.")
        return Transition(
            replace(
                state,
                visual=replace(
                    state.visual,
                    status=VisualStatus.FAILED,
                    failure_stage=event.stage,
                ),
                last_event=type(event).__name__,
            ),
            ("Keep ordinary coaching available; show Retry and Dismiss.",),
        )
    if isinstance(event, RetryJob):
        if not _matches(state, event.visual_id, VisualStatus.FAILED):
            return _unchanged(state, event, "Ignored stale or duplicate Retry action.")
        if state.visual.failure_stage == FailureStage.EDIT and state.visual.still_id:
            visual = replace(state.visual, status=VisualStatus.GENERATING, failure_stage=None)
            effect = "Retry editing the accepted still; keep the same provenance tokens."
        elif state.settled:
            cleared = replace(
                state,
                visual=replace(
                    state.visual,
                    failure_stage=None,
                    still_id=None,
                ),
            )
            return _start_capture(cleared, event, "Retry authorizes one fresh transient still.")
        else:
            visual = replace(
                state.visual,
                status=VisualStatus.WAITING_FOR_SETTLE,
                failure_stage=None,
                capture_request_id=None,
                still_id=None,
            )
            effect = "Wait for compatible settled evidence before retrying capture."
        return Transition(
            replace(state, visual=visual, last_event=type(event).__name__),
            (effect,),
        )
    if isinstance(event, CancelJob):
        if state.visual.id != event.visual_id or state.visual.status not in {
            VisualStatus.WAITING_FOR_SETTLE,
            VisualStatus.CAPTURING,
            VisualStatus.GENERATING,
            VisualStatus.FAILED,
        }:
            return _unchanged(state, event, "Ignored stale or duplicate Cancel action.")
        return _clear_and_suppress(
            state,
            event,
            "Invalidate the job immediately; best-effort cancel physical work and discard late output.",
        )
    if isinstance(event, DismissImage):
        if state.visual.id != event.visual_id or state.visual.status not in {
            VisualStatus.AVAILABLE,
            VisualStatus.FAILED,
        }:
            return _unchanged(state, event, "Ignored stale or duplicate Dismiss action.")
        effect = (
            "Clear only the visual artifact; live coaching state is unchanged."
            if state.visual.status == VisualStatus.AVAILABLE
            else "Dismiss the scoped visual failure; live coaching state is unchanged."
        )
        return Transition(
            replace(state, visual=VisualGuidance(), last_event=type(event).__name__),
            (effect,),
        )
    if isinstance(event, AnotherExample):
        if not _matches(state, event.visual_id, VisualStatus.AVAILABLE):
            return _unchanged(state, event, "Ignored stale Another example action.")
        return _start_explicit_repeat(state, event)
    raise AssertionError(f"Unhandled event: {event!r}")


def _progress_evaluated(state: State, event: ProgressEvaluated) -> Transition:
    if (
        event.instruction_id != state.instruction.id
        or event.scene_revision != state.scene_revision
        or event.evidence_revision != state.evidence_revision
        or not state.settled
    ):
        return _unchanged(
            state,
            event,
            "Ignored progress without current Instruction, scene, and settled-evidence identity.",
        )
    if event.progress == Progress.INSUFFICIENT:
        action = _action_key(state.instruction.text)
        failed = state.failed_actions
        if action not in failed:
            failed += (action,)
        next_state = replace(
            state,
            failed_actions=failed,
            no_progress_streak=state.no_progress_streak + 1,
            last_event=type(event).__name__,
        )
        if (
            state.instruction.visualizable
            and len(failed) >= PROACTIVE_FAILED_ACTION_BUDGET
            and not _has_live_job(state)
            and _offer_key(state) not in state.suppressed_offer_keys
        ):
            return _offer(next_state, event, "bounded_no_progress")
        return Transition(next_state, ("Retain or refine text coaching; do not offer on the first miss.",))
    if event.progress == Progress.IMPROVING:
        return Transition(
            replace(
                state,
                failed_actions=(),
                no_progress_streak=0,
                improved_since_offer=(
                    state.improved_since_offer
                    or _offer_key(state) in state.suppressed_offer_keys
                ),
                last_event=type(event).__name__,
            ),
            ("Keep the current Instruction; clear the failed-action sequence and remember genuine recovery.",),
        )
    if event.progress == Progress.DEVIATING:
        suppressed = set(state.suppressed_offer_keys)
        effect = "Do not infer a visual offer; the Shot Strategy policy handles regression."
        if state.improved_since_offer:
            suppressed.discard(_offer_key(state))
            effect = "Improvement followed by regression starts a new offer episode; evidence must qualify again."
        return Transition(
            replace(
                state,
                failed_actions=(),
                no_progress_streak=0,
                suppressed_offer_keys=frozenset(suppressed),
                improved_since_offer=False,
                last_event=type(event).__name__,
            ),
            (effect,),
        )
    if event.progress in {Progress.ACHIEVED, Progress.BLOCKED}:
        return Transition(
            replace(
                state,
                failed_actions=(),
                no_progress_streak=0,
                last_event=type(event).__name__,
            ),
            ("Do not infer a visual offer; the Shot Strategy policy decides the Instruction lifecycle.",),
        )
    raise AssertionError(event.progress)


def _replace_instruction(state: State, event: ReplaceInstruction) -> Transition:
    sequence = state.instruction_sequence + 1
    effects = ()
    if _has_live_job(state):
        effects = ("Invalidate visual guidance tied to the superseded Instruction.",)
    return Transition(
        replace(
            state,
            instruction_sequence=sequence,
            instruction=Instruction(
                id=f"instruction-{sequence}",
                criterion_id=state.instruction.criterion_id,
                text=event.text,
                visualizable=event.visualizable,
            ),
            no_progress_streak=0,
            visual=VisualGuidance(),
            last_event=type(event).__name__,
        ),
        effects,
    )


def _offer(state: State, event: Event, reason: str) -> Transition:
    sequence = state.visual_sequence + 1
    visual = VisualGuidance(
        status=VisualStatus.OFFERED,
        id=f"visual-{sequence}",
        source_task_id=state.task_id,
        source_instruction_id=state.instruction.id,
        source_criterion_id=state.instruction.criterion_id,
        source_scene_revision=state.scene_revision,
        source_evidence_revision=state.evidence_revision,
        demonstrated_action=state.instruction.text,
    )
    suppressed = set(state.suppressed_offer_keys)
    suppressed.add(_offer_key(state))
    return Transition(
        replace(
            state,
            visual_sequence=sequence,
            suppressed_offer_keys=frozenset(suppressed),
            improved_since_offer=False,
            visual=visual,
            last_event=type(event).__name__,
        ),
        (f"Offer once ({reason}); wait for explicit Generate before capture or editing.",),
    )


def _start_capture(state: State, event: Event, reason: str) -> Transition:
    sequence = state.visual.capture_sequence + 1
    request_id = f"capture-{state.visual.id}-{sequence}"
    visual = replace(
        state.visual,
        status=VisualStatus.CAPTURING,
        capture_sequence=sequence,
        capture_request_id=request_id,
        failure_stage=None,
        still_id=None,
    )
    return Transition(
        replace(state, visual=visual, last_event=type(event).__name__),
        (f"{reason} Request {request_id}; do not save it.",),
    )


def _start_explicit_repeat(state: State, event: Event) -> Transition:
    sequence = state.visual_sequence + 1
    visual = replace(
        state.visual,
        status=VisualStatus.WAITING_FOR_SETTLE,
        id=f"visual-{sequence}",
        source_scene_revision=state.scene_revision,
        capture_sequence=0,
        capture_request_id=None,
        still_id=None,
        failure_stage=None,
        provenance=None,
    )
    repeated = replace(state, visual_sequence=sequence, visual=visual)
    if state.settled:
        return _start_capture(repeated, event, "Another example is explicit consent.")
    return Transition(
        replace(repeated, last_event=type(event).__name__),
        ("Another example is explicit consent: wait for settled evidence, then capture.",),
    )


def _clear_and_suppress(state: State, event: Event, effect: str) -> Transition:
    suppressed = set(state.suppressed_offer_keys)
    suppressed.add(_offer_key(state))
    return Transition(
        replace(
            state,
            suppressed_offer_keys=frozenset(suppressed),
            visual=VisualGuidance(),
            last_event=type(event).__name__,
        ),
        (effect,),
    )


def _offer_key(state: State) -> tuple[str, str, int]:
    return (state.task_id, state.instruction.criterion_id, state.scene_revision)


def _action_key(text: str) -> str:
    return " ".join(text.casefold().split())


def _has_live_job(state: State) -> bool:
    return state.visual.status != VisualStatus.IDLE


def _matches(state: State, visual_id: str | None, status: VisualStatus) -> bool:
    return state.visual.id == visual_id and state.visual.status == status


def _unchanged(state: State, event: Event, effect: str) -> Transition:
    return Transition(replace(state, last_event=type(event).__name__), (effect,))


def presentation(state: State) -> dict[str, str | None]:
    visual = state.visual
    activity = {
        VisualStatus.WAITING_FOR_SETTLE: "Hold still for the visual example…",
        VisualStatus.CAPTURING: "Capturing a fresh still…",
        VisualStatus.GENERATING: "Creating an edited illustration…",
        VisualStatus.FAILED: (
            "Couldn’t capture a still. Retry or dismiss."
            if visual.failure_stage == FailureStage.CAPTURE
            else "Couldn’t create the illustration. Retry or dismiss."
        ),
    }.get(visual.status)
    offer = None
    if visual.status == VisualStatus.OFFERED:
        offer = "Would an edited example help? [Generate] [Not now]"
    return {
        "instruction": state.instruction.text,
        "offer": offer,
        "activity": activity,
        "provenance": visual.provenance,
        "demonstrates": visual.demonstrated_action if visual.status == VisualStatus.AVAILABLE else None,
    }
