#!/usr/bin/env python3
"""Minimal bidirectional connection test for the HelloCamera iOS client."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

try:
    from .wire_protocol import decode_binary
except ImportError:
    from wire_protocol import decode_binary

MAX_MESSAGE_BYTES = 8 * 1024 * 1024
OUTPUT_PATH = Path(__file__).resolve().parent / "received" / "latest_preview.jpg"


async def send_simple_message(
    connection: ServerConnection,
    observation_id: int,
) -> None:
    """Send one text-only instruction associated with a received observation."""
    result = {
        "type": "result",
        "version": 1,
        "messageId": str(uuid.uuid4()),
        "observationId": observation_id,
        "timestampMs": int(time.time() * 1000),
        "text": (
            "Connection successful — the desktop received observation "
            f"{observation_id} and saved its preview image."
        ),
    }
    await connection.send(json.dumps(result, separators=(",", ":")))
    print(f"[sent to iPhone] {result['text']}", flush=True)


async def receive_observations(connection: ServerConnection) -> None:
    """Print observations, save their preview JPEG, and send one test result."""
    path = connection.request.path if connection.request else ""
    if path != "/camera":
        await connection.close(code=1008, reason="Use the /camera endpoint")
        return

    pending_observations: dict[str, dict[str, Any]] = {}
    test_message_sent = False
    peer = connection.remote_address
    print(f"[connected] {peer}", flush=True)

    try:
        async for message in connection:
            if isinstance(message, str):
                payload = json.loads(message)
                message_type = payload.get("type")

                if message_type == "hello":
                    print(
                        f"[hello] client={payload.get('client')} "
                        f"capabilities={payload.get('capabilities')}",
                        flush=True,
                    )
                elif message_type == "observation":
                    image_message_id = payload.get("imageMessageId")
                    if not isinstance(image_message_id, str):
                        raise ValueError("observation is missing imageMessageId")
                    pending_observations[image_message_id] = payload
                    print("[observation]", flush=True)
                    print(
                        json.dumps(payload, indent=2, ensure_ascii=False),
                        flush=True,
                    )
                elif message_type == "error":
                    print(
                        "[client error] "
                        f"code={payload.get('code')} detail={payload.get('detail')}",
                        flush=True,
                    )
                else:
                    print(f"[text message] {payload}", flush=True)
                continue

            header, image_bytes = decode_binary(message)
            if header.get("type") != "preview_image":
                print(
                    f"[binary message] type={header.get('type')} "
                    f"bytes={len(image_bytes)}",
                    flush=True,
                )
                continue

            image_message_id = header.get("messageId")
            observation = pending_observations.pop(image_message_id, None)
            if observation is None:
                print(
                    f"[ignored preview] no observation for {image_message_id}",
                    flush=True,
                )
                continue

            observation_id = int(observation["observationId"])
            if int(header["observationId"]) != observation_id:
                raise ValueError("preview observationId does not match metadata")
            if not image_bytes:
                raise ValueError("preview image payload is empty")

            OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary_path = OUTPUT_PATH.with_suffix(".tmp")
            temporary_path.write_bytes(image_bytes)
            temporary_path.replace(OUTPUT_PATH)
            print(
                f"[saved preview] observation={observation_id} "
                f"bytes={len(image_bytes)} path={OUTPUT_PATH}",
                flush=True,
            )

            if not test_message_sent:
                await send_simple_message(connection, observation_id)
                test_message_sent = True
    except ConnectionClosed:
        pass
    except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
        print(f"[protocol error] {error}", flush=True)
        await connection.close(code=1008, reason="Invalid camera-client message")
    finally:
        print(f"[disconnected] {peer}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    async def run_server() -> None:
        print(
            f"Listening on ws://{args.host}:{args.port}/camera\n"
            "Enter ws://<Windows-hotspot-IP>:"
            f"{args.port}/camera on the iPhone.",
            flush=True,
        )
        async with serve(
            receive_observations,
            args.host,
            args.port,
            max_size=MAX_MESSAGE_BYTES,
        ):
            await asyncio.get_running_loop().create_future()

    try:
        asyncio.run(run_server())
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)


if __name__ == "__main__":
    main()
