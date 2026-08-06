"""Executable semantic checkers for the HelloCamera phone-client conformance kit.

These functions encode the **normative** phone-side wire rules from
[docs/PROTOCOL_V2.md](../docs/PROTOCOL_V2.md) and the closed v1/v2 JSON Schemas.
They are deliberately minimal: each checker mirrors one approved rule and cites
the normative section it implements. They introduce **no** protocol behavior beyond
what the approved v2 contracts already define, and they are not part of the
production composition root — they live under ``tests/`` so the conformance kit
(see ``docs/conformance/``) is self-checking and portable.

A companion iPhone implementation is expected to enforce the same rules. The
golden conversations in ``docs/conformance/golden/`` are admitted or rejected by
exactly these checkers plus the two JSON Schemas.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from jsonschema import Draft202012Validator, FormatChecker
from PIL import Image
from io import BytesIO

REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_DIR = REPO_ROOT / "docs"
V1_SCHEMA_PATH = SCHEMA_DIR / "protocol-v1.schema.json"
V2_SCHEMA_PATH = SCHEMA_DIR / "protocol-v2.schema.json"

V1_SCHEMA = json.loads(V1_SCHEMA_PATH.read_text(encoding="utf-8"))
V2_SCHEMA = json.loads(V2_SCHEMA_PATH.read_text(encoding="utf-8"))

# Wire type → schema definition name, mirroring camera_agent.protocol but kept
# local so the kit does not depend on the production package's internal map.
V1_TYPE_TO_DEF = {
    "hello": "hello",
    "observation": "observation",
    "error": "clientError",
    "result": "result",
    "capture_high_resolution": "captureHighResolution",
    "preview_image": "previewImageHeader",
    "high_resolution_image": "highResolutionImageHeader",
    "result_image": "resultImageHeader",
}
V2_TYPE_TO_DEF = {
    "protocol_v2_offer": "protocolOffer",
    "protocol_v2_accept": "protocolAccept",
    "coaching_state_v2": "coachingState",
    "user_action_v2": "userAction",
    "action_result_v2": "actionResult",
    "protocol_error_v2": "protocolError",
    "visual_guidance_image_v2": "visualGuidanceImageHeader",
}

MAX_MESSAGE_BYTES = (
    8 * 1024 * 1024
)  # PROTOCOL_V2.md §2: complete WebSocket message cap.

_FORMAT_CHECKER = FormatChecker()


class ConformanceError(ValueError):
    """A golden conversation violates a normative phone-client rule."""


def _validator_for(message: dict[str, Any]) -> Draft202012Validator:
    """Return the schema validator bound to the definition for ``message``."""
    message_type = message.get("type") if isinstance(message, dict) else None
    if message_type in V1_TYPE_TO_DEF:
        schema = V1_SCHEMA
        def_name = V1_TYPE_TO_DEF[message_type]
    elif message_type in V2_TYPE_TO_DEF:
        schema = V2_SCHEMA
        def_name = V2_TYPE_TO_DEF[message_type]
    else:
        raise ConformanceError(f"unknown or unmapped wire type: {message_type!r}")
    return Draft202012Validator(
        {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]},
        format_checker=_FORMAT_CHECKER,
    )


def validate_wire_object(message: Any) -> dict[str, Any]:
    """Validate one closed wire object against its v1 or v2 schema definition.

    Closed-object semantics (PROTOCOL.md and PROTOCOL_V2.md §2): unknown fields,
    wrong types, malformed UUIDs, missing required fields, and invalid enum
    values reject the whole object.
    """
    if not isinstance(message, dict):
        raise ConformanceError("wire object must be a JSON object")
    validator = _validator_for(message)
    errors = sorted(validator.iter_errors(message), key=lambda e: list(e.absolute_path))
    if errors:
        error = errors[0]
        location = ".".join(str(p) for p in error.absolute_path) or "<message>"
        raise ConformanceError(f"{location}: {error.message}")
    return message


def schema_of(message: dict[str, Any]) -> str:
    """Return ``"v1"`` or ``"v2"`` for a closed wire object."""
    message_type = message.get("type")
    if message_type in V1_TYPE_TO_DEF:
        return "v1"
    if message_type in V2_TYPE_TO_DEF:
        return "v2"
    raise ConformanceError(f"cannot classify schema for type {message_type!r}")


# ---------------------------------------------------------------------------
# Negotiation (PROTOCOL_V2.md §4)
# ---------------------------------------------------------------------------


def check_negotiation_order(steps: Iterable[dict[str, Any]]) -> None:
    """Exact v1 hello must precede the offer; the offer must precede acceptance.

    §4.1 phone sequence: hello → protocol_v2_offer → observations.
    §4.2 desktop: accept only after hello and offer on this connection.
    """
    order = [
        step.get("message", {}).get("type")
        for step in steps
        if step.get("frame") == "text"
    ]
    if "protocol_v2_offer" in order and "hello" in order:
        if order.index("protocol_v2_offer") < order.index("hello"):
            raise ConformanceError("protocol_v2_offer must follow the exact v1 hello")
    if "protocol_v2_accept" in order and "protocol_v2_offer" in order:
        if order.index("protocol_v2_accept") < order.index("protocol_v2_offer"):
            raise ConformanceError("protocol_v2_accept must follow protocol_v2_offer")
    if "protocol_v2_accept" in order and "hello" in order:
        if order.index("protocol_v2_accept") < order.index("hello"):
            raise ConformanceError("protocol_v2_accept must follow the v1 hello")


def check_capability_acceptance(
    accept: dict[str, Any], offer: dict[str, Any], hello_capabilities: list[str]
) -> None:
    """Acceptance validity per §4.2: subset, mandatory bundle, visual prerequisites."""
    accepted = set(accept.get("capabilities", []))
    offered = set(offer.get("capabilities", []))
    if not accepted.issubset(offered):
        raise ConformanceError(
            f"accepted capabilities {accepted - offered} were not offered {offered}"
        )
    if "camera_agent_interaction_v2" not in accepted:
        raise ConformanceError(
            "camera_agent_interaction_v2 is mandatory in every acceptance"
        )
    if "generated_visual_guidance_v2" in accepted:
        needed = {"high_resolution_request", "sample_image"}
        missing = needed - set(hello_capabilities)
        if missing:
            raise ConformanceError(
                "generated_visual_guidance_v2 requires v1 hello capabilities "
                f"{sorted(needed)}; missing {sorted(missing)}"
            )


# ---------------------------------------------------------------------------
# Complete coaching state (PROTOCOL_V2.md §6)
# ---------------------------------------------------------------------------

# Phase/lane matrix from §6.1. Each phase names the required/forbidden shape of
# the task, instruction, activity, overlays, and visualGuidance lanes.
PHASE_LANE_MATRIX: dict[str, dict[str, str]] = {
    "needs_intention": {
        "task": "null",
        "instruction": "null",
        "activity": "waiting",
        "overlays": "null",
        "visual": "null",
    },
    "orienting": {
        "task": "nonnull",
        "instruction": "null",
        "activity": "working_or_waiting",
        "overlays": "null",
        "visual": "null",
    },
    "coaching": {
        "task": "nonnull",
        "instruction": "action_not_outdated",
        "activity": "nullable",
        "overlays": "nullable",
        "visual": "nullable",
    },
    "evaluating": {
        "task": "nonnull",
        "instruction": "not_outdated_or_null",
        "activity": "working_or_waiting",
        "overlays": "nullable",
        "visual": "nullable",
    },
    "ready": {
        "task": "nonnull",
        "instruction": "ready_current_or_needs_revalidation",
        "activity": "null",
        "overlays": "null",
        "visual": "null",
    },
    "recovering": {
        "task": "nonnull",
        "instruction": "any_or_null",
        "activity": "recovering",
        "overlays": "nullable",
        "visual": "nullable",
    },
    "paused": {
        "task": "nonnull",
        "instruction": "current_or_needs_revalidation_or_null",
        "activity": "null_if_instruction_else_waiting",
        "overlays": "null",
        "visual": "null",
    },
}


def check_phase_lane_matrix(state: dict[str, Any]) -> None:
    """Reject a coaching_state_v2 whose lanes violate the §6.1 phase matrix."""
    phase = state.get("phase")
    rule = PHASE_LANE_MATRIX.get(phase)
    if rule is None:
        raise ConformanceError(f"unknown phase {phase!r}")

    task_id = state.get("taskId")
    intention = state.get("acceptedIntention")
    task_null = task_id is None and intention is None
    task_nonnull = task_id is not None and intention is not None
    if task_id is not None or intention is not None:
        if not task_nonnull:
            raise ConformanceError(
                "taskId and acceptedIntention must be both null or both non-null"
            )
    expected_task = rule["task"]
    if expected_task == "null" and not task_null:
        raise ConformanceError(f"phase {phase!r} requires both task and intention null")
    if expected_task == "nonnull" and not task_nonnull:
        raise ConformanceError(
            f"phase {phase!r} requires both task and intention non-null"
        )

    instruction = state.get("instruction")
    activity = state.get("activity")
    overlays = state.get("overlays")
    visual = state.get("visualGuidance")

    # Cross-cutting rule (§6.1): whenever instruction is null, Activity is non-null.
    if instruction is None and activity is None:
        raise ConformanceError(
            "whenever instruction is null, Activity must be non-null"
        )

    def _instruction_ok(spec: str) -> None:
        if instruction is None:
            return
        kind = instruction.get("kind")
        freshness = instruction.get("freshness")
        if spec == "action_not_outdated":
            if kind != "action":
                raise ConformanceError(
                    f"phase {phase!r} requires an actionable Instruction"
                )
            if freshness == "may_be_outdated":
                raise ConformanceError(
                    f"phase {phase!r} Instruction must not be may_be_outdated"
                )
        elif spec == "ready_current_or_needs_revalidation":
            if kind != "ready":
                raise ConformanceError(f"phase {phase!r} requires a ready Instruction")
            if freshness not in ("current", "needs_revalidation"):
                raise ConformanceError(
                    f"phase {phase!r} ready Instruction must be current or needs_revalidation"
                )
        elif spec == "current_or_needs_revalidation_or_null":
            if freshness not in ("current", "needs_revalidation"):
                raise ConformanceError(
                    f"phase {phase!r} Instruction must be current or needs_revalidation"
                )
        elif spec == "not_outdated_or_null":
            if freshness == "may_be_outdated":
                raise ConformanceError(
                    f"phase {phase!r} Instruction must not be may_be_outdated"
                )

    _instruction_ok(rule["instruction"])

    act_spec = rule["activity"]
    if act_spec == "null" and activity is not None:
        raise ConformanceError(f"phase {phase!r} requires Activity to be null")
    if act_spec == "waiting" and (
        activity is None or activity.get("kind") != "waiting"
    ):
        raise ConformanceError(f"phase {phase!r} requires waiting Activity")
    if act_spec == "working_or_waiting" and (
        activity is None or activity.get("kind") not in ("working", "waiting")
    ):
        raise ConformanceError(f"phase {phase!r} requires working or waiting Activity")
    if act_spec == "recovering" and (
        activity is None or activity.get("kind") != "recovering"
    ):
        raise ConformanceError(f"phase {phase!r} requires recovering Activity")
    if act_spec == "null_if_instruction_else_waiting":
        if instruction is not None and activity is not None:
            raise ConformanceError(
                f"phase {phase!r} with an Instruction requires Activity to be null"
            )
        if instruction is None and (
            activity is None or activity.get("kind") != "waiting"
        ):
            raise ConformanceError(
                f"phase {phase!r} without an Instruction requires waiting Activity"
            )

    if rule["overlays"] == "null" and overlays is not None:
        raise ConformanceError(f"phase {phase!r} forbids overlays")
    if rule["visual"] == "null" and visual is not None:
        raise ConformanceError(f"phase {phase!r} forbids a visual-guidance lane")


def check_instruction_immutability(
    prev_instruction: dict[str, Any] | None, next_instruction: dict[str, Any]
) -> None:
    """§6.2: for one instructionId, kind, text, and addressee are immutable."""
    if prev_instruction is None:
        return
    if prev_instruction.get("instructionId") != next_instruction.get("instructionId"):
        return  # different identity; immutability does not apply
    for field in ("kind", "text", "addressee"):
        if prev_instruction.get(field) != next_instruction.get(field):
            raise ConformanceError(
                f"Instruction {field} is immutable for one instructionId: "
                f"{prev_instruction.get(field)!r} -> {next_instruction.get(field)!r}"
            )


def check_state_admission(
    next_state: dict[str, Any],
    *,
    accepted_session: str,
    last_revision: int,
) -> None:
    """§6: a snapshot applies only when sessionId matches and revision is greater."""
    if next_state.get("sessionId") != accepted_session:
        raise ConformanceError(
            f"coaching_state_v2 sessionId {next_state.get('sessionId')!r} does not match "
            f"accepted session {accepted_session!r}"
        )
    if (
        next_state.get("stateRevision") is None
        or next_state["stateRevision"] <= last_revision
    ):
        raise ConformanceError(
            f"stateRevision {next_state.get('stateRevision')!r} must be strictly greater "
            f"than the last applied revision {last_revision}"
        )


# ---------------------------------------------------------------------------
# Explicit one-use actions (PROTOCOL_V2.md §7)
# ---------------------------------------------------------------------------

# §7 action-availability matrix: action kind → required target kind and the
# predicate on the named target's current state.
ACTION_AVAILABILITY: dict[str, dict[str, Any]] = {
    "try_another_suggestion": {
        "target": "instruction",
        "when": "current_actionable_instruction",
    },
    "pause_coaching": {"target": "task", "when": "connected_active"},
    "resume_coaching": {"target": "task", "when": "connected_paused"},
    "generate_visual_guidance": {
        "target": "visual_offer",
        "when": "visual_offer_offered",
    },
    "decline_visual_guidance": {
        "target": "visual_offer",
        "when": "visual_offer_offered",
    },
    "cancel_visual_guidance": {
        "target": "visual_job",
        "when": "job_waiting_capturing_generating",
    },
    "retry_visual_guidance": {"target": "visual_job", "when": "job_failed"},
    "dismiss_visual_guidance": {
        "target": "visual_job",
        "when": "job_failed_or_available",
    },
    "another_visual_example": {"target": "visual_job", "when": "job_available"},
}


def _visual_status(state: dict[str, Any]) -> str | None:
    visual = state.get("visualGuidance")
    if visual is None:
        return None
    return visual.get("status")


def check_action_target(action: dict[str, Any], state: dict[str, Any]) -> None:
    """§7: an action kind must be valid for its target object's current state,
    and the target ID MUST name the active matching object in the same snapshot.
    """
    kind = action.get("kind")
    target = action.get("target", {})
    rule = ACTION_AVAILABILITY.get(kind)
    if rule is None:
        raise ConformanceError(f"unknown action kind {kind!r}")
    if target.get("kind") != rule["target"]:
        raise ConformanceError(
            f"action {kind!r} requires target kind {rule['target']!r}, got {target.get('kind')!r}"
        )
    when = rule["when"]
    phase = state.get("phase")
    instruction = state.get("instruction")
    visual = state.get("visualGuidance")
    if when == "current_actionable_instruction":
        if (
            instruction is None
            or instruction.get("kind") != "action"
            or phase not in ("coaching", "evaluating", "recovering")
        ):
            raise ConformanceError(
                "try_another_suggestion requires a current actionable Instruction in an active phase"
            )
    elif when == "connected_active":
        # §6.1: needs_intention has no task and therefore no protocol actions;
        # paused exposes only resume. A valid task Pause requires a connected,
        # active task, i.e. orienting/coaching/evaluating/ready/recovering.
        if phase not in ("orienting", "coaching", "evaluating", "ready", "recovering"):
            raise ConformanceError("pause_coaching requires a connected, active task")
    elif when == "connected_paused":
        if phase != "paused":
            raise ConformanceError("resume_coaching requires a paused task")
    elif when == "visual_offer_offered":
        if (
            visual is None
            or visual.get("kind") != "offer"
            or visual.get("status") != "offered"
        ):
            raise ConformanceError(
                "generate/decline_visual_guidance require visual offer/offered"
            )
    elif when == "job_waiting_capturing_generating":
        if visual is None or visual.get("status") not in (
            "waiting_for_settle",
            "capturing",
            "generating",
        ):
            raise ConformanceError(
                "cancel_visual_guidance requires waiting/capturing/generating job"
            )
    elif when == "job_failed":
        if visual is None or visual.get("status") != "failed":
            raise ConformanceError("retry_visual_guidance requires a failed job")
    elif when == "job_failed_or_available":
        if visual is None or visual.get("status") not in ("failed", "available"):
            raise ConformanceError(
                "dismiss_visual_guidance requires a failed or available job"
            )
    elif when == "job_available":
        if visual is None or visual.get("status") != "available":
            raise ConformanceError("another_visual_example requires an available job")

    # The target ID MUST name the active matching object in the same snapshot.
    target_id = target.get("id")
    if rule["target"] == "instruction":
        if instruction is None or target_id != instruction.get("instructionId"):
            raise ConformanceError("action target must name the current Instruction")
    elif rule["target"] == "task":
        if state.get("taskId") is None or target_id != state.get("taskId"):
            raise ConformanceError("action target must name the current task")
    elif rule["target"] in ("visual_offer", "visual_job"):
        if visual is None or target_id != visual.get("visualId"):
            raise ConformanceError("action target must name the current visual object")


def check_action_session(action_msg: dict[str, Any], accepted_session: str) -> None:
    """§7: a user_action_v2 naming another session never executes."""
    if action_msg.get("sessionId") != accepted_session:
        raise ConformanceError(
            f"user_action_v2 sessionId {action_msg.get('sessionId')!r} does not match "
            f"accepted session {accepted_session!r}; never executes"
        )


def check_action_message_id_reuse(user_action_steps: list[dict[str, Any]]) -> None:
    """§7: exact replay (same messageId, identical payload) returns the cached
    disposition; reuse of a messageId with different content is a
    protocol_error_v2 invalid_message.

    ``user_action_steps`` is the list of every user_action_v2 step in one
    conversation, in order. A messageId that maps to two different actionId
    values is a contradictory reuse.
    """
    seen: dict[str, str] = {}
    for step in user_action_steps:
        message = step.get("message", {})
        message_id = message.get("messageId")
        action_id = message.get("actionId")
        if message_id is None:
            continue
        previous = seen.get(message_id)
        if previous is None:
            seen[message_id] = action_id
        elif previous != action_id:
            raise ConformanceError(
                f"user_action_v2 messageId {message_id!r} reused with different "
                f"actionId content ({previous!r} -> {action_id!r}); "
                "protocol_error_v2 invalid_message"
            )


# ---------------------------------------------------------------------------
# Generated-image admission (PROTOCOL_V2.md §8.2)
# ---------------------------------------------------------------------------

PROVENANCE_LABEL = (
    "Edited illustration based on an earlier still — not the live preview."
)


def _payload_bytes(spec: dict[str, Any]) -> bytes:
    """Materialize a payload described by a golden binary step for admission tests."""
    kind = spec.get("kind", "png")
    width = int(spec.get("width", 8))
    height = int(spec.get("height", 8))
    if kind == "corrupt":
        return b"\x00\x01\x02not a real image"
    if kind == "empty":
        return b""
    if kind == "jpeg":
        buf = BytesIO()
        Image.new("RGB", (width, height), (120, 80, 60)).save(buf, format="JPEG")
        return buf.getvalue()
    # default png
    buf = BytesIO()
    Image.new("RGB", (width, height), (120, 80, 60)).save(buf, format="PNG")
    return buf.getvalue()


def admit_visual_guidance_bytes(
    header: dict[str, Any], payload: bytes, *, current_reference: dict[str, Any] | None
) -> None:
    """§8.2 phone-side byte admission.

    Bytes are accepted only while the current state references the exact session,
    visual job, image identity, and first-announcement revision. The phone decodes
    the payload, verifies media matches ``mimeType``, verifies decoded width/height
    exactly match the header, and enforces the 8 MiB message cap.
    """
    if current_reference is None:
        raise ConformanceError(
            "late bytes: no current artifact reference; harmless discard"
        )
    ref = current_reference
    if header.get("sessionId") != ref.get("sessionId"):
        raise ConformanceError(
            "visual_guidance_image_v2 sessionId does not match current reference"
        )
    if header.get("visualJobId") != ref.get("visualJobId"):
        raise ConformanceError(
            "visual_guidance_image_v2 visualJobId does not match current reference"
        )
    if header.get("messageId") != ref.get("imageMessageId"):
        raise ConformanceError(
            "visual_guidance_image_v2 messageId does not match current artifact imageMessageId"
        )
    if header.get("announcedAtStateRevision") != ref.get("announcedAtStateRevision"):
        raise ConformanceError(
            "visual_guidance_image_v2 announcedAtStateRevision does not match first announcement"
        )

    if not payload:
        raise ConformanceError("image payload is empty")
    # The complete WebSocket message is 4-byte length prefix + compact JSON
    # header bytes + raw image bytes, capped at 8 MiB (PROTOCOL_V2.md §2).
    header_bytes = len(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    if 4 + header_bytes + len(payload) > MAX_MESSAGE_BYTES:
        raise ConformanceError("complete message exceeds the 8 MiB cap")

    mime = header.get("mimeType")
    if mime == "image/png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ConformanceError("payload is not a PNG despite mimeType=image/png")
    if mime == "image/jpeg" and not payload.startswith(b"\xff\xd8"):
        raise ConformanceError("payload is not a JPEG despite mimeType=image/jpeg")

    try:
        with Image.open(BytesIO(payload)) as image:
            decoded_width, decoded_height = image.size
    except Exception as error:  # noqa: BLE001 — integrity failure is a scoped reject
        raise ConformanceError(f"payload failed to decode: {error}") from error
    if (decoded_width, decoded_height) != (int(header["width"]), int(header["height"])):
        raise ConformanceError(
            f"decoded dimensions {(decoded_width, decoded_height)} do not match header "
            f"{(int(header['width']), int(header['height']))}"
        )
