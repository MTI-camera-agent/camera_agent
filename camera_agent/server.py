"""Single-client protocol transport around the fixed-plan coaching loop."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from .artifacts import ArtifactRecorder
from .coaching import CoachingLoop
from .config import HarnessConfig
from .domain import CoachingEvent, CoachingEventKind, ObservationContext
from .ports import ImageEditor, Reasoner
from .protocol import (
    KNOWN_TYPES,
    ObservationAssembler,
    ProtocolError,
    decode_binary,
    make_result,
    validate_image_payload,
    validate_message,
)
from .reference import ReferenceState, ReferenceWorkflow

LOGGER = logging.getLogger("camera_agent")


class CameraAgentServer:
    def __init__(
        self,
        reasoner: Reasoner,
        editor: ImageEditor,
        config: HarnessConfig,
        *,
        artifacts: ArtifactRecorder | None = None,
    ) -> None:
        self._reasoner = reasoner
        self._editor = editor
        self._config = config
        self._artifacts = artifacts
        self._active: ServerConnection | None = None
        self._active_lock = asyncio.Lock()

    async def handle_client(self, connection: ServerConnection) -> None:
        path = connection.request.path if connection.request else ""
        if path != "/camera":
            await connection.close(code=1008, reason="Use the /camera endpoint")
            return
        async with self._active_lock:
            if self._active is not None:
                await connection.close(
                    code=1013,
                    reason="Another camera is already connected",
                )
                return
            self._active = connection
        session = ConnectionSession(
            connection,
            self._reasoner,
            self._editor,
            self._config,
            artifacts=self._artifacts,
        )
        try:
            await session.run()
        finally:
            await session.close()
            async with self._active_lock:
                if self._active is connection:
                    self._active = None

    async def run_forever(self) -> None:
        LOGGER.warning(
            "Trusted-LAN development server: ws:// traffic is unencrypted and unauthenticated"
        )
        LOGGER.info(
            "Listening on ws://%s:%s/camera",
            self._config.host,
            self._config.port,
        )
        async with serve(
            self.handle_client,
            self._config.host,
            self._config.port,
            max_size=self._config.max_message_bytes,
        ):
            await asyncio.get_running_loop().create_future()


class ConnectionSession:
    def __init__(
        self,
        connection: ServerConnection,
        reasoner: Reasoner,
        editor: ImageEditor,
        config: HarnessConfig,
        *,
        artifacts: ArtifactRecorder | None,
    ) -> None:
        self._connection = connection
        self._config = config
        self._assembler = ObservationAssembler(
            ttl_seconds=config.assembler_ttl_seconds
        )
        self._send_lock = asyncio.Lock()
        self._hello_received = False
        self._capabilities: set[str] = set()
        self._latest_context: ObservationContext | None = None
        self._last_sent_observation_id = 0
        self._task_id: str | None = None
        self._step_id: str | None = None
        self._instruction: str | None = None
        self._closed = False
        self._loop = CoachingLoop(
            reasoner,
            config.change_detection,
            self._accept_coaching_event,
            artifacts=artifacts,
        )
        self._reference = ReferenceWorkflow(
            editor,
            config,
            self._send_json,
            self._send_pair,
            self._reference_state,
        )

    async def run(self) -> None:
        peer = self._connection.remote_address
        LOGGER.info("camera connected peer=%s", peer)
        await self._loop.start()
        try:
            async for message in self._connection:
                if isinstance(message, str):
                    await self._receive_text(message)
                else:
                    await self._receive_binary(message)
        except ConnectionClosed:
            pass
        except (json.JSONDecodeError, ProtocolError, KeyError, TypeError, ValueError) as error:
            LOGGER.warning("protocol error peer=%s error=%s", peer, error)
            await self._connection.close(
                code=1008,
                reason="Invalid protocol-v1 message",
            )
        finally:
            LOGGER.info("camera disconnected peer=%s", peer)

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        await self._loop.close()
        await self._reference.close()

    async def _receive_text(self, raw: str) -> None:
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise ProtocolError("text message must be a JSON object")
        message_type = payload.get("type")
        if message_type not in KNOWN_TYPES:
            LOGGER.info("ignoring unknown text message type=%r", message_type)
            return
        message = validate_message(payload)
        if message_type == "hello":
            if self._hello_received:
                raise ProtocolError("hello may appear only once per connection")
            self._hello_received = True
            self._capabilities = set(message["capabilities"])
            LOGGER.info("hello capabilities=%s", sorted(self._capabilities))
            return
        if not self._hello_received:
            raise ProtocolError("hello must precede client messages")
        if message_type == "observation":
            context = self._assembler.add_metadata(message)
            if context is not None:
                await self._accept_context(context)
        elif message_type == "error":
            LOGGER.warning(
                "client error request=%s code=%s detail=%s",
                message.get("requestId"),
                message["code"],
                message["detail"],
            )
            await self._reference.accept_client_error(message.get("requestId"))
        else:
            raise ProtocolError(f"client sent server-only text message: {message_type}")

    async def _receive_binary(self, raw: bytes) -> None:
        if not self._hello_received:
            raise ProtocolError("hello must precede binary messages")
        header, payload = decode_binary(raw)
        validate_image_payload(header, payload)
        if header["type"] == "preview_image":
            context = self._assembler.add_preview(header, payload)
            if context is not None:
                await self._accept_context(context)
            return
        if header["type"] == "high_resolution_image":
            await self._reference.accept_still(header, payload)
            return
        raise ProtocolError(
            f"client sent server-only binary message: {header['type']}"
        )

    async def _accept_context(self, context: ObservationContext) -> None:
        self._latest_context = context
        await self._loop.submit(context)

    async def _accept_coaching_event(self, event: CoachingEvent) -> None:
        if self._closed:
            return
        if event.kind == CoachingEventKind.TASK_STARTED:
            self._task_id = event.task_id
            self._step_id = None
            self._instruction = None
            await self._reference.reset_for_task()
            await self._send_result(
                event.context,
                text="Analyzing new shot…",
            )
            return
        if event.task_id != self._task_id:
            return
        if event.kind == CoachingEventKind.FAILED:
            if self._instruction is None:
                await self._send_result(
                    event.context,
                    text="Coaching is temporarily unavailable—update your intention to retry.",
                )
            return
        if event.kind == CoachingEventKind.READY:
            self._step_id = None
            self._instruction = event.instruction or "Ready—take the shot."
            await self._send_result(event.context, text=self._instruction)
            await self._reference.request(event, self._capabilities)
            return
        if event.kind != CoachingEventKind.GUIDANCE or not event.instruction:
            return
        self._step_id = event.step_id
        self._instruction = event.instruction
        overlays = event.overlays
        latest = self._latest_context
        if (
            "overlay_primitives" not in self._capabilities
            or latest is None
            or event.context.camera_signature != latest.camera_signature
        ):
            overlays = ()
        await self._send_result(
            event.context,
            text=event.instruction,
            overlays=overlays,
        )
        await self._reference.request(event, self._capabilities)

    async def _send_result(
        self,
        source: ObservationContext,
        *,
        text: str,
        overlays=(),
    ) -> None:
        latest = self._latest_context or source
        observation_id = max(source.observation_id, self._last_sent_observation_id)
        if observation_id > latest.observation_id:
            observation_id = latest.observation_id
        await self._send_json(
            make_result(
                observation_id,
                text=text,
                overlays=tuple(overlays),
            )
        )
        self._last_sent_observation_id = max(
            self._last_sent_observation_id,
            observation_id,
        )

    def _reference_state(self) -> ReferenceState:
        return ReferenceState(
            task_id=self._task_id,
            step_id=self._step_id,
            context=self._latest_context,
            instruction=self._instruction,
        )

    async def _send_json(self, message: dict[str, Any]) -> None:
        async with self._send_lock:
            await self._connection.send(json.dumps(message, separators=(",", ":")))

    async def _send_pair(self, result: dict[str, Any], binary: bytes) -> None:
        async with self._send_lock:
            await self._connection.send(json.dumps(result, separators=(",", ":")))
            await self._connection.send(binary)


async def run_server(
    reasoner: Reasoner,
    editor: ImageEditor,
    config: HarnessConfig,
) -> None:
    artifacts = (
        ArtifactRecorder(config.debug_artifacts)
        if config.debug_artifacts
        else None
    )
    if artifacts is not None:
        LOGGER.info("debug artifacts directory=%s", artifacts.directory)
    server = CameraAgentServer(
        reasoner,
        editor,
        config,
        artifacts=artifacts,
    )
    await server.run_forever()
