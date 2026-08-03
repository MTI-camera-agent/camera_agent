"""PROTOTYPE — pure shot-strategy/progress reducer for issue 7.

The question: can a stable, priority-ordered set of observable criteria absorb
whole-shot evidence updates and choose one next action without rebuilding the
strategy after every observation?
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Mapping


class Progress(StrEnum):
    UNASSESSED = "unassessed"
    ACHIEVED = "achieved"
    IMPROVING = "improving"
    INSUFFICIENT = "insufficient"
    DEVIATING = "deviating"
    BLOCKED = "blocked"
    READY = "ready"


class Decision(StrEnum):
    HOLD = "hold exact instruction"
    REFINE = "refine instruction"
    ADVANCE = "advance focus"
    PATCH = "patch strategy"
    REBUILD = "rebuild strategy"
    READY = "declare ready"


@dataclass(slots=True, frozen=True)
class Criterion:
    key: str
    label: str
    must_have: bool
    priority: int
    actions: tuple[str, ...]


@dataclass(slots=True)
class CriterionEvidence:
    progress: Progress = Progress.UNASSESSED
    confidence: float = 0.0
    evidence_id: int | None = None
    note: str = ""
    consecutive_insufficient: int = 0
    action_index: int = 0
    rejected_actions: set[int] = field(default_factory=set)


@dataclass(slots=True, frozen=True)
class Instruction:
    identity: int
    criterion_key: str
    text: str


@dataclass(slots=True)
class State:
    strategy_revision: int
    criteria: tuple[Criterion, ...]
    evidence: dict[str, CriterionEvidence]
    evidence_id: int = 0
    instruction: Instruction | None = None
    ready: bool = False
    overall_progress: Progress = Progress.UNASSESSED
    last_decision: Decision = Decision.ADVANCE
    activity: str = "Looking at the scene…"
    pending_patch_for: str | None = None
    next_instruction_identity: int = 1


READINESS_CONFIDENCE = 0.70
NO_PROGRESS_LIMIT = 2


def sample_state() -> State:
    """A portrait strategy with two must-haves and one optional refinement."""
    criteria = (
        Criterion(
            "framing",
            "Full body visible with a small margin",
            True,
            10,
            (
                "Photographer, step back until both feet fit with a small margin.",
                "Photographer, switch to 0.5× and keep the full body inside the frame.",
            ),
        ),
        Criterion(
            "pose",
            "Requested confident, open stance",
            True,
            20,
            (
                "Subject, turn your front foot slightly toward the camera.",
                "Subject, shift your weight gently onto your back foot.",
            ),
        ),
        Criterion(
            "background",
            "Reduce the bright edge distraction",
            False,
            30,
            ("Photographer, move one small step to your right.",),
        ),
    )
    state = State(
        strategy_revision=1,
        criteria=criteria,
        evidence={criterion.key: CriterionEvidence() for criterion in criteria},
    )
    return apply_evaluation(
        state,
        {
            "framing": (Progress.INSUFFICIENT, 0.92, "feet clipped"),
            "pose": (Progress.INSUFFICIENT, 0.76, "stance not yet open"),
            "background": (Progress.INSUFFICIENT, 0.61, "bright edge visible"),
        },
    )


def apply_evaluation(
    state: State,
    updates: Mapping[str, tuple[Progress, float, str]],
) -> State:
    """Apply one accepted current-evidence evaluation and choose one response.

    Every must-have must be assessed from this evidence identity. This prevents
    readiness from being assembled out of unrelated old frames.
    """
    next_state = deepcopy(state)
    missing = [
        criterion.key
        for criterion in next_state.criteria
        if criterion.must_have and criterion.key not in updates
    ]
    if missing:
        raise ValueError(f"current evidence omitted must-haves: {', '.join(missing)}")

    next_state.evidence_id += 1
    current_evidence_id = next_state.evidence_id
    for key, (progress, confidence, note) in updates.items():
        item = next_state.evidence[key]
        item.progress = progress
        item.confidence = confidence
        item.evidence_id = current_evidence_id
        item.note = note
        item.consecutive_insufficient = (
            item.consecutive_insufficient + 1
            if progress == Progress.INSUFFICIENT
            else 0
        )

    if _is_ready(next_state):
        next_state.ready = True
        next_state.overall_progress = Progress.READY
        next_state.last_decision = Decision.READY
        next_state.activity = "Ready—take the shot."
        _set_instruction(next_state, "ready", "Ready—take the shot.")
        return next_state

    next_state.ready = False
    blocked = _first(next_state, Progress.BLOCKED, must_have_only=True)
    if blocked is not None:
        return _request_patch(next_state, blocked, Progress.BLOCKED)

    deviating = _first(next_state, Progress.DEVIATING, must_have_only=True)
    if deviating is not None:
        next_state.overall_progress = Progress.DEVIATING
        next_state.last_decision = Decision.REFINE
        next_state.activity = "Correcting a regression found in the current view."
        _issue_action(next_state, deviating)
        return next_state

    active = _active_criterion(next_state)
    if active is None:
        active = _next_unsatisfied(next_state)
    if active is None:
        # A low-confidence must-have cannot satisfy readiness, but still needs focus.
        active = _first_low_confidence_must_have(next_state)
    if active is None:
        raise RuntimeError("non-ready strategy has no criterion to work on")

    item = next_state.evidence[active.key]
    next_state.overall_progress = item.progress
    if item.progress == Progress.ACHIEVED:
        following = _next_unsatisfied(next_state)
        if following is None:
            following = _first_low_confidence_must_have(next_state)
        if following is None:
            raise RuntimeError("achieved but readiness invariant was not satisfied")
        next_state.last_decision = Decision.ADVANCE
        next_state.activity = f"{active.label}: achieved; advancing focus."
        _issue_action(next_state, following)
        return next_state

    if item.progress == Progress.IMPROVING and _instruction_targets(next_state, active):
        next_state.last_decision = Decision.HOLD
        next_state.activity = "Improving—keep making the current adjustment."
        return next_state

    if item.progress == Progress.INSUFFICIENT and _instruction_targets(next_state, active):
        if item.consecutive_insufficient < NO_PROGRESS_LIMIT:
            next_state.last_decision = Decision.HOLD
            next_state.activity = "No clear progress yet; checking once more before changing approach."
            return next_state
        if _select_next_action(item, active):
            next_state.last_decision = Decision.REFINE
            next_state.activity = "No progress; trying a different action for the same criterion."
            _issue_action(next_state, active)
            return next_state
        return _request_patch(next_state, active, Progress.INSUFFICIENT)

    next_state.last_decision = Decision.ADVANCE
    next_state.activity = "Selecting the highest-priority unmet criterion."
    _issue_action(next_state, active)
    return next_state


def reject_instruction(state: State) -> State:
    """Record explicit rejection and locally patch the strategy when possible."""
    next_state = deepcopy(state)
    active = _active_criterion(next_state)
    if active is None or next_state.instruction is None:
        return next_state
    item = next_state.evidence[active.key]
    item.rejected_actions.add(item.action_index)
    next_state.instruction = None
    next_state.ready = False
    next_state.strategy_revision += 1
    if _select_next_action(item, active):
        next_state.last_decision = Decision.PATCH
        next_state.overall_progress = Progress.INSUFFICIENT
        next_state.activity = "Rejected action removed; using a local strategy alternative."
        _issue_action(next_state, active)
        return next_state
    return _request_patch(next_state, active, Progress.BLOCKED, bump_revision=False)


def apply_local_patch(state: State) -> State:
    """Simulate a reasoner returning a replacement action for one criterion."""
    next_state = deepcopy(state)
    if next_state.pending_patch_for is None:
        return next_state
    key = next_state.pending_patch_for
    criterion = next(criterion for criterion in next_state.criteria if criterion.key == key)
    patched = Criterion(
        criterion.key,
        criterion.label,
        criterion.must_have,
        criterion.priority,
        criterion.actions + ("Photographer, change position and reframe around the subject.",),
    )
    next_state.criteria = tuple(
        patched if candidate.key == key else candidate
        for candidate in next_state.criteria
    )
    item = next_state.evidence[key]
    item.action_index = len(patched.actions) - 1
    item.progress = Progress.INSUFFICIENT
    item.consecutive_insufficient = 0
    next_state.pending_patch_for = None
    next_state.strategy_revision += 1
    next_state.last_decision = Decision.PATCH
    next_state.overall_progress = Progress.INSUFFICIENT
    next_state.activity = "Local strategy patch accepted; unaffected criteria and evidence retained."
    _issue_action(next_state, patched)
    return next_state


def request_rebuild(state: State) -> State:
    """Use only for intention change or broad scene discontinuity."""
    next_state = deepcopy(state)
    next_state.instruction = None
    next_state.ready = False
    next_state.overall_progress = Progress.BLOCKED
    next_state.last_decision = Decision.REBUILD
    next_state.activity = "Scene assumptions changed; rebuilding the Shot Strategy from fresh evidence."
    next_state.pending_patch_for = None
    return next_state


def _request_patch(
    state: State,
    criterion: Criterion,
    progress: Progress,
    *,
    bump_revision: bool = False,
) -> State:
    state.instruction = None
    state.ready = False
    state.overall_progress = progress
    state.last_decision = Decision.PATCH
    state.activity = f"Replanning only “{criterion.label}”; other criteria remain intact."
    state.pending_patch_for = criterion.key
    if bump_revision:
        state.strategy_revision += 1
    return state


def _is_ready(state: State) -> bool:
    return all(
        not criterion.must_have
        or (
            state.evidence[criterion.key].progress == Progress.ACHIEVED
            and state.evidence[criterion.key].confidence >= READINESS_CONFIDENCE
            and state.evidence[criterion.key].evidence_id == state.evidence_id
        )
        for criterion in state.criteria
    )


def _active_criterion(state: State) -> Criterion | None:
    if state.instruction is None or state.instruction.criterion_key == "ready":
        return None
    return next(
        (criterion for criterion in state.criteria if criterion.key == state.instruction.criterion_key),
        None,
    )


def _next_unsatisfied(state: State) -> Criterion | None:
    return next(
        (
            criterion
            for criterion in sorted(state.criteria, key=lambda candidate: candidate.priority)
            if criterion.must_have
            and state.evidence[criterion.key].progress != Progress.ACHIEVED
        ),
        None,
    )


def _first_low_confidence_must_have(state: State) -> Criterion | None:
    return next(
        (
            criterion
            for criterion in sorted(state.criteria, key=lambda candidate: candidate.priority)
            if criterion.must_have
            and state.evidence[criterion.key].confidence < READINESS_CONFIDENCE
        ),
        None,
    )


def _first(state: State, progress: Progress, *, must_have_only: bool) -> Criterion | None:
    return next(
        (
            criterion
            for criterion in sorted(state.criteria, key=lambda candidate: candidate.priority)
            if (criterion.must_have or not must_have_only)
            and state.evidence[criterion.key].progress == progress
        ),
        None,
    )


def _instruction_targets(state: State, criterion: Criterion) -> bool:
    return state.instruction is not None and state.instruction.criterion_key == criterion.key


def _select_next_action(item: CriterionEvidence, criterion: Criterion) -> bool:
    for index in range(item.action_index + 1, len(criterion.actions)):
        if index not in item.rejected_actions:
            item.action_index = index
            item.consecutive_insufficient = 0
            return True
    return False


def _issue_action(state: State, criterion: Criterion) -> None:
    item = state.evidence[criterion.key]
    while item.action_index in item.rejected_actions:
        if not _select_next_action(item, criterion):
            state.instruction = None
            state.pending_patch_for = criterion.key
            state.last_decision = Decision.PATCH
            state.activity = f"No acceptable action remains for “{criterion.label}”; patching it."
            return
    _set_instruction(state, criterion.key, criterion.actions[item.action_index])


def _set_instruction(state: State, criterion_key: str, text: str) -> None:
    if state.instruction is not None and state.instruction.text == text:
        return
    state.instruction = Instruction(state.next_instruction_identity, criterion_key, text)
    state.next_instruction_identity += 1
