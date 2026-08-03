"""PROTOTYPE — pure reducer for Camera Agent Harness v2 runtime state.

This is a decision artifact, not production code. The question is whether one
serialized reducer over orthogonal facts can preserve one Instruction while
motion, analysis, connection recovery, and Generated Visual Guidance change
independently. User-facing phase and Activity are projections, never mutable
state lanes of their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import StrEnum


class Mode(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


class Connection(StrEnum):
    CONNECTED = "connected"
    VERIFYING = "connected_needs_fresh_evidence"
    DISCONNECTED = "disconnected"


class Phase(StrEnum):
    """Derived user-facing coaching phase. Visualizing is intentionally absent."""

    NEEDS_INTENTION = "needs_intention"
    ORIENTING = "orienting"
    COACHING = "coaching"
    EVALUATING = "evaluating"
    READY = "ready"
    RECOVERING = "recovering"
    PAUSED = "paused"


class Evidence(StrEnum):
    NEEDED = "fresh_evidence_needed"
    MOVING = "moving"
    SETTLING = "settling"
    SETTLED = "settled"


class Freshness(StrEnum):
    CURRENT = "current"
    UNVERIFIED = "needs_revalidation"
    MAY_BE_OUTDATED = "may_be_outdated"


class InstructionDisposition(StrEnum):
    ACHIEVED = "achieved"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"
    IRRELEVANT = "irrelevant"
    TASK_ENDED = "task_ended"


class Readiness(StrEnum):
    NOT_READY = "not_ready"
    READY = "ready"
    UNVERIFIED = "needs_revalidation"


class AnalysisKind(StrEnum):
    ORIENT = "orient"
    EVALUATE = "evaluate"
    REPLAN = "replan"


class AnalysisOutcome(StrEnum):
    GUIDANCE = "guidance"
    ADVANCE = "advance"
    HOLD = "hold"
    READY = "ready"


class VisualStatus(StrEnum):
    IDLE = "idle"
    OFFERED = "offered"
    CAPTURING = "capturing"
    GENERATING = "generating"
    AVAILABLE = "available"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class Instruction:
    id: str
    text: str
    freshness: Freshness = Freshness.CURRENT


@dataclass(frozen=True, slots=True)
class InstructionRecord:
    id: str
    text: str
    disposition: InstructionDisposition


@dataclass(frozen=True, slots=True)
class AnalysisRun:
    id: str
    kind: AnalysisKind
    task_generation: int
    evidence_revision: int
    prior_readiness: Readiness


@dataclass(frozen=True, slots=True)
class VisualGuidance:
    status: VisualStatus = VisualStatus.IDLE
    id: str | None = None
    source_task_generation: int | None = None
    source_instruction_id: str | None = None
    source_evidence_revision: int | None = None
    label: str | None = None


@dataclass(frozen=True, slots=True)
class State:
    mode: Mode = Mode.ACTIVE
    connection: Connection = Connection.CONNECTED
    evidence: Evidence = Evidence.NEEDED
    intention: str = ""
    task_generation: int = 0
    evidence_revision: int = 0
    instruction_sequence: int = 0
    analysis_sequence: int = 0
    visual_sequence: int = 0
    instruction: Instruction | None = None
    instruction_history: tuple[InstructionRecord, ...] = ()
    readiness: Readiness = Readiness.NOT_READY
    readiness_evidence_revision: int | None = None
    analysis: AnalysisRun | None = None
    visual: VisualGuidance = field(default_factory=VisualGuidance)
    coaching_problem: str | None = None
    needs_evaluation: bool = False
    replan_requested: bool = False
    last_event: str = "initial"


# Events are semantic inputs. Thresholds, queues, transports, and models stay
# behind adapters that translate their own details before crossing this seam.
@dataclass(frozen=True, slots=True)
class SetIntention:
    text: str


@dataclass(frozen=True, slots=True)
class ClearIntention:
    pass


@dataclass(frozen=True, slots=True)
class MotionObserved:
    material: bool = True


@dataclass(frozen=True, slots=True)
class SettlingObserved:
    pass


@dataclass(frozen=True, slots=True)
class SettledObserved:
    pass


@dataclass(frozen=True, slots=True)
class AnalysisCompleted:
    run_id: str
    outcome: AnalysisOutcome
    instruction: str | None = None


@dataclass(frozen=True, slots=True)
class AnalysisFailed:
    run_id: str
    detail: str = "The scene could not be evaluated. Hold still to try again."


@dataclass(frozen=True, slots=True)
class RejectInstruction:
    instruction_id: str | None


@dataclass(frozen=True, slots=True)
class InstructionBecameIrrelevant:
    instruction_id: str | None


@dataclass(frozen=True, slots=True)
class Pause:
    pass


@dataclass(frozen=True, slots=True)
class Resume:
    pass


@dataclass(frozen=True, slots=True)
class Disconnect:
    pass


@dataclass(frozen=True, slots=True)
class Reconnect:
    continuity_trusted: bool


@dataclass(frozen=True, slots=True)
class UserCaptured:
    pass


@dataclass(frozen=True, slots=True)
class OfferVisualGuidance:
    pass


@dataclass(frozen=True, slots=True)
class AcceptVisualGuidance:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class VisualStillCaptured:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class VisualGenerated:
    visual_id: str | None
    label: str = "Edited illustration of the suggested adjustment"


@dataclass(frozen=True, slots=True)
class VisualFailed:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class RetryVisualGuidance:
    visual_id: str | None


@dataclass(frozen=True, slots=True)
class CancelVisualGuidance:
    visual_id: str | None


Event = (
    SetIntention
    | ClearIntention
    | MotionObserved
    | SettlingObserved
    | SettledObserved
    | AnalysisCompleted
    | AnalysisFailed
    | RejectInstruction
    | InstructionBecameIrrelevant
    | Pause
    | Resume
    | Disconnect
    | Reconnect
    | UserCaptured
    | OfferVisualGuidance
    | AcceptVisualGuidance
    | VisualStillCaptured
    | VisualGenerated
    | VisualFailed
    | RetryVisualGuidance
    | CancelVisualGuidance
)


@dataclass(frozen=True, slots=True)
class Transition:
    state: State
    effects: tuple[str, ...] = ()


def initial_state() -> State:
    return State()


def phase(state: State) -> Phase:
    """Project authoritative facts into one coaching phase."""

    if state.mode is Mode.PAUSED:
        return Phase.PAUSED
    if not state.intention:
        return Phase.NEEDS_INTENTION
    if state.connection is not Connection.CONNECTED:
        return Phase.RECOVERING
    if state.analysis is not None and state.analysis.kind is AnalysisKind.EVALUATE:
        return Phase.EVALUATING
    if state.coaching_problem:
        return Phase.RECOVERING
    if (
        state.instruction is not None
        and state.instruction.freshness is not Freshness.CURRENT
    ):
        return Phase.RECOVERING
    if state.readiness is Readiness.READY:
        return Phase.READY
    if state.instruction is not None:
        return Phase.COACHING
    return Phase.ORIENTING


def evolve(state: State, event: Event) -> Transition:
    """Apply one event atomically and return commands for external adapters."""

    effects: list[str] = []
    next_state = replace(state, last_event=type(event).__name__)

    if isinstance(event, SetIntention):
        text = " ".join(event.text.split())
        if not text:
            return evolve(state, ClearIntention())
        history = _archive_current(state, InstructionDisposition.TASK_ENDED)
        effects.extend(_cancel_work(state))
        next_state = replace(
            next_state,
            evidence=Evidence.NEEDED,
            intention=text,
            task_generation=state.task_generation + 1,
            evidence_revision=state.evidence_revision + 1,
            instruction=None,
            instruction_history=history,
            readiness=Readiness.NOT_READY,
            readiness_evidence_revision=None,
            analysis=None,
            visual=VisualGuidance(),
            coaching_problem=None,
            needs_evaluation=False,
            replan_requested=False,
        )
        effects.append("request fresh observation after intention acceptance")

    elif isinstance(event, ClearIntention):
        history = _archive_current(state, InstructionDisposition.TASK_ENDED)
        effects.extend(_cancel_work(state))
        next_state = replace(
            next_state,
            evidence=Evidence.NEEDED,
            intention="",
            task_generation=state.task_generation + 1,
            evidence_revision=state.evidence_revision + 1,
            instruction=None,
            instruction_history=history,
            readiness=Readiness.NOT_READY,
            readiness_evidence_revision=None,
            analysis=None,
            visual=VisualGuidance(),
            coaching_problem=None,
            needs_evaluation=False,
            replan_requested=False,
        )

    elif isinstance(event, MotionObserved):
        effects.extend(_cancel_analysis(state))
        visual = state.visual
        if event.material and visual.status is not VisualStatus.IDLE:
            visual = VisualGuidance()
            effects.append("discard visual guidance tied to the older scene")
        next_state = replace(
            next_state,
            evidence=Evidence.MOVING,
            evidence_revision=state.evidence_revision + 1,
            analysis=None,
            visual=visual,
            coaching_problem=None,
            needs_evaluation=state.needs_evaluation or event.material,
        )
        # Motion alone does not revoke Readiness or replace the Instruction.

    elif isinstance(event, SettlingObserved):
        effects.extend(_cancel_analysis(state))
        next_state = replace(
            next_state,
            evidence=Evidence.SETTLING,
            evidence_revision=state.evidence_revision + 1,
            analysis=None,
            needs_evaluation=state.needs_evaluation or state.instruction is not None,
        )

    elif isinstance(event, SettledObserved):
        next_state = replace(next_state, evidence=Evidence.SETTLED)
        if _can_analyze(next_state):
            if next_state.connection is Connection.VERIFYING:
                kind = (
                    AnalysisKind.EVALUATE
                    if next_state.instruction is not None
                    else AnalysisKind.ORIENT
                )
                next_state, started = _start_analysis(next_state, kind)
                effects.append(started)
            elif next_state.instruction is None:
                kind = (
                    AnalysisKind.REPLAN
                    if next_state.replan_requested
                    else AnalysisKind.ORIENT
                )
                next_state, started = _start_analysis(next_state, kind)
                effects.append(started)
            elif next_state.needs_evaluation:
                next_state, started = _start_analysis(
                    next_state,
                    AnalysisKind.EVALUATE,
                )
                effects.append(started)

    elif isinstance(event, AnalysisCompleted):
        run = state.analysis
        if run is None or run.id != event.run_id:
            effects.append(f"ignore stale analysis result {event.run_id}")
        elif (
            run.task_generation != state.task_generation
            or run.evidence_revision != state.evidence_revision
        ):
            next_state = replace(next_state, analysis=None)
            effects.append(f"ignore obsolete analysis result {event.run_id}")
        elif event.outcome is AnalysisOutcome.HOLD:
            instruction = _with_freshness(state.instruction, Freshness.CURRENT)
            restored_readiness = (
                Readiness.READY
                if run.prior_readiness in {Readiness.READY, Readiness.UNVERIFIED}
                and instruction is not None
                and instruction.text == "Ready—take the shot."
                else run.prior_readiness
            )
            next_state = replace(
                next_state,
                connection=Connection.CONNECTED,
                instruction=instruction,
                readiness=restored_readiness,
                readiness_evidence_revision=(
                    state.evidence_revision
                    if restored_readiness is Readiness.READY
                    else state.readiness_evidence_revision
                ),
                analysis=None,
                coaching_problem=None,
                needs_evaluation=False,
                replan_requested=False,
            )
            effects.append("emit no Instruction update; identity and text stay stable")
        elif event.outcome is AnalysisOutcome.READY:
            history = state.instruction_history
            instruction = state.instruction
            sequence = state.instruction_sequence
            if (
                instruction is not None
                and instruction.text == "Ready—take the shot."
            ):
                instruction = replace(instruction, freshness=Freshness.CURRENT)
                effects.append("keep Ready Instruction identity stable")
            else:
                history = _archive_current(state, InstructionDisposition.ACHIEVED)
                sequence += 1
                instruction = Instruction(
                    id=f"instruction-{sequence}",
                    text="Ready—take the shot.",
                )
                effects.append(f"publish {instruction.id}")
            visual = state.visual
            if (
                visual.status is not VisualStatus.IDLE
                and visual.source_instruction_id != instruction.id
            ):
                visual = VisualGuidance()
                effects.append("discard visual guidance for achieved Instruction")
            next_state = replace(
                next_state,
                connection=Connection.CONNECTED,
                instruction=instruction,
                instruction_history=history,
                instruction_sequence=sequence,
                readiness=Readiness.READY,
                readiness_evidence_revision=state.evidence_revision,
                analysis=None,
                visual=visual,
                coaching_problem=None,
                needs_evaluation=False,
                replan_requested=False,
            )
        else:
            text = " ".join((event.instruction or "").split())
            if not text:
                raise ValueError("guidance outcome requires one actionable Instruction")
            if state.instruction is not None and state.instruction.text == text:
                next_state = replace(
                    next_state,
                    connection=Connection.CONNECTED,
                    instruction=replace(
                        state.instruction,
                        freshness=Freshness.CURRENT,
                    ),
                    analysis=None,
                    coaching_problem=None,
                    needs_evaluation=False,
                    replan_requested=False,
                )
                effects.append("treat identical guidance as hold; preserve Instruction identity")
                _assert_invariants(next_state)
                return Transition(next_state, tuple(effects))
            disposition = (
                InstructionDisposition.ACHIEVED
                if event.outcome is AnalysisOutcome.ADVANCE
                else InstructionDisposition.SUPERSEDED
            )
            history = _archive_current(state, disposition)
            sequence = state.instruction_sequence + 1
            instruction = Instruction(id=f"instruction-{sequence}", text=text)
            visual = state.visual
            if visual.status is not VisualStatus.IDLE:
                visual = VisualGuidance()
                effects.append("discard visual guidance for replaced Instruction")
            next_state = replace(
                next_state,
                connection=Connection.CONNECTED,
                instruction=instruction,
                instruction_history=history,
                instruction_sequence=sequence,
                readiness=Readiness.NOT_READY,
                readiness_evidence_revision=None,
                analysis=None,
                visual=visual,
                coaching_problem=None,
                needs_evaluation=False,
                replan_requested=False,
            )
            effects.append(
                f"publish {instruction.id}; close previous Instruction as {disposition.value}"
            )

    elif isinstance(event, AnalysisFailed):
        run = state.analysis
        if run is None or run.id != event.run_id:
            effects.append(f"ignore stale analysis failure {event.run_id}")
        else:
            next_state = replace(
                next_state,
                connection=Connection.CONNECTED,
                analysis=None,
                coaching_problem=event.detail,
                needs_evaluation=state.instruction is not None,
            )
            effects.append("preserve usable Instruction and expose one recovery action")

    elif isinstance(event, RejectInstruction):
        if state.instruction is None or event.instruction_id != state.instruction.id:
            effects.append("ignore duplicate or stale Instruction rejection")
        else:
            history = _archive_current(state, InstructionDisposition.REJECTED)
            effects.extend(_cancel_work(state))
            next_state = replace(
                next_state,
                instruction=None,
                instruction_history=history,
                readiness=Readiness.NOT_READY,
                readiness_evidence_revision=None,
                analysis=None,
                visual=VisualGuidance(),
                coaching_problem=None,
                needs_evaluation=False,
                replan_requested=True,
            )
            if _can_analyze(next_state) and state.evidence is Evidence.SETTLED:
                next_state, started = _start_analysis(next_state, AnalysisKind.REPLAN)
                effects.append(started)

    elif isinstance(event, InstructionBecameIrrelevant):
        if state.instruction is None or event.instruction_id != state.instruction.id:
            effects.append("ignore duplicate or stale irrelevance event")
        else:
            history = _archive_current(state, InstructionDisposition.IRRELEVANT)
            effects.extend(_cancel_work(state))
            next_state = replace(
                next_state,
                evidence=Evidence.NEEDED,
                evidence_revision=state.evidence_revision + 1,
                instruction=None,
                instruction_history=history,
                readiness=Readiness.NOT_READY,
                readiness_evidence_revision=None,
                analysis=None,
                visual=VisualGuidance(),
                coaching_problem=None,
                needs_evaluation=False,
                replan_requested=False,
            )
            effects.append("request fresh evidence for a relevant Instruction")

    elif isinstance(event, Pause):
        if state.mode is Mode.ACTIVE:
            effects.extend(_cancel_work(state))
            next_state = replace(
                next_state,
                mode=Mode.PAUSED,
                analysis=None,
                visual=VisualGuidance(),
                coaching_problem=None,
            )

    elif isinstance(event, Resume):
        if state.mode is Mode.PAUSED:
            readiness = (
                Readiness.UNVERIFIED
                if state.readiness is Readiness.READY
                else state.readiness
            )
            next_state = replace(
                next_state,
                mode=Mode.ACTIVE,
                evidence=Evidence.NEEDED,
                evidence_revision=state.evidence_revision + 1,
                instruction=_with_freshness(
                    state.instruction,
                    Freshness.UNVERIFIED,
                ),
                readiness=readiness,
                analysis=None,
                needs_evaluation=state.instruction is not None,
            )
            effects.append("request fresh observation before coaching resumes")

    elif isinstance(event, Disconnect):
        effects.extend(_cancel_work(state))
        readiness = (
            Readiness.UNVERIFIED
            if state.readiness is Readiness.READY
            else state.readiness
        )
        next_state = replace(
            next_state,
            connection=Connection.DISCONNECTED,
            evidence=Evidence.NEEDED,
            evidence_revision=state.evidence_revision + 1,
            instruction=_with_freshness(
                state.instruction,
                Freshness.MAY_BE_OUTDATED,
            ),
            readiness=readiness,
            analysis=None,
            visual=VisualGuidance(),
            coaching_problem="Connection lost. Keep using the camera; guidance may be outdated.",
            needs_evaluation=state.instruction is not None,
        )

    elif isinstance(event, Reconnect):
        if state.connection is not Connection.DISCONNECTED:
            effects.append("ignore reconnect while already connected")
        elif event.continuity_trusted:
            next_state = replace(
                next_state,
                connection=Connection.VERIFYING,
                evidence=Evidence.NEEDED,
                evidence_revision=state.evidence_revision + 1,
                instruction=_with_freshness(
                    state.instruction,
                    Freshness.UNVERIFIED,
                ),
                analysis=None,
                coaching_problem=None,
                needs_evaluation=state.instruction is not None,
            )
            effects.append("request fresh evidence to revalidate retained state")
        else:
            history = _archive_current(state, InstructionDisposition.TASK_ENDED)
            next_state = replace(
                next_state,
                connection=Connection.CONNECTED,
                evidence=Evidence.NEEDED,
                task_generation=state.task_generation + 1,
                evidence_revision=state.evidence_revision + 1,
                instruction=None,
                instruction_history=history,
                readiness=Readiness.NOT_READY,
                readiness_evidence_revision=None,
                analysis=None,
                visual=VisualGuidance(),
                coaching_problem=None,
                needs_evaluation=False,
                replan_requested=False,
            )
            effects.append("rebuild task from repeated intention and fresh evidence")

    elif isinstance(event, UserCaptured):
        effects.extend(_cancel_analysis(state))
        next_state = replace(
            next_state,
            evidence=Evidence.NEEDED,
            evidence_revision=state.evidence_revision + 1,
            analysis=None,
            coaching_problem=None,
            needs_evaluation=state.instruction is not None,
        )
        effects.append("acknowledge capture neutrally; request fresh live evidence")
        # Capture never revokes readiness or criticizes timing.

    elif isinstance(event, OfferVisualGuidance):
        if (
            state.connection is Connection.CONNECTED
            and state.mode is Mode.ACTIVE
            and state.intention
            and state.instruction is not None
            and state.instruction.freshness is Freshness.CURRENT
            and state.visual.status is VisualStatus.IDLE
        ):
            sequence = state.visual_sequence + 1
            next_state = replace(
                next_state,
                visual_sequence=sequence,
                visual=VisualGuidance(
                    status=VisualStatus.OFFERED,
                    id=f"visual-{sequence}",
                    source_task_generation=state.task_generation,
                    source_instruction_id=state.instruction.id,
                    source_evidence_revision=state.evidence_revision,
                ),
            )
            effects.append("show Generate and Not now; do not capture yet")

    elif isinstance(event, AcceptVisualGuidance):
        if (
            _visual_matches(state, event.visual_id, VisualStatus.OFFERED)
            and _visual_source_is_current(state)
        ):
            next_state = replace(
                next_state,
                visual=replace(state.visual, status=VisualStatus.CAPTURING),
            )
            effects.append("request one high-resolution still")
        else:
            effects.append("ignore duplicate or stale Generate action")

    elif isinstance(event, VisualStillCaptured):
        if _visual_matches(state, event.visual_id, VisualStatus.CAPTURING):
            next_state = replace(
                next_state,
                visual=replace(state.visual, status=VisualStatus.GENERATING),
            )
            effects.append("start asynchronous image edit")
        else:
            effects.append("ignore stale visual still")

    elif isinstance(event, VisualGenerated):
        current_instruction_id = (
            state.instruction.id if state.instruction is not None else None
        )
        if (
            _visual_matches(state, event.visual_id, VisualStatus.GENERATING)
            and state.visual.source_task_generation == state.task_generation
            and state.visual.source_instruction_id == current_instruction_id
        ):
            next_state = replace(
                next_state,
                visual=replace(
                    state.visual,
                    status=VisualStatus.AVAILABLE,
                    label=event.label,
                ),
            )
            effects.append("publish generated image without changing coaching state")
        else:
            effects.append("discard stale generated image")

    elif isinstance(event, VisualFailed):
        if (
            event.visual_id == state.visual.id
            and state.visual.status in {VisualStatus.CAPTURING, VisualStatus.GENERATING}
        ):
            next_state = replace(
                next_state,
                visual=replace(state.visual, status=VisualStatus.FAILED),
            )
            effects.append("show visual-guidance retry; ordinary coaching continues")
        else:
            effects.append("ignore stale visual-guidance failure")

    elif isinstance(event, RetryVisualGuidance):
        if (
            _visual_matches(state, event.visual_id, VisualStatus.FAILED)
            and state.connection is Connection.CONNECTED
            and state.mode is Mode.ACTIVE
            and _visual_source_is_current(state)
        ):
            next_state = replace(
                next_state,
                visual=replace(state.visual, status=VisualStatus.CAPTURING),
            )
            effects.append("retry with one new high-resolution still")
        else:
            effects.append("ignore stale visual-guidance retry")

    elif isinstance(event, CancelVisualGuidance):
        if event.visual_id == state.visual.id and state.visual.status is not VisualStatus.IDLE:
            next_state = replace(next_state, visual=VisualGuidance())
            effects.append("cancel or discard visual-guidance work")
        else:
            effects.append("ignore duplicate or stale visual cancellation")

    _assert_invariants(next_state)
    return Transition(next_state, tuple(effects))


def presentation(state: State) -> dict[str, str | None]:
    """Derive visible text so Activity cannot contradict authoritative facts."""

    current_phase = phase(state)
    if state.connection is Connection.DISCONNECTED:
        activity = "Connection lost—guidance may be outdated."
    elif state.mode is Mode.PAUSED:
        activity = "Coaching paused."
    elif state.coaching_problem:
        activity = state.coaching_problem
    elif current_phase is Phase.NEEDS_INTENTION:
        activity = "Describe the shot you want."
    elif state.analysis is not None:
        activity = {
            AnalysisKind.ORIENT: "Looking at the scene…",
            AnalysisKind.EVALUATE: "Checking your adjustment—hold still.",
            AnalysisKind.REPLAN: "Finding another suggestion…",
        }[state.analysis.kind]
    elif current_phase in {Phase.ORIENTING, Phase.RECOVERING}:
        activity = "Waiting for a fresh settled view…"
    else:
        activity = None

    visual_activity = {
        VisualStatus.IDLE: None,
        VisualStatus.OFFERED: "Visual guidance available—Generate or Not now.",
        VisualStatus.CAPTURING: "Capturing a still for visual guidance…",
        VisualStatus.GENERATING: "Generating an edited illustration…",
        VisualStatus.AVAILABLE: state.visual.label,
        VisualStatus.FAILED: "Visual guidance failed—Retry or dismiss.",
    }[state.visual.status]

    instruction_treatment = None
    if state.instruction is not None:
        instruction_treatment = (
            "secondary"
            if current_phase in {Phase.EVALUATING, Phase.ORIENTING, Phase.RECOVERING}
            else "inactive"
            if current_phase is Phase.PAUSED
            else "primary"
        )

    return {
        "phase": current_phase.value,
        "instruction": state.instruction.text if state.instruction else None,
        "instruction_treatment": instruction_treatment,
        "coaching_activity": activity,
        "visual_activity": visual_activity,
    }


def _can_analyze(state: State) -> bool:
    return (
        state.connection is not Connection.DISCONNECTED
        and state.mode is Mode.ACTIVE
        and bool(state.intention)
        and state.analysis is None
    )


def _start_analysis(state: State, kind: AnalysisKind) -> tuple[State, str]:
    sequence = state.analysis_sequence + 1
    run = AnalysisRun(
        id=f"analysis-{sequence}",
        kind=kind,
        task_generation=state.task_generation,
        evidence_revision=state.evidence_revision,
        prior_readiness=state.readiness,
    )
    return (
        replace(
            state,
            analysis=run,
            analysis_sequence=sequence,
            coaching_problem=None,
        ),
        f"start {kind.value} as {run.id}",
    )


def _archive_current(
    state: State,
    disposition: InstructionDisposition,
) -> tuple[InstructionRecord, ...]:
    if state.instruction is None:
        return state.instruction_history
    record = InstructionRecord(
        id=state.instruction.id,
        text=state.instruction.text,
        disposition=disposition,
    )
    return (*state.instruction_history, record)


def _with_freshness(
    instruction: Instruction | None,
    freshness: Freshness,
) -> Instruction | None:
    return replace(instruction, freshness=freshness) if instruction else None


def _visual_matches(
    state: State,
    visual_id: str | None,
    expected: VisualStatus,
) -> bool:
    return state.visual.id == visual_id and state.visual.status is expected


def _visual_source_is_current(state: State) -> bool:
    instruction_id = state.instruction.id if state.instruction is not None else None
    return (
        state.visual.source_task_generation == state.task_generation
        and state.visual.source_instruction_id == instruction_id
    )


def _cancel_analysis(state: State) -> list[str]:
    return [f"cancel/discard {state.analysis.id}"] if state.analysis else []


def _cancel_work(state: State) -> list[str]:
    effects = _cancel_analysis(state)
    if state.visual.status in {VisualStatus.CAPTURING, VisualStatus.GENERATING}:
        effects.append(f"cancel/discard {state.visual.id}")
    return effects


def _assert_invariants(state: State) -> None:
    if state.analysis is not None:
        if state.connection is Connection.DISCONNECTED:
            raise AssertionError("analysis cannot run while disconnected")
        if state.mode is Mode.PAUSED or not state.intention:
            raise AssertionError("analysis requires an active task")
    if phase(state) is Phase.EVALUATING:
        if state.analysis is None or state.analysis.kind is not AnalysisKind.EVALUATE:
            raise AssertionError("Evaluating means one current evaluation is running")
        if state.instruction is None:
            raise AssertionError("Evaluating retains the Instruction")
    if state.readiness is Readiness.READY:
        if state.instruction is None or state.instruction.text != "Ready—take the shot.":
            raise AssertionError("Ready owns one stable take-the-shot Instruction")
        if state.readiness_evidence_revision is None:
            raise AssertionError("Ready requires accepted supporting evidence")
    if state.mode is Mode.PAUSED and state.analysis is not None:
        raise AssertionError("paused coaching has no analysis")
    if state.visual.status is not VisualStatus.IDLE:
        if not state.visual.id or state.visual.source_task_generation is None:
            raise AssertionError("non-idle visual guidance has explicit identity")
    if state.visual.status in {VisualStatus.CAPTURING, VisualStatus.GENERATING}:
        if state.connection is not Connection.CONNECTED or state.mode is Mode.PAUSED:
            raise AssertionError("visual work cannot continue offline or paused")
