"""Interactive wire-trace player for the protocol-v2 decision prototype."""

from __future__ import annotations

import json
import os

from .model import PhoneProjection, load_validators, short, validate_message
from .scenarios import SCENARIOS, Frame

BOLD = "\x1b[1m"
DIM = "\x1b[2m"
RESET = "\x1b[0m"


def main() -> None:
    validators = load_validators()
    for _, frames in SCENARIOS.values():
        for frame in frames:
            validate_message(frame.message, validators)

    while True:
        key = _menu()
        if key in {"q", "quit", "exit"}:
            return
        if key not in SCENARIOS:
            continue
        _play(key, validators)


def _menu() -> str:
    _clear()
    print(f"{BOLD}PROTOTYPE — protocol-v2 interaction extension{RESET}")
    print(f"{DIM}Every bundled trace is schema-valid. Choose a wire flow to inspect.{RESET}\n")
    for key, (name, frames) in SCENARIOS.items():
        print(f"  {BOLD}{key}{RESET}  {name} ({len(frames)} frames)")
    print(f"  {BOLD}q{RESET}  quit")
    return input("\nScenario> ").strip().lower()


def _play(key: str, validators) -> None:
    name, frames = SCENARIOS[key]
    projection = PhoneProjection()
    index = 0
    last_frame: Frame | None = None
    effect = "Press Enter to send the first frame."

    while True:
        _render(name, index, len(frames), projection, last_frame, effect)
        command = input("\n[Enter] next  [a] run all  [r] restart  [m] menu  [q] quit > ").strip().lower()
        if command == "q":
            raise SystemExit(0)
        if command == "m":
            return
        if command == "r":
            projection = PhoneProjection()
            index = 0
            last_frame = None
            effect = "Trace restarted."
            continue
        if command == "a":
            while index < len(frames):
                last_frame = frames[index]
                validity = validate_message(last_frame.message, validators)
                effect = f"{validity}; {projection.apply(last_frame.direction, last_frame.message)}"
                index += 1
            continue
        if index >= len(frames):
            effect = "Trace complete. Restart it or return to the menu."
            continue
        last_frame = frames[index]
        validity = validate_message(last_frame.message, validators)
        effect = f"{validity}; {projection.apply(last_frame.direction, last_frame.message)}"
        index += 1


def _render(
    name: str,
    index: int,
    total: int,
    projection: PhoneProjection,
    frame: Frame | None,
    effect: str,
) -> None:
    _clear()
    snapshot = projection.snapshot or {}
    instruction = snapshot.get("instruction") or {}
    activity = snapshot.get("activity") or {}
    visual = snapshot.get("visualGuidance") or {}
    visual_activity = visual.get("activity") or {}
    overlays = snapshot.get("overlays") or {}
    actions = list(projection.current_actions.values())

    print(f"{BOLD}PROTOTYPE — {name}{RESET}")
    print(f"{DIM}Frame {index}/{total}; full snapshots replace every rendering lane atomically.{RESET}\n")
    _field("wire mode", "v2" if projection.negotiated_v2 else "v1 / negotiating")
    _field("connection", str(projection.connection_number or "—"))
    _field("session / revision", f"{short(projection.session_id)} / {projection.revision}")
    _field("latest observation", str(projection.latest_observation_id or "—"))
    _field("accepted intention", snapshot.get("acceptedIntention") or "—")
    _field("phase", snapshot.get("phase") or "—")
    _field(
        "Instruction",
        (
            f"{short(instruction.get('instructionId'))} [{instruction.get('freshness')}] "
            f"{instruction.get('text')}"
            if instruction
            else "—"
        ),
    )
    _field("coaching Activity", activity.get("text") or "—")
    _field(
        "overlays",
        (
            f"visible: {len(overlays.get('items', []))} from O{overlays.get('sourceObservationId')}"
            if overlays and projection.overlay_visible
            else f"suppressed: {projection.overlay_suppression}"
            if overlays
            else "—"
        ),
    )
    _field(
        "available actions",
        ", ".join(f"{item['kind']}:{short(item['actionId'])}" for item in actions) or "—",
    )
    _field(
        "visual lane",
        f"{visual.get('kind')} {visual.get('status')} {short(visual.get('visualId'))}" if visual else "—",
    )
    _field("visual Activity", visual_activity.get("text") or "—")
    _field("visual bytes", "received" if projection.visual_image_received else "—")
    _field("action acknowledgement", projection.action_result or "—")
    _field("legacy result text", projection.legacy_text or "—")
    _field("last admission", effect)

    if frame is None:
        return
    payload_kind = "binary header + bytes" if frame.binary else "text JSON"
    print(f"\n{BOLD}Last wire frame — {frame.direction} ({payload_kind}){RESET}")
    print(f"{DIM}{frame.note}{RESET}")
    print(json.dumps(frame.message, indent=2, ensure_ascii=False))


def _field(name: str, value: str) -> None:
    print(f"{BOLD}{name:23}{RESET} {value}")


def _clear() -> None:
    os.system("clear" if os.name != "nt" else "cls")


if __name__ == "__main__":
    main()
