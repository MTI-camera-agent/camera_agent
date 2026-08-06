"""Protocol-v1 validation, framing, assembly, and result construction.

The shared transport primitives (``ProtocolError``, ``encode_binary``,
``decode_binary``, ``ObservationAssembler``) live in :mod:`camera_agent.transport`
and are re-exported here so the frozen v1 surface keeps working unchanged. This
module keeps the v1-only schema validator (closed v1 objects) and the v1 image
dimension caps (``validate_image_payload``) that the protocol-v1 baseline
regression fixtures pin.
"""

from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .domain import ImageData, Overlay
from .transport import (
    ObservationAssembler,
    ProtocolError,
    V1_TYPE_TO_DEFINITION as _TYPE_TO_DEFINITION,
    decode_binary,
    encode_binary,
)

PROTOCOL_VERSION = 1
KNOWN_TYPES = {
    "hello",
    "observation",
    "error",
    "result",
    "capture_high_resolution",
    "preview_image",
    "high_resolution_image",
    "result_image",
}
SCHEMA_PATH = (
    Path(__file__).resolve().parent.parent / "docs" / "protocol-v1.schema.json"
)
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_FORMAT_CHECKER = FormatChecker()


def now_ms() -> int:
    return int(time.time() * 1000)


def validate_message(message: Any) -> dict[str, Any]:
    if not isinstance(message, dict):
        raise ProtocolError("message must be a JSON object")
    message_type = message.get("type")
    definition = _TYPE_TO_DEFINITION.get(message_type)
    if definition is None:
        raise ProtocolError(f"unknown message type: {message_type!r}")
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{definition}", "$defs": SCHEMA["$defs"]},
        format_checker=_FORMAT_CHECKER,
    )
    errors = sorted(validator.iter_errors(message), key=lambda error: list(error.path))
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<message>"
        raise ProtocolError(f"{location}: {error.message}")
    if message_type == "result":
        ids = [overlay["id"] for overlay in message.get("overlays", [])]
        if len(ids) != len(set(ids)):
            raise ProtocolError("overlays: ids must be unique")
    return message


def validate_image_payload(header: dict[str, Any], payload: bytes) -> None:
    mime_type = header["mimeType"]
    if mime_type == "image/jpeg" and not payload.startswith(b"\xff\xd8"):
        raise ProtocolError("JPEG payload has an invalid signature")
    if mime_type == "image/png" and not payload.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ProtocolError("PNG payload has an invalid signature")
    longest = max(int(header["width"]), int(header["height"]))
    if header["type"] == "preview_image" and longest > 640:
        raise ProtocolError("preview image exceeds the 640 px long-edge limit")
    if header["type"] == "high_resolution_image" and longest > 1024:
        raise ProtocolError("high-resolution image exceeds the 1024 px long-edge limit")


def make_result(
    observation_id: int,
    *,
    text: str | None = None,
    overlays: tuple[Overlay, ...] = (),
    image_message_id: str | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "result",
        "version": PROTOCOL_VERSION,
        "messageId": str(uuid.uuid4()),
        "observationId": observation_id,
        "timestampMs": now_ms(),
    }
    if text:
        result["text"] = text
    if overlays:
        result["overlays"] = [overlay.to_wire() for overlay in overlays[:3]]
    if image_message_id:
        result["imageMessageId"] = image_message_id
    return validate_message(result)


def make_capture_request(request_id: str) -> dict[str, Any]:
    return validate_message(
        {
            "type": "capture_high_resolution",
            "version": PROTOCOL_VERSION,
            "requestId": request_id,
        }
    )


def make_result_image_header(
    message_id: str,
    observation_id: int,
    image: ImageData,
) -> dict[str, Any]:
    return validate_message(
        {
            "type": "result_image",
            "version": PROTOCOL_VERSION,
            "messageId": message_id,
            "observationId": observation_id,
            "requestId": None,
            "timestampMs": now_ms(),
            "mimeType": image.mime_type,
            "width": image.width,
            "height": image.height,
            "initiation": None,
        }
    )


__all__ = [
    "PROTOCOL_VERSION",
    "KNOWN_TYPES",
    "SCHEMA",
    "SCHEMA_PATH",
    "ProtocolError",
    "ObservationAssembler",
    "now_ms",
    "validate_message",
    "encode_binary",
    "decode_binary",
    "validate_image_payload",
    "make_result",
    "make_capture_request",
    "make_result_image_header",
]
