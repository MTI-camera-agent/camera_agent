"""Tracing and resource high-water capture over public contract values.

The replay harness records complete state/output/invariant traces and
memory/queue/fragment/image high-water marks
(``docs/CAMERA_AGENT_V2_EVALUATION.md`` §3, §7). These traces observe only
public contract values (``RuntimeOutput`` and the Adapter calls a test drives
through the public seams) plus the mechanical resource counters the scripted
adapters own. They never read private reducer state.

- ``OutputTrace`` records the ordered stream of ``RuntimeOutput`` values a test
  observed through ``CoachingRuntime.outputs``;
- ``CallTrace`` records every Adapter invocation (context pack / authorized
  request) and its terminal outcome, as the public-observable proxy for the
  runtime-internal declarative effects; and
- ``ResourceHighWater`` tracks peak pending calls, peak concurrent physical
  calls, retained image pins, and send-queue depth.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from camera_agent.v2.contracts import RuntimeOutput, output_kind


@dataclass(slots=True)
class OutputTrace:
    """An ordered, append-only record of observed ``RuntimeOutput`` values.

    A test appends each output it observes through ``CoachingRuntime.outputs``
    in committed order. The trace exposes ordered access and reusable
    assertions over revisions and kinds.
    """

    _outputs: list[RuntimeOutput] = field(default_factory=list)

    def append(self, output: RuntimeOutput) -> None:
        self._outputs.append(output)

    def extend(self, outputs: "OutputTrace | list[RuntimeOutput]") -> None:
        items = outputs._outputs if isinstance(outputs, OutputTrace) else outputs
        self._outputs.extend(items)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._outputs)

    def __len__(self) -> int:
        return len(self._outputs)

    def __getitem__(self, index: int) -> RuntimeOutput:
        return self._outputs[index]

    @property
    def outputs(self) -> tuple[RuntimeOutput, ...]:
        return tuple(self._outputs)

    def kinds(self) -> tuple[Any, ...]:
        return tuple(output_kind(o) for o in self._outputs)

    def projections(self) -> tuple[Any, ...]:
        from camera_agent.v2.contracts import CoachingProjection

        return tuple(o for o in self._outputs if isinstance(o, CoachingProjection))

    def state_revisions(self) -> tuple[int, ...]:
        """Return every committed projection's ``state_revision`` in order."""
        return tuple(p.state_revision for p in self.projections())


@dataclass(slots=True)
class RecordedCall:
    """One Adapter invocation recorded by a scripted adapter.

    ``purpose`` is the ``RemotePurpose`` of the call, ``payload`` is the
    immutable context pack or authorized request the Adapter received, and
    ``outcome_kind`` records how the call terminated (``success | failure |
    cancelled | timed_out``). Outcome payloads are not stored here: a test
    reads them back from the scripted adapter's response table.

    A trace row is mutable: the terminal ``completed_at`` and ``outcome_kind``
    fields are filled in when the call matures, after the row was appended at
    admission time. It is a test trace record, not a contract value, so it is
    not frozen.
    """

    call_id: int
    purpose: str
    payload_kind: str
    started_at: float
    completed_at: float | None
    outcome_kind: str


@dataclass(slots=True)
class CallTrace:
    """An ordered record of every Adapter call driven through a public seam.

    This is the public-observable proxy for the runtime-internal declarative
    effects: the runtime launches an ``Effect`` that becomes an Adapter call,
    and the scripted Adapter records that call here. Tests assert request order,
    retry coalescing, and staleness through this trace rather than private
    reducer lanes.
    """

    _calls: list[RecordedCall] = field(default_factory=list)

    def record(self, call: RecordedCall) -> None:
        self._calls.append(call)

    def __iter__(self):  # type: ignore[no-untyped-def]
        return iter(self._calls)

    def __len__(self) -> int:
        return len(self._calls)

    def __getitem__(self, index: int) -> RecordedCall:
        return self._calls[index]

    @property
    def calls(self) -> tuple[RecordedCall, ...]:
        return tuple(self._calls)

    def purposes_in_order(self) -> tuple[str, ...]:
        return tuple(c.purpose for c in self._calls)


@dataclass(slots=True)
class ResourceHighWater:
    """Peak resource counters the scripted adapters and tests own.

    These counters capture the mandatory resource bounds a runtime must respect:
    peak pending work, peak concurrent physical calls (capped at two for the
    VLM), retained image pins, and send-queue depth. A runtime owns its own
    internal counters; these are the deterministic-test mirror over the public
    observable surface (pending Adapter calls and pinned fixtures).
    """

    peak_pending: int = 0
    peak_concurrent: int = 0
    peak_retained_images: int = 0
    peak_send_queue_frames: int = 0
    peak_send_queue_bytes: int = 0

    def observe_pending(self, count: int) -> None:
        if count > self.peak_pending:
            self.peak_pending = count

    def observe_concurrent(self, count: int) -> None:
        if count > self.peak_concurrent:
            self.peak_concurrent = count

    def observe_retained_images(self, count: int) -> None:
        if count > self.peak_retained_images:
            self.peak_retained_images = count

    def observe_send_queue(self, frames: int, bytes_: int) -> None:
        if frames > self.peak_send_queue_frames:
            self.peak_send_queue_frames = frames
        if bytes_ > self.peak_send_queue_bytes:
            self.peak_send_queue_bytes = bytes_

    def snapshot(self) -> dict[str, int]:
        return {
            "peak_pending": self.peak_pending,
            "peak_concurrent": self.peak_concurrent,
            "peak_retained_images": self.peak_retained_images,
            "peak_send_queue_frames": self.peak_send_queue_frames,
            "peak_send_queue_bytes": self.peak_send_queue_bytes,
        }
