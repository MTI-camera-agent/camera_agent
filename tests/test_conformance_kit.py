"""Executable self-check for the HelloCamera phone-client conformance kit.

This module is the executable part of the conformance kit in
``docs/conformance/``. It does three things:

1. it re-computes the SHA-256 of both normative schemas and asserts they match the
   hashes pinned in ``docs/conformance/SCHEMA_HASHES.json`` (so editing a schema
   without re-freezing it fails the kit);
2. it loads every golden conversation in ``docs/conformance/golden/`` and, for each,
   validates every wire object against the pinned schema and runs the named
   semantic checker, asserting that valid conversations are admitted and invalid
   conversations are rejected exactly as documented; and
3. it asserts the normative handoff document captures the matrices, the
   phone-local disconnect projection, overlay suppression, image admission, the
   exact provenance label, the always-available shutter, and one evidence row per
   phone-owned W01–W14 assertion.

The kit introduces no phone source code and no protocol behavior beyond the
approved v2 contracts. It exercises only the already-landed public schema and
wire-contract seam; the dormant v2 runtime path stays off the production
composition root.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from tests.conformance_semantics import (
    PROVENANCE_LABEL,
    ConformanceError,
    _payload_bytes,
    admit_visual_guidance_bytes,
    check_action_message_id_reuse,
    check_action_session,
    check_action_target,
    check_capability_acceptance,
    check_instruction_immutability,
    check_negotiation_order,
    check_phase_lane_matrix,
    check_state_admission,
    validate_wire_object,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
CONFORMANCE_DIR = REPO_ROOT / "docs" / "conformance"
GOLDEN_DIR = CONFORMANCE_DIR / "golden"
HASHES_PATH = CONFORMANCE_DIR / "SCHEMA_HASHES.json"
KIT_DOC_PATH = CONFORMANCE_DIR / "PHONE_CLIENT_CONFORMANCE_KIT.md"
V1_SCHEMA_PATH = REPO_ROOT / "docs" / "protocol-v1.schema.json"
V2_SCHEMA_PATH = REPO_ROOT / "docs" / "protocol-v2.schema.json"

REQUIRED_AREAS = {
    "negotiation",
    "state-replacement",
    "actions",
    "reconnect",
    "generated-image",
}

# W01–W14 are all phone-owned protocol assertions (CAMERA_AGENT_V2_EVALUATION.md §5.6).
PHONE_OWNED_ASSERTIONS = [f"W{n:02d}" for n in range(1, 15)]


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _golden_files() -> list[Path]:
    return sorted(GOLDEN_DIR.rglob("*.json"))


def _conversations() -> list[tuple[Path, dict]]:
    return [(path, _load_json(path)) for path in _golden_files()]


def _step_message(step: dict) -> dict | None:
    """The wire object carried by a text or binary step, or None for event steps."""
    if step.get("frame") == "text":
        return step.get("message")
    if step.get("frame") == "binary":
        return step.get("header")
    return None


def _wire_steps(conv: dict) -> list[dict]:
    return [step for step in conv["steps"] if step.get("frame") in ("text", "binary")]


def _accept(conv: dict) -> dict | None:
    for step in conv["steps"]:
        message = step.get("message") or {}
        if message.get("type") == "protocol_v2_accept":
            return message
    return None


def _accepted_session(conv: dict) -> str | None:
    accept = _accept(conv)
    return accept.get("sessionId") if accept else None


def _prior_coaching_states(conv: dict, before_step: int) -> list[dict]:
    states = []
    for step in conv["steps"]:
        if step.get("n", 0) >= before_step:
            break
        message = step.get("message") or {}
        if message.get("type") == "coaching_state_v2":
            states.append(message)
    return states


def _most_recent_artifact_reference(conv: dict, before_step: int) -> dict | None:
    """The current artifact reference the phone holds just before ``before_step``."""
    reference = None
    for step in conv["steps"]:
        if step.get("n", 0) >= before_step:
            break
        message = step.get("message") or {}
        if message.get("type") != "coaching_state_v2":
            continue
        visual = message.get("visualGuidance")
        if visual is None:
            reference = None  # a later state cleared the visual lane
            continue
        artifact = visual.get("artifact")
        if artifact is None:
            continue
        reference = {
            "sessionId": message.get("sessionId"),
            "visualJobId": visual.get("visualId"),
            "imageMessageId": artifact.get("imageMessageId"),
            "announcedAtStateRevision": artifact.get("announcedAtStateRevision"),
        }
    return reference


def _run_rejection_checker(conv: dict) -> None:
    """Invoke the named semantic checker and assert it raises for the invalid step."""
    rejection = conv["rejection"]
    name = rejection["checker"]
    at = rejection["at"]
    steps = conv["steps"]
    step = next(step for step in steps if step.get("n") == at)

    if name == "check_negotiation_order":
        check_negotiation_order(steps)
    elif name == "check_capability_acceptance":
        offer = next(
            (
                s.get("message")
                for s in steps
                if (s.get("message") or {}).get("type") == "protocol_v2_offer"
            ),
            {},
        )
        hello = next(
            (
                s.get("message")
                for s in steps
                if (s.get("message") or {}).get("type") == "hello"
            ),
            {},
        )
        check_capability_acceptance(
            step["message"], offer, hello.get("capabilities", [])
        )
    elif name == "check_phase_lane_matrix":
        check_phase_lane_matrix(step["message"])
    elif name == "check_instruction_immutability":
        prior_states = _prior_coaching_states(conv, at)
        prev_instruction = None
        for state in reversed(prior_states):
            if state.get("instruction") is not None:
                prev_instruction = state["instruction"]
                break
        check_instruction_immutability(prev_instruction, step["message"]["instruction"])
    elif name == "check_state_admission":
        accepted_session = _accepted_session(conv) or ""
        last_revision = 0
        for state in _prior_coaching_states(conv, at):
            last_revision = max(last_revision, int(state.get("stateRevision", 0)))
        check_state_admission(
            step["message"],
            accepted_session=accepted_session,
            last_revision=last_revision,
        )
    elif name == "check_action_session":
        accepted_session = _accepted_session(conv) or ""
        check_action_session(step["message"], accepted_session)
    elif name == "check_action_message_id_reuse":
        user_action_steps = [
            s for s in steps if (s.get("message") or {}).get("type") == "user_action_v2"
        ]
        check_action_message_id_reuse(user_action_steps)
    elif name == "admit_visual_guidance_bytes":
        header = step["header"]
        payload = _payload_bytes(step.get("payload", {}))
        reference = _most_recent_artifact_reference(conv, at)
        admit_visual_guidance_bytes(header, payload, current_reference=reference)
    else:
        raise ConformanceError(f"unknown rejection checker {name!r}")


def _assert_valid_conversation_passes(conv: dict) -> None:
    """Every wire object is schema-valid; matrices hold; admits succeed."""
    steps = conv["steps"]

    # 1. Every text message and binary header is schema-valid.
    for step in _wire_steps(conv):
        message = _step_message(step)
        assert message is not None, (
            f"{conv['id']}: step {step.get('n')} has no wire object"
        )
        validate_wire_object(message)

    # 2. Negotiation order and capability acceptance hold when all three are present.
    types = {(step.get("message") or {}).get("type") for step in steps}
    if {"hello", "protocol_v2_offer", "protocol_v2_accept"} <= types:
        check_negotiation_order(steps)  # must not raise
        offer = next(
            s["message"]
            for s in steps
            if s["message"].get("type") == "protocol_v2_offer"
        )
        accept = next(
            s["message"]
            for s in steps
            if s["message"].get("type") == "protocol_v2_accept"
        )
        hello = next(s["message"] for s in steps if s["message"].get("type") == "hello")
        check_capability_acceptance(
            accept, offer, hello.get("capabilities", [])
        )  # must not raise

    # 3. Each committed coaching_state_v2 obeys the phase/lane matrix, has strictly
    #    increasing revisions, matches the accepted session, and exposes only
    #    action-kind/target combinations the §7 matrix permits.
    accepted_session = _accepted_session(conv)
    last_revision = 0
    for step in steps:
        message = step.get("message") or {}
        if message.get("type") != "coaching_state_v2":
            continue
        check_phase_lane_matrix(message)  # must not raise
        if accepted_session is not None:
            check_state_admission(
                message, accepted_session=accepted_session, last_revision=last_revision
            )
        last_revision = int(message["stateRevision"])
        for action in message.get("availableActions", []):
            check_action_target(action, message)  # must not raise

    # 4. Binary steps marked admit:true must succeed against the current reference.
    for step in steps:
        if step.get("frame") == "binary" and step.get("admit"):
            header = step["header"]
            payload = _payload_bytes(step.get("payload", {}))
            reference = _most_recent_artifact_reference(conv, step["n"])
            admit_visual_guidance_bytes(header, payload, current_reference=reference)

    # 5. A phone-local disconnect projection, if present, matches §4.3.
    projection = conv.get("phoneLocalProjection")
    if projection is not None:
        _assert_disconnect_projection(projection)


def _assert_disconnect_projection(projection: dict) -> None:
    assert projection["phase"] == "recovering"
    instruction = projection["retainedInstruction"]
    assert instruction["freshness"] == "may_be_outdated", (
        "retained Instruction must render as may_be_outdated after disconnect"
    )
    assert projection["activity"]["kind"] == "recovering"
    assert projection["overlays"] == "cleared"
    assert projection["availableActions"] == "cleared"
    assert projection["visualGuidance"] == "cleared"
    assert projection["sessionIdUnchanged"] is True
    assert projection["stateRevisionUnchanged"] is True
    assert projection["cameraIntentionShutter"] == "usable"


def _assert_invalid_conversation_rejects(conv: dict) -> None:
    """The documented step is rejected; prior steps are schema-valid."""
    rejection = conv["rejection"]
    at = rejection["at"]
    kind = rejection["kind"]

    # Prior wire steps are schema-valid (the last valid projection is retained).
    for step in _wire_steps(conv):
        if step.get("n", 0) >= at:
            break
        message = _step_message(step)
        if message is not None:
            validate_wire_object(message)

    step = next(step for step in conv["steps"] if step.get("n") == at)
    if kind == "schema":
        message = _step_message(step)
        assert message is not None, (
            f"{conv['id']}: schema rejection step {at} has no wire object"
        )
        with pytest.raises(ConformanceError):
            validate_wire_object(message)
    elif kind == "semantic":
        # A semantic rejection is still schema-valid at the offending step.
        message = _step_message(step)
        if message is not None:
            validate_wire_object(message)
        with pytest.raises(ConformanceError):
            _run_rejection_checker(conv)
    else:
        raise AssertionError(f"{conv['id']}: unknown rejection kind {kind!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_schema_hashes_match_the_live_schema_files() -> None:
    """Acceptance: the kit records schema hashes that pin the live schemas."""
    hashes = _load_json(HASHES_PATH)
    recorded = {entry["name"]: entry["sha256"] for entry in hashes["schemas"]}
    assert (
        recorded["protocol-v1"]
        == hashlib.sha256(V1_SCHEMA_PATH.read_bytes()).hexdigest()
    )
    assert (
        recorded["protocol-v2"]
        == hashlib.sha256(V2_SCHEMA_PATH.read_bytes()).hexdigest()
    )
    by_path = {entry["path"]: entry["sha256"] for entry in hashes["schemas"]}
    assert by_path["docs/protocol-v1.schema.json"] == recorded["protocol-v1"]
    assert by_path["docs/protocol-v2.schema.json"] == recorded["protocol-v2"]


def test_the_kit_covers_every_required_area_with_valid_and_invalid_conversations() -> (
    None
):
    by_area: dict[str, set[bool]] = {area: set() for area in REQUIRED_AREAS}
    for _, conv in _conversations():
        by_area.setdefault(conv["area"], set()).add(conv["valid"])
    for area in REQUIRED_AREAS:
        assert by_area[area] == {True, False}, (
            f"area {area!r} must have at least one valid and one invalid golden conversation; "
            f"got validity set {by_area[area]}"
        )


_CONVERSATIONS = _conversations()


@pytest.mark.parametrize(
    "path,conv",
    _CONVERSATIONS,
    ids=[path.stem for path, _ in _CONVERSATIONS],
)
def test_each_golden_conversation_is_executable_and_self_consistent(
    path: Path, conv: dict
) -> None:
    # Structural metadata every golden conversation must carry.
    for key in (
        "id",
        "area",
        "title",
        "assertions",
        "valid",
        "summary",
        "steps",
        "outcome",
    ):
        assert key in conv, f"{path.name}: missing {key!r}"
    assert conv["area"] in REQUIRED_AREAS, f"{path.name}: unknown area {conv['area']!r}"
    assert isinstance(conv["steps"], list) and conv["steps"], (
        f"{path.name}: steps must be non-empty"
    )
    assert conv["assertions"], f"{path.name}: must reference at least one Wxx assertion"
    for assertion in conv["assertions"]:
        assert assertion in PHONE_OWNED_ASSERTIONS, (
            f"{path.name}: non-W01–W14 assertion {assertion!r}"
        )

    if conv["valid"]:
        _assert_valid_conversation_passes(conv)
    else:
        assert "rejection" in conv, (
            f"{path.name}: invalid conversation missing rejection block"
        )
        for key in ("at", "kind", "rule", "effect"):
            assert key in conv["rejection"], f"{path.name}: rejection missing {key!r}"
        _assert_invalid_conversation_rejects(conv)


def test_the_normative_document_captures_the_matrices_and_behaviors() -> None:
    """Acceptance: the kit captures the matrices, projections, and invariants."""
    text = KIT_DOC_PATH.read_text(encoding="utf-8")

    # Acceptance criterion 2: phase/lane and action-availability matrices.
    assert "Phase/lane matrix" in text
    for phase in (
        "needs_intention",
        "orienting",
        "coaching",
        "evaluating",
        "ready",
        "recovering",
        "paused",
    ):
        assert phase in text, f"phase/lane matrix must list phase {phase!r}"
    assert "Action-availability matrix" in text
    for kind in (
        "try_another_suggestion",
        "pause_coaching",
        "resume_coaching",
        "generate_visual_guidance",
        "decline_visual_guidance",
        "cancel_visual_guidance",
        "retry_visual_guidance",
        "dismiss_visual_guidance",
        "another_visual_example",
    ):
        assert kind in text, f"action-availability matrix must list kind {kind!r}"

    # Acceptance criterion 2: phone-local disconnect projection, overlay
    # suppression, image admission, exact provenance label, shutter.
    assert "Phone-local disconnect projection" in text
    assert "Overlay suppression" in text
    assert "Artifact announcement and image admission" in text
    assert PROVENANCE_LABEL in text, "the exact provenance label must appear verbatim"
    assert "Always-available shutter" in text

    # Acceptance criterion 3: one evidence row per phone-owned W01–W14.
    assert "W01–W14 evidence contract" in text
    for assertion in PHONE_OWNED_ASSERTIONS:
        # Each row begins with the assertion id in a table cell.
        assert f"| {assertion} |" in text, f"kit must define evidence for {assertion}"


def test_the_normative_document_records_the_schema_hashes_reference() -> None:
    text = KIT_DOC_PATH.read_text(encoding="utf-8")
    assert "SCHEMA_HASHES.json" in text
    assert "SHA-256" in text
