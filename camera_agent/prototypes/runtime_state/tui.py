"""Interactive shell for the throwaway runtime-state reducer prototype."""

from __future__ import annotations

import os

from .model import (
    AcceptVisualGuidance,
    AnalysisCompleted,
    AnalysisFailed,
    AnalysisOutcome,
    CancelVisualGuidance,
    Disconnect,
    InstructionBecameIrrelevant,
    MotionObserved,
    OfferVisualGuidance,
    Pause,
    Reconnect,
    RejectInstruction,
    Resume,
    RetryVisualGuidance,
    SetIntention,
    SettledObserved,
    SettlingObserved,
    UserCaptured,
    VisualFailed,
    VisualGenerated,
    VisualStillCaptured,
    VisualStatus,
    evolve,
    initial_state,
    phase,
    presentation,
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"

INTENTIONS = (
    "A confident full-body portrait at sunset",
    "Center the plant with breathing room",
    "A relaxed seated portrait",
)
GUIDANCE = (
    "Photographer: step half a pace left.",
    "Subject: turn your shoulders slightly toward the window.",
    "Photographer: lower the camera a little.",
)


def main() -> None:
    state = initial_state()
    effects: tuple[str, ...] = ()
    intention_index = 0
    guidance_index = 0
    last_analysis_id: str | None = None
    last_visual_id: str | None = None
    last_instruction_id: str | None = None

    while True:
        if state.analysis is not None:
            last_analysis_id = state.analysis.id
        if state.visual.id is not None:
            last_visual_id = state.visual.id
        if state.instruction is not None:
            last_instruction_id = state.instruction.id
        _render(state, effects)
        raw = input(f"\n{BOLD}>{RESET} ").strip().lower()
        if raw == "q":
            return

        event = None
        if raw == "i":
            event = SetIntention(INTENTIONS[intention_index % len(INTENTIONS)])
            intention_index += 1
        elif raw == "m":
            event = MotionObserved(material=True)
        elif raw == "n":
            event = SettlingObserved()
        elif raw == "s":
            event = SettledObserved()
        elif raw in {"g", "j", "h", "r", "x"}:
            if state.analysis is None:
                effects = ("No analysis is current; settle a changed/fresh view first.",)
                continue
            if raw in {"g", "j"}:
                event = AnalysisCompleted(
                    state.analysis.id,
                    (
                        AnalysisOutcome.ADVANCE
                        if raw == "j"
                        else AnalysisOutcome.GUIDANCE
                    ),
                    GUIDANCE[guidance_index % len(GUIDANCE)],
                )
                guidance_index += 1
            elif raw == "h":
                event = AnalysisCompleted(state.analysis.id, AnalysisOutcome.HOLD)
            elif raw == "r":
                event = AnalysisCompleted(state.analysis.id, AnalysisOutcome.READY)
            else:
                event = AnalysisFailed(state.analysis.id)
        elif raw == "t":
            event = RejectInstruction(
                state.instruction.id if state.instruction else None
            )
        elif raw == "e":
            event = RejectInstruction(last_instruction_id)
        elif raw == "y":
            event = InstructionBecameIrrelevant(
                state.instruction.id if state.instruction else None
            )
        elif raw == "a":
            if last_analysis_id is None:
                effects = ("No previous analysis identity exists yet.",)
                continue
            event = AnalysisCompleted(last_analysis_id, AnalysisOutcome.READY)
        elif raw == "z":
            event = VisualGenerated(last_visual_id)
        elif raw == "p":
            event = Resume() if state.mode.value == "paused" else Pause()
        elif raw == "d":
            event = Disconnect()
        elif raw == "k":
            event = Reconnect(continuity_trusted=True)
        elif raw == "b":
            event = Reconnect(continuity_trusted=False)
        elif raw == "u":
            event = UserCaptured()
        elif raw == "o":
            event = OfferVisualGuidance()
        elif raw == "v":
            event = _advance_visual(state)
        elif raw == "f":
            event = VisualFailed(state.visual.id)
        elif raw == "c":
            event = CancelVisualGuidance(state.visual.id)
        else:
            effects = (f"Unknown command: {raw!r}",)
            continue

        transition = evolve(state, event)
        state = transition.state
        effects = transition.effects


def _advance_visual(state):
    visual_id = state.visual.id
    return {
        VisualStatus.OFFERED: AcceptVisualGuidance(visual_id),
        VisualStatus.CAPTURING: VisualStillCaptured(visual_id),
        VisualStatus.GENERATING: VisualGenerated(visual_id),
        VisualStatus.FAILED: RetryVisualGuidance(visual_id),
    }.get(state.visual.status, CancelVisualGuidance(visual_id))


def _render(state, effects: tuple[str, ...]) -> None:
    os.system("clear" if os.name != "nt" else "cls")
    visible = presentation(state)
    instruction = state.instruction

    print(f"{BOLD}PROTOTYPE — Camera Agent v2 runtime reducer{RESET}")
    print(f"{DIM}Drive awkward event orders; watch identity and concurrent lanes.{RESET}\n")
    _field("mode", state.mode.value)
    _field("connection", state.connection.value)
    _field("phase (derived)", phase(state).value)
    _field("evidence", state.evidence.value)
    _field("task", f"generation-{state.task_generation}" if state.intention else "—")
    _field("intention", state.intention or "—")
    _field(
        "instruction",
        (
            f"{instruction.id} [{instruction.freshness.value}] {instruction.text}"
            if instruction
            else "—"
        ),
    )
    _field(
        "analysis",
        f"{state.analysis.id} ({state.analysis.kind.value})" if state.analysis else "—",
    )
    _field("readiness", state.readiness.value)
    _field(
        "visual",
        f"{state.visual.id or '—'} ({state.visual.status.value})",
    )
    _field("coaching activity", visible["coaching_activity"] or "—")
    _field("visual activity", visible["visual_activity"] or "—")
    _field(
        "instruction history",
        ", ".join(f"{item.id}:{item.disposition.value}" for item in state.instruction_history)
        or "—",
    )
    _field("last event", state.last_event)
    _field("effects", "; ".join(effects) if effects else "—")

    print(f"\n{BOLD}Events{RESET}")
    print("[i] intention  [m] material motion  [n] settling  [s] settled")
    print("[g] revise  [j] next milestone  [h] hold  [r] ready  [x] analysis fail")
    print("[t] reject current  [e] repeat old reject  [y] mark irrelevant")
    print("[p] pause/resume  [u] user capture  [a] inject late analysis result")
    print("[o] offer visual  [v] advance/retry  [f] fail  [c] cancel  [z] late image")
    print("[d] disconnect  [k] trusted reconnect  [b] rebuild reconnect  [q] quit")


def _field(name: str, value: str) -> None:
    print(f"{BOLD}{name:18}{RESET} {value}")


if __name__ == "__main__":
    main()
