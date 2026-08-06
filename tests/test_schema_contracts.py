"""Protocol schema contracts.

Both the protocol-v1 executable contract and the protocol-v2 interaction
extension are normative JSON Schemas (Draft 2020-12). These tests freeze that
contract so a future edit cannot silently ship a malformed schema or collapse
the two vocabularies into one.

See docs/README.md for the implementation-ready planning set and the
docs/V1_BASELINE_DELTAS.md characterization of the v1 baseline these schemas
govern.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs"
V1_SCHEMA_PATH = SCHEMA_DIR / "protocol-v1.schema.json"
V2_SCHEMA_PATH = SCHEMA_DIR / "protocol-v2.schema.json"

# The production validator resolves the v1 schema from this exact path, so the
# regression must read the same file rather than a copy.
V1_SCHEMA = json.loads(V1_SCHEMA_PATH.read_text(encoding="utf-8"))
V2_SCHEMA = json.loads(V2_SCHEMA_PATH.read_text(encoding="utf-8"))


def _validator(schema: dict) -> Draft202012Validator:
    return Draft202012Validator(schema, format_checker=FormatChecker())


def test_both_schemas_are_valid_draft_2020_12() -> None:
    """Acceptance: "both schemas validate" as normative JSON Schemas."""
    Draft202012Validator.check_schema(V1_SCHEMA)
    Draft202012Validator.check_schema(V2_SCHEMA)
    assert V1_SCHEMA["$schema"].endswith("draft/2020-12/schema")
    assert V2_SCHEMA["$schema"].endswith("draft/2020-12/schema")


def test_schemas_have_distinct_authoritative_ids() -> None:
    assert V1_SCHEMA["$id"] == "https://hellocamera.local/protocol-v1.schema.json"
    assert V2_SCHEMA["$id"] == "https://hellocamera.local/protocol-v2.schema.json"
    assert V1_SCHEMA["$id"] != V2_SCHEMA["$id"]


def _wire_type(definition: object) -> str | None:
    """Pull the message ``type`` const from a def, handling ``allOf`` headers."""
    if not isinstance(definition, dict):
        return None

    def _from_properties(props: object) -> str | None:
        if isinstance(props, dict) and isinstance(props.get("type"), dict):
            const = props["type"].get("const")
            if isinstance(const, str):
                return const
        return None

    found = _from_properties(definition.get("properties"))
    if found is not None:
        return found
    for branch in definition.get("allOf", []):
        found = _from_properties(branch.get("properties") if isinstance(branch, dict) else None)
        if found is not None:
            return found
    return None


def _oneof_wire_types(schema: dict) -> set[str]:
    types: set[str] = set()
    for ref in schema.get("oneOf", []):
        target = ref.get("$ref") if isinstance(ref, dict) else None
        if not target:
            continue
        definition = schema["$defs"].get(target.rsplit("/", 1)[-1])
        wire_type = _wire_type(definition)
        if wire_type is not None:
            types.add(wire_type)
    return types


def test_schemas_are_self_contained_with_disjoint_message_vocabularies() -> None:
    from camera_agent.protocol import KNOWN_TYPES

    v1_types = _oneof_wire_types(V1_SCHEMA)
    v2_types = _oneof_wire_types(V2_SCHEMA)
    # The v1 schema's top-level vocabulary is exactly the production KNOWN_TYPES.
    assert v1_types == KNOWN_TYPES
    # v2 extends the protocol without reusing any v1 wire type.
    assert v1_types & v2_types == set(), (
        "v1 and v2 wire types must not collide; negotiation selects a projection"
    )
    # The v2 extension governs complete state, actions, and visual guidance.
    assert {"protocol_v2_offer", "coaching_state_v2", "user_action_v2"} <= v2_types


def test_v1_schema_validates_a_production_result_round_trip() -> None:
    from camera_agent.protocol import make_result, validate_message

    result = validate_message(make_result(7, text="Move slightly left."))
    assert _validator(V1_SCHEMA).validate(result) is None
    with pytest.raises(Exception):  # noqa: PT011 — closed-object rejection
        validate_message({**result, "surprise": True})


def test_v2_schema_validates_complete_coaching_state_and_rejects_missing_fields() -> None:
    # The normative example from docs/PROTOCOL_V2.md §6, frozen here.
    coaching_state_v2 = {
        "type": "coaching_state_v2",
        "version": 2,
        "messageId": "44444444-4444-4444-8444-444444444444",
        "timestampMs": 1785123456200,
        "sessionId": "33333333-3333-4333-8333-333333333333",
        "stateRevision": 7,
        "taskId": "55555555-5555-4555-8555-555555555555",
        "acceptedIntention": "A confident full-body portrait at sunset",
        "phase": "evaluating",
        "instruction": {
            "instructionId": "66666666-6666-4666-8666-666666666666",
            "kind": "action",
            "text": "Photographer: move one step to your left.",
            "addressee": "photographer",
            "freshness": "needs_revalidation",
        },
        "activity": {"kind": "working", "text": "Checking your adjustment—hold still."},
        "overlays": None,
        "availableActions": [
            {
                "actionId": "77777777-7777-4777-8777-777777777777",
                "kind": "try_another_suggestion",
                "target": {"kind": "instruction", "id": "66666666-6666-4666-8666-666666666666"},
            },
            {
                "actionId": "88888888-8888-4888-8888-888888888888",
                "kind": "pause_coaching",
                "target": {"kind": "task", "id": "55555555-5555-4555-8555-555555555555"},
            },
        ],
        "visualGuidance": None,
    }
    assert _validator(V2_SCHEMA).validate(coaching_state_v2) is None

    # A snapshot missing the required session/revision is rejected atomically;
    # the last valid projection must remain (see docs/PROTOCOL_V2.md §6).
    incomplete = dict(coaching_state_v2)
    del incomplete["sessionId"]
    del incomplete["stateRevision"]
    assert list(_validator(V2_SCHEMA).iter_errors(incomplete)), (
        "missing required fields must be rejected"
    )
