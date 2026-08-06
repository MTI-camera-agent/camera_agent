"""Shared protocol transport primitive tests (issue #20).

These tests prove the hardened transport-edge mechanics through the public wire
seam: strict Draft 2020-12 v1/v2 schema selection with format checking, bounded
observation assembly, complete media admission, and the serialized bounded
writer. They contain no coaching semantics and do not import the dormant
``camera_agent.v2`` package.

The v1 baseline (``tests/test_v1_baseline.py``) freezes the v1-only behavior of
the same shared primitives; these tests cover the v1/v2 shared hardening.
"""

from __future__ import annotations

import asyncio
import struct
import uuid
from io import BytesIO

import pytest
from PIL import Image

from camera_agent import transport
from camera_agent.protocol import (
    ObservationAssembler,
    ProtocolError,
    decode_binary,
    encode_binary,
)
from tests.helpers import JPEG, observation_message, preview_header

# ---------------------------------------------------------------------------
# 0. The shared primitives are re-exported unchanged from the v1 surface
#    so the frozen v1 baseline is not regressed, and the module is production-
#    safe (does not import the dormant v2 package).
# ---------------------------------------------------------------------------


def test_shared_primitives_are_reexported_from_protocol() -> None:
    assert transport.ProtocolError is ProtocolError
    assert transport.encode_binary is encode_binary
    assert transport.decode_binary is decode_binary
    assert transport.ObservationAssembler is ObservationAssembler


def test_transport_module_does_not_import_dormant_v2_package() -> None:
    import inspect

    source = inspect.getsource(transport)
    assert "from camera_agent.v2" not in source
    assert "import camera_agent.v2" not in source
    assert "from .v2" not in source


# ---------------------------------------------------------------------------
# 1. Strict Draft 2020-12 validation selects the correct v1 or v2 schema and
#    distinguishes unknown text types from known-invalid objects.
# ---------------------------------------------------------------------------


def _v2_coaching_state() -> dict:
    return {
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
        "availableActions": [],
        "visualGuidance": None,
    }


def _v1_result() -> dict:
    return {
        "type": "result",
        "version": 1,
        "messageId": str(uuid.uuid4()),
        "observationId": 7,
        "timestampMs": 1000,
        "text": "Move slightly left.",
    }


def test_validate_wire_object_selects_v1_schema_for_v1_message() -> None:
    result = transport.validate_wire_object(_v1_result())
    assert result.kind == "valid"
    assert result.schema == "v1"
    assert result.message_type == "result"
    assert result.error is None


def test_validate_wire_object_selects_v2_schema_for_v2_message() -> None:
    result = transport.validate_wire_object(_v2_coaching_state())
    assert result.kind == "valid"
    assert result.schema == "v2"
    assert result.message_type == "coaching_state_v2"
    assert result.error is None


def test_validate_wire_object_ignores_unknown_text_types_for_forward_compat() -> None:
    # A well-formed JSON object whose type is neither v1 nor v2 is "unknown":
    # it MUST be ignored for forward compatibility, not rejected as invalid.
    unknown = {"type": "some_future_extension_v3", "payload": "anything"}
    result = transport.validate_wire_object(unknown)
    assert result.kind == "unknown"
    assert result.schema is None
    assert result.message_type == "some_future_extension_v3"
    assert result.error is None


def test_validate_wire_object_rejects_known_invalid_v1_object() -> None:
    # A recognized v1 type with a closed-object violation is known-invalid.
    invalid = _v1_result()
    invalid["surprise"] = True  # closed object rejects unknown fields
    result = transport.validate_wire_object(invalid)
    assert result.kind == "invalid"
    assert result.schema == "v1"
    assert result.message_type == "result"
    assert result.error  # non-empty diagnostic


def test_validate_wire_object_rejects_known_invalid_v2_object() -> None:
    # A recognized v2 type missing a required field is known-invalid; the last
    # valid projection MUST remain (the caller returns a scoped protocol error).
    invalid = _v2_coaching_state()
    del invalid["sessionId"]
    del invalid["stateRevision"]
    result = transport.validate_wire_object(invalid)
    assert result.kind == "invalid"
    assert result.schema == "v2"
    assert result.message_type == "coaching_state_v2"
    assert result.error


