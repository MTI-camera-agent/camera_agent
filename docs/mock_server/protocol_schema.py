"""JSON Schema validation helpers for HelloCamera protocol v1."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "protocol-v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)

_FORMAT_CHECKER = FormatChecker()
_TYPE_TO_DEFINITION = {
    "hello": "hello",
    "observation": "observation",
    "error": "clientError",
    "result": "result",
    "capture_high_resolution": "captureHighResolution",
    "preview_image": "previewImageHeader",
    "high_resolution_image": "highResolutionImageHeader",
    "result_image": "resultImageHeader",
}


class ProtocolValidationError(ValueError):
    """Raised when a known v1 message does not satisfy the wire contract."""


def validate_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise ProtocolValidationError("message must be a JSON object")
    message_type = message.get("type")
    definition = _TYPE_TO_DEFINITION.get(message_type)
    if definition is None:
        raise ProtocolValidationError(f"unknown message type: {message_type!r}")

    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": SCHEMA["$defs"]},
        format_checker=_FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(message), key=lambda item: list(item.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<message>"
        raise ProtocolValidationError(f"{location}: {error.message}")

    if message_type == "result":
        overlay_ids = [
            overlay["id"]
            for overlay in message.get("overlays", [])
        ]
        if len(overlay_ids) != len(set(overlay_ids)):
            raise ProtocolValidationError("overlays: ids must be unique")
    return message
