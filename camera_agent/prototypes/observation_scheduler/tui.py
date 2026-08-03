"""PROTOTYPE — terminal driver for the observation scheduler reducer."""

from __future__ import annotations

from dataclasses import replace

from .model import (
    Action,
    Completion,
    CompletionOutcome,
    State,
    reduce,
)

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"
CLEAR = "\x1b[2J\x1b[H"

KEYS = {
    "t": Action.TICK,
    "qf": Action.QUIET_FRAME,
    "m": Action.MATERIAL_FRAME,
    "c": Action.HARD_CAMERA_CHANGE,
    "p": Action.PROBE_CHANGE,
    "i": Action.NEW_INTENTION,
    "r": Action.EXPLICIT_REPLAN,
}


def _request(value) -> str:
    if value is None:
        return "—"
    return (
        f"{value.purpose.value}/{value.trigger.value} "
        f"P{value.priority} E{value.evidence_id} O{value.source_observation_id}"
    )


def _run(value) -> str:
    if value is None:
        return "—"
    return f"Run {value.run_id}: {_request(value.request)}"


def render(state: State) -> None:
    print(CLEAR, end="")
    print(f"{BOLD}PROTOTYPE — observation gating + VLM scheduling{RESET}")
    print(f"{DIM}Demo ticks are qualitative; numerical budgets remain measurement-driven.{RESET}\n")

    instruction = "—"
    if state.instruction_id is not None:
        instruction = (
            f"{state.instruction_id} @ strategy {state.instruction_strategy_revision}, "
            f"{state.instruction_freshness.value}, Ready={state.ready}"
        )
    rows = (
        ("clock", state.tick),
        ("task / strategy", f"{state.task_epoch} / {state.strategy_revision}"),
        ("Instruction", instruction),
        ("recovery", state.recovery or "—"),
        ("latest Observation", state.latest_observation_id),
        ("camera context", state.camera_context),
        (
            "evidence",
            f"{state.evidence_status.value} "
            f"E{state.evidence_id or '—'} from O{state.evidence_source_observation_id or '—'} "
            f"(quiet streak {state.quiet_streak})",
        ),
        ("material pending", state.material_trigger.value if state.material_trigger else "no"),
        ("heartbeat", f"tier {state.heartbeat_tier}, due {state.heartbeat_due or '—'}"),
        ("pending latest-only", _request(state.pending)),
        ("authoritative", _run(state.active)),
        (
            "physical orphans",
            ", ".join(f"Run {run.run_id}" for run in state.orphans) or "—",
        ),
    )
    for name, value in rows:
        print(f"{BOLD}{name:20}{RESET} {value}")

    print(f"\n{BOLD}Last transition effects{RESET}")
    for effect in state.effects or ("No effect.",):
        print(f"  • {effect}")

    print(f"\n{BOLD}Drive adversarial paths{RESET}")
    print(f"  {BOLD}m{RESET}  material preview/metadata delta    {BOLD}c{RESET}  hard camera change")
    print(f"  {BOLD}p{RESET}  optional cheap probe changes        {BOLD}qf{RESET} quiet/equivalent frame")
    print(f"  {BOLD}t{RESET}  tick heartbeat clock                {BOLD}i{RESET}  new intention")
    print(f"  {BOLD}r{RESET}  explicit replan                     {BOLD}h{RESET}  current run returns hold")
    print(f"  {BOLD}u{RESET}  current run returns new Instruction {BOLD}y{RESET}  current run returns Ready")
    print(f"  {BOLD}f{RESET}  current run fails                   {BOLD}l{RESET}  oldest orphan returns late")
    print(f"  {BOLD}x{RESET}  exit")
    print(
        f"\n{DIM}Try: m, qf (settle/start), c (cancel), qf (replacement), "
        "c, qf (cap/coalesce), l (dispatch latest).{RESET}"
    )


def _completion(state: State, key: str) -> Completion | None:
    if key == "l":
        if not state.orphans:
            return None
        return Completion(state.orphans[0].run_id, CompletionOutcome.HOLD)
    if state.active is None:
        return None
    outcome = {
        "h": CompletionOutcome.HOLD,
        "u": CompletionOutcome.REVISE,
        "y": CompletionOutcome.READY,
        "f": CompletionOutcome.FAILED,
    }.get(key)
    return Completion(state.active.run_id, outcome) if outcome is not None else None


def main() -> None:
    state = State()
    while True:
        render(state)
        key = input("\nAction> ").strip().lower()
        if key in {"x", "exit", "quit"}:
            return
        event = KEYS.get(key) or _completion(state, key)
        if event is None:
            state = replace(state, effects=(f"Action {key!r} is unavailable in this state.",))
            continue
        state = reduce(state, event).state


if __name__ == "__main__":
    main()
