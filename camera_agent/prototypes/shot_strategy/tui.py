"""PROTOTYPE — interactive shot-strategy progress explorer."""

from __future__ import annotations

from .model import (
    Progress,
    State,
    apply_evaluation,
    apply_local_patch,
    reject_instruction,
    request_rebuild,
    sample_state,
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def main() -> None:
    state = sample_state()
    while True:
        _render(state)
        command = input("\n> ").strip().lower()
        if command == "q":
            return
        if command == "0":
            state = sample_state()
        elif command in {"i", "p", "a", "b"}:
            state = _update_active(state, {
                "i": Progress.INSUFFICIENT,
                "p": Progress.IMPROVING,
                "a": Progress.ACHIEVED,
                "b": Progress.BLOCKED,
            }[command])
        elif command == "d":
            state = _deviate_achieved_or_active(state)
        elif command == "r":
            state = reject_instruction(state)
        elif command == "l":
            state = apply_local_patch(state)
        elif command == "m":
            state = request_rebuild(state)


def _current_updates(state: State) -> dict[str, tuple[Progress, float, str]]:
    updates: dict[str, tuple[Progress, float, str]] = {}
    for criterion in state.criteria:
        item = state.evidence[criterion.key]
        progress = item.progress
        if progress in {Progress.UNASSESSED, Progress.BLOCKED}:
            progress = Progress.INSUFFICIENT
        updates[criterion.key] = (progress, max(item.confidence, 0.82), item.note or "carried into current assessment")
    return updates


def _update_active(state: State, progress: Progress) -> State:
    if state.instruction is None or state.instruction.criterion_key == "ready":
        return state
    updates = _current_updates(state)
    note = {
        Progress.INSUFFICIENT: "no meaningful directional change",
        Progress.IMPROVING: "moving in the requested direction",
        Progress.ACHIEVED: "criterion is plausibly satisfied",
        Progress.BLOCKED: "current action is infeasible or cannot be judged",
    }[progress]
    updates[state.instruction.criterion_key] = (progress, 0.90, note)
    return apply_evaluation(state, updates)


def _deviate_achieved_or_active(state: State) -> State:
    updates = _current_updates(state)
    target = next(
        (
            criterion
            for criterion in state.criteria
            if criterion.must_have and state.evidence[criterion.key].progress == Progress.ACHIEVED
        ),
        None,
    )
    if target is None and state.instruction is not None:
        target = next(
            criterion for criterion in state.criteria
            if criterion.key == state.instruction.criterion_key
        )
    if target is None:
        return state
    updates[target.key] = (Progress.DEVIATING, 0.91, "moved materially away from the criterion")
    return apply_evaluation(state, updates)


def _render(state: State) -> None:
    print("\033[2J\033[H", end="")
    print(f"{BOLD}PROTOTYPE — Shot Strategy / Progress Decision{RESET}")
    print(f"{DIM}Whole-shot evidence updates; one persistent Instruction; local patch before rebuild.{RESET}\n")
    print(f"{BOLD}strategy revision{RESET}: {state.strategy_revision}")
    print(f"{BOLD}evidence identity{RESET}: {state.evidence_id}")
    print(f"{BOLD}overall progress{RESET}: {state.overall_progress.value}")
    print(f"{BOLD}decision{RESET}: {state.last_decision.value}")
    print(f"{BOLD}activity{RESET}: {state.activity}")
    print(f"{BOLD}pending patch{RESET}: {state.pending_patch_for or '—'}")
    instruction = state.instruction
    print(
        f"{BOLD}Instruction{RESET}: "
        + (f"I-{instruction.identity} [{instruction.criterion_key}] {instruction.text}" if instruction else "—")
    )
    print(f"\n{BOLD}Criteria (all must-haves are reassessed on each evidence identity){RESET}")
    for criterion in state.criteria:
        item = state.evidence[criterion.key]
        marker = "MUST" if criterion.must_have else "nice"
        print(
            f"  {criterion.priority:02d} {marker:4} {criterion.key:10} "
            f"{item.progress.value:12} conf={item.confidence:.2f} "
            f"evidence={item.evidence_id or '—'} action={item.action_index + 1}/{len(criterion.actions)}"
        )
        print(f"     {DIM}{criterion.label}; {item.note or 'not assessed'}{RESET}")

    print(f"\n{BOLD}Actions{RESET}")
    print("  [i] insufficient   [p] improving   [a] achieved   [d] deviating")
    print("  [b] blocked        [r] reject action [l] apply local patch")
    print("  [m] broad scene discontinuity (rebuild)   [0] reset   [q] quit")


if __name__ == "__main__":
    main()
