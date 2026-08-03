"""One fixed-plan, change-driven camera coaching loop."""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

from .artifacts import ArtifactRecorder
from .change_detection import ObservationChangeDetector
from .config import ChangeDetectionConfig
from .domain import (
    CoachingEvent,
    CoachingEventKind,
    ObservationContext,
    PlanningDecision,
    PlanningRequest,
    ShotPlan,
    VerificationDecision,
    VerificationOutcome,
    VerificationRequest,
    explicit_sample_permission,
    normalize_intention,
)
from .ports import Reasoner

LOGGER = logging.getLogger("camera_agent.coaching")

EventHandler = Callable[[CoachingEvent], Awaitable[None]]


class CoachingLoop:
    """Own every state transition in the observe/compare/analyze interaction."""

    def __init__(
        self,
        reasoner: Reasoner,
        change_config: ChangeDetectionConfig,
        emit: EventHandler,
        *,
        artifacts: ArtifactRecorder | None = None,
    ) -> None:
        self._reasoner = reasoner
        self._detector = ObservationChangeDetector(change_config)
        self._confirmations_required = change_config.routine_change_confirmations
        self._stale_global_mae = change_config.inference_stale_global_mae
        self._stale_block_mae = change_config.inference_stale_block_mae
        self._emit = emit
        self._artifacts = artifacts
        self._condition = asyncio.Condition()
        self._worker: asyncio.Task[None] | None = None
        self._closed = False
        self._generation = 0
        self._task_id: str | None = None
        self._intention = ""
        self._sample_allowed = False
        self._plan: ShotPlan | None = None
        self._active_step_index = 0
        self._instruction: str | None = None
        self._ready = False
        self._baseline: ObservationContext | None = None
        self._latest: ObservationContext | None = None
        self._queued: ObservationContext | None = None
        self._in_flight = False
        self._in_flight_context: ObservationContext | None = None
        self._hard_change_during_inference = False
        self._change_candidate: ObservationContext | None = None
        self._change_confirmations = 0

    @property
    def task_id(self) -> str | None:
        return self._task_id

    @property
    def current_instruction(self) -> str | None:
        return self._instruction

    @property
    def active_step_id(self) -> str | None:
        if self._plan is None or not self._plan.steps:
            return None
        return self._plan.steps[self._active_step_index].id

    async def start(self) -> None:
        if self._worker is None:
            self._worker = asyncio.create_task(
                self._run(),
                name="coaching-loop",
            )

    async def submit(self, context: ObservationContext) -> None:
        intention = normalize_intention(context.intention)
        task_started: CoachingEvent | None = None
        generation = 0
        async with self._condition:
            if self._closed:
                return
            if not intention:
                self._reset_locked()
                self._condition.notify_all()
                return
            is_new = (
                self._task_id is None
                or intention != self._intention
                or context.reason == "intention_updated"
            )
            if is_new:
                self._generation += 1
                generation = self._generation
                self._task_id = str(uuid.uuid4())
                self._intention = intention
                self._sample_allowed = explicit_sample_permission(intention)
                self._plan = None
                self._active_step_index = 0
                self._instruction = None
                self._ready = False
                self._baseline = None
                self._latest = context
                self._queued = None
                self._clear_candidate_locked()
                task_started = CoachingEvent(
                    kind=CoachingEventKind.TASK_STARTED,
                    task_id=self._task_id,
                    context=context,
                    intention=intention,
                )
            else:
                self._latest = context
                if self._in_flight and self._is_hard_change_during_inference(context):
                    self._hard_change_during_inference = True
                if not self._in_flight and self._queued is None:
                    self._consider_change_locked(context)
                self._condition.notify_all()
                return

        if task_started is not None:
            await self._emit(task_started)
        async with self._condition:
            if (
                not self._closed
                and generation == self._generation
                and self._task_id == task_started.task_id
            ):
                self._queued = context
                self._condition.notify_all()

    async def flush(self) -> None:
        async with self._condition:
            await self._condition.wait_for(
                lambda: self._closed
                or (self._queued is None and not self._in_flight)
            )

    async def close(self) -> None:
        async with self._condition:
            if self._closed:
                return
            self._closed = True
            self._condition.notify_all()
        if self._worker is not None:
            self._worker.cancel()
            await asyncio.gather(self._worker, return_exceptions=True)
            self._worker = None

    async def _run(self) -> None:
        while True:
            async with self._condition:
                await self._condition.wait_for(
                    lambda: self._closed or self._queued is not None
                )
                if self._closed:
                    return
                context = self._queued
                self._queued = None
                if context is None or self._task_id is None:
                    continue
                generation = self._generation
                task_id = self._task_id
                intention = self._intention
                sample_allowed = self._sample_allowed
                plan = self._plan
                active_step_index = self._active_step_index
                instruction = self._instruction
                ready = self._ready
                baseline = self._baseline
                self._in_flight = True
                self._in_flight_context = context
                self._hard_change_during_inference = False

            phase = "plan" if plan is None else "verify"
            result: PlanningDecision | VerificationDecision | None = None
            error: str | None = None
            try:
                if plan is None:
                    result = await self._reasoner.create_plan(
                        PlanningRequest(
                            intention=intention,
                            sample_allowed=sample_allowed,
                            camera=dict(context.camera),
                            observation_reason=context.reason,
                            current_image=context.image,
                        )
                    )
                else:
                    if baseline is None or instruction is None:
                        raise RuntimeError("verification state is incomplete")
                    result = await self._reasoner.verify_step(
                        VerificationRequest(
                            intention=intention,
                            sample_allowed=sample_allowed,
                            plan=plan,
                            active_step_index=active_step_index,
                            current_instruction=instruction,
                            was_ready=ready,
                            camera=dict(context.camera),
                            observation_reason=context.reason,
                            baseline_image=baseline.image,
                            current_image=context.image,
                        )
                    )
            except asyncio.CancelledError:
                raise
            except Exception as caught:
                error = str(caught)
                LOGGER.warning(
                    "reasoning failed phase=%s task=%s observation=%s error=%s",
                    phase,
                    task_id,
                    context.observation_id,
                    caught,
                )

            event: CoachingEvent | None = None
            disposition = "failed" if error is not None else "accepted"
            async with self._condition:
                current = self._latest
                task_changed = (
                    generation != self._generation or task_id != self._task_id
                )
                view_assessment = (
                    self._detector.assess(context, current)
                    if (
                        not task_changed
                        and current is not None
                        and current.image_message_id != context.image_message_id
                    )
                    else None
                )
                view_changed = (
                    not task_changed
                    and (
                        self._hard_change_during_inference
                        or (
                            view_assessment is not None
                            and (
                                view_assessment.visual_global_mae
                                >= self._stale_global_mae
                                or view_assessment.visual_block_mae
                                >= self._stale_block_mae
                            )
                        )
                    )
                )
                if task_changed:
                    disposition = "superseded"
                elif view_changed:
                    disposition = "stale"
                    self._baseline = context
                elif error is None and result is not None:
                    try:
                        event = self._accept_result_locked(
                            task_id,
                            intention,
                            context,
                            result,
                        )
                        # Frames received during inference that differ only by
                        # ordinary held-preview drift are equivalent to the
                        # analyzed source. Recording the newest equivalent view
                        # prevents that drift from immediately scheduling
                        # another call.
                        if current is not None:
                            self._baseline = current
                    except Exception as caught:
                        error = str(caught)
                        disposition = "failed"
                        self._baseline = context
                else:
                    # Prevent an unchanged failed frame from causing a tight loop.
                    self._baseline = context

            if self._artifacts is not None:
                self._artifacts.record_attempt(
                    phase=phase,
                    task_id=task_id,
                    intention=intention,
                    context=context,
                    baseline_image_message_id=(
                        baseline.image_message_id if baseline is not None else None
                    ),
                    disposition=disposition,
                    result=result,
                    error=error,
                )
            if event is not None:
                await self._emit(event)
            elif disposition == "failed" and plan is None:
                await self._emit(
                    CoachingEvent(
                        kind=CoachingEventKind.FAILED,
                        task_id=task_id,
                        context=context,
                        intention=intention,
                    )
                )
            async with self._condition:
                self._in_flight = False
                self._in_flight_context = None
                self._hard_change_during_inference = False
                if (
                    generation == self._generation
                    and task_id == self._task_id
                    and self._latest is not None
                ):
                    # A result for a moving view is never applied. The newest
                    # frame must still pass the normal settling confirmation;
                    # otherwise a slow first inference could immediately
                    # analyze another in-motion frame.
                    self._consider_change_locked(self._latest)
                self._condition.notify_all()

    def _accept_result_locked(
        self,
        task_id: str,
        intention: str,
        context: ObservationContext,
        result: PlanningDecision | VerificationDecision,
    ) -> CoachingEvent | None:
        self._baseline = context
        self._clear_candidate_locked()
        if isinstance(result, PlanningDecision):
            self._plan = result.plan
            self._active_step_index = 0
            if result.ready:
                self._ready = True
                self._instruction = "Ready—take the shot."
                return self._event(
                    CoachingEventKind.READY,
                    task_id,
                    intention,
                    context,
                    instruction=self._instruction,
                    sample_instruction=result.sample_instruction,
                )
            if not result.plan.steps or result.instruction is None:
                raise RuntimeError("accepted planning result is incomplete")
            self._ready = False
            self._instruction = result.instruction
            return self._event(
                CoachingEventKind.GUIDANCE,
                task_id,
                intention,
                context,
                step_id=result.plan.steps[0].id,
                instruction=result.instruction,
                overlays=result.overlays,
                sample_instruction=result.sample_instruction,
            )

        if result.outcome == VerificationOutcome.HOLD:
            return None
        if result.outcome == VerificationOutcome.REVISE:
            if result.instruction is None:
                raise RuntimeError("revised guidance has no instruction")
            self._ready = False
            self._instruction = result.instruction
            return self._event(
                CoachingEventKind.GUIDANCE,
                task_id,
                intention,
                context,
                step_id=self.active_step_id,
                instruction=result.instruction,
                overlays=result.overlays,
                sample_instruction=result.sample_instruction,
            )
        if result.outcome == VerificationOutcome.ADVANCE:
            self._active_step_index += 1
            self._ready = False
            self._instruction = result.instruction
            return self._event(
                CoachingEventKind.GUIDANCE,
                task_id,
                intention,
                context,
                step_id=self.active_step_id,
                instruction=result.instruction,
                overlays=result.overlays,
                sample_instruction=result.sample_instruction,
            )
        if result.outcome == VerificationOutcome.RESUME:
            if result.step_index is None:
                raise RuntimeError("resume result has no step index")
            self._active_step_index = result.step_index
            self._ready = False
            self._instruction = result.instruction
            return self._event(
                CoachingEventKind.GUIDANCE,
                task_id,
                intention,
                context,
                step_id=self.active_step_id,
                instruction=result.instruction,
                overlays=result.overlays,
                sample_instruction=result.sample_instruction,
            )
        self._ready = True
        self._instruction = "Ready—take the shot."
        return self._event(
            CoachingEventKind.READY,
            task_id,
            intention,
            context,
            instruction=self._instruction,
        )

    def _consider_change_locked(self, context: ObservationContext) -> None:
        if (
            self._baseline is None
            or self._task_id is None
            or self._in_flight
            or self._queued is not None
        ):
            return
        if self._plan is not None and self._instruction is None:
            return
        if context.image_message_id == self._baseline.image_message_id:
            self._clear_candidate_locked()
            return
        changed = self._detector.assess(self._baseline, context)
        if not changed.significant:
            self._clear_candidate_locked()
            return
        if self._confirmations_required <= 1:
            self._queued = context
            self._clear_candidate_locked()
            return
        previous = self._change_candidate
        if previous is None:
            self._change_candidate = context
            self._change_confirmations = 1
            return
        settled = not self._detector.assess(previous, context).significant
        self._change_candidate = context
        self._change_confirmations = (
            self._change_confirmations + 1 if settled else 1
        )
        if self._change_confirmations >= self._confirmations_required:
            self._queued = context
            self._clear_candidate_locked()

    def _reset_locked(self) -> None:
        self._generation += 1
        self._task_id = None
        self._intention = ""
        self._sample_allowed = False
        self._plan = None
        self._active_step_index = 0
        self._instruction = None
        self._ready = False
        self._baseline = None
        self._latest = None
        self._queued = None
        self._in_flight_context = None
        self._hard_change_during_inference = False
        self._clear_candidate_locked()

    def _clear_candidate_locked(self) -> None:
        self._change_candidate = None
        self._change_confirmations = 0

    def _is_hard_change_during_inference(
        self,
        context: ObservationContext,
    ) -> bool:
        source = self._in_flight_context
        if source is None:
            return False
        return (
            context.reason
            in {"zoom_changed", "focus_changed", "exposure_changed"}
            or source.camera_signature != context.camera_signature
        )

    @staticmethod
    def _event(
        kind: CoachingEventKind,
        task_id: str,
        intention: str,
        context: ObservationContext,
        *,
        step_id: str | None = None,
        instruction: str | None = None,
        overlays=(),
        sample_instruction: str | None = None,
    ) -> CoachingEvent:
        return CoachingEvent(
            kind=kind,
            task_id=task_id,
            context=context,
            intention=intention,
            step_id=step_id,
            instruction=instruction,
            overlays=tuple(overlays),
            sample_instruction=sample_instruction,
        )