def test_validate_wire_object_rejects_malformed_uuid_with_format_checking() -> None:
    invalid = _v1_result()
    invalid["messageId"] = "not-a-uuid"  # format check: uuid
    result = transport.validate_wire_object(invalid)
    assert result.kind == "invalid"
    assert "messageId" in result.error or "uuid" in result.error.lower()


def test_validate_wire_object_rejects_non_object_text() -> None:
    result = transport.validate_wire_object("not even a dict")  # type: ignore[arg-type]
    assert result.kind == "invalid"
    assert result.schema is None


def test_classify_wire_type_returns_v1_v2_or_none() -> None:
    assert transport.classify_wire_type("result") == "v1"
    assert transport.classify_wire_type("coaching_state_v2") == "v2"
    assert transport.classify_wire_type("some_future_extension_v3") is None


def test_require_valid_wire_object_raises_on_unknown_and_known_invalid() -> None:
    # require_valid_wire_object is the binary-framing helper: it requires a
    # recognized, schema-valid v1/v2 object, so unknown types raise just like
    # known-invalid ones. Forward-compatible text handling uses validate_wire_object.
    unknown = {"type": "some_future_extension_v3"}
    with pytest.raises(ProtocolError):
        transport.require_valid_wire_object(unknown)
    invalid = _v1_result()
    invalid["surprise"] = True
    with pytest.raises(ProtocolError):
        transport.require_valid_wire_object(invalid)


# ---------------------------------------------------------------------------
# 2. Bounded observation assembly: both image and observation identities match,
#    16 unmatched entries per side, five-second expiry.
# ---------------------------------------------------------------------------


def test_assembler_joins_only_when_both_image_and_observation_identities_match() -> (
    None
):
    # A preview whose imageMessageId matches but observationId does not is rejected:
    # the pair is consumed and discarded so a stale half cannot later join.
    mismatched_assembler = ObservationAssembler()
    observation = observation_message(1)
    assert mismatched_assembler.add_metadata(observation) is None
    mismatched = preview_header(observation)
    mismatched["observationId"] = 2
    with pytest.raises(ProtocolError):
        mismatched_assembler.add_preview(mismatched, JPEG)

    # On a fresh assembler, the matching preview assembles because BOTH identities
    # (imageMessageId/messageId AND observationId) agree.
    assembler = ObservationAssembler()
    observation = observation_message(1)
    assert assembler.add_metadata(observation) is None
    assembled = assembler.add_preview(preview_header(observation), JPEG)
    assert assembled is not None
    assert assembled.observation_id == 1


def test_assembler_bounded_to_sixteen_unmatched_entries_per_side() -> None:
    assembler = ObservationAssembler()
    metas = [observation_message(i) for i in range(1, 18)]  # 17 metadata frames
    for meta in metas:
        assert assembler.add_metadata(meta) is None
    # The oldest metadata (metas[0]) was evicted by the 16-entry-per-side bound.
    assert assembler.add_preview(preview_header(metas[0]), JPEG) is None
    # The newest retained metadata still assembles with its matching preview.
    assembled = assembler.add_preview(preview_header(metas[-1]), JPEG)
    assert assembled is not None
    assert assembled.observation_id == metas[-1]["observationId"]


def test_assembler_unmatched_fragments_expire_after_five_seconds() -> None:
    assembler = ObservationAssembler()
    observation = observation_message(1)
    assembler.add_metadata(observation, now=0.0)
    # Within the 5-second TTL the metadata is still joinable.
    assert assembler.add_preview(preview_header(observation), JPEG, now=4.9) is not None
    # After the 5-second TTL the unmatched metadata expires and will not join.
    assembler.add_metadata(observation, now=10.0)
    assert assembler.add_preview(preview_header(observation), JPEG, now=15.1) is None


def test_assembler_default_bounds_match_normative_transport_bounds() -> None:
    assembler = ObservationAssembler()
    assert assembler.max_unmatched == 16
    assert assembler.ttl_seconds == 5.0


# ---------------------------------------------------------------------------
# 3. Binary framing, 8 MiB bounds, media/type agreement, complete decode,
#    integrity, and exact dimensions are validated safely.
# ---------------------------------------------------------------------------


def _png_bytes(width: int, height: int) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), (120, 80, 60)).save(buffer, format="PNG")
    return buffer.getvalue()


