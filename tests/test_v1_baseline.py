"""Protocol-v1 baseline regression fixtures.

These tests FREEZE the protocol-v1 wire and observable behavior of the current
fixed-plan baseline before dormant v2 implementation begins. They are
characterization tests: they pin current behavior so the eventual v2 cutover
cannot silently regress it. They MUST NOT be relaxed to match new v2 behavior;
v2 changes land behind protocol-v2 negotiation and the atomic composition-root
cutover (see docs/HARNESS_ARCHITECTURE.md, "Migration and atomic cutover", and
docs/V1_BASELINE_DELTAS.md for the per-delta classification).

The five frozen areas, mirroring the ticket #16 acceptance criteria:

1. exact v1 framing
2. dual-ID observation correlation
3. result/image ordering
4. overlay freshness
5. representative observable loop traces
"""

from __future__ import annotations

import asyncio
import json
import struct
import uuid

import pytest
from websockets.asyncio.client import connect

from camera_agent.adapters.fake import FakeEditor, ScriptedReasoner
from camera_agent.domain import (
    ImageData,
    Overlay,
    PlanningDecision,
    VerificationOutcome,
)
from camera_agent.protocol import (
    ObservationAssembler,
    ProtocolError,
    decode_binary,
    encode_binary,
    make_result,
    make_result_image_header,
    validate_message,
)
from tests.helpers import (
    JPEG,
    fixture,
    observation_message,
    open_test_server,
    planning,
    preview_header,
    send_hello,
    send_observation,
    shot_plan,
    verification,
)


# ---------------------------------------------------------------------------
# 1. Exact v1 framing
# ---------------------------------------------------------------------------


def test_binary_envelope_is_big_endian_length_prefix_plus_compact_header_plus_payload() -> None:
    """A v1 binary frame is exactly ``uint32-be(len(json)) + compact json + payload``."""
    header = preview_header(observation_message())
    encoded = encode_binary(header, JPEG)
    json_bytes = json.dumps(header, separators=(",", ":"), sort_keys=True).encode("utf-8")
    assert encoded == struct.pack(">I", len(json_bytes)) + json_bytes + JPEG

    decoded_header, decoded_payload = decode_binary(encoded)
    assert decoded_header == header
    assert decoded_payload == JPEG


def test_decode_binary_rejects_short_oversized_header_and_empty_payload() -> None:
    with pytest.raises(ProtocolError):
        decode_binary(b"")  # shorter than the length prefix
    with pytest.raises(ProtocolError):
        decode_binary(struct.pack(">I", 70_000) + b"{}")  # header exceeds 64 KiB guard
    with pytest.raises(ProtocolError):
        decode_binary(encode_binary(preview_header(observation_message()), b""))  # empty image


def test_make_result_emits_closed_v1_object_with_exact_required_fields() -> None:
    result = make_result(42, text="Move slightly left.")
    assert result["type"] == "result"
    assert result["version"] == 1
    assert result["observationId"] == 42
    assert isinstance(result["messageId"], str)
    assert isinstance(result["timestampMs"], int)
    assert result["text"] == "Move slightly left."
    # v1 objects are closed: an unknown field is rejected, not ignored.
    with pytest.raises(ProtocolError):
        validate_message({**result, "surprise": True})


def test_result_carries_text_overlays_or_image_message_id_and_nothing_else() -> None:
    arrow = Overlay("aim", "arrow", ((0.1, 0.2), (0.8, 0.5)), text="aim here")
    message_id = "11111111-1111-4111-8111-111111111111"

    text_only = make_result(1, text="Move left.")
    assert "overlays" not in text_only and "imageMessageId" not in text_only

    with_overlays = make_result(1, overlays=(arrow,))
    assert [o["id"] for o in with_overlays["overlays"]] == ["aim"]

    with_image = make_result(1, image_message_id=message_id)
    assert with_image["imageMessageId"] == message_id


# ---------------------------------------------------------------------------
# 2. Dual-ID observation correlation
# ---------------------------------------------------------------------------


def test_metadata_and_preview_assemble_only_when_both_ids_match() -> None:
    assembler = ObservationAssembler()
    observation = observation_message(1)
    assert assembler.add_metadata(observation) is None  # metadata alone is incomplete
    assert assembler.add_preview(preview_header(observation), JPEG) is not None
    # Both sides are consumed on a successful match.
    assert assembler.add_metadata(observation_message(1)) is None


def test_observation_id_mismatch_between_metadata_and_preview_is_rejected() -> None:
    assembler = ObservationAssembler()
    observation = observation_message(1)
    assembler.add_metadata(observation)
    header = preview_header(observation)
    header["observationId"] = 2  # same imageMessageId, wrong observationId
    with pytest.raises(ProtocolError):
        assembler.add_preview(header, JPEG)


