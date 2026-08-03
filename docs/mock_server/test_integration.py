import asyncio
import json
import unittest
import uuid

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve

from mock_server.mock_camera_agent import handle_client
from mock_server.wire_protocol import decode_binary, encode_binary


class MockAgentIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_preview_receives_text_overlay_and_sample_image(self) -> None:
        async with serve(handle_client, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f"ws://127.0.0.1:{port}/camera") as connection:
                await connection.send(json.dumps({
                    "type": "hello",
                    "version": 1,
                    "messageId": str(uuid.uuid4()),
                    "client": "HelloCamera-iOS",
                    "capabilities": ["preview_jpeg"],
                }))
                await connection.send(json.dumps({
                    "type": "observation",
                    "version": 1,
                    "messageId": str(uuid.uuid4()),
                    "observationId": 1,
                    "timestampMs": 1000,
                    "reason": "stream",
                    "intention": "portrait",
                    "camera": {
                        "lensID": "wide-camera",
                        "lensName": "Back Camera",
                        "zoomFactor": 1,
                        "focalLength35mm": 24,
                        "focusPoint": None,
                        "exposurePoint": None,
                        "exposureBias": 0,
                        "iso": 50,
                        "exposureDurationSeconds": 0.01,
                        "whiteBalanceRedGain": 2,
                        "whiteBalanceGreenGain": 1,
                        "whiteBalanceBlueGain": 1.8,
                        "flashMode": "off",
                        "orientation": "portrait",
                        "frameWidth": 480,
                        "frameHeight": 640,
                        "cropAspectRatio": 0.75,
                        "rollRadians": 0,
                        "pitchRadians": 0,
                    },
                    "imageMessageId": "22222222-2222-4222-8222-222222222222",
                }))
                await connection.send(encode_binary({
                    "type": "preview_image",
                    "version": 1,
                    "messageId": "22222222-2222-4222-8222-222222222222",
                    "observationId": 1,
                    "requestId": None,
                    "timestampMs": 1000,
                    "mimeType": "image/jpeg",
                    "width": 480,
                    "height": 640,
                    "initiation": None,
                }, b"\xff\xd8fixture\xff\xd9"))

                result = json.loads(await connection.recv())
                self.assertEqual(result["type"], "result")
                self.assertEqual(result["observationId"], 1)
                self.assertGreaterEqual(len(result["overlays"]), 2)

                image_header, image = decode_binary(await connection.recv())
                self.assertEqual(image_header["type"], "result_image")
                self.assertEqual(image_header["messageId"], result["imageMessageId"])
                self.assertTrue(image.startswith(b"\x89PNG"))


if __name__ == "__main__":
    unittest.main()
