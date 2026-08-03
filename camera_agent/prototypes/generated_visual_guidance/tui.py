"""Interactive shell for the Generated Visual Guidance policy prototype."""

from __future__ import annotations

import os

from .model import (
    AcceptOffer,
    AnotherExample,
    CancelJob,
    DeclineOffer,
    DismissImage,
    FailureStage,
    GenerationCompleted,
    JobFailed,
    MotionObserved,
    Progress,
    ProgressEvaluated,
    ReplaceInstruction,
    RetryJob,
    SettledObserved,
    StillCaptured,
    UserAskedForVisual,
    VisualStatus,
    evolve,
    initial_state,
    presentation,
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"

ALTERNATIVES = (
    "Subject: angle your near shoulder a little toward the camera.",
    "Subject: rotate your torso slightly while keeping your face toward the lens.",
)


def main() -> None:
    state = initial_state()
    effects: tuple[str, ...] = ()
    alternative_index = 0
    last_visual_id: str | None = None
    last_capture_request_id: str | None = None

    while True:
        if state.visual.id is not None:
            last_visual_id = state.visual.id
        if state.visual.capture_request_id is not None:
            last_capture_request_id = state.visual.capture_request_id
        _render(state, effects)
        raw = input(f"\n{BOLD}>{RESET} ").strip().lower()
        if raw == "q":
            return

        event = None
        if raw == "e":
            event = _progress_event(state, Progress.INSUFFICIENT)
        elif raw == "p":
            event = _progress_event(state, Progress.IMPROVING)
        elif raw == "z":
            event = _progress_event(state, Progress.ACHIEVED)
        elif raw == "b":
            event = _progress_event(state, Progress.BLOCKED)
        elif raw == "k":
            event = _progress_event(state, Progress.DEVIATING)
        elif raw == "n":
            event = ReplaceInstruction(ALTERNATIVES[alternative_index % len(ALTERNATIVES)])
            alternative_index += 1
        elif raw == "u":
            event = UserAskedForVisual()
        elif raw == "y":
            event = AcceptOffer(state.visual.id)
        elif raw == "d":
            event = DeclineOffer(state.visual.id)
        elif raw == "m":
            event = MotionObserved(material=True)
        elif raw == "v":
            event = MotionObserved(material=False)
        elif raw == "s":
            event = SettledObserved()
        elif raw == "h":
            event = StillCaptured(state.visual.id, state.visual.capture_request_id)
        elif raw == "j":
            event = StillCaptured(last_visual_id, last_capture_request_id)
        elif raw == "g":
            event = GenerationCompleted(state.visual.id)
        elif raw == "f":
            stage = (
                FailureStage.EDIT
                if state.visual.status == VisualStatus.GENERATING
                else FailureStage.CAPTURE
            )
            event = JobFailed(state.visual.id, stage)
        elif raw == "r":
            event = RetryJob(state.visual.id)
        elif raw == "c":
            event = CancelJob(state.visual.id)
        elif raw == "x":
            event = DismissImage(state.visual.id)
        elif raw == "a":
            event = AnotherExample(state.visual.id)
        elif raw == "l":
            event = GenerationCompleted(last_visual_id)
        else:
            effects = (f"Unknown command: {raw!r}",)
            continue

        transition = evolve(state, event)
        state = transition.state
        effects = transition.effects


def _render(state, effects: tuple[str, ...]) -> None:
    os.system("clear" if os.name != "nt" else "cls")
    visible = presentation(state)
    visual = state.visual

    print(f"{BOLD}PROTOTYPE — Generated Visual Guidance policy{RESET}")
    print(f"{DIM}Test offer timing, explicit consent, freshness, cancellation, and provenance.{RESET}\n")
    _field("task", state.task_id)
    _field("scene", f"revision-{state.scene_revision} ({'settled' if state.settled else 'moving'})")
    _field("evidence", f"revision-{state.evidence_revision}")
    _field("criterion", state.instruction.criterion_id)
    _field("instruction", f"{state.instruction.id}: {visible['instruction']}")
    _field("failed actions", ", ".join(state.failed_actions) or "—")
    _field("no-progress streak", str(state.no_progress_streak))
    _field("visual job", f"{visual.id or '—'} ({visual.status.value})")
    _field("offer", visible["offer"] or "—")
    _field("visual activity", visible["activity"] or "—")
    _field("demonstrates", visible["demonstrates"] or "—")
    _field("provenance", visible["provenance"] or "—")
    _field("suppressed offers", str(len(state.suppressed_offer_keys)))
    _field("recovery since offer", "yes" if state.improved_since_offer else "no")
    _field("last event", state.last_event)
    _field("effects", "; ".join(effects) if effects else "—")

    print(f"\n{BOLD}Coaching evidence{RESET}")
    print("[e] insufficient  [p] improving  [k] regressed  [z] achieved  [b] blocked")
    print("[n] next text action")
    print(f"\n{BOLD}Visual guidance{RESET}")
    controls = ["[u] ask for visual"]
    if visual.status == VisualStatus.OFFERED:
        controls += ["[y] Generate", "[d] Not now"]
    if visual.status in {VisualStatus.WAITING_FOR_SETTLE, VisualStatus.CAPTURING, VisualStatus.GENERATING}:
        controls += ["[c] Cancel"]
    if visual.status == VisualStatus.CAPTURING:
        controls += ["[h] still arrives", "[f] fail capture"]
    if visual.status == VisualStatus.GENERATING:
        controls += ["[g] image arrives", "[f] fail edit"]
    if visual.status == VisualStatus.FAILED:
        controls += ["[r] Retry", "[x] Dismiss"]
    if visual.status == VisualStatus.AVAILABLE:
        controls += ["[x] Dismiss", "[a] Another example"]
    print("  ".join(controls))
    print(f"\n{BOLD}Freshness / adversarial{RESET}")
    print("[v] ordinary motion  [m] material scene change  [s] settled")
    print("[j] late still  [l] late image  [q] quit")


def _progress_event(state, progress: Progress) -> ProgressEvaluated:
    return ProgressEvaluated(
        progress,
        instruction_id=state.instruction.id,
        scene_revision=state.scene_revision,
        evidence_revision=state.evidence_revision,
    )


def _field(name: str, value: str) -> None:
    print(f"{BOLD}{name:20}{RESET} {value}")


if __name__ == "__main__":
    main()