def test_interleaved_pairs_assemble_out_of_order_by_image_message_id() -> None:
    assembler = ObservationAssembler()
    first = observation_message(1)
    second = observation_message(2)
    assembler.add_metadata(first)
    assembler.add_metadata(second)
    # Previews arrive in reverse order; each joins its own metadata.
    assembled_second = assembler.add_preview(preview_header(second), JPEG)
    assembled_first = assembler.add_preview(preview_header(first), JPEG)
    assert assembled_second.observation_id == 2
    assert assembled_first.observation_id == 1
    assert assembled_first.image.mime_type == "image/jpeg"


def test_unmatched_fragments_are_bounded_to_sixteen_per_side() -> None:
    assembler = ObservationAssembler()
    metas = [observation_message(i) for i in range(1, 18)]  # 17 metadata frames
    for meta in metas:
        assert assembler.add_metadata(meta) is None
    # The oldest metadata (metas[0]) was evicted by the 16-entry bound.
    assert assembler.add_preview(preview_header(metas[0]), JPEG) is None
    # The newest retained metadata still assembles with its preview.
    assembled = assembler.add_preview(preview_header(metas[-1]), JPEG)
    assert assembled.observation_id == metas[-1]["observationId"]


def test_unmatched_fragments_expire_after_five_seconds() -> None:
    assembler = ObservationAssembler()
    observation = observation_message(1)
    assembler.add_metadata(observation, now=0.0)
    # Within the 5-second TTL the metadata is still joinable.
    assert assembler.add_preview(preview_header(observation), JPEG, now=4.9) is not None

    assembler.add_metadata(observation, now=10.0)
    assert assembler.add_preview(preview_header(observation), JPEG, now=15.1) is None


# ---------------------------------------------------------------------------
# 3. Result/image ordering
# ---------------------------------------------------------------------------


def test_result_with_image_message_id_pairs_with_result_image_of_same_id() -> None:
    message_id = "11111111-1111-4111-8111-111111111111"
    image = ImageData(JPEG, "image/jpeg", 480, 640)
    result = make_result(9, text="Ask the subject to sit.", image_message_id=message_id)
    header = make_result_image_header(message_id, 9, image)
    # The result announces the image; the following binary frame carries it.
    assert result["imageMessageId"] == header["messageId"] == message_id
    assert header["type"] == "result_image"
    assert header["observationId"] == 9
    decoded_header, decoded_payload = decode_binary(encode_binary(header, image.data))
    assert decoded_header == header
    assert decoded_payload == image.data


def test_text_only_result_has_no_image_message_id_and_no_paired_binary() -> None:
    result = make_result(9, text="Move left.")
    assert "imageMessageId" not in result


# ---------------------------------------------------------------------------
# 4. Overlay freshness
# ---------------------------------------------------------------------------


def _plan_with_overlay(instruction: str, overlay: Overlay) -> PlanningDecision:
    return PlanningDecision(
        assessment="Current view assessed.",
        plan=shot_plan(),
        ready=False,
        instruction=instruction,
        overlays=(overlay,),
    )


@pytest.mark.asyncio
async def test_overlays_suppressed_without_overlay_primitives_capability() -> None:
    arrow = Overlay("aim", "arrow", ((0.1, 0.2), (0.8, 0.5)), text="aim here")
    reasoner = ScriptedReasoner(plans=[_plan_with_overlay("Move closer.", arrow)])
    async with open_test_server(reasoner) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
            await send_hello(connection, ["preview_jpeg"])  # no overlay_primitives
            await send_observation(
                connection,
                observation_message(1, reason="intention_updated"),
                fixture("plant-medium-centered.jpg"),
            )
            await asyncio.wait_for(connection.recv(), 1)  # "Analyzing new shot…"
            guidance = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert guidance["text"] == "Move closer."
            assert "overlays" not in guidance  # freshness: capability gate suppresses


@pytest.mark.asyncio
async def test_overlays_delivered_with_capability_on_matching_camera() -> None:
    arrow = Overlay("aim", "arrow", ((0.1, 0.2), (0.8, 0.5)), text="aim here", color="#FF0000")
    reasoner = ScriptedReasoner(plans=[_plan_with_overlay("Move closer.", arrow)])
    async with open_test_server(reasoner) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
            await send_hello(connection, ["preview_jpeg", "overlay_primitives"])
            await send_observation(
                connection,
                observation_message(1, reason="intention_updated"),
                fixture("plant-medium-centered.jpg"),
            )
            await asyncio.wait_for(connection.recv(), 1)  # "Analyzing new shot…"
            guidance = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert guidance["text"] == "Move closer."
            assert [o["id"] for o in guidance["overlays"]] == ["aim"]
            assert guidance["overlays"][0]["expiresInMilliseconds"] == 1800


