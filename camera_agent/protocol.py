"""Protocol-v1 validation, framing, assembly, and result construction."""

from __future__ import annotations

import json
import struct
import time
import uuid
from collections import OrderedDict
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

from .domain import ImageData, ObservationContext, Overlay

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
SCHEMA_PATH = Path(__file__).resolve().parent.parent / "docs" / "protocol-v1.schema.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(SCHEMA)
_FORMAT_CHECKER = FormatChecker()


class ProtocolError(ValueError):
    """A known message or binary envelope violates protocol v1."""


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


def encode_binary(header: dict[str, Any], payload: bytes) -> bytes:
    encoded = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded + payload


def decode_binary(message: bytes, *, max_header_bytes: int = 64 * 1024) -> tuple[dict[str, Any], bytes]:
    if len(message) < 4:
        raise ProtocolError("binary message is shorter than its length prefix")
    (header_length,) = struct.unpack(">I", message[:4])
    end = 4 + header_length
    if header_length == 0 or header_length > max_header_bytes or end > len(message):
        raise ProtocolError("binary message has an invalid header length")
    try:
        header = json.loads(message[4:end])
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ProtocolError(f"invalid binary JSON header: {error}") from error
    payload = message[end:]
    if not payload:
        raise ProtocolError("binary image payload is empty")
    return validate_message(header), payload


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


class ObservationAssembler:
    """Correlate interleaved metadata and preview frames behind one small interface."""

    def __init__(self, *, ttl_seconds: float = 5.0, max_unmatched: int = 16) -> None:
        self._ttl_seconds = ttl_seconds
        self._max_unmatched = max_unmatched
        self._metadata: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()
        self._images: OrderedDict[str, tuple[dict[str, Any], bytes, float]] = OrderedDict()

    def add_metadata(self, message: dict[str, Any], now: float | None = None) -> ObservationContext | None:
        now = time.monotonic() if now is None else now
        self._expire(now)
        key = message["imageMessageId"]
        self._metadata[key] = (message, now)
        self._trim(self._metadata)
        return self._assemble(key, now)

    def add_preview(
        self,
        header: dict[str, Any],
        payload: bytes,
        now: float | None = None,
    ) -> ObservationContext | None:
        now = time.monotonic() if now is None else now
        self._expire(now)
        key = header["messageId"]
        self._images[key] = (header, payload, now)
        self._trim(self._images)
        return self._assemble(key, now)

    def _assemble(self, key: str, now: float) -> ObservationContext | None:
        metadata_entry = self._metadata.get(key)
        image_entry = self._images.get(key)
        if metadata_entry is None or image_entry is None:
            return None
        metadata, _ = self._metadata.pop(key)
        header, payload, _ = self._images.pop(key)
        if metadata["observationId"] != header["observationId"]:
            raise ProtocolError("preview observationId does not match its metadata")
        return ObservationContext(
            observation_id=int(metadata["observationId"]),
            timestamp_ms=int(metadata["timestampMs"]),
            reason=str(metadata["reason"]),
            intention=str(metadata["intention"]),
            camera=dict(metadata["camera"]),
            image_message_id=key,
            image=ImageData(
                data=payload,
                mime_type=header["mimeType"],
                width=int(header["width"]),
                height=int(header["height"]),
            ),
            received_monotonic=now,
        )

    def _expire(self, now: float) -> None:
        cutoff = now - self._ttl_seconds
        for entries in (self._metadata, self._images):
            while entries:
                _, value = next(iter(entries.items()))
                if value[-1] >= cutoff:
                    break
                entries.popitem(last=False)

    def _trim(self, entries: OrderedDict[str, Any]) -> None:
        while len(entries) > self._max_unmatched:
            entries.popitem(last=False)


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
        {"type": "capture_high_resolution", "version": PROTOCOL_VERSION, "requestId": request_id}
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
