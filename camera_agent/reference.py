"""Optional generated-reference workflow, isolated from coaching state."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .config import HarnessConfig
from .domain import CoachingEvent, ImageData, ObservationContext
from .ports import ImageEditor
from .protocol import (
    encode_binary,
    make_capture_request,
    make_result,
    make_result_image_header,
)

LOGGER = logging.getLogger("camera_agent.reference")


@dataclass(frozen=True, slots=True)
class ReferenceState:
    task_id: str | None
    step_id: str | None
    context: ObservationContext | None
    instruction: str | None


@dataclass(frozen=True, slots=True)
class _Pending:
    request_id: str
    task_id: str
    step_id: str | None
    source: ObservationContext
    edit_instruction: str


class ReferenceWorkflow:
    def __init__(
        self,
        editor: ImageEditor,
        config: HarnessConfig,
        send_json: Callable[[dict[str, Any]], Awaitable[None]],
        send_pair: Callable[[dict[str, Any], bytes], Awaitable[None]],
        current_state: Callable[[], ReferenceState],
    ) -> None:
        self._editor = editor
        self._config = config
        self._send_json = send_json
        self._send_pair = send_pair
        self._current_state = current_state
        self._pending: _Pending | None = None
        self._timeout_task: asyncio.Task[None] | None = None
        self._edit_task: asyncio.Task[None] | None = None
        self._attempted: set[tuple[str, str | None]] = set()

    async def request(
        self,
        event: CoachingEvent,
        capabilities: set[str],
    ) -> None:
        instruction = event.sample_instruction
        if not instruction:
            return
        if not {"high_resolution_request", "sample_image"}.issubset(capabilities):
            LOGGER.info("reference unavailable capabilities=%s", sorted(capabilities))
            return
        key = (event.task_id, event.step_id)
        if key in self._attempted or self._pending is not None or self._editing:
            return
        self._attempted.add(key)
        request_id = str(uuid.uuid4())
        self._pending = _Pending(
            request_id=request_id,
            task_id=event.task_id,
            step_id=event.step_id,
            source=event.context,
            edit_instruction=instruction,
        )
        LOGGER.info(
            "requesting generated-reference still request=%s task=%s step=%s",
            request_id,
            event.task_id,
            event.step_id,
        )
        await self._send_json(make_capture_request(request_id))
        self._timeout_task = asyncio.create_task(
            self._expire(request_id),
            name=f"reference-timeout-{request_id}",
        )

    async def reset_for_task(self) -> None:
        self._pending = None
        self._attempted.clear()
        for task in (self._timeout_task, self._edit_task):
            if task is not None:
                task.cancel()
        await asyncio.gather(
            *(task for task in (self._timeout_task, self._edit_task) if task),
            return_exceptions=True,
        )
        self._timeout_task = None
        self._edit_task = None

    async def accept_still(self, header: dict[str, Any], payload: bytes) -> None:
        if header["initiation"] == "user":
            LOGGER.info("received user-initiated still bytes=%s", len(payload))
            return
        pending = self._pending
        if pending is None or header.get("requestId") != pending.request_id:
            LOGGER.info("ignored unmatched transient still request=%s", header.get("requestId"))
            return
        self._pending = None
        if self._timeout_task is not None:
            self._timeout_task.cancel()
            self._timeout_task = None
        image = ImageData(
            data=payload,
            mime_type=header["mimeType"],
            width=int(header["width"]),
            height=int(header["height"]),
        )
        LOGGER.info(
            "received generated-reference still request=%s bytes=%s",
            pending.request_id,
            len(payload),
        )
        self._edit_task = asyncio.create_task(
            self._edit_and_send(pending, image),
            name=f"reference-edit-{pending.request_id}",
        )

    async def accept_client_error(self, request_id: str | None) -> None:
        if (
            request_id
            and self._pending is not None
            and self._pending.request_id == request_id
        ):
            self._pending = None
            if self._timeout_task is not None:
                self._timeout_task.cancel()
                self._timeout_task = None

    async def close(self) -> None:
        await self.reset_for_task()

    @property
    def _editing(self) -> bool:
        return self._edit_task is not None and not self._edit_task.done()

    async def _expire(self, request_id: str) -> None:
        await asyncio.sleep(self._config.still_timeout_seconds)
        if self._pending is not None and self._pending.request_id == request_id:
            LOGGER.warning("generated-reference still timed out request=%s", request_id)
            self._pending = None

    async def _edit_and_send(self, pending: _Pending, image: ImageData) -> None:
        instruction = (
            pending.edit_instruction
            + " Preserve the subject identity and all unrelated content, lighting, "
            "background, and framing except where the requested change requires it."
        )
        try:
            edited = await self._editor.edit(image, instruction)
            if len(edited.image.data) + 64 * 1024 > self._config.max_message_bytes:
                LOGGER.warning(
                    "discarded oversized reference request=%s bytes=%s",
                    pending.request_id,
                    len(edited.image.data),
                )
                return
            state = self._current_state()
            if (
                state.task_id != pending.task_id
                or state.step_id != pending.step_id
                or state.context is None
                or not state.instruction
            ):
                LOGGER.info("discarded stale generated reference request=%s", pending.request_id)
                return
            message_id = str(uuid.uuid4())
            result = make_result(
                state.context.observation_id,
                text=state.instruction,
                image_message_id=message_id,
            )
            header = make_result_image_header(
                message_id,
                state.context.observation_id,
                edited.image,
            )
            await self._send_pair(result, encode_binary(header, edited.image.data))
            LOGGER.info("sent generated reference request=%s", pending.request_id)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            LOGGER.warning(
                "generated reference failed request=%s error=%s",
                pending.request_id,
                error,
            )
