#!/usr/bin/env python3
"""Protocol-v1 test fixture for the HelloCamera iOS client."""

from __future__ import annotations

import argparse
import asyncio
import json
import socket
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from websockets.asyncio.server import ServerConnection, serve

try:
    from .protocol_schema import ProtocolValidationError, validate_message
    from .wire_protocol import decode_binary, encode_binary, reference_png
except ImportError:
    from protocol_schema import ProtocolValidationError, validate_message
    from wire_protocol import decode_binary, encode_binary, reference_png

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 8 * 1024 * 1024


def now_ms() -> int:
    return int(time.time() * 1000)


@dataclass
class ClientState:
    observations: dict[int, dict[str, Any]] = field(default_factory=dict)
    preview_count: int = 0
    last_result_time: float = 0
    hello_received: bool = False


async def send_result(connection: ServerConnection, observation: dict[str, Any], include_image: bool) -> None:
    observation_id = int(observation["observationId"])
    image_message_id = str(uuid.uuid4()) if include_image else None
    result = {
        "type": "result",
        "version": PROTOCOL_VERSION,
        "messageId": str(uuid.uuid4()),
        "observationId": observation_id,
        "timestampMs": now_ms(),
        "text": "Move the main subject slightly left, then keep the horizon on the upper guide.",
        "overlays": [
            {
                "id": "subject-target",
                "kind": "rectangle",
                "points": [{"x": 0.18, "y": 0.28}, {"x": 0.52, "y": 0.78}],
                "color": "#FFD340",
                "lineWidth": 3,
                "expiresInMilliseconds": 1800,
            },
            {
                "id": "move-left",
                "kind": "arrow",
                "points": [{"x": 0.70, "y": 0.54}, {"x": 0.54, "y": 0.54}],
                "color": "#62E6FF",
                "lineWidth": 4,
                "expiresInMilliseconds": 1800,
            },
            {
                "id": "label",
                "kind": "text",
                "points": [{"x": 0.18, "y": 0.27}],
                "text": "Place subject here",
                "color": "#FFD340",
                "expiresInMilliseconds": 1800,
            },
        ],
        "imageMessageId": image_message_id,
    }
    validate_message(result)
    await connection.send(json.dumps(result, separators=(",", ":")))

    if image_message_id:
        image = reference_png()
        header = {
            "type": "result_image",
            "version": PROTOCOL_VERSION,
            "messageId": image_message_id,
            "observationId": observation_id,
            "requestId": None,
            "timestampMs": now_ms(),
            "mimeType": "image/png",
            "width": 360,
            "height": 240,
            "initiation": None,
        }
        validate_message(header)
        await connection.send(encode_binary(header, image))


async def handle_client(connection: ServerConnection) -> None:
    path = connection.request.path if connection.request else ""
    if path != "/camera":
        await connection.close(code=1008, reason="Use the /camera endpoint")
        return

    peer = connection.remote_address
    state = ClientState()
    print(f"[connected] {peer}", flush=True)
    try:
        async for message in connection:
            if isinstance(message, str):
                payload = validate_message(json.loads(message))
                message_type = payload.get("type")
                if message_type == "hello":
                    state.hello_received = True
                    print(f"[hello] {payload.get('client')} capabilities={payload.get('capabilities')}", flush=True)
                elif message_type == "observation":
                    if not state.hello_received:
                        raise ProtocolValidationError("hello must precede observations")
                    observation_id = int(payload["observationId"])
                    state.observations[observation_id] = payload
                    camera = payload.get("camera", {})
                    print(
                        f"[observation {observation_id}] reason={payload.get('reason')} "
                        f"lens={camera.get('lensName')} zoom={camera.get('zoomFactor')} "
                        f"intent={payload.get('intention')!r}",
                        flush=True,
                    )
                elif message_type == "error":
                    print(
                        f"[client error] request={payload.get('requestId')} "
                        f"code={payload.get('code')} detail={payload.get('detail')}",
                        flush=True,
                    )
            else:
                header, image = decode_binary(message)
                validate_message(header)
                if not image:
                    raise ProtocolValidationError("binary image payload must not be empty")
                message_type = header.get("type")
                if message_type == "preview_image":
                    state.preview_count += 1
                    observation_id = int(header["observationId"])
                    observation = state.observations.pop(observation_id, None)
                    if not observation:
                        continue
                    if observation["imageMessageId"] != header["messageId"]:
                        raise ProtocolValidationError(
                            "preview imageMessageId does not match its observation"
                        )
                    now = time.monotonic()
                    if now - state.last_result_time >= 1:
                        state.last_result_time = now
                        await send_result(
                            connection,
                            observation,
                            include_image=state.preview_count % 10 == 1,
                        )
                    if state.preview_count % 20 == 0:
                        request = {
                            "type": "capture_high_resolution",
                            "version": PROTOCOL_VERSION,
                            "requestId": str(uuid.uuid4()),
                        }
                        validate_message(request)
                        print(f"[request still] {request['requestId']}", flush=True)
                        await connection.send(json.dumps(request, separators=(",", ":")))
                elif message_type == "high_resolution_image":
                    print(
                        f"[still] initiation={header.get('initiation')} request={header.get('requestId')} "
                        f"{header.get('width')}x{header.get('height')} bytes={len(image)}",
                        flush=True,
                    )
    except (json.JSONDecodeError, ProtocolValidationError, ValueError) as error:
        print(f"[protocol error] {peer}: {error}", flush=True)
        await connection.close(code=1008, reason="Invalid protocol-v1 message")
    except Exception as error:
        print(f"[connection error] {peer}: {error}", flush=True)
    finally:
        print(f"[disconnected] {peer}", flush=True)


def local_addresses(port: int) -> list[str]:
    addresses = {"127.0.0.1"}
    try:
        addresses.update(
            item[4][0]
            for item in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET)
        )
    except socket.gaierror:
        pass
    return [f"ws://{address}:{port}/camera" for address in sorted(addresses)]


async def run(host: str, port: int) -> None:
    print("HelloCamera mock agent listening on:", flush=True)
    for address in local_addresses(port):
        print(f"  {address}", flush=True)
    print("Use the Windows/desktop LAN address from the iPhone.", flush=True)
    async with serve(handle_client, host, port, max_size=MAX_MESSAGE_BYTES):
        await asyncio.get_running_loop().create_future()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.host, args.port))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
