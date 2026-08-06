"""Shared protocol transport primitives for the v1 and v2 wire edges.

This module is **transport-edge only**. It hardens four reusable protocol-edge
mechanics that both protocol versions rely on:

- strict JSON Schema Draft 2020-12 validation with format checking that selects
  the correct v1 or v2 schema and distinguishes *unknown* text types (ignored
  for forward compatibility) from *known-invalid* objects (rejected atomically);
- bounded observation assembly that joins metadata and preview bytes only when
  both image and observation identities match, retaining at most 16 unmatched
  entries per side for 5 seconds;
- safe binary media admission that enforces the 8 MiB message cap, media/type
  agreement, complete decode, integrity, and exact dimensions; and
- one serialized send queue bounded at 32 frames or 16 MiB that preserves
  producer order and closes/detaches rather than dropping a frame that would
  exceed the bound.

It contains **no semantic coaching decisions**: schema selection, framing,
observation correlation, byte admission, and backpressure are transport
responsibilities; the runtime owns semantics. See ``docs/PROTOCOL_V2.md`` §2 and
the approved architecture in ``docs/HARNESS_ARCHITECTURE.md``.

The module is production-safe: it loads the normative JSON Schema documents from
``docs/`` and does **not** import the dormant ``camera_agent.v2`` package, so the
production composition root may adopt the v1 pieces without pulling v2 online
before the atomic-cutover ticket.
"""

from __future__ import annotations

import asyncio
import json
import struct
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Awaitable

from jsonschema import Draft202012Validator, FormatChecker

from .domain import ImageData, ObservationContext

__all__ = [
    "ProtocolError",
    # wire schema selection
    "WireValidation",
    "classify_wire_type",
    "validate_wire_object",
    "require_valid_wire_object",
    # binary framing
    "encode_binary",
    "decode_binary",
    # complete media admission
    "admit_image_bytes",
    # bounded observation assembly
    "ObservationAssembler",
    # serialized bounded writer
    "SendQueueBounds",
    "SendQueueOverflow",
    "SerializedWriter",
]


class ProtocolError(ValueError):
    """A known wire message or binary envelope violates protocol v1 or v2.

    Unknown text-message types are **not** a ``ProtocolError``: they are ignored
    for forward compatibility. Only a recognized v1 or v2 type that fails schema
    or semantic validation, or an invalid binary envelope, raises this.
    """


# ---------------------------------------------------------------------------
# Normative schemas (loaded from docs/, not the dormant v2 package)
# ---------------------------------------------------------------------------

_SCHEMA_DIR = Path(__file__).resolve().parent.parent / "docs"
_V1_SCHEMA_PATH = _SCHEMA_DIR / "protocol-v1.schema.json"
_V2_SCHEMA_PATH = _SCHEMA_DIR / "protocol-v2.schema.json"

_V1_SCHEMA = json.loads(_V1_SCHEMA_PATH.read_text(encoding="utf-8"))
_V2_SCHEMA = json.loads(_V2_SCHEMA_PATH.read_text(encoding="utf-8"))
Draft202012Validator.check_schema(_V1_SCHEMA)
Draft202012Validator.check_schema(_V2_SCHEMA)

_FORMAT_CHECKER = FormatChecker()

# Wire type → authoritative schema + definition name. v1 and v2 vocabularies are
# disjoint: negotiation selects one projection, and an unknown type is ignored.
V1_TYPE_TO_DEFINITION: dict[str, str] = {
    "hello": "hello",
    "observation": "observation",
    "error": "clientError",
    "result": "result",
    "capture_high_resolution": "captureHighResolution",
    "preview_image": "previewImageHeader",
    "high_resolution_image": "highResolutionImageHeader",
    "result_image": "resultImageHeader",
}
V2_TYPE_TO_DEFINITION: dict[str, str] = {
    "protocol_v2_offer": "protocolOffer",
    "protocol_v2_accept": "protocolAccept",
    "coaching_state_v2": "coachingState",
    "user_action_v2": "userAction",
    "action_result_v2": "actionResult",
    "protocol_error_v2": "protocolError",
    "visual_guidance_image_v2": "visualGuidanceImageHeader",
}


def classify_wire_type(message_type: Any) -> str | None:
    """Return ``"v1"`` or ``"v2"`` for a known wire type, else ``None``.

    ``None`` marks an unknown text-message type: it MUST be ignored for forward
    compatibility rather than rejected as invalid (PROTOCOL_V2.md §2).
    """

    if message_type in V1_TYPE_TO_DEFINITION:
        return "v1"
    if message_type in V2_TYPE_TO_DEFINITION:
        return "v2"
    return None


