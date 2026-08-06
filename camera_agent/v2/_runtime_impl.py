"""The first tracer-bullet ``CoachingRuntime`` implementation (issue #21).

This is the concrete realization of the dormant v2 ``CoachingRuntime``
Interface for the *first* coaching tracer bullet: ordered admission from no
intention through Task creation and initial Strategy completion to one
persistent Instruction or immediate evidence-backed Ready.

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
    EvidenceSettledEvent,
    IntentionAcceptedEvent,
    Receipt,
    ReceiptDisposition,
    ReasonerStrategyEvent,
    RuntimeEvent,
    RuntimeOutput,
    TaskEndedEvent,
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
    Instruction,
    InstructionKind,
    Mode,
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

    def __init__(self, config: RuntimeConfig, reasoner: Any, editor: Any) -> None:
        self._config = config
        self._reasoner = reasoner
        self._editor = editor

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
        self._readiness: Readiness | None = None
        self._analysis = AnalysisState.IDLE
        self._analysis_purpose: AnalysisPurpose | None = None
        self._authoritative_run: Provenance | None = None
        self._last_snapshot: EvidenceSnapshot | None = None

        # The initial committed state (revision 0) is a complete immutable
        # projection: no intention -> needs_intention with truthful waiting
        # Activity and no reasoning. Emitted at construction so a caller that
        # never submits still observes the authoritative initial state.
        self._output_queue.put_nowait(self._build_projection())

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
                return Receipt(event_id=event.event_id, order=order,
                                disposition=ReceiptDisposition.STALE)
            if event.event_id in self._seen_event_ids:
                return Receipt(event_id=event.event_id, order=order,
                                disposition=ReceiptDisposition.DUPLICATE)
            self._seen_event_ids.add(event.event_id)
            effect_specs, outputs, disposition = self._apply(event)
            for output in outputs:
                self._output_queue.put_nowait(output)
            pending = effect_specs
        # Launch effects only after state commit + output enqueue so async work
        # never mutates state or writes ahead of the committed projection.
        for spec in pending:
            self._launch_strategy_effect(spec[0], spec[1])
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

    def _commit_projection(self) -> CoachingProjection:
        self._next_revision += 1
        return self._build_projection()

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
            return Activity(ActivityKind.WAITING,
                            "Tell me what you'd like to photograph.")
        if phase == CoachingPhase.RECOVERING:
            return Activity(ActivityKind.RECOVERING,
                            "Reconnecting — hold still.")
        if phase == CoachingPhase.PAUSED:
            return Activity(ActivityKind.WAITING, "Coaching is paused.")
        if phase == CoachingPhase.EVALUATING:
            return Activity(ActivityKind.WORKING, "Checking your progress.")
        if phase == CoachingPhase.ORIENTING:
            return Activity(ActivityKind.WORKING,
                            "Looking at the scene to plan your shot.")
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
        if isinstance(event, EvidenceSettledEvent):
            return self._apply_evidence_settled(event)
        if isinstance(event, ReasonerStrategyEvent):
            return self._apply_reasoner_strategy(event)
        if isinstance(event, AdapterFailureEvent):
            return self._apply_adapter_failure(event)
        if isinstance(event, TaskEndedEvent):
            return self._apply_task_ended(event)
        # Events outside the tracer-bullet scope (pause/resume/capture/disconnect/
        # progress/revision/editor/high-res) are admitted as harmless no-ops and
        # land in later v2 tickets. They never mutate coaching state here.
        return [], [], ReceiptDisposition.ADMITTED

    def _apply_intention(self, event: IntentionAcceptedEvent):
        # A new or changed accepted intention invalidates old authority, clears
        # dependent Evidence/Strategy/Instruction/Readiness/analysis, and
        # allocates a fresh application-owned Task. Post-intention Evidence is
        # required before any reasoning, so evidence is cleared too.
        self._task_epoch += 1
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
        outputs = [self._commit_projection()]
        return [], outputs, ReceiptDisposition.ADMITTED

    def _reset_dependent_state(self) -> None:
        """Clear every state lane that depends on the current Task/authority.

        Used when a new intention, task end, or a current failure invalidates
        the authoritative run. Mode/connection are not reset here; only the
        Task-bound coaching lanes.
        """
        self._evidence = None
        self._strategy = None
        self._instruction = None
        self._readiness = None
        self._last_snapshot = None
        self._analysis = AnalysisState.IDLE
        self._analysis_purpose = None
        self._authoritative_run = None

    def _apply_evidence_settled(self, event: EvidenceSettledEvent):
        if self._task is None:
            # Settled evidence with no accepted intention is harmless; no
            # coaching state to admit it against.
            return [], [], ReceiptDisposition.ORPHANED
        if event.task_id != self._task.task_id:
            # Evidence bound to an older task is stale.
            return [], [], ReceiptDisposition.STALE
        self._evidence = event.evidence
        effects: list[tuple[Provenance, StrategyContextPack]] = []
        if (self._strategy is None
                and self._analysis is AnalysisState.IDLE
                and self._authoritative_run is None):
            run_id = new_identity()
            provenance = Provenance(
                purpose=RemotePurpose.STRATEGY,
                run_id=run_id,
                identities={
                    "task": self._task.task_id,
                    "evidence": event.evidence.evidence_id,
                },
            )
            self._analysis = AnalysisState.REQUESTED
            self._analysis_purpose = AnalysisPurpose.ORIENT
            self._authoritative_run = provenance
            pack = self._build_strategy_pack(provenance, event.evidence)
            effects.append((provenance, pack))
        outputs = [self._commit_projection()]
        return effects, outputs, ReceiptDisposition.ADMITTED

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
        outputs = [self._commit_projection()]
        return [], outputs, ReceiptDisposition.ADMITTED

    def _apply_adapter_failure(self, event: AdapterFailureEvent):
        # Tracer-bullet failure handling: a current failure clears the
        # authoritative run and preserves any usable guidance; full scoped
        # recovery/retry (U06) lands in a later ticket.
        if (self._authoritative_run is not None
                and event.provenance.run_id == self._authoritative_run.run_id):
            self._reset_dependent_state()
            return [], [self._commit_projection()], ReceiptDisposition.ADMITTED
        return [], [], ReceiptDisposition.STALE

    def _apply_task_ended(self, event: TaskEndedEvent):
        if self._task is None or event.task_id != self._task.task_id:
            return [], [], ReceiptDisposition.STALE
        self._task = None
        self._reset_dependent_state()
        return [], [self._commit_projection()], ReceiptDisposition.ADMITTED

    # --- strategy admission (assigns application-authored IDs) -----------

    def _build_strategy_pack(
        self, provenance: Provenance, evidence: EvidenceIdentity,
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

    def _admit_strategy(self, proposal: StrategyProposal) -> tuple[ShotStrategy, EvidenceSnapshot]:
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
            criteria.append(Criterion(
                criterion_id=criterion_id,
                importance=CriterionImportance(proposed.importance),
                priority=proposed.priority,
                observable_target=proposed.observable_target,
                candidate_actions=actions,
                responsible_actor=actor,
                constraints=tuple(proposed.constraints),
            ))
        if len(must_have_indices) != len(proposal.must_have_assessments):
            raise ValueError("must-have assessments must cover every proposed must-have")
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

    def _derive_first_action(self, strategy: ShotStrategy, snapshot: EvidenceSnapshot) -> None:
        # Issue one actionable Instruction for the highest-priority unmet
        # must-have (lowest priority value = highest priority). If every
        # must-have is achieved the admission path would have derived Ready.
        unmet: list[Criterion] = []
        for criterion in strategy.criteria:
            if criterion.importance is not CriterionImportance.MUST_HAVE:
                continue
            assessment = self._find_assessment(snapshot, criterion.criterion_id)
            if (assessment is None
                    or assessment.classification is not CriterionClassification.ACHIEVED):
                unmet.append(criterion)
        if not unmet:
            self._derive_ready(snapshot)
            return
        target = min(unmet, key=lambda c: c.priority)
        if not target.candidate_actions:
            # No feasible action available; keep orienting truthfully rather
            # than fabricating an Instruction. Full blocked-action handling
            # (P06) lands in a later ticket.
            self._instruction = None
            self._readiness = None
            return
        action = target.candidate_actions[0]
        self._instruction = Instruction(
            instruction_id=new_identity(),
            kind=InstructionKind.ACTION,
            text=action.text,
            addressee=action.responsible_actor or target.responsible_actor,
        )
        self._readiness = None

    def _find_assessment(self, snapshot: EvidenceSnapshot, criterion_id: UUID):
        for assessment in snapshot.must_have_assessments:
            if assessment.criterion_id == criterion_id:
                return assessment
        return None

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
        return provenance.is_current(current)

    # --- effect execution ------------------------------------------------

    def _launch_strategy_effect(
        self, provenance: Provenance, pack: StrategyContextPack,
    ) -> None:
        task = asyncio.create_task(self._run_strategy(provenance, pack))
        self._effect_tasks.add(task)
        task.add_done_callback(self._effect_tasks.discard)
        task.add_done_callback(_retrieve_exception)

    async def _run_strategy(self, provenance: Provenance, pack: StrategyContextPack) -> None:
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
            await self.submit(AdapterFailureEvent(
                event_id=new_identity(),
                provenance=provenance,
                failure=outcome.failure,
                throttle_delay_seconds=outcome.throttle_delay_seconds,
            ))
        elif isinstance(outcome, StrategyProposal):
            await self.submit(ReasonerStrategyEvent(
                event_id=new_identity(),
                provenance=provenance,
                proposal=outcome,
            ))
        else:
            # Wrong outcome type for a strategy call is a contract violation.
            await self.submit(AdapterFailureEvent(
                event_id=new_identity(),
                provenance=provenance,
                failure=TypedFailure.INVALID_OUTPUT,
            ))


__all__ = ["_CoachingRuntime"]
