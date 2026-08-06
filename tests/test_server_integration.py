from __future__ import annotations

import asyncio
import json
import uuid

import pytest
from websockets.asyncio.client import connect

from camera_agent.adapters.fake import FakeEditor, ScriptedReasoner
from camera_agent.domain import VerificationOutcome
from camera_agent.protocol import decode_binary, encode_binary
from tests.helpers import (
    JPEG,
    fixture,
    observation_message,
    open_test_server,
    planning,
    send_hello,
    send_observation,
    verification,
)


@pytest.mark.asyncio
async def test_guidance_stays_unchanged_until_settled_difference() -> None:
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.")],
        verifications=[verification(VerificationOutcome.HOLD)],
    )
    async with open_test_server(reasoner) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
            await send_hello(connection, ["preview_jpeg"])
            first = observation_message(1, reason="intention_updated")
            baseline = fixture("plant-medium-centered.jpg")
            await send_observation(connection, first, baseline)
            initial = json.loads(await asyncio.wait_for(connection.recv(), 1))
            guidance = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert initial["text"] == "Analyzing new shot…"
            assert guidance["text"] == "Move closer."

            for observation_id in range(2, 6):
                await send_observation(
                    connection,
                    observation_message(observation_id),
                    baseline,
                )
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.recv(), 0.15)
            assert not reasoner.verification_requests

            close = fixture("plant-close-filled.jpg")
            await send_observation(connection, observation_message(6), close)
            await send_observation(connection, observation_message(7), close)
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(connection.recv(), 0.2)
            assert len(reasoner.verification_requests) == 1
            assert guidance["text"] == "Move closer."


@pytest.mark.asyncio
async def test_new_intention_immediately_clears_old_instruction() -> None:
    reasoner = ScriptedReasoner(
        plans=[planning("Move toward the plant."), planning("Frame the screen.")],
    )
    async with open_test_server(reasoner) as websocket_server:
        port = websocket_server.sockets[0].getsockname()[1]
        async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
            await send_hello(connection, ["preview_jpeg"])
            first = observation_message(
                1,
                reason="intention_updated",
                intention="A close shot of the plant",
            )
            await send_observation(connection, first, JPEG)
            await connection.recv()
            old = json.loads(await connection.recv())
            assert "plant" in old["text"]

            second = observation_message(
                2,
                reason="intention_updated",
                intention="A wide shot of the screen",
            )
            await send_observation(connection, second, JPEG)
            reset = json.loads(await asyncio.wait_for(connection.recv(), 1))
            new = json.loads(await asyncio.wait_for(connection.recv(), 1))
            assert reset["text"] == "Analyzing new shot…"
            assert new["text"] == "Frame the screen."
            assert reasoner.planning_requests[-1].intention == "A wide shot of the screen"


@pytest.mark.asyncio
async def test_generated_reference_is_isolated_and_has_no_pending_text() -> None:
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
            observation = observation_message(
                1,
                reason="intention_updated",
                intention="Show me a pose reference for a portrait",
            )
            await send_observation(connection, observation, JPEG)
            assert json.loads(await connection.recv())["text"] == "Analyzing new shot…"
            guidance = json.loads(await connection.recv())
            capture = json.loads(await connection.recv())
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
            result = json.loads(await asyncio.wait_for(connection.recv(), 1))
            header, image = decode_binary(await asyncio.wait_for(connection.recv(), 1))
            assert result["text"] == guidance["text"]
            assert header["type"] == "result_image"
            assert image == JPEG
            assert len(editor.calls) == 1