def _v2_image_header(mime: str = "image/png", width: int = 8, height: int = 8) -> dict:
    return {
        "type": "visual_guidance_image_v2",
        "version": 2,
        "messageId": str(uuid.uuid4()),
        "timestampMs": 1785123456200,
        "sessionId": "33333333-3333-4333-8333-333333333333",
        "visualJobId": "22222222-2222-4222-8222-222222222222",
        "announcedAtStateRevision": 7,
        "mimeType": mime,
        "width": width,
        "height": height,
    }


def test_decode_binary_round_trips_v2_image_header_and_payload() -> None:
    header = _v2_image_header()
    payload = _png_bytes(8, 8)
    decoded_header, decoded_payload = decode_binary(encode_binary(header, payload))
    assert decoded_header == header
    assert decoded_payload == payload


def test_decode_binary_rejects_short_oversized_header_and_empty_payload() -> None:
    with pytest.raises(ProtocolError):
        decode_binary(b"")  # shorter than the length prefix
    with pytest.raises(ProtocolError):
        decode_binary(struct.pack(">I", 70_000) + b"{}")  # header exceeds 64 KiB guard
    with pytest.raises(ProtocolError):
        decode_binary(encode_binary(_v2_image_header(), b""))  # empty image payload


def test_decode_binary_enforces_eight_mib_message_cap_at_the_framing_layer() -> None:
    # A complete binary message over the 8 MiB cap is rejected at the framing
    # layer before header allocation or decode, even before media admission runs.
    header = _v2_image_header(mime="image/png", width=8, height=8)
    oversized = encode_binary(header, b"\x00") + b"\x00" * (8 * 1024 * 1024)
    with pytest.raises(ProtocolError, match="8 MiB"):
        decode_binary(oversized)


def test_admit_image_bytes_accepts_a_valid_decodable_exact_dimension_image() -> None:
    header = _v2_image_header(mime="image/png", width=16, height=12)
    payload = _png_bytes(16, 12)
    # No exception: media/type agree, decode succeeds, integrity holds, dims match.
    transport.admit_image_bytes(header, payload)


def test_admit_image_bytes_rejects_empty_payload() -> None:
    header = _v2_image_header()
    with pytest.raises(ProtocolError):
        transport.admit_image_bytes(header, b"")


def test_admit_image_bytes_rejects_media_type_signature_disagreement() -> None:
    # mimeType claims PNG but the payload is a JPEG (and vice versa).
    header = _v2_image_header(mime="image/png")
    with pytest.raises(ProtocolError):
        transport.admit_image_bytes(header, JPEG)
    header_jpeg = _v2_image_header(mime="image/jpeg")
    with pytest.raises(ProtocolError):
        transport.admit_image_bytes(header_jpeg, _png_bytes(8, 8))


def test_admit_image_bytes_rejects_corrupt_payload_that_fails_decode() -> None:
    header = _v2_image_header(mime="image/png", width=8, height=8)
    with pytest.raises(ProtocolError):
        transport.admit_image_bytes(header, b"\x00\x01\x02not a real image")


def test_admit_image_bytes_rejects_dimension_mismatch() -> None:
    header = _v2_image_header(mime="image/png", width=32, height=32)
    payload = _png_bytes(8, 8)  # decodes fine but dimensions disagree
    with pytest.raises(ProtocolError):
        transport.admit_image_bytes(header, payload)


def test_admit_image_bytes_enforces_eight_mib_message_cap() -> None:
    assert transport.MAX_MESSAGE_BYTES == 8 * 1024 * 1024
    header = _v2_image_header(mime="image/png", width=8, height=8)
    payload = _png_bytes(8, 8)  # a valid, decodable, exact-dimension image
    # Under the default 8 MiB cap the complete message is admitted.
    transport.admit_image_bytes(header, payload)
    # A custom cap smaller than the complete message rejects before decode.
    with pytest.raises(ProtocolError):
        transport.admit_image_bytes(header, payload, max_message_bytes=10)
    # A payload that pushes the complete message over 8 MiB is rejected before
    # any decode attempt (the signature padding is not a real image).
    oversized_payload = b"\x89PNG\r\n\x1a\n" + b"\x00" * (8 * 1024 * 1024)
    with pytest.raises(ProtocolError, match="8 MiB"):
        transport.admit_image_bytes(header, oversized_payload)


