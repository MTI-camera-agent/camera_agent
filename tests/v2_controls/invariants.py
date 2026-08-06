"""Reusable mandatory-invariant assertions over public v2 contract values.

Every deterministic scenario and seeded interleaving run checks the mandatory
invariants in ``docs/CAMERA_AGENT_V2_EVALUATION.md`` §4. These helpers assert
the invariants that operate purely on public contract values
(``RuntimeOutput`` / ``CoachingProjection`` / ``Instruction`` / ``Readiness``
/ ``VisualGuidanceSidecar``) so any scenario can reuse them without inspecting
private reducer state.

Each assertion raises ``InvariantViolation`` (a ``RuntimeError`` subtype) on
failure and returns ``None`` on success, so a test can compose several in one
scenario:

    assert_at_most_one_active_instruction(projection)
    assert_ready_cites_current_evidence(projection, config)
    assert_visual_sidecar_isolated(projection)

These assertions are test controls, not runtime checks and not public seams.
"""

from __future__ import annotations

from typing import Iterable
from uuid import UUID

from camera_agent.v2.config import RuntimeConfig
from camera_agent.v2.contracts import (
    CoachingProjection,
    OutputKind,
    RuntimeOutput,
    output_kind,
)
from camera_agent.v2.values import (
    ActivityKind,
    CriterionClassification,
    EvidenceSnapshot,
    Instruction,
    InstructionDisposition,
    InstructionKind,
    ReadinessState,
    VisualGuidanceSidecar,
)


class InvariantViolation(RuntimeError):
    """A mandatory v2 invariant was violated by observed public output."""


def assert_coaching_projection_well_formed(projection: CoachingProjection) -> None:
    """A committed projection must be internally consistent.

    Dataclass construction already enforces revision non-negativity, the
    Instruction-needs-Task rule, and unique action ids. This helper adds the
    public-invariant view: a non-null Instruction requires a Task, Activity
    text is non-empty, and a ready Instruction is paired with Ready.
    """
    if projection.task is None and projection.instruction is not None:
        raise InvariantViolation("an Instruction requires a Task")
    if projection.activity is not None and not projection.activity.text.strip():
        raise InvariantViolation("Activity text must be nonempty")
    instruction = projection.instruction
    if instruction is not None and instruction.kind is InstructionKind.READY:
        if projection.readiness is None or projection.readiness.state is not ReadinessState.READY:
            raise InvariantViolation("a ready Instruction requires a READY Readiness record")


def assert_at_most_one_active_instruction(projection: CoachingProjection) -> None:
    """Invariant §4.1: at most one active Instruction exists.

    A projection carries at most one ``instruction``; the action set targets at
    most that one Instruction. This helper asserts the single-instruction
    invariant plus the rule that an Instruction's available actions either
    target the current Instruction or another typed target (never a second
    Instruction).
    """
    instruction = projection.instruction
    if instruction is None:
        return
    from camera_agent.v2.values import ActionTargetKind

    targeting = [
        a for a in projection.available_actions
        if a.target.kind is ActionTargetKind.INSTRUCTION
    ]
    for action in targeting:
        if action.target.identity != instruction.instruction_id:
            raise InvariantViolation(
                "an available action must target the current Instruction"
            )


def assert_instruction_immutable_for_identity(
    a: Instruction,
    b: Instruction,
) -> None:
    """Invariant §4.2: two Instructions with the same identity share content.

    ``kind``, ``text``, and ``addressee`` are immutable for one
    ``instruction_id``; changing any creates a new identity. ``freshness`` may
    change without replacing the Instruction.
    """
    if a.instruction_id != b.instruction_id:
        raise InvariantViolation("identity must match to assert immutability")
    if a.content_tuple() != b.content_tuple():
        raise InvariantViolation(
            "Instruction content changed for the same identity"
        )


def assert_single_terminal_disposition(
    dispositions: Iterable[InstructionDisposition],
) -> None:
    """Invariant §4.3: a closed Instruction records exactly one terminal disposition."""
    seen = list(dispositions)
    if len(seen) != 1:
        raise InvariantViolation(
            f"a closed Instruction must record exactly one disposition, got {seen}"
        )


def assert_truthful_activity_when_no_instruction(projection: CoachingProjection) -> None:
    """Invariant §4.4: no Instruction implies truthful Activity or scoped recovery.

    When no persistent Instruction exists the projection MUST carry Activity
    text (truthful waiting/working/recovering) rather than a blank.
    """
    if projection.instruction is None:
        if projection.activity is None or not projection.activity.text.strip():
            raise InvariantViolation(
                "a projection without an Instruction must carry truthful Activity"
            )
        if projection.activity.kind not in {
            ActivityKind.WORKING,
            ActivityKind.WAITING,
            ActivityKind.RECOVERING,
        }:
            raise InvariantViolation("Activity kind must be a truthful kind")


