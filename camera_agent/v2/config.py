"""Immutable, versioned v2 runtime configuration with normative bounds.

These are the canonical threshold-bearing configuration values for the dormant v2
``CoachingRuntime``. Every value is frozen for one runtime instance, versioned in
evidence output, and marked calibrated or **uncalibrated**.

The defaults mirror the empirical starting points in
``docs/CAMERA_AGENT_V2_EVALUATION.md`` §9. They are intentionally conservative and
MUST NOT be weakened retrospectively for an active release run. A value may move
from uncalibrated to calibrated only through the versioned calibration procedure in
``docs/CAMERA_AGENT_V2_EVALUATION.md`` §10.

This module is dormant v2 contract code. It is not imported by the production
composition root (``camera_agent.server`` / ``camera_agent.__main__``) until the
atomic-cutover ticket.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .identity import RuntimeVersion


# Reasoner typed failures that the runtime may automatically retry once. All other
# failures (``rejected``, ``misconfigured``) are never automatically retried.
_AUTO_RETRYABLE_REASONER_FAILURES = frozenset(
    {"deadline_exceeded", "unavailable", "throttled", "invalid_output"}
)


@dataclass(frozen=True, slots=True)
class HeartbeatCadence:
    """Versioned heartbeat backoff cadence (15, 30, then 60 seconds).

    The cap remains 60 seconds for the Instruction-age interval. At most three
    heartbeat calls are permitted in any rolling two-minute window.
    """

    first_interval_seconds: float = 15.0
    second_interval_seconds: float = 30.0
    cap_interval_seconds: float = 60.0
    max_calls_per_rolling_window: int = 3
    rolling_window_seconds: float = 120.0

    def __post_init__(self) -> None:
        if not (0.0 < self.first_interval_seconds <= self.second_interval_seconds):
            raise ValueError("heartbeat intervals must be 0 < first <= second")
        if self.second_interval_seconds > self.cap_interval_seconds:
            raise ValueError("heartbeat cap must be >= second interval")
        if self.cap_interval_seconds <= 0:
            raise ValueError("heartbeat cap must be positive")
        if self.max_calls_per_rolling_window < 1:
            raise ValueError("heartbeat call budget must be at least 1")
        if self.rolling_window_seconds <= 0:
            raise ValueError("heartbeat rolling window must be positive")

    @property
    def intervals_seconds(self) -> tuple[float, float, float]:
        return (
            self.first_interval_seconds,
            self.second_interval_seconds,
            self.cap_interval_seconds,
        )


@dataclass(frozen=True, slots=True)
class ReasonerRetryPolicy:
    """Versioned Reasoner attempt deadline and automatic-retry budget.

    An 8-second per-attempt deadline, at most one automatic retry, and a 2-second
    cap on honored provider throttle delay. Only the configured typed failures are
    automatically retryable; ``rejected`` and ``misconfigured`` never auto-retry.
    Every retry uses a freshly assembled Context Pack and runs only while the
    semantic purpose remains current.
    """

    attempt_deadline_seconds: float = 8.0
    max_automatic_retries: int = 1
    throttle_delay_cap_seconds: float = 2.0
    auto_retryable_failures: frozenset[str] = _AUTO_RETRYABLE_REASONER_FAILURES

    def __post_init__(self) -> None:
        if self.attempt_deadline_seconds <= 0:
            raise ValueError("reasoner attempt deadline must be positive")
        if self.max_automatic_retries < 0:
            raise ValueError("reasoner retry budget must not be negative")
        if self.throttle_delay_cap_seconds < 0:
            raise ValueError("reasoner throttle delay cap must not be negative")
        if not self.auto_retryable_failures:
            raise ValueError("at least one reasoner failure must be auto-retryable")

    def is_auto_retryable(self, typed_failure: str) -> bool:
        return typed_failure in self.auto_retryable_failures


@dataclass(frozen=True, slots=True)
class VisualDeadlines:
    """Versioned capture and illustration-editor deadlines.

    High-resolution capture has a 5-second deadline; the editor has a 60-second
    attempt deadline. Neither is retried automatically; each accepted explicit
    Retry authorizes exactly one new attempt under the same deadline.
    """

    capture_deadline_seconds: float = 5.0
    editor_deadline_seconds: float = 60.0
    max_automatic_retries: int = 0

    def __post_init__(self) -> None:
        if self.capture_deadline_seconds <= 0:
            raise ValueError("capture deadline must be positive")
        if self.editor_deadline_seconds <= 0:
            raise ValueError("editor deadline must be positive")
        if self.max_automatic_retries != 0:
            raise ValueError("visual capture/edit must never auto-retry")


@dataclass(frozen=True, slots=True)
class FrameSignalPolicy:
    """Versioned deterministic frame-signal and material-change thresholds.

    These are the CPU-cheap deterministic signal crossings (spec §4.2). A hard
    camera-context change (lens/orientation/frame dimensions), a material
    preview/metadata delta, or a calibrated quality crossing immediately
    invalidates settled Evidence. Deterministic signals MAY invalidate, request
    reasoning, or enter a Context Pack; they MUST NOT establish semantic
    achievement or Readiness. The values are inherited from the v1 material-
    change thresholds and are explicitly **uncalibrated** until a documented
    calibration run promotes them.
    """

    camera_hard_change_keys: tuple[str, ...] = (
        "lensID",
        "orientation",
        "frameWidth",
        "frameHeight",
    )
    visual_material_global_mae: float = 0.04
    visual_material_block_mae: float = 0.10
    visual_material_hash_distance: int = 6
    visual_thumbnail_size: int = 64
    visual_blur_radius: float = 1.0
    visual_alignment_radius: int = 2
    sharpness_regression_threshold: float = 0.15
    luminance_change_threshold: float = 0.10
    highlight_clipping_threshold: float = 0.02
    shadow_clipping_threshold: float = 0.02

    def __post_init__(self) -> None:
        if not self.camera_hard_change_keys:
            raise ValueError("at least one hard camera-context key is required")
        for name, value in {
            "visual_material_global_mae": self.visual_material_global_mae,
            "visual_material_block_mae": self.visual_material_block_mae,
            "sharpness_regression_threshold": self.sharpness_regression_threshold,
            "luminance_change_threshold": self.luminance_change_threshold,
            "highlight_clipping_threshold": self.highlight_clipping_threshold,
            "shadow_clipping_threshold": self.shadow_clipping_threshold,
        }.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")
        if self.visual_material_hash_distance <= 0:
            raise ValueError("visual_material_hash_distance must be positive")
        if self.visual_thumbnail_size < 8 or self.visual_thumbnail_size % 4:
            raise ValueError("visual_thumbnail_size must be >= 8 and divisible by 4")
        if self.visual_blur_radius < 0:
            raise ValueError("visual_blur_radius must not be negative")
        if self.visual_alignment_radius < 0:
            raise ValueError("visual_alignment_radius must not be negative")


@dataclass(frozen=True, slots=True)
class SettledPolicy:
    """Versioned asymmetric Settled hysteresis.

    A new Evidence identity is emitted only when configurable mutually equivalent
    post-change observations meet both a confirmation count and a dwell duration.
    A material change immediately invalidates settled Evidence.
    """

    confirmation_count: int = 2
    dwell_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.confirmation_count < 1:
            raise ValueError("settled confirmation count must be at least 1")
        if self.dwell_seconds <= 0:
            raise ValueError("settled dwell duration must be positive")


@dataclass(frozen=True, slots=True)
class StrategyBounds:
    """Versioned Shot Strategy and Criterion size bounds.

    A Strategy is at most six Criteria (four must-have, two nice-to-have). Each
    Criterion carries at most three candidate actions. Per Criterion, at most two
    recent distinct attempted actions are retained.
    """

    max_criteria: int = 6
    max_must_have: int = 4
    max_nice_to_have: int = 2
    max_candidate_actions_per_criterion: int = 3
    max_recent_distinct_actions_per_criterion: int = 2

    def __post_init__(self) -> None:
        if self.max_criteria < 1:
            raise ValueError("strategy must allow at least one criterion")
        if self.max_must_have < 1:
            raise ValueError("strategy must allow at least one must-have")
        if self.max_must_have + self.max_nice_to_have != self.max_criteria:
            raise ValueError("must-have + nice-to-have must equal total criteria")
        if self.max_candidate_actions_per_criterion < 1:
            raise ValueError("a criterion needs at least one candidate action")
        if self.max_recent_distinct_actions_per_criterion < 1:
            raise ValueError("recent distinct action retention must be at least 1")


@dataclass(frozen=True, slots=True)
class ContextPackBounds:
    """Versioned Context Pack content bounds.

    Structured text is capped at 32 KiB UTF-8 excluding image bytes. Strategy and
    revision calls receive at most one current preview; progress receives at most
    one current plus one previous compatible preview; editing receives exactly one
    accepted high-resolution still. An Adapter MAY publish a stricter limit; the
    runtime uses the lower bound.
    """

    structured_text_max_bytes: int = 32 * 1024
    strategy_revision_max_previews: int = 1
    progress_max_previews: int = 2
    edit_exact_stills: int = 1

    def __post_init__(self) -> None:
        if self.structured_text_max_bytes <= 0:
            raise ValueError("context text cap must be positive")
        if self.strategy_revision_max_previews != 1:
            raise ValueError("strategy/revision receives exactly 1 current preview")
        if self.progress_max_previews != 2:
            raise ValueError("progress receives 1 current + 1 previous preview")
        if self.edit_exact_stills != 1:
            raise ValueError("edit receives exactly 1 accepted still")


@dataclass(frozen=True, slots=True)
class EvidenceMemoryBounds:
    """Versioned Task Memory retention bounds for Evidence and previews."""

    max_previous_compatible_snapshots: int = 1
    max_retained_previews: int = 2

    def __post_init__(self) -> None:
        if self.max_previous_compatible_snapshots < 0:
            raise ValueError("previous snapshot retention must not be negative")
        if self.max_retained_previews < 1:
            raise ValueError("at least one preview must be retained")


@dataclass(frozen=True, slots=True)
class ActionReplayBounds:
    """Versioned one-use action replay window.

    Action UUIDs are minted from a session-scoped monotonic ordinal. The runtime
    retains at most 256 action receipts and 256 action-message receipts for 10
    minutes; after eviction, old input is safely ``stale`` rather than
    historically classified.
    """

    max_action_receipts: int = 256
    max_action_message_receipts: int = 256
    retention_seconds: float = 600.0

    def __post_init__(self) -> None:
        if self.max_action_receipts < 1:
            raise ValueError("action receipt capacity must be at least 1")
        if self.max_action_message_receipts < 1:
            raise ValueError("action-message receipt capacity must be at least 1")
        if self.retention_seconds <= 0:
            raise ValueError("action receipt retention must be positive")


@dataclass(frozen=True, slots=True)
class TransportBounds:
    """Versioned transport-edge and diagnostic resource bounds.

    The transport edge retains at most 16 unmatched observation entries per side
    for 5 seconds, caps every message at 8 MiB, and caps each serialized send queue
    at 32 frames or 16 MiB. Crossing a bound closes and detaches the connection.
    Diagnostics are capped at 200 files or 256 MiB per run.
    """

    observation_fragment_max_unmatched_per_side: int = 16
    observation_fragment_ttl_seconds: float = 5.0
    max_message_bytes: int = 8 * 1024 * 1024
    send_queue_max_frames: int = 32
    send_queue_max_bytes: int = 16 * 1024 * 1024
    diagnostic_max_files: int = 200
    diagnostic_max_bytes: int = 256 * 1024 * 1024

    def __post_init__(self) -> None:
        if self.observation_fragment_max_unmatched_per_side < 1:
            raise ValueError("observation fragment capacity must be at least 1")
        if self.observation_fragment_ttl_seconds <= 0:
            raise ValueError("observation fragment TTL must be positive")
        if self.max_message_bytes <= 0:
            raise ValueError("message byte cap must be positive")
        if self.send_queue_max_frames < 1:
            raise ValueError("send queue frame cap must be at least 1")
        if self.send_queue_max_bytes < 1:
            raise ValueError("send queue byte cap must be at least 1")
        if self.diagnostic_max_files < 1:
            raise ValueError("diagnostic file cap must be at least 1")
        if self.diagnostic_max_bytes < 1:
            raise ValueError("diagnostic byte cap must be at least 1")


@dataclass(frozen=True, slots=True)
class ProgressPolicy:
    """Versioned deterministic progress policy bounds.

    A first action is retained through two accepted Settled ``insufficient``
    assessments spanning at least 10 seconds. After two distinct insufficient
    actions with no intervening improvement, the runtime requests a local
    Criterion patch. The same threshold requests a visual-guidance offer.
    """

    insufficient_count_before_alternative: int = 2
    insufficient_span_seconds: float = 10.0
    distinct_insufficient_actions_before_patch: int = 2
    visual_offer_distinct_insufficient_actions: int = 2

    def __post_init__(self) -> None:
        if self.insufficient_count_before_alternative < 1:
            raise ValueError("insufficient count must be at least 1")
        if self.insufficient_span_seconds <= 0:
            raise ValueError("insufficient span must be positive")
        if self.distinct_insufficient_actions_before_patch < 1:
            raise ValueError("distinct action count must be at least 1")
        if self.visual_offer_distinct_insufficient_actions < 1:
            raise ValueError("visual offer action count must be at least 1")


@dataclass(frozen=True, slots=True)
class ContinuityBounds:
    """Versioned ``RuntimeHost`` cross-connection continuity bounds."""

    max_detached_sessions: int = 1
    detached_ttl_seconds: float = 60.0
    reject_second_active_connection: bool = True

    def __post_init__(self) -> None:
        if self.max_detached_sessions < 0:
            raise ValueError("detached session capacity must not be negative")
        if self.detached_ttl_seconds <= 0:
            raise ValueError("detached TTL must be positive")


@dataclass(frozen=True, slots=True)
class DiagnosticTargets:
    """Diagnostic latency targets (p95). These are not release gates.

    They are reported as distributions by operation, semantic purpose, event
    class, disposition, and cold/warm state. Failures are right-censored at the
    configured terminal deadline, never silently dropped.
    """

    action_ack_p95_ms: float = 250.0
    event_to_activity_p95_ms: float = 250.0
    settled_to_useful_instruction_p95_ms: float = 6_000.0
    accepted_still_to_available_warm_p95_ms: float = 15_000.0
    failure_to_recovery_p95_ms: float = 1_000.0

    def __post_init__(self) -> None:
        for name, value in {
            "action_ack_p95_ms": self.action_ack_p95_ms,
            "event_to_activity_p95_ms": self.event_to_activity_p95_ms,
            "settled_to_useful_instruction_p95_ms": (
                self.settled_to_useful_instruction_p95_ms
            ),
            "accepted_still_to_available_warm_p95_ms": (
                self.accepted_still_to_available_warm_p95_ms
            ),
            "failure_to_recovery_p95_ms": self.failure_to_recovery_p95_ms,
        }.items():
            if value <= 0:
                raise ValueError(f"{name} must be positive")


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    """Immutable, versioned configuration for one ``CoachingRuntime`` instance.

    All threshold-bearing configuration is frozen for one runtime instance,
    versioned in evidence, and marked calibrated or **uncalibrated**. The initial
    values are the empirical starting points from the evaluation contract and are
    explicitly **uncalibrated** until a documented calibration run promotes them.
    """

    version: RuntimeVersion = field(default_factory=RuntimeVersion)
    calibrated: bool = False

    ready_confidence_threshold: float = 0.75
    confidence_min: float = 0.0
    confidence_max: float = 1.0
    nice_to_have_instruction_budget: int = 0
    physical_vlm_max_concurrency: int = 2
    max_authoritative_runs: int = 1
    max_pending_semantic_requests: int = 1

    grounding_max_facts: int = 4
    grounding_fact_max_chars: int = 160
    uncertainty_max_reasons: int = 3
    overlay_source_max_age_seconds: float = 2.0

    heartbeat: HeartbeatCadence = field(default_factory=HeartbeatCadence)
    reasoner_retry: ReasonerRetryPolicy = field(default_factory=ReasonerRetryPolicy)
    visual: VisualDeadlines = field(default_factory=VisualDeadlines)
    settled: SettledPolicy = field(default_factory=SettledPolicy)
    frame_signals: FrameSignalPolicy = field(default_factory=FrameSignalPolicy)
    strategy: StrategyBounds = field(default_factory=StrategyBounds)
    context: ContextPackBounds = field(default_factory=ContextPackBounds)
    evidence_memory: EvidenceMemoryBounds = field(default_factory=EvidenceMemoryBounds)
    action_replay: ActionReplayBounds = field(default_factory=ActionReplayBounds)
    transport: TransportBounds = field(default_factory=TransportBounds)
    progress: ProgressPolicy = field(default_factory=ProgressPolicy)
    continuity: ContinuityBounds = field(default_factory=ContinuityBounds)
    diagnostics: DiagnosticTargets = field(default_factory=DiagnosticTargets)

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence_min < self.confidence_max <= 1.0):
            raise ValueError("confidence range must satisfy 0 <= min < max <= 1")
        if not (
            self.confidence_min
            <= self.ready_confidence_threshold
            <= self.confidence_max
        ):
            raise ValueError("ready confidence threshold must be within [min, max]")
        if self.physical_vlm_max_concurrency < 1:
            raise ValueError("physical VLM concurrency must be at least 1")
        if self.max_authoritative_runs < 1:
            raise ValueError("at least one authoritative run must be permitted")
        if self.max_pending_semantic_requests < 0:
            raise ValueError("pending semantic request capacity must not be negative")
        if self.nice_to_have_instruction_budget != 0:
            raise ValueError("v2 emits zero nice-to-have Instructions")
        if self.grounding_max_facts < 1:
            raise ValueError("a grounding assessment needs at least one fact")
        if self.grounding_fact_max_chars < 1:
            raise ValueError("grounding fact character cap must be positive")
        if self.uncertainty_max_reasons < 0:
            raise ValueError("uncertainty reason cap must not be negative")
        if self.overlay_source_max_age_seconds <= 0:
            raise ValueError("overlay source age bound must be positive")

    @property
    def is_uncalibrated(self) -> bool:
        return not self.calibrated