@dataclass(frozen=True, slots=True)
class WireValidation:
    """The outcome of validating one wire object against the v1/v2 schemas.

    - ``kind == "valid"``: the object passed strict schema validation. ``schema``
      is ``"v1"`` or ``"v2"``.
    - ``kind == "unknown"``: the object is a JSON dict whose ``type`` is neither
      v1 nor v2. The caller MUST ignore it for forward compatibility. ``schema``
      is ``None`` and ``error`` is ``None``.
    - ``kind == "invalid"``: the object is a recognized v1 or v2 type that failed
      strict schema validation (closed-object semantics, format checking). The
      caller returns a scoped protocol error without clearing valid state.
    """

    kind: str
    schema: str | None
    message_type: str | None
    error: str | None


def _schema_and_def(message_type: str) -> tuple[dict[str, Any], str] | None:
    if message_type in V1_TYPE_TO_DEFINITION:
        return _V1_SCHEMA, V1_TYPE_TO_DEFINITION[message_type]
    if message_type in V2_TYPE_TO_DEFINITION:
        return _V2_SCHEMA, V2_TYPE_TO_DEFINITION[message_type]
    return None


def validate_wire_object(message: Any) -> WireValidation:
    """Validate one closed wire object against its v1 or v2 schema definition.

    Strict Draft 2020-12 validation with format checking is applied. Unknown text
    types are reported as ``kind == "unknown"`` (ignored for forward
    compatibility); recognized types that fail are ``kind == "invalid"``.
    """

    if not isinstance(message, dict):
        return WireValidation(
            kind="invalid",
            schema=None,
            message_type=None,
            error="wire object must be a JSON object",
        )
    message_type = message.get("type")
    mapping = _schema_and_def(message_type)
    if mapping is None:
        return WireValidation(
            kind="unknown",
            schema=None,
            message_type=message_type if isinstance(message_type, str) else None,
            error=None,
        )
    schema, def_name = mapping
    validator = Draft202012Validator(
        {"$ref": f"#/$defs/{def_name}", "$defs": schema["$defs"]},
        format_checker=_FORMAT_CHECKER,
    )
    errors = sorted(
        validator.iter_errors(message), key=lambda error: list(error.absolute_path)
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<message>"
        return WireValidation(
            kind="invalid",
            schema=classify_wire_type(message_type),
            message_type=message_type,
            error=f"{location}: {error.message}",
        )
    return WireValidation(
        kind="valid",
        schema=classify_wire_type(message_type),
        message_type=message_type,
        error=None,
    )


def require_valid_wire_object(message: Any) -> dict[str, Any]:
    """Return ``message`` only if it is a recognized, schema-valid v1 or v2 object.

    Both unknown text types and known-invalid objects raise ``ProtocolError``:
    this is the "I require a validated wire object" helper used by binary framing.
    For forward-compatible text-message handling (ignore unknown types), call
    :func:`validate_wire_object` and branch on ``result.kind`` instead.
    """

    result = validate_wire_object(message)
    if result.kind == "valid":
        return message  # type: ignore[return-value]
    if result.kind == "unknown":
        raise ProtocolError(f"unknown text-message type: {result.message_type!r}")
    raise ProtocolError(result.error or "wire object is invalid")


# ---------------------------------------------------------------------------
# Binary framing: 4-byte big-endian length prefix + compact JSON header + payload
# ---------------------------------------------------------------------------

#: Guard against allocating a malformed or oversized header before decoding.
_MAX_HEADER_BYTES = 64 * 1024

#: The complete WebSocket message cap: 4-byte length prefix + JSON header + bytes.
#: Enforced both at the framing layer (:func:`decode_binary`) and at image
#: admission (:func:`admit_image_bytes`) so a caller cannot bypass the bound.
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def encode_binary(header: dict[str, Any], payload: bytes) -> bytes:
    """Encode the shared v1/v2 binary envelope: ``uint32-be(len(json)) + json + payload``."""

    encoded = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return struct.pack(">I", len(encoded)) + encoded + payload


def decode_binary(
    message: bytes,
    *,
    max_header_bytes: int = _MAX_HEADER_BYTES,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
) -> tuple[dict[str, Any], bytes]:
    """Decode the shared binary envelope and validate the header as a wire object.

    Enforces, in order: the 8 MiB complete-message cap (so a malformed or
    oversized transfer is rejected before allocation); a non-short length prefix;
    a header length that is nonzero and no larger than ``max_header_bytes``; a
    non-empty image payload; and strict schema validation of the header via
    :func:`require_valid_wire_object`.
    """

    if len(message) > max_message_bytes:
        raise ProtocolError("binary message exceeds the 8 MiB message cap")
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
    require_valid_wire_object(header)
    return header, payload


# ---------------------------------------------------------------------------
# Complete media admission (PROTOCOL_V2.md §2, §8.2)
# ---------------------------------------------------------------------------

_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_JPEG_SIGNATURE = b"\xff\xd8"


def admit_image_bytes(
    header: dict[str, Any],
    payload: bytes,
    *,
    max_message_bytes: int = MAX_MESSAGE_BYTES,
) -> None:
    """Safely admit one binary image transfer shared by v1 and v2.

    Enforces, in order:

    - a non-empty payload;
    - the complete-message byte cap (length prefix + compact JSON header +
      payload) so a malformed or oversized transfer is rejected before allocation;
    - media/type agreement: the payload signature matches ``mimeType``;
    - complete decode and integrity: the payload decodes as an image; and
    - exact dimensions: decoded width/height equal the header's declared values.

    Any failure raises ``ProtocolError``; the caller treats it as a scoped reject
    that does not clear unrelated valid state.
    """

    from PIL import Image
    from io import BytesIO

    if not payload:
        raise ProtocolError("image payload is empty")

    # Header bytes are encoded exactly as they travel on the wire so the cap
    # reflects the real complete-message size.
    header_bytes = len(
        json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    )
    if 4 + header_bytes + len(payload) > max_message_bytes:
        raise ProtocolError("complete image message exceeds the 8 MiB cap")

    mime_type = header.get("mimeType")
    if mime_type == "image/png" and not payload.startswith(_PNG_SIGNATURE):
        raise ProtocolError("payload is not a PNG despite mimeType=image/png")
    if mime_type == "image/jpeg" and not payload.startswith(_JPEG_SIGNATURE):
        raise ProtocolError("payload is not a JPEG despite mimeType=image/jpeg")
    if mime_type not in ("image/png", "image/jpeg"):
        raise ProtocolError(f"unsupported image mimeType: {mime_type!r}")

    try:
        with Image.open(BytesIO(payload)) as image:
            decoded_width, decoded_height = image.size
    except Exception as error:  # noqa: BLE001 — integrity failure is a scoped reject
        raise ProtocolError(f"image payload failed to decode: {error}") from error

    expected_width = int(header["width"])
    expected_height = int(header["height"])
    if (decoded_width, decoded_height) != (expected_width, expected_height):
        raise ProtocolError(
            f"decoded dimensions {(decoded_width, decoded_height)} do not match "
            f"header {(expected_width, expected_height)}"
        )


# ---------------------------------------------------------------------------
# Bounded observation assembly
# ---------------------------------------------------------------------------


class ObservationAssembler:
    """Correlate interleaved metadata and preview frames behind one small interface.

    Metadata and preview bytes join only when BOTH the image message identity
    (``imageMessageId`` on the metadata, ``messageId`` on the preview header) and
    the observation identity (``observationId``) match. Each side retains at most
    ``max_unmatched`` fragments for ``ttl_seconds`` seconds. Older or excess
    fragments are evicted in arrival order.
    """

    def __init__(
        self,
        *,
        ttl_seconds: float = 5.0,
        max_unmatched: int = 16,
    ) -> None:
        if max_unmatched < 1:
            raise ValueError("observation fragment capacity must be at least 1")
        if ttl_seconds <= 0:
            raise ValueError("observation fragment TTL must be positive")
        self._ttl_seconds = ttl_seconds
        self._max_unmatched = max_unmatched
        self._metadata: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()
        self._images: OrderedDict[str, tuple[dict[str, Any], bytes, float]] = (
            OrderedDict()
        )

    @property
    def ttl_seconds(self) -> float:
        return self._ttl_seconds

    @property
    def max_unmatched(self) -> int:
        return self._max_unmatched

    def add_metadata(
        self, message: dict[str, Any], now: float | None = None
    ) -> ObservationContext | None:
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


# ---------------------------------------------------------------------------
# Serialized bounded writer (PROTOCOL_V2.md §2)
# ---------------------------------------------------------------------------

#: Default send-queue bounds: 32 queued frames or 16 MiB of queued bytes.
_DEFAULT_MAX_FRAMES = 32
_DEFAULT_MAX_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class SendQueueBounds:
    """Per-direction serialized send-queue bounds.

    A frame that would exceed ``max_frames`` queued frames or ``max_bytes`` of
    queued bytes makes the connection unusable: the writer raises
    ``SendQueueOverflow`` and the caller closes and detaches rather than silently
    dropping an ordered frame.
    """

    max_frames: int = _DEFAULT_MAX_FRAMES
    max_bytes: int = _DEFAULT_MAX_BYTES

    def __post_init__(self) -> None:
        if self.max_frames < 1:
            raise ValueError("send queue frame cap must be at least 1")
        if self.max_bytes < 1:
            raise ValueError("send queue byte cap must be at least 1")


class SendQueueOverflow(RuntimeError):
    """A frame would exceed the serialized send-queue frame or byte bound.

    The connection is unusable: the caller MUST close and follow normal
    detach/reconnect recovery. The overflowing frame is **not** silently dropped
    — the writer raises so the caller can close and detach.
    """


@dataclass(slots=True)
class _QueuedFrame:
    data: str | bytes
    size: int


SendFn = Callable[[str | bytes], Awaitable[None]]


class SerializedWriter:
    """One serialized, bounded send queue for one WebSocket direction.

    Producers call ``submit_text`` / ``submit_binary``; a single background
    drainer flushes frames to the wire in producer order. The queue is bounded
    at ``max_frames`` frames or ``max_bytes`` of queued bytes. A frame that would
    exceed either bound raises ``SendQueueOverflow`` (the caller closes and
    detaches) rather than silently dropping ordered output.

    This is transport-edge only: it owns ordering and backpressure, not coaching
    semantics. The runtime commits state before enqueuing output; this writer
    never allocates revisions or interprets content.
    """

    def __init__(
        self,
        send: SendFn,
        *,
        bounds: SendQueueBounds | None = None,
    ) -> None:
        self._send = send
        self._bounds = bounds or SendQueueBounds()
        self._queue: asyncio.Queue[_QueuedFrame | Any] = asyncio.Queue()
        self._pending_frames = 0
        self._pending_bytes = 0
        self._cond = asyncio.Condition()
        self._closed = False
        self._overflowed = False
        self._drain_task = asyncio.create_task(self._drain())

    # -- producer surface ---------------------------------------------------

    async def submit_text(self, message: str) -> None:
        """Enqueue one text frame, preserving producer order."""
        await self._submit(message, len(message.encode("utf-8")))

    async def submit_binary(self, frame: bytes) -> None:
        """Enqueue one binary frame, preserving producer order."""
        await self._submit(frame, len(frame))

    async def join(self) -> None:
        """Wait until every admitted frame has been flushed to the wire."""
        async with self._cond:
            while self._pending_frames > 0 and not self._closed:
                await self._cond.wait()

    async def close(self) -> None:
        """Stop the drainer and release the queue.

        Outstanding admitted frames are abandoned: the caller is closing the
        connection, so further wire writes are the caller's responsibility. After
        ``close`` the writer rejects every new submission.
        """
        self._closed = True
        self._drain_task.cancel()
        try:
            await self._drain_task
        except asyncio.CancelledError:
            pass
        async with self._cond:
            self._cond.notify_all()

    # -- introspection ------------------------------------------------------

    @property
    def overflowed(self) -> bool:
        return self._overflowed

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def pending_frames(self) -> int:
        return self._pending_frames

    @property
    def pending_bytes(self) -> int:
        return self._pending_bytes

    # -- internals ----------------------------------------------------------

    async def _submit(self, data: str | bytes, size: int) -> None:
        async with self._cond:
            if self._closed or self._overflowed:
                raise SendQueueOverflow(
                    "serialized send queue is closed or already overflowed"
                )
            if size > self._bounds.max_bytes:
                self._overflowed = True
                self._cond.notify_all()
                raise SendQueueOverflow(
                    f"frame of {size} bytes exceeds the send-queue byte bound "
                    f"of {self._bounds.max_bytes} bytes"
                )
            if self._pending_frames + 1 > self._bounds.max_frames:
                self._overflowed = True
                self._cond.notify_all()
                raise SendQueueOverflow(
                    f"frame would exceed the send-queue frame bound "
                    f"of {self._bounds.max_frames} frames"
                )
            if self._pending_bytes + size > self._bounds.max_bytes:
                self._overflowed = True
                self._cond.notify_all()
                raise SendQueueOverflow(
                    f"frame would exceed the send-queue byte bound "
                    f"of {self._bounds.max_bytes} bytes"
                )
            self._pending_frames += 1
            self._pending_bytes += size
            await self._queue.put(_QueuedFrame(data, size))

    async def _drain(self) -> None:
        try:
            while True:
                item = await self._queue.get()
                frame: _QueuedFrame = item  # type: ignore[assignment]
                try:
                    await self._send(frame.data)
                except Exception:
                    # A send failure makes the connection unusable. Admitted but
                    # unflushed frames are abandoned; the caller closes.
                    async with self._cond:
                        self._closed = True
                        self._pending_frames = 0
                        self._pending_bytes = 0
                        self._cond.notify_all()
                    return
                async with self._cond:
                    self._pending_frames = max(0, self._pending_frames - 1)
                    self._pending_bytes = max(0, self._pending_bytes - frame.size)
                    self._cond.notify_all()
        except asyncio.CancelledError:
            return
