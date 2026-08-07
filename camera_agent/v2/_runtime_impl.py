"""The tracer-bullet ``CoachingRuntime`` implementation (issues #21–#23).

This is the concrete realization of the dormant v2 ``CoachingRuntime``
Interface. The first tracer bullet (#21) admitted ordered semantic events from
no intention through Task creation and initial Strategy completion to one
persistent Instruction or immediate evidence-backed Ready. Issue #22 added
deterministic frame-signal measurement and asymmetric Settled hysteresis. Issue
#23 adds progress assessment: every accepted settled view produces one
Evidence Snapshot assessing each Must-have once, and the achieved / improving /
deviating / Ready policies preserve immutable Instruction semantics while
keeping Nice-to-haves from instructing or blocking Ready.

Scope (issue #21 acceptance criteria):

- No intention produces ``needs_intention``, truthful waiting Activity, no
  reasoning, and a complete immutable projection (T01).
- A changed/explicitly-updated intention invalidates old authority, allocates
  application-owned Task provenance, and immediately projects truthful
  Orienting Activity (T02).
- A scripted Strategy completion is admitted atomically and produces one
  actionable Instruction or same-Evidence Ready without a second call (T03/T04).
- Concurrent submissions receive one authoritative mailbox order; state is
  committed before effects launch or outputs become deliverable; stale
  completions are harmless; idle ``close`` terminates output iteration (U12).

Everything else (Evidence settling hysteresis, progress evaluation, heartbeat,
recovery, visual sidecar, retry/deadline, protocol projection) lands in later
v2 tickets against the same public Interface. This module remains dormant v2
code: it is not imported by the production composition root until the
atomic-cutover ticket.

The internal transition is the pure ``current state + one semantic event ->
next state + declarative effects`` contract; callers and tests observe only
``submit``/``outputs``/``close`` and the immutable ``RuntimeOutput`` stream.
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from uuid import UUID

from .config import RuntimeConfig
from .contracts import (
    AdapterFailureEvent,
    CoachingProjection,
    IntentionAcceptedEvent,
    ObservationReceivedEvent,
    ReasonerProgressEvent,
    Receipt,
    ReceiptDisposition,
    ReasonerStrategyEvent,
    RuntimeEvent,
    RuntimeOutput,
    TaskEndedEvent,
    UserCaptureEvent,
)
from .identity import (
    AnalysisPurpose,
    Provenance,
    RemotePurpose,
    new_identity,
)
from .seams import (
    AdapterFailure,
    ContextImage,
    ProgressContextPack,
    ProgressEvidence,
    StrategyContextPack,
    StrategyProposal,
)
from .values import (
    Activity,
    ActivityKind,
    Addressee,
    AnalysisState,
    CandidateAction,
    ConnectionState,
    CoachingPhase,
    Criterion,
    CriterionClassification,
    CriterionImportance,
    EvidenceIdentity,
    EvidenceSnapshot,
    EvidenceState,
    FrameSignals,
    Instruction,
    InstructionDisposition,
    InstructionFreshness,
    InstructionKind,
    Mode,
    Observation,
    Readiness,
    ReadinessState,
    ShotStrategy,
    Task,
    TypedFailure,
)

# Marker enqueued by ``close`` so a blocked ``outputs`` reader wakes and the
# public async iterator terminates deterministically without depending on
# physical cancellation of in-flight effects.
_CLOSE_SENTINEL = object()


def _retrieve_exception(task: asyncio.Task) -> None:
    """Swallow/retrieve background-effect exceptions so asyncio never warns.

    Effect tasks translate every outcome (including provider exceptions) into a
    correlated ``RuntimeEvent`` and re-enter the mailbox. An unhandled exception
    here is a runtime bug; retrieving it avoids ``Task exception was never
    retrieved`` noise while still surfacing via ``task.exception()`` if needed.
    """

    if task.cancelled():
        return
    task.exception()


class _CoachingRuntime:
    """The concrete (non-Protocol) ``CoachingRuntime`` for the tracer bullet.

    The public surface is exactly ``submit``/``outputs``/``close``; every other
    attribute is private implementation structure. No caller receives writable
    state lanes, coordinates reducer steps, or bypasses completion admission.
    """

    def __init__(
        self,
        config: RuntimeConfig,
        reasoner: Any,
        editor: Any,
        *,
        signal_computer: Any = None,
    ) -> None:
        self._config = config
        self._reasoner = reasoner
        self._editor = editor
        self._signal_computer = signal_computer

        self._session_id = new_identity()
        self._lock = asyncio.Lock()
        self._output_queue: asyncio.Queue[RuntimeOutput | object] = asyncio.Queue()
        self._effect_tasks: set[asyncio.Task] = set()
        self._closed_event = asyncio.Event()

        self._next_order = 0
        self._next_revision = 0
        self._seen_event_ids: set[UUID] = set()
        self._closed = False

        # Authoritative state (spec §3.2). Only the reducer mutates these, under
        # the mailbox lock, before any output is enqueued or effect launched.
        self._task: Task | None = None
        self._task_epoch = -1
        self._mode = Mode.ACTIVE
        self._connection = ConnectionState.CONNECTED
        self._evidence: EvidenceIdentity | None = None
        self._strategy: ShotStrategy | None = None
        self._instruction: Instruction | None = None
        self._instruction_criterion_id: UUID | None = None
        self._instruction_dispositions: dict[UUID, InstructionDisposition] = {}
        self._readiness: Readiness | None = None
        self._analysis = AnalysisState.IDLE
        self._analysis_purpose: AnalysisPurpose | None = None
        self._authoritative_run: Provenance | None = None
        self._last_snapshot: EvidenceSnapshot | None = None
        self._previous_snapshot: EvidenceSnapshot | None = None

        # Settling hysteresis (spec §4.3). The runtime emits a new Evidence
        # identity only when configurable mutually equivalent post-change
        # observations meet both a confirmation count and a dwell duration.
        # ``_settled_observation`` is the exact analyzed observation Evidence
        # and spatial overlays are bound to; ``_latest_observation`` is the
        # newest view proven equivalent to it, which text MAY be projected
        # against. A hard camera-context or material visual/quality change
        # immediately invalidates settled Evidence, overlays, queued work, and
        # the authoritative run token.
        self._evidence_state = EvidenceState.MISSING
        self._settling_baseline: Observation | None = None
        self._settling_count = 0
        self._settling_first_arrival: float | None = None
        self._settled_observation: Observation | None = None
        self._latest_observation: Observation | None = None
        self._last_signals: FrameSignals | None = None
        self._last_projection_key: tuple | None = None

        # The initial committed state (revision 0) is a complete immutable
        # projection: no intention -> needs_intention with truthful waiting
        # Activity and no reasoning. Emitted at construction so a caller that
        # never submits still observes the authoritative initial state.
        initial = self._build_projection()
        self._output_queue.put_nowait(initial)
        self._last_projection_key = self._projection_key(initial)

    # --- public Interface ------------------------------------------------

    async def submit(self, event: RuntimeEvent) -> Receipt:
        """Admit one semantic event in authoritative mailbox order.

        Acknowledges admission without waiting for remote work. The reducer
        commits next state, enqueues resulting outputs, and collects effects
        all under the mailbox lock; effects are launched only after the lock is
        released so state always commits before effects run or outputs deliver.
        """
        async with self._lock:
            order = self._take_order()
            if self._closed:
                # Closed runtime: authority is invalidated; any late submission
                # is a harmless stale discard.
                return Receipt(
                    event_id=event.event_id,
                    order=order,
                    disposition=ReceiptDisposition.STALE,
                )
            if event.event_id in self._seen_event_ids:
                return Receipt(
                    event_id=event.event_id,
                    order=order,
                    disposition=ReceiptDisposition.DUPLICATE,
                )
            self._seen_event_ids.add(event.event_id)
            effect_specs, outputs, disposition = self._apply(event)
            for output in outputs:
                self._output_queue.put_nowait(output)
            pending = effect_specs
        # Launch effects only after state commit + output enqueue so async work
        # never mutates state or writes ahead of the committed projection.
        for spec in pending:
            self._launch_reasoner_effect(spec[0], spec[1])
        return Receipt(event_id=event.event_id, order=order, disposition=disposition)

    async def outputs(self):
        """Yield complete immutable projections in committed mailbox order.

        Terminates deterministically after ``close``: close sets the closed
        event and enqueues a sentinel, so a reader blocked on the queue wakes
        and stops, and a reader created after close drains committed buffered
        outputs and stops — without depending on physical cancellation of
        in-flight effects.
        """
        while True:
            if self._closed_event.is_set():
                # Close fired before/while reading: drain any outputs committed
                # before close (and the sentinel if still buffered), then stop.
                while not self._output_queue.empty():
                    item = self._output_queue.get_nowait()
                    if item is _CLOSE_SENTINEL:
                        return
                    yield item  # type: ignore[misc]
                return
            item = await self._output_queue.get()
            if item is _CLOSE_SENTINEL:
                return
            yield item  # type: ignore[misc]

    async def close(self) -> None:
        """Immediately invalidate outstanding authority and stop output iteration.

        Cancels in-flight effect tasks (best-effort physical cancellation), sets
        the closed event, and enqueues a sentinel so every blocked ``outputs``
        reader wakes and terminates. Late completions that race with close
        re-enter ``submit`` and are discarded as stale. The runtime never blocks
        on physical cancellation of a non-cancellable call.
        """
        async with self._lock:
            if self._closed:
                return
            self._closed = True
            for task in list(self._effect_tasks):
                task.cancel()
            self._output_queue.put_nowait(_CLOSE_SENTINEL)
        self._closed_event.set()

    # --- mailbox ordering ------------------------------------------------

    def _take_order(self) -> int:
        order = self._next_order
        self._next_order += 1
        return order

    def _commit_projection(self) -> CoachingProjection | None:
        # Duplicate-projection suppression: emit a new projection only when the
        # user-visible semantic content changed. Equivalent routine frames that
        # coalesce without a new Evidence identity or instruction change produce
        # no inference backlog. The committed revision advances only when the
        # projection is actually emitted.
        provisional = self._build_projection()
        key = self._projection_key(provisional)
        if self._last_projection_key is not None and key == self._last_projection_key:
            return None
        self._next_revision += 1
        self._last_projection_key = key
        return replace(provisional, state_revision=self._next_revision)

    def _build_projection(self) -> CoachingProjection:
        phase = self._derive_phase()
        activity = self._derive_activity(phase)
        return CoachingProjection(
            session_id=self._session_id,
            state_revision=self._next_revision,
            task=self._task,
            phase=phase,
            instruction=self._instruction,
            activity=activity,
            overlays=None,
            available_actions=(),
            visual_guidance=None,
            readiness=self._readiness,
        )

    def _projection_key(self, projection: CoachingProjection) -> tuple:
        """The committed semantic state of the runtime, ignoring revision.

        Two consecutive reducer transitions that produce the same key are
        duplicates and only the first is emitted. This implements duplicate-
        projection suppression so equivalent routine frames that coalesce
        without a new Evidence identity do not produce an inference backlog,
        while real state transitions (settling, strategy requested, an
        Instruction admitted, a freshness change) still emit a projection.
        """

        instruction = projection.instruction
        instruction_key = (
            (
                instruction.instruction_id,
                instruction.kind,
                instruction.text,
                instruction.addressee,
                instruction.freshness,
            )
            if instruction is not None
            else None
        )
        readiness = projection.readiness
        readiness_key = (
            (
                readiness.state,
                readiness.evidence_snapshot_id,
                readiness.supporting_evidence_id,
            )
            if readiness is not None
            else None
        )
        task = projection.task
        task_key = (
            (
                task.task_id,
                task.strategy_revision,
            )
            if task is not None
            else None
        )
        activity = projection.activity
        activity_key = (activity.kind, activity.text) if activity is not None else None
        return (
            projection.phase,
            task_key,
            instruction_key,
            activity_key,
            readiness_key,
            self._analysis,
            self._analysis_purpose,
        )

    # --- phase / activity derivation (spec §3.2 first-matching rule) ------

    def _derive_phase(self) -> str:
        if self._task is None:
            return CoachingPhase.NEEDS_INTENTION
        if self._connection is ConnectionState.DISCONNECTED:
            return CoachingPhase.RECOVERING
        if self._mode is Mode.PAUSED:
            return CoachingPhase.PAUSED
        if self._analysis in (AnalysisState.REQUESTED, AnalysisState.RUNNING) and (
            self._analysis_purpose in (AnalysisPurpose.EVALUATE, AnalysisPurpose.REPLAN)
        ):
            return CoachingPhase.EVALUATING
        if self._instruction is not None and (
            self._instruction.kind is InstructionKind.READY
        ):
            return CoachingPhase.READY
        if self._instruction is not None and (
            self._instruction.kind is InstructionKind.ACTION
        ):
            return CoachingPhase.COACHING
        return CoachingPhase.ORIENTING

    def _derive_activity(self, phase: str) -> Activity:
        if phase == CoachingPhase.NEEDS_INTENTION:
            return Activity(
                ActivityKind.WAITING, "Tell me what you'd like to photograph."
            )
        if phase == CoachingPhase.RECOVERING:
            return Activity(ActivityKind.RECOVERING, "Reconnecting — hold still.")
        if phase == CoachingPhase.PAUSED:
            return Activity(ActivityKind.WAITING, "Coaching is paused.")
        if phase == CoachingPhase.EVALUATING:
            return Activity(ActivityKind.WORKING, "Checking your progress.")
        if phase == CoachingPhase.ORIENTING:
            return Activity(
                ActivityKind.WORKING, "Looking at the scene to plan your shot."
            )
        if phase == CoachingPhase.READY:
            return Activity(ActivityKind.WORKING, "Ready.")
        return Activity(ActivityKind.WORKING, "Coaching.")

    # --- reducer ---------------------------------------------------------

    def _apply(self, event: RuntimeEvent):
        """Pure transition: mutate authoritative state, return effects + outputs.

        Returns ``(effect_specs, outputs, disposition)``. ``effect_specs`` are
        ``(provenance, pack)`` pairs launched after the lock releases. Outputs
        are immutable projections enqueued in committed order.
        """
        if isinstance(event, IntentionAcceptedEvent):
            return self._apply_intention(event)
        if isinstance(event, ObservationReceivedEvent):
            return self._apply_observation(event)
        if isinstance(event, ReasonerStrategyEvent):
            return self._apply_reasoner_strategy(event)
        if isinstance(event, ReasonerProgressEvent):
            return self._apply_reasoner_progress(event)
        if isinstance(event, AdapterFailureEvent):
            return self._apply_adapter_failure(event)
        if isinstance(event, UserCaptureEvent):
            return self._apply_user_capture(event)
        if isinstance(event, TaskEndedEvent):
            return self._apply_task_ended(event)
        # Events outside the current scope (pause/resume/disconnect/revision/
        # editor/high-res) are admitted as harmless no-ops and land in later
        # v2 tickets. They never mutate coaching state here.
        return [], [], ReceiptDisposition.ADMITTED

    def _apply_intention(self, event: IntentionAcceptedEvent):
        # A new or changed accepted intention invalidates old authority, clears
        # dependent Evidence/Strategy/Instruction/Readiness/analysis, and
        # allocates a fresh application-owned Task. Post-intention Evidence is
        # required before any reasoning, so evidence is cleared too.
        self._task_epoch += 1
        self._close_instruction(InstructionDisposition.TASK_ENDED)
        self._task = Task(
            task_epoch=self._task_epoch,
            task_id=new_identity(),
            accepted_intention=event.accepted_intention,
            # Placeholder revision replaced when a Strategy is admitted.
            strategy_revision=new_identity(),
        )
        self._reset_dependent_state()
        self._mode = Mode.ACTIVE
        self._connection = ConnectionState.CONNECTED
        outputs = self._emit()
        return [], outputs, ReceiptDisposition.ADMITTED

    def _reset_dependent_state(self) -> None:
        """Clear every state lane that depends on the current Task/authority.

        Used when a new intention, task end, a current failure, or a material
        frame-signal change invalidates the authoritative run. Mode/connection
        are not reset here; only the Task-bound coaching lanes.
        """
        self._evidence = None
        self._strategy = None
        self._instruction = None
        self._instruction_criterion_id = None
        self._readiness = None
        self._last_snapshot = None
        self._previous_snapshot = None
        self._analysis = AnalysisState.IDLE
        self._analysis_purpose = None
        self._authoritative_run = None
        self._evidence_state = EvidenceState.MISSING
        self._settling_baseline = None
        self._settling_count = 0
        self._settling_first_arrival = None
        self._settled_observation = None
        self._latest_observation = None
        self._last_signals = None

    def _emit(self) -> list[RuntimeOutput]:
        """Commit and enqueue a projection only if its content changed.

        Implements duplicate-projection suppression so equivalent routine frames
        that coalesce without a new Evidence identity do not produce an
        inference backlog.
        """
        projection = self._commit_projection()
        return [projection] if projection is not None else []

    # --- observation settling (spec §4.2 / §4.3) -------------------------

    def _apply_observation(self, event: ObservationReceivedEvent):
        # A complete immutable observation is admitted to the mailbox. The
        # runtime owns deterministic frame measurement, material-change
        # assessment, and asymmetric Settled hysteresis. With no accepted task
        # there is no coaching state to admit against; the observation is a
        # harmless orphan (it cannot become authoritative coaching Evidence).
        if self._task is None:
            return [], [], ReceiptDisposition.ORPHANED
        observation = event.observation
        # Settled dwell is measured in arrival-time space: the span between the
        # first post-change observation's transport-recorded arrival and the
        # confirming observation's arrival. This decouples Settled from reducer
        # processing latency so a delayed submit cannot skew the dwell.
        now = observation.arrival_monotonic_seconds
        reference = (
            self._settled_observation
            if self._evidence_state is EvidenceState.SETTLED
            else self._settling_baseline
        )
        signals = (
            self._signal_computer(reference, observation)
            if self._signal_computer is not None and reference is not None
            else FrameSignals(
                decode_available=True,
                material_change=False,
                equivalent_to_reference=False,
            )
        )
        self._last_signals = signals
        self._latest_observation = observation

        # Decode failure is conservative fail-open change handling: it
        # immediately invalidates settled Evidence regardless of other signals.
        # A hard camera-context or material visual/quality change likewise
        # immediately invalidates Evidence, overlays, queued work, and the
        # authoritative run token (spec §4.3 / issue #22 AC1).
        if reference is None:
            # First post-change frame: start a new settling period. Nothing
            # authoritative exists to invalidate; this observation is the
            # settling baseline.
            self._begin_settling(observation, now)
            return [], self._emit(), ReceiptDisposition.ADMITTED

        if signals.material_change:
            self._invalidate_settled(reasons=signals.material_reasons)
            self._begin_settling(observation, now)
            return [], self._emit(), ReceiptDisposition.ADMITTED

        if signals.equivalent_to_reference:
            if self._evidence_state is EvidenceState.SETTLED:
                # Equivalent routine frame: coalesce without a new Evidence
                # identity or queued call (issue #22 AC3). Text may be projected
                # against this newest equivalent view while overlays remain
                # bound to the exact analyzed observation (S11).
                if signals.quality_crossing:
                    # A calibrated quality crossing may request revalidation
                    # only; it never establishes semantic achievement or Ready
                    # (issue #22 AC4). It marks the supporting Instruction /
                    # Readiness as needing revalidation.
                    self._mark_needs_revalidation()
                return [], self._emit(), ReceiptDisposition.ADMITTED
            # Settling: count this equivalent post-change observation toward
            # confirmation. A new Evidence identity is admitted only after at
            # least two mutually equivalent post-change observations spanning
            # at least 500 ms (issue #22 AC2).
            self._settling_count += 1
            if self._settling_first_arrival is None:
                self._settling_first_arrival = now
            return self._maybe_settle(observation, now)

        # A non-equivalent, non-material drift: the scene is no longer
        # equivalent to the current settled Evidence. It does not immediately
        # invalidate the identity (only material/hard/quality crossings do),
        # but it restarts settling so a fresh confirmed identity replaces it.
        # The retained Instruction/Ready stays visible as ``may_be_outdated``
        # until fresh settled Evidence is accepted (no flicker / revocation).
        self._mark_may_be_outdated()
        self._begin_settling(observation, now)
        return [], self._emit(), ReceiptDisposition.ADMITTED

    def _begin_settling(self, observation: Observation, now: float) -> None:
        self._evidence_state = EvidenceState.SETTLING
        self._settling_baseline = observation
        self._settling_count = 1
        self._settling_first_arrival = now

    def _maybe_settle(
        self,
        observation: Observation,
        now: float,
    ) -> tuple[list, list, ReceiptDisposition]:
        policy = self._config.settled
        span = (
            now - self._settling_first_arrival
            if self._settling_first_arrival is not None
            else 0.0
        )
        if (
            self._settling_count < policy.confirmation_count
            or span < policy.dwell_seconds
        ):
            return [], self._emit(), ReceiptDisposition.ADMITTED
        # Settled: allocate an application-authored Evidence identity bound to
        # this exact observation and admit it. Overlays remain bound to this
        # exact analyzed observation; text may use the newest equivalent view.
        evidence = EvidenceIdentity(
            evidence_id=new_identity(),
            camera_context_id=new_identity(),
            observation_id=observation.observation_id,
            source_bytes_hash=observation.preview.bytes_hash,
        )
        self._evidence = evidence
        self._settled_observation = observation
        self._evidence_state = EvidenceState.SETTLED
        self._settling_baseline = None
        self._settling_count = 0
        self._settling_first_arrival = None
        effects = self._request_work_for_settled_evidence(evidence)
        return effects, self._emit(), ReceiptDisposition.ADMITTED

    def _request_work_for_settled_evidence(
        self,
        evidence: EvidenceIdentity,
    ) -> list[tuple[Provenance, StrategyContextPack]]:
        """Request the priority-appropriate reasoning run for fresh Evidence.

        With no Strategy yet, fresh settled Evidence requests orientation. With
        an admitted Strategy, fresh settled Evidence requests a material progress
        evaluation (#23): every accepted settled view produces one Evidence
        Snapshot assessing each Must-have once, and the achieved / improving /
        deviating / Ready policies preserve immutable Instruction semantics.
        """

        effects: list[tuple[Provenance, StrategyContextPack]] = []
        if (
            self._strategy is None
            and self._analysis is AnalysisState.IDLE
            and self._authoritative_run is None
        ):
            run_id = new_identity()
            provenance = Provenance(
                purpose=RemotePurpose.STRATEGY,
                run_id=run_id,
                identities={
                    "task": self._task.task_id,
                    "evidence": evidence.evidence_id,
                },
            )
            self._analysis = AnalysisState.REQUESTED
            self._analysis_purpose = AnalysisPurpose.ORIENT
            self._authoritative_run = provenance
            pack = self._build_strategy_pack(provenance, evidence)
            effects.append((provenance, pack))
        elif (
            self._strategy is not None
            and self._analysis is AnalysisState.IDLE
            and self._authoritative_run is None
        ):
            run_id = new_identity()
            provenance = Provenance(
                purpose=RemotePurpose.PROGRESS,
                run_id=run_id,
                identities={
                    "task": self._task.task_id,
                    "evidence": evidence.evidence_id,
                    "strategy": self._strategy.strategy_id,
                },
            )
            self._analysis = AnalysisState.REQUESTED
            self._analysis_purpose = AnalysisPurpose.EVALUATE
            self._authoritative_run = provenance
            pack = self._build_progress_pack(provenance, evidence)
            effects.append((provenance, pack))
        return effects

    def _invalidate_settled(self, *, reasons: tuple[str, ...]) -> None:
        """Immediately invalidate settled Evidence, overlays, queued work, run.

        A hard camera-context or material visual/quality change invalidates
        every Evidence-derived lane and the authoritative run token. The
        persistent Instruction and Readiness are NOT revoked: their support is
        marked ``needs_revalidation`` so guidance does not flicker, but stale
        completions become harmless discards (issue #22 AC1).
        """

        self._evidence = None
        self._last_snapshot = None
        self._previous_snapshot = None
        self._evidence_state = EvidenceState.MISSING
        self._settled_observation = None
        self._settling_baseline = None
        self._settling_count = 0
        self._settling_first_arrival = None
        if self._authoritative_run is not None:
            self._analysis = AnalysisState.IDLE
            self._analysis_purpose = None
            self._authoritative_run = None
        self._mark_needs_revalidation()

    def _mark_needs_revalidation(self) -> None:
        if self._instruction is not None and (
            self._instruction.freshness is InstructionFreshness.CURRENT
        ):
            self._instruction = replace(
                self._instruction,
                freshness=InstructionFreshness.NEEDS_REVALIDATION,
            )
        if self._readiness is not None and (
            self._readiness.state is ReadinessState.READY
        ):
            self._readiness = Readiness(state=ReadinessState.NEEDS_REVALIDATION)

    def _mark_may_be_outdated(self) -> None:
        if self._instruction is not None and (
            self._instruction.freshness is InstructionFreshness.CURRENT
        ):
            self._instruction = replace(
                self._instruction,
                freshness=InstructionFreshness.MAY_BE_OUTDATED,
            )
        if self._readiness is not None and (
            self._readiness.state is ReadinessState.READY
        ):
            self._readiness = Readiness(state=ReadinessState.NEEDS_REVALIDATION)

    def _apply_reasoner_strategy(self, event: ReasonerStrategyEvent):
        # Only a current-token completion may act. Stale, late, or orphaned
        # completions are harmless dispositions.
        if not self._is_current_run(event.provenance):
            return [], [], ReceiptDisposition.STALE
        assert self._task is not None and self._evidence is not None
        proposal = event.proposal
        try:
            strategy, snapshot = self._admit_strategy(proposal)
        except (ValueError, TypeError):
            # Atomic admission: malformed/incomplete output is rejected, not
            # partially repaired. The tracer bullet preserves prior guidance
            # (none here) and clears the authoritative run.
            self._analysis = AnalysisState.IDLE
            self._analysis_purpose = None
            self._authoritative_run = None
            return [], [], ReceiptDisposition.MALFORMED
        self._strategy = strategy
        self._task = replace(self._task, strategy_revision=strategy.strategy_id)
        self._analysis = AnalysisState.IDLE
        self._analysis_purpose = None
        self._authoritative_run = None
        self._last_snapshot = snapshot
        if self._can_derive_ready(snapshot):
            self._derive_ready(snapshot)
        else:
            self._derive_first_action(strategy, snapshot)
        outputs = self._emit()
        return [], outputs, ReceiptDisposition.ADMITTED

    def _apply_adapter_failure(self, event: AdapterFailureEvent):
        # Failure handling: a current failure clears the authoritative run and
        # either preserves usable guidance (progress failures mark the active
        # Instruction/Readiness for revalidation without revoking it, per T08)
        # or, for a strategy failure with no admitted guidance yet, clears
        # dependent coaching state. Full scoped recovery/retry (U06) lands in a
        # later ticket.
        if (
            self._authoritative_run is not None
            and event.provenance.run_id == self._authoritative_run.run_id
        ):
            purpose = self._authoritative_run.purpose
            if purpose is RemotePurpose.PROGRESS:
                self._analysis = AnalysisState.IDLE
                self._analysis_purpose = None
                self._authoritative_run = None
                self._mark_needs_revalidation()
            else:
                self._reset_dependent_state()
            return [], self._emit(), ReceiptDisposition.ADMITTED
        return [], [], ReceiptDisposition.STALE

    def _apply_user_capture(self, event: UserCaptureEvent):
        # A local user capture is neutrally acknowledged, invalidates analysis
        # tied to an older view, and requires fresh live Evidence. It MUST NOT
        # be interpreted as achievement, rejection, refusal, or "too soon."
        # Capture marks any Ready for revalidation without revoking it (T08);
        # fresh Settled Evidence later reconfirms or replaces it through a
        # progress assessment. The full neutral acknowledgement output (U04/U05)
        # lands in a later ticket; this handler owns only the state transition.
        if self._task is None or event.task_id != self._task.task_id:
            return [], [], ReceiptDisposition.STALE
        self._evidence = None
        self._last_snapshot = None
        self._previous_snapshot = None
        self._evidence_state = EvidenceState.MISSING
        self._settled_observation = None
        self._settling_baseline = None
        self._settling_count = 0
        self._settling_first_arrival = None
        if self._authoritative_run is not None:
            self._analysis = AnalysisState.IDLE
            self._analysis_purpose = None
            self._authoritative_run = None
        self._mark_needs_revalidation()
        return [], self._emit(), ReceiptDisposition.ADMITTED

    def _apply_task_ended(self, event: TaskEndedEvent):
        if self._task is None or event.task_id != self._task.task_id:
            return [], [], ReceiptDisposition.STALE
        self._close_instruction(InstructionDisposition.TASK_ENDED)
        self._task = None
        self._reset_dependent_state()
        return [], self._emit(), ReceiptDisposition.ADMITTED

    # --- strategy admission (assigns application-authored IDs) -----------

    def _build_strategy_pack(
        self,
        provenance: Provenance,
        evidence: EvidenceIdentity,
    ) -> StrategyContextPack:
        # Tracer-bullet limitation: the ObservationAssembler that supplies real
        # preview dimensions lands in a later ticket. The scripted Reasoner is
        # drive-by-pack-identity and ignores image content, so a structurally
        # valid placeholder ContextImage (real source-byte hash, nominal
        # dimensions) keeps the pack provenance-correct without fabricating
        # semantic content. Production never imports this dormant path.
        image = ContextImage(
            image_id=new_identity(),
            bytes_hash=evidence.source_bytes_hash,
            width=1,
            height=1,
        )
        return StrategyContextPack(
            provenance=provenance,
            accepted_intention=self._task.accepted_intention,  # type: ignore[union-attr]
            journey="general",
            evidence=evidence,
            current_image=image,
            creation_reason="initial orientation",
            explicit_visual_request=False,
        )

    def _admit_strategy(
        self, proposal: StrategyProposal
    ) -> tuple[ShotStrategy, EvidenceSnapshot]:
        """Atomically validate the proposal and assign application-authored IDs.

        The Reasoner proposes Criteria (no ids) and must-have assessments. The
        runtime assigns every Criterion identity, builds the authoritative
        ShotStrategy and EvidenceSnapshot, and rewrites assessment criterion
        references to the assigned ids. Malformed/incomplete output raises and
        is rejected atomically.
        """
        must_have_indices: list[int] = []
        criteria: list[Criterion] = []
        for idx, proposed in enumerate(proposal.criteria):
            criterion_id = new_identity()
            if proposed.importance == "must_have":
                must_have_indices.append(idx)
            actor = self._map_actor(proposed.responsible_actor)
            actions = tuple(
                CandidateAction(text=action_text)
                for action_text in proposed.candidate_actions
            )
            criteria.append(
                Criterion(
                    criterion_id=criterion_id,
                    importance=CriterionImportance(proposed.importance),
                    priority=proposed.priority,
                    observable_target=proposed.observable_target,
                    candidate_actions=actions,
                    responsible_actor=actor,
                    constraints=tuple(proposed.constraints),
                )
            )
        if len(must_have_indices) != len(proposal.must_have_assessments):
            raise ValueError(
                "must-have assessments must cover every proposed must-have"
            )
        strategy_id = new_identity()
        strategy = ShotStrategy(
            strategy_id=strategy_id,
            criteria=tuple(criteria),
            creation_reason="initial orientation",
        )
        must_assessments = []
        for offset, assessment in enumerate(proposal.must_have_assessments):
            mh_idx = must_have_indices[offset]
            assigned_id = criteria[mh_idx].criterion_id
            must_assessments.append(replace(assessment, criterion_id=assigned_id))
        snapshot = EvidenceSnapshot(
            snapshot_id=new_identity(),
            evidence=self._evidence,  # type: ignore[arg-type]
            task_id=self._task.task_id,  # type: ignore[union-attr]
            strategy_id=strategy_id,
            must_have_assessments=tuple(must_assessments),
        )
        return strategy, snapshot

    def _can_derive_ready(self, snapshot: EvidenceSnapshot) -> bool:
        threshold = self._config.ready_confidence_threshold
        for assessment in snapshot.must_have_assessments:
            if assessment.classification is not CriterionClassification.ACHIEVED:
                return False
            if assessment.confidence is None:
                return False
            if assessment.confidence < threshold:
                return False
            if not assessment.has_current_grounding():
                return False
        return True

    def _derive_ready(self, snapshot: EvidenceSnapshot) -> None:
        # A ready Instruction is immutable for its identity. On reconfirmation
        # the caller preserves the exact identity (T08); this helper allocates a
        # *new* ready Instruction, used on first derivation from Strategy or
        # from an accepted regression that replaces a prior Ready.
        evidence_id = self._evidence.evidence_id  # type: ignore[union-attr]
        self._instruction = Instruction(
            instruction_id=new_identity(),
            kind=InstructionKind.READY,
            text="Ready—take the shot.",
            source_evidence_id=evidence_id,
        )
        self._readiness = Readiness(
            state=ReadinessState.READY,
            evidence_snapshot_id=snapshot.snapshot_id,
            supporting_evidence_id=evidence_id,
        )
        self._instruction_criterion_id = None

    def _derive_first_action(
        self, strategy: ShotStrategy, snapshot: EvidenceSnapshot
    ) -> None:
        # Issue one actionable Instruction for the highest-priority unmet
        # must-have (lowest priority value = highest priority). If every
        # must-have is achieved the admission path would have derived Ready.
        if self._can_derive_ready(snapshot):
            self._derive_ready(snapshot)
            return
        target = self._highest_unmet_must_have(snapshot)
        if target is None or not target.candidate_actions:
            # No feasible action available; keep orienting truthfully rather
            # than fabricating an Instruction. Full blocked-action handling
            # (P06) lands in a later ticket.
            self._instruction = None
            self._instruction_criterion_id = None
            self._readiness = None
            return
        self._derive_action_for_criterion(target)

    def _find_assessment(self, snapshot: EvidenceSnapshot, criterion_id: UUID):
        for assessment in snapshot.must_have_assessments:
            if assessment.criterion_id == criterion_id:
                return assessment
        return None

    # --- progress assessment and policy (#23) ----------------------------

    def _build_progress_pack(
        self,
        provenance: Provenance,
        evidence: EvidenceIdentity,
    ) -> ProgressContextPack:
        # Same tracer-bullet limitation as the strategy pack: a structurally
        # valid placeholder ContextImage keeps provenance correct without
        # fabricating semantic content. The previous compatible preview is
        # the prior snapshot's source bytes when one is retained.
        current_image = ContextImage(
            image_id=new_identity(),
            bytes_hash=evidence.source_bytes_hash,
            width=1,
            height=1,
        )
        previous_image: ContextImage | None = None
        if self._previous_snapshot is not None:
            previous_image = ContextImage(
                image_id=new_identity(),
                bytes_hash=self._previous_snapshot.evidence.source_bytes_hash,
                width=1,
                height=1,
            )
        active_text = self._instruction.text if self._instruction is not None else None
        return ProgressContextPack(
            provenance=provenance,
            strategy=self._strategy,  # type: ignore[arg-type]
            active_instruction_text=active_text,
            evidence=evidence,
            current_image=current_image,
            previous_image=previous_image,
        )

    def _apply_reasoner_progress(self, event: ReasonerProgressEvent):
        # Only a current-token progress completion may act. Stale, late, or
        # orphaned completions are harmless dispositions.
        if not self._is_current_run(event.provenance):
            return [], [], ReceiptDisposition.STALE
        assert (
            self._task is not None
            and self._evidence is not None
            and self._strategy is not None
        )
        try:
            snapshot = self._admit_progress(event.evidence)
        except (ValueError, TypeError):
            # Atomic admission: malformed/incomplete progress is rejected, not
            # partially repaired. Prior guidance is preserved (issue #23 P01)
            # and the authoritative run is cleared so a fresh Settled Evidence
            # may request a new evaluation.
            self._analysis = AnalysisState.IDLE
            self._analysis_purpose = None
            self._authoritative_run = None
            return [], self._emit(), ReceiptDisposition.MALFORMED
        # Retain at most one previous compatible snapshot for the next
        # progress Context Pack (spec §4.4 / §6.4).
        self._previous_snapshot = self._last_snapshot
        self._last_snapshot = snapshot
        self._analysis = AnalysisState.IDLE
        self._analysis_purpose = None
        self._authoritative_run = None
        self._apply_progress_policy(snapshot)
        outputs = self._emit()
        return [], outputs, ReceiptDisposition.ADMITTED

    def _admit_progress(self, evidence: ProgressEvidence) -> EvidenceSnapshot:
        """Atomically validate progress and assign the application-authored
        Snapshot identity.

        Every Must-have is assessed exactly once against the same current
        compatible Evidence, with bounded grounding, finite or null
        confidence, bounded typed uncertainty, and a typed blocked reason when
        applicable. ``CriterionAssessment`` construction enforces the per-row
        bounds; this method enforces must-have coverage, unique references, and
        valid criterion references. Nice-to-have assessments are diagnostic only
        and never block Ready or produce an Instruction (P02). Malformed output
        raises and is rejected atomically (P01).
        """
        strategy = self._strategy  # type: ignore[assignment]
        must_have_ids = {
            c.criterion_id
            for c in strategy.criteria
            if c.importance is CriterionImportance.MUST_HAVE
        }
        assessed_ids = [a.criterion_id for a in evidence.must_have_assessments]
        if len(set(assessed_ids)) != len(assessed_ids):
            raise ValueError("must-have criterion references must be unique")
        if set(assessed_ids) != must_have_ids:
            raise ValueError("progress must assess every must-have exactly once")
        nice_ids = {
            c.criterion_id
            for c in strategy.criteria
            if c.importance is CriterionImportance.NICE_TO_HAVE
        }
        nice_assessed_ids = [a.criterion_id for a in evidence.nice_to_have_assessments]
        if len(set(nice_assessed_ids)) != len(nice_assessed_ids):
            raise ValueError("nice-to-have criterion references must be unique")
        for cid in nice_assessed_ids:
            if cid not in nice_ids:
                raise ValueError("nice-to-have assessment references unknown criterion")
        return EvidenceSnapshot(
            snapshot_id=new_identity(),
            evidence=self._evidence,  # type: ignore[arg-type]
            task_id=self._task.task_id,  # type: ignore[union-attr]
            strategy_id=strategy.strategy_id,
            must_have_assessments=evidence.must_have_assessments,
            nice_to_have_assessments=evidence.nice_to_have_assessments,
            applicability=evidence.applicability,
        )

    def _apply_progress_policy(self, snapshot: EvidenceSnapshot) -> None:
        """Apply the achieved / improving / deviating / Ready policies.

        Nice-to-haves never instruct or block Ready (P02). Ready is derived only
        when every Must-have is achieved at the configured threshold in the same
        Evidence (T07). Improving preserves the exact Instruction identity and
        text (T05). Achieved closes once and advances to the highest-priority
        unmet Must-have (T06). A higher-priority deviating Must-have may preempt
        with one corrective Instruction (P05). Ready regression may replace Ready
        with one corrective Instruction; reconfirmation preserves identity
        (T08). At most one Instruction is ever active (no stacked instructions).
        """
        if self._can_derive_ready(snapshot):
            self._reconfirm_or_derive_ready(snapshot)
            return
        active = self._instruction
        if active is not None and active.kind is InstructionKind.READY:
            # T08 accepted regression: replace Ready with one corrective action
            # Instruction for the highest-priority non-achieved Must-have.
            self._close_instruction(InstructionDisposition.SUPERSEDED)
            self._readiness = None
            target = self._highest_unmet_must_have(snapshot)
            if target is not None and target.candidate_actions:
                self._derive_action_for_criterion(target)
            else:
                self._instruction_criterion_id = None
            return
        # active is an action Instruction (or none).
        preempt = self._highest_deviating_above(
            snapshot, self._instruction_criterion_id
        )
        if preempt is not None:
            # P05: a higher-priority deviating Must-have preempts the current
            # action Instruction with one corrective Instruction.
            self._close_instruction(InstructionDisposition.SUPERSEDED)
            self._readiness = None
            self._derive_action_for_criterion(preempt)
            return
        active_criterion_id = self._instruction_criterion_id
        if active_criterion_id is not None:
            assessment = self._find_assessment(snapshot, active_criterion_id)
            if (
                assessment is not None
                and assessment.classification is CriterionClassification.ACHIEVED
            ):
                # T06: close the achieved Instruction once and advance to the
                # highest-priority unmet Must-have. Ready was already ruled
                # out at the top of this method, so at least one other
                # Must-have remains unmet here.
                self._close_instruction(InstructionDisposition.ACHIEVED)
                target = self._highest_unmet_must_have(snapshot)
                if target is not None and target.candidate_actions:
                    self._derive_action_for_criterion(target)
                else:
                    self._instruction_criterion_id = None
                return
            # T05: improving or still-insufficient — preserve the exact
            # Instruction identity and text. Revalidation against fresh
            # Evidence restores freshness to CURRENT (Activity may change;
            # trajectory coalesces boundedly).
            self._refresh_current_freshness()
            return
        # No active Instruction but a Strategy exists (e.g., a prior blocked
        # Criterion had no feasible action): derive an action for the
        # highest-priority unmet Must-have, or Ready (handled above).
        self._derive_first_action(self._strategy, snapshot)  # type: ignore[arg-type]

    def _reconfirm_or_derive_ready(self, snapshot: EvidenceSnapshot) -> None:
        active = self._instruction
        if active is not None and active.kind is InstructionKind.READY:
            # T08 reconfirmation: preserve the exact ready Instruction identity
            # and text; refresh freshness to CURRENT and re-bind Readiness to
            # the new current compatible Evidence Snapshot.
            self._instruction = replace(
                active,
                freshness=InstructionFreshness.CURRENT,
            )
            self._readiness = Readiness(
                state=ReadinessState.READY,
                evidence_snapshot_id=snapshot.snapshot_id,
                supporting_evidence_id=self._evidence.evidence_id,  # type: ignore[union-attr]
            )
            return
        # First Ready derivation from progress: close any active action
        # Instruction as superseded, then allocate a new ready Instruction.
        if active is not None:
            self._close_instruction(InstructionDisposition.SUPERSEDED)
        self._derive_ready(snapshot)

    def _refresh_current_freshness(self) -> None:
        if (
            self._instruction is not None
            and self._instruction.freshness is not InstructionFreshness.CURRENT
        ):
            self._instruction = replace(
                self._instruction,
                freshness=InstructionFreshness.CURRENT,
            )

    def _close_instruction(self, disposition: InstructionDisposition) -> None:
        """Record exactly one terminal disposition for the active Instruction.

        A closed Instruction records exactly one disposition (achieved,
        superseded, rejected, irrelevant, or task_ended). The active lane is
        cleared; the disposition history is retained for invariant checking.
        """
        if self._instruction is None:
            return
        iid = self._instruction.instruction_id
        if iid not in self._instruction_dispositions:
            self._instruction_dispositions[iid] = disposition
        self._instruction = None
        self._instruction_criterion_id = None

    def _derive_action_for_criterion(self, criterion: Criterion) -> None:
        action = criterion.candidate_actions[0]
        self._instruction = Instruction(
            instruction_id=new_identity(),
            kind=InstructionKind.ACTION,
            text=action.text,
            addressee=action.responsible_actor or criterion.responsible_actor,
        )
        self._instruction_criterion_id = criterion.criterion_id
        self._readiness = None

    def _highest_unmet_must_have(
        self,
        snapshot: EvidenceSnapshot,
    ) -> Criterion | None:
        unmet: list[Criterion] = []
        for criterion in self._strategy.criteria:  # type: ignore[union-attr]
            if criterion.importance is not CriterionImportance.MUST_HAVE:
                continue
            assessment = self._find_assessment(snapshot, criterion.criterion_id)
            if (
                assessment is None
                or assessment.classification is not CriterionClassification.ACHIEVED
            ):
                unmet.append(criterion)
        if not unmet:
            return None
        return min(unmet, key=lambda c: c.priority)

    def _highest_deviating_above(
        self,
        snapshot: EvidenceSnapshot,
        active_criterion_id: UUID | None,
    ) -> Criterion | None:
        # P05: a Must-have with strictly higher priority (lower priority value)
        # than the active Criterion that classifies ``deviating`` may preempt.
        active_priority: int | None = None
        if active_criterion_id is not None:
            for criterion in self._strategy.criteria:  # type: ignore[union-attr]
                if criterion.criterion_id == active_criterion_id:
                    active_priority = criterion.priority
                    break
        deviating: list[Criterion] = []
        for criterion in self._strategy.criteria:  # type: ignore[union-attr]
            if criterion.importance is not CriterionImportance.MUST_HAVE:
                continue
            assessment = self._find_assessment(snapshot, criterion.criterion_id)
            if (
                assessment is not None
                and assessment.classification is CriterionClassification.DEVIATING
                and (active_priority is None or criterion.priority < active_priority)
            ):
                deviating.append(criterion)
        if not deviating:
            return None
        return min(deviating, key=lambda c: c.priority)

    def _map_actor(self, actor: str | None):
        if actor is None:
            return None
        normalized = actor.strip().lower()
        if normalized == "photographer":
            return Addressee.PHOTOGRAPHER
        if normalized == "subject":
            return Addressee.SUBJECT
        return None

    # --- current-token authority -----------------------------------------

    def _is_current_run(self, provenance: Provenance) -> bool:
        authoritative = self._authoritative_run
        if authoritative is None:
            return False
        if provenance.run_id != authoritative.run_id:
            return False
        current: dict[str, UUID | None] = {}
        if self._task is not None:
            current["task"] = self._task.task_id
        if self._evidence is not None:
            current["evidence"] = self._evidence.evidence_id
        if self._strategy is not None:
            current["strategy"] = self._strategy.strategy_id
        return provenance.is_current(current)

    # --- effect execution ------------------------------------------------

    def _launch_reasoner_effect(
        self,
        provenance: Provenance,
        pack: StrategyContextPack | ProgressContextPack,
    ) -> None:
        if provenance.purpose is RemotePurpose.STRATEGY:
            task = asyncio.create_task(self._run_strategy(provenance, pack))  # type: ignore[arg-type]
        elif provenance.purpose is RemotePurpose.PROGRESS:
            task = asyncio.create_task(self._run_progress(provenance, pack))  # type: ignore[arg-type]
        else:
            # Revision/other reasoner effects land in later tickets.
            return
        self._effect_tasks.add(task)
        task.add_done_callback(self._effect_tasks.discard)
        task.add_done_callback(_retrieve_exception)

    async def _run_strategy(
        self, provenance: Provenance, pack: StrategyContextPack
    ) -> None:
        try:
            outcome = await self._reasoner.propose_strategy(pack)
        except asyncio.CancelledError:
            raise
        except Exception:  # provider contract violation
            outcome = AdapterFailure(
                failure=TypedFailure.INVALID_OUTPUT,
                provenance=provenance,
            )
        if isinstance(outcome, AdapterFailure):
            await self.submit(
                AdapterFailureEvent(
                    event_id=new_identity(),
                    provenance=provenance,
                    failure=outcome.failure,
                    throttle_delay_seconds=outcome.throttle_delay_seconds,
                )
            )
        elif isinstance(outcome, StrategyProposal):
            await self.submit(
                ReasonerStrategyEvent(
                    event_id=new_identity(),
                    provenance=provenance,
                    proposal=outcome,
                )
            )
        else:
            # Wrong outcome type for a strategy call is a contract violation.
            await self.submit(
                AdapterFailureEvent(
                    event_id=new_identity(),
                    provenance=provenance,
                    failure=TypedFailure.INVALID_OUTPUT,
                )
            )

    async def _run_progress(
        self, provenance: Provenance, pack: ProgressContextPack
    ) -> None:
        try:
            outcome = await self._reasoner.assess_progress(pack)
        except asyncio.CancelledError:
            raise
        except Exception:  # provider contract violation
            outcome = AdapterFailure(
                failure=TypedFailure.INVALID_OUTPUT,
                provenance=provenance,
            )
        if isinstance(outcome, AdapterFailure):
            await self.submit(
                AdapterFailureEvent(
                    event_id=new_identity(),
                    provenance=provenance,
                    failure=outcome.failure,
                    throttle_delay_seconds=outcome.throttle_delay_seconds,
                )
            )
        elif isinstance(outcome, ProgressEvidence):
            await self.submit(
                ReasonerProgressEvent(
                    event_id=new_identity(),
                    provenance=provenance,
                    evidence=outcome,
                )
            )
        else:
            # Wrong outcome type for a progress call is a contract violation.
            await self.submit(
                AdapterFailureEvent(
                    event_id=new_identity(),
                    provenance=provenance,
                    failure=TypedFailure.INVALID_OUTPUT,
                )
            )


__all__ = ["_CoachingRuntime"]