# ---------------------------------------------------------------------------
# 4. The serialized writer preserves producer order and closes/detaches rather
#    than dropping a frame that would exceed 32 frames or 16 MiB.
# ---------------------------------------------------------------------------


def test_send_queue_bounds_default_to_thirty_two_frames_and_sixteen_mib() -> None:
    bounds = transport.SendQueueBounds()
    assert bounds.max_frames == 32
    assert bounds.max_bytes == 16 * 1024 * 1024


@pytest.mark.asyncio
async def test_writer_preserves_producer_order() -> None:
    received: list[str] = []

    async def send(data: str | bytes) -> None:
        received.append(data)

    writer = transport.SerializedWriter(send)
    for index in range(5):
        await writer.submit_text(f"frame-{index}")
    await writer.join()
    assert received == [f"frame-{index}" for index in range(5)]
    await writer.close()


@pytest.mark.asyncio
async def test_writer_overflows_at_frame_bound_and_does_not_drop_the_overflowing_frame() -> (
    None
):
    received: list[str] = []
    gate = asyncio.Event()

    async def send(data: str | bytes) -> None:
        await gate.wait()  # block the drainer so the queue fills deterministically
        received.append(data)

    bounds = transport.SendQueueBounds(max_frames=4, max_bytes=16 * 1024 * 1024)
    writer = transport.SerializedWriter(send, bounds=bounds)
    # Fill the queue to exactly the frame bound.
    for index in range(4):
        await writer.submit_text(f"frame-{index}")
    # The next frame would exceed the bound: it is NOT silently dropped — the
    # writer raises SendQueueOverflow and becomes unusable (close + detach).
    with pytest.raises(transport.SendQueueOverflow):
        await writer.submit_text("overflow-frame")
    assert writer.overflowed
    # Subsequent submissions fail fast; the connection is unusable.
    with pytest.raises(transport.SendQueueOverflow):
        await writer.submit_text("after-overflow")
    # Release the drainer: the already-admitted frames flush in producer order.
    gate.set()
    await writer.join()
    assert received == ["frame-0", "frame-1", "frame-2", "frame-3"]
    await writer.close()


@pytest.mark.asyncio
async def test_writer_overflows_at_byte_bound() -> None:
    received: list[bytes] = []
    gate = asyncio.Event()

    async def send(data: str | bytes) -> None:
        await gate.wait()
        received.append(data)

    # 1024-byte queue bound; each frame is 512 bytes so two fit and the third
    # would exceed the byte bound.
    bounds = transport.SendQueueBounds(max_frames=32, max_bytes=1024)
    writer = transport.SerializedWriter(send, bounds=bounds)
    frame = b"\x00" * 512
    await writer.submit_binary(frame)  # pending = 512
    await writer.submit_binary(frame)  # pending = 1024 (exactly at bound)
    with pytest.raises(transport.SendQueueOverflow):
        await writer.submit_binary(frame)  # would exceed 1024
    assert writer.overflowed
    gate.set()
    await writer.join()
    assert received == [frame, frame]
    await writer.close()


@pytest.mark.asyncio
async def test_writer_rejects_a_single_frame_larger_than_the_byte_bound() -> None:
    async def send(data: str | bytes) -> None:
        pass

    bounds = transport.SendQueueBounds(max_frames=32, max_bytes=256)
    writer = transport.SerializedWriter(send, bounds=bounds)
    with pytest.raises(transport.SendQueueOverflow):
        await writer.submit_binary(b"\x00" * 257)
    assert writer.overflowed
    await writer.close()


@pytest.mark.asyncio
async def test_writer_close_stops_the_drainer_and_releases_the_queue() -> None:
    async def send(data: str | bytes) -> None:
        pass

    writer = transport.SerializedWriter(send)
    await writer.close()
    # After close the writer is unusable for new submissions.
    with pytest.raises(transport.SendQueueOverflow):
        await writer.submit_text("late")


@pytest.mark.asyncio
async def test_writer_drain_send_failure_makes_writer_unusable() -> None:
    async def send(data: str | bytes) -> None:
        raise ConnectionError("socket gone")

    writer = transport.SerializedWriter(send)
    await writer.submit_text("frame-0")
    # The drainer hits a send failure; the writer becomes unusable.
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    assert writer.closed
    with pytest.raises(transport.SendQueueOverflow):
        await writer.submit_text("after-failure")
    await writer.close()