def test_result_overlays_capped_at_three_with_unique_ids() -> None:
    overlays = tuple(
        Overlay(f"o{i}", "arrow", ((0.1, 0.2), (0.8, 0.5))) for i in range(5)
    )
    result = make_result(1, overlays=overlays)
    assert len(result["overlays"]) == 3
    ids = [o["id"] for o in result["overlays"]]
    assert len(ids) == len(set(ids))


def test_overlay_wire_is_closed_and_enforces_geometry_rules() -> None:
    arrow = Overlay("aim", "arrow", ((0.1, 0.2), (0.8, 0.5)), text="aim here")
    wire = arrow.to_wire()
    assert wire["id"] == "aim"
    assert wire["kind"] == "arrow"
    assert wire["points"] == [{"x": 0.1, "y": 0.2}, {"x": 0.8, "y": 0.5}]
    assert wire["expiresInMilliseconds"] == 1800  # default freshness window

    valid = make_result(1, text="Move left.", overlays=(arrow,))
    validate_message(valid)  # schema-accepts a well-formed arrow

    # An arrow needs at least two points; a malformed overlay rejects the result.
    malformed = {
        **valid,
        "overlays": [
            {"id": "a", "kind": "arrow", "points": [{"x": 0.1, "y": 0.2}], "expiresInMilliseconds": 1800}
        ],
    }
    with pytest.raises(ProtocolError):
        validate_message(malformed)


# ---------------------------------------------------------------------------
# 5. Representative observable loop traces
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_guidance_hold_then_ready_observable_loop_trace() -> None:
    """A representative v1 loop: analyze -> guidance -> hold on equivalent frames
    -> settled change -> Ready, as an exact sequence of wire messages."""
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.")],
        verifications=[verification(VerificationOutcome.READY)],
    )
    async with open_test_server(reasoner) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
            await send_hello(connection, ["preview_jpeg"])
            baseline = fixture("plant-medium-centered.jpg")
            await send_observation(
                connection,
                observation_message(1, reason="intention_updated"),
                baseline,
            )
            analyzing = json.loads(await asyncio.wait_for(connection.recv(), 1))
            guidance = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert analyzing["text"] == "Analyzing new shot…"
            assert guidance["text"] == "Move closer."

            # Equivalent routine frames do not re-enter the VLM or emit guidance.
            for observation_id in range(2, 4):
                await send_observation(connection, observation_message(observation_id), baseline)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.recv(), 0.2)
            assert not reasoner.verification_requests

            # A material visual change must settle across two confirmations.
            changed = fixture("plant-close-filled.jpg")
            await send_observation(connection, observation_message(4), changed)
            await send_observation(connection, observation_message(5), changed)
            ready = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert ready["type"] == "result"
            assert ready["text"] == "Ready—take the shot."
            assert len(reasoner.verification_requests) == 1


@pytest.mark.asyncio
async def test_generated_reference_result_then_image_observable_loop_trace() -> None:
    """A representative v1 generated-reference trace: guidance result, then a
    capture request, then a result+result_image pair correlated by messageId."""
    reasoner = ScriptedReasoner(
        plans=[
            planning(
                "Ask the subject to sit.",
                sample_instruction="Change the subject from standing to sitting.",
            )
        ]
    )
    editor = FakeEditor()
    async with open_test_server(reasoner, editor) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
            await send_hello(
                connection,
                ["preview_jpeg", "high_resolution_request", "sample_image"],
            )
            await send_observation(
                connection,
                observation_message(
                    1,
                    reason="intention_updated",
                    intention="Show me a pose reference for a portrait",
                ),
                JPEG,
            )
            analyzing = json.loads(await asyncio.wait_for(connection.recv(), 1))
            guidance = json.loads(await asyncio.wait_for(connection.recv(), 1))
            capture = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert analyzing["text"] == "Analyzing new shot…"
            assert guidance["text"] == "Ask the subject to sit."
            assert capture["type"] == "capture_high_resolution"

            still = {
                "type": "high_resolution_image",
                "version": 1,
                "messageId": str(uuid.uuid4()),
                "observationId": None,
                "requestId": capture["requestId"],
                "timestampMs": 2000,
                "mimeType": "image/jpeg",
                "width": 32,
                "height": 32,
                "initiation": "agent",
            }
            await connection.send(encode_binary(still, JPEG))

            # Ordering: the result announces imageMessageId; the very next frame
            # is the result_image binary whose messageId equals that announcement.
            result = json.loads(await asyncio.wait_for(connection.recv(), 1))
            header, image = decode_binary(await asyncio.wait_for(connection.recv(), 1))
            assert result["text"] == guidance["text"]
            assert result["imageMessageId"] == header["messageId"]
            assert header["type"] == "result_image"
            assert image == JPEG
            assert len(editor.calls) == 1
