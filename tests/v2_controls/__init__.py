"""Deterministic public-seam test controls for the dormant v2 runtime.

This package is the test-only realization of the deterministic replay harness
described in ``docs/CAMERA_AGENT_V2_EVALUATION.md`` §3. It provides the
mechanical substitutions and strict scripted adapters that every subsequent v2
behavior slice uses to prove behavior through the public ``CoachingRuntime``,
``CoachingReasoner``, and ``IllustrationEditor`` seams rather than private
reducer coordination.

The controls are **not** a public semantic seam and **not** importable by the
production composition root (``camera_agent.server`` / ``camera_agent.__main__``).
They live under ``tests/`` precisely so they cannot become a second coaching
authority, a writable runtime-state lane, or a fakeable interface around
deterministic policy. They only:

- implement the already-approved public Adapter seams as strict scripted
  doubles (``ScriptedReasoner``, ``ScriptedEditor``);
- drive virtual monotonic time and deterministic or recorded identities;
- hand out immutable image fixtures;
- trace observed public outputs and Adapter calls and capture resource
  high-water marks; and
- offer reusable mandatory-invariant assertions over public contract values.

Nothing here mutates runtime state, allocates state revisions, writes to a
phone, or owns scheduling, retry, freshness, or visual-job policy. The dormant
v2 runtime path stays off the production composition root until the
atomic-cutover ticket.
"""

from __future__ import annotations

from .clock import ScheduledTimer, VirtualMonotonicClock
from .fixtures import ImageFixture, default_preview_fixture, default_still_fixture
from .identity import (
    DeterministicIdentityFactory,
    IdentitySeed,
    RecordedIdentityMap,
    deterministic_session_salt,
)
from .invariants import (
    InvariantViolation,
    assert_at_most_one_active_instruction,
    assert_coaching_projection_well_formed,
    assert_instruction_immutable_for_identity,
    assert_no_obsolete_current_output,
    assert_output_order_is_committed,
    assert_ready_cites_current_evidence,
    assert_single_terminal_disposition,
    assert_truthful_activity_when_no_instruction,
    assert_visual_sidecar_isolated,
)
from .scripted_adapters import (
    CallLifecycle,
    CompletionDriver,
    PendingCall,
    ScriptedEditor,
    ScriptedOutcome,
    ScriptedReasoner,
    ScriptedResponse,
)
from .tracing import CallTrace, OutputTrace, ResourceHighWater

__all__ = [
    # clock
    "VirtualMonotonicClock",
    "ScheduledTimer",
    # identity
    "DeterministicIdentityFactory",
    "IdentitySeed",
    "RecordedIdentityMap",
    "deterministic_session_salt",
    # fixtures
    "ImageFixture",
    "default_preview_fixture",
    "default_still_fixture",
    # scripted adapters
    "ScriptedResponse",
    "ScriptedOutcome",
    "PendingCall",
    "CallLifecycle",
    "CompletionDriver",
    "ScriptedReasoner",
    "ScriptedEditor",
    # tracing
    "CallTrace",
    "OutputTrace",
    "ResourceHighWater",
    # invariants
    "InvariantViolation",
    "assert_at_most_one_active_instruction",
    "assert_coaching_projection_well_formed",
    "assert_instruction_immutable_for_identity",
    "assert_no_obsolete_current_output",
    "assert_output_order_is_committed",
    "assert_ready_cites_current_evidence",
    "assert_single_terminal_disposition",
    "assert_truthful_activity_when_no_instruction",
    "assert_visual_sidecar_isolated",
]