def assert_ready_cites_current_evidence(
    projection: CoachingProjection,
    snapshot: EvidenceSnapshot | None,
    config: RuntimeConfig,
) -> None:
    """Invariant §4.7: Ready cites one current compatible Evidence Snapshot that
    assesses every must-have at the configured confidence threshold, and
    nice-to-haves never block Ready (§4.8).
    """
    readiness = projection.readiness
    if readiness is None or readiness.state is not ReadinessState.READY:
        return
    instruction = projection.instruction
    if instruction is None or instruction.kind is not InstructionKind.READY:
        raise InvariantViolation("READY must be carried by a ready Instruction")
    if instruction.source_evidence_id is None:
        raise InvariantViolation("a ready Instruction must cite its source Evidence")
    if readiness.evidence_snapshot_id is None or readiness.supporting_evidence_id is None:
        raise InvariantViolation("Ready requires a supporting Snapshot and Evidence")
    if snapshot is None:
        raise InvariantViolation("a supporting Evidence Snapshot must be supplied")
    if snapshot.snapshot_id != readiness.evidence_snapshot_id:
        raise InvariantViolation(
            "Ready must cite the same Evidence Snapshot it was derived from"
        )
    threshold = config.ready_confidence_threshold
    for assessment in snapshot.must_have_assessments:
        if assessment.classification is not CriterionClassification.ACHIEVED:
            raise InvariantViolation("Ready requires every must-have to be achieved")
        if assessment.confidence is None:
            raise InvariantViolation("Ready requires non-null must-have confidence")
        if assessment.confidence < threshold:
            raise InvariantViolation(
                "Ready requires every must-have confidence at or above the threshold"
            )
        if not assessment.has_current_grounding():
            raise InvariantViolation(
                "a must-have assessment supporting Ready needs current grounding"
            )


def assert_visual_sidecar_isolated(projection: CoachingProjection) -> None:
    """Invariant §4.18: Generated Visual Guidance does not mutate live Evidence,
    Strategy, Instruction, or Readiness.

    The sidecar is concurrent, not an exclusive phase: a delivered artifact MAY
    coexist with an Instruction or with Ready. The isolation violation is a
    delivered artifact that *erases* the current Instruction (an artifact must
    never replace the persistent Instruction or Ready evidence). The stronger
    "a generated artifact must not itself be the Ready evidence" check belongs
    to ``assert_ready_cites_current_evidence``, which asserts the ready
    Instruction cites a real Evidence Snapshot rather than a generated image.
    """
    sidecar: VisualGuidanceSidecar | None = projection.visual_guidance
    if sidecar is None:
        return
    if sidecar.artifact is not None and projection.instruction is None:
        raise InvariantViolation(
            "a delivered artifact must not erase the current Instruction"
        )


def assert_no_obsolete_current_output(trace: list[RuntimeOutput]) -> None:
    """Invariant §4.20: no obsolete output is presented as current.

    Projections must carry strictly increasing ``state_revision``; a later
    projection with a smaller or equal revision is an obsolete-current
    presentation. Non-projection outputs are skipped.
    """
    last_revision: int | None = None
    for output in trace:
        if output_kind(output) is not OutputKind.COACHING_PROJECTION:
            continue
        projection: CoachingProjection = output  # type: ignore[assignment]
        if last_revision is not None and projection.state_revision <= last_revision:
            raise InvariantViolation(
                "a later projection must carry a strictly greater state revision"
            )
        last_revision = projection.state_revision


def assert_output_order_is_committed(trace: list[RuntimeOutput]) -> None:
    """The observed output stream is the committed mailbox order.

    An explicit action is executed at most once: at most one ``ACCEPTED``
    ``ActionResultOutput`` may appear per ``action_id``. Duplicate or stale
    transmissions are acknowledged idempotently (``DUPLICATE``/``STALE``) and do
    not re-execute; this helper asserts the one-use execution mirror of
    invariant §4.15.
    """
    from camera_agent.v2.contracts import ActionResultOutput
    from camera_agent.v2.values import ActionDisposition

    executed: set[UUID] = set()
    for output in trace:
        if output_kind(output) is not OutputKind.ACTION_RESULT:
            continue
        action: ActionResultOutput = output  # type: ignore[assignment]
        if action.disposition is ActionDisposition.ACCEPTED:
            if action.action_id in executed:
                raise InvariantViolation(
                    "an explicit action must be executed at most once"
                )
            executed.add(action.action_id)
