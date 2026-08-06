# Protocol-v1 Baseline and v2 Delta Classification

This document freezes the observable protocol-v1 baseline and classifies every
v1 behavior that differs from the approved Camera Agent Harness v2 contracts
landed from commit `af512e5`. It is the characterization evidence referenced by
[CAMERA_AGENT_V2_EVALUATION.md](CAMERA_AGENT_V2_EVALUATION.md): "Existing
fixed-plan wording and legacy generated-reference behavior are characterization
evidence only where v2 intentionally changes them."

The current branch keeps the v1 composition root operational. The v2 contracts
are dormant normative source; they do not cut over runtime authority until the
atomic-cutover ticket (see [HARNESS_ARCHITECTURE.md](HARNESS_ARCHITECTURE.md),
"Migration and atomic cutover"). Protocol v2 is reached only through
progressive negotiation over the exact v1 hello; a v1-only connection uses the
same runtime through the lossy v1 fallback projection defined in
[PROTOCOL_V2.md](PROTOCOL_V2.md) §12.

## Classification buckets

Each v1 delta is classified into exactly one bucket:

- **Preserved** — the v1 behavior is retained by v2 (either unchanged, or as
  the v1 fallback projection when the v2 addition requires v2 negotiation).
- **Strategy-derived wording** — v1 fixed-plan step wording is replaced by
  v2 Strategy/Criterion-derived wording and an Evidence Snapshot.
- **Instruction-over-Activity projection** — v1's single `result.text`
  instruction (with no separate Activity, phase, or one-use actions) is the
  lossy v1 fallback form of v2's persistent Instruction plus transient Activity
  plus derived phase.
- **disabled v1 Generated Visual Guidance** — the v1 generated-reference
  workflow is disabled under v1 because v1 cannot express identified Generate
  consent.

## Classification

| # | v1 baseline behavior | Classification | v2 contract reference | Frozen by |
| --- | --- | --- | --- | --- |
| 1 | Hello handshake: `client="HelloCamera-iOS"`, capabilities, once per connection | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §4.1; [SPEC](CAMERA_AGENT_V2_SPEC.md) §9 | `tests/test_v1_baseline.py` §5 |
| 2 | Binary envelope: big-endian `uint32` length prefix + compact JSON header + raw payload | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §2 | `tests/test_v1_baseline.py` §1 |
| 3 | Dual-ID observation correlation: join on `imageMessageId`, cross-check `observationId`; at most 16 unmatched per side for 5 s | Preserved | [EVAL](CAMERA_AGENT_V2_EVALUATION.md) S01; [PROTOCOL_V2.md](PROTOCOL_V2.md) §2 | `tests/test_v1_baseline.py` §2 |
| 4 | Preview and high-resolution image transport: JPEG/PNG signatures, 640/1024 px long-edge limits, non-empty payload | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §2; [PROTOCOL.md](PROTOCOL.md) | `tests/test_v1_baseline.py` §1, §3 |
| 5 | Result closed object: `version=1`, required fields, unique `messageId`, unknown fields rejected | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §12; [PROTOCOL.md](PROTOCOL.md) | `tests/test_v1_baseline.py` §1 |
| 6 | Overlay primitives and normalized coordinates (arrow/line/rectangle/circle/path/text) | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §6.4 ("Coordinates and geometry follow protocol v1") | `tests/test_v1_baseline.py` §4 |
| 7 | Overlay freshness: `overlay_primitives` capability gating, camera-signature mismatch suppression, `expiresInMilliseconds` expiry | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §6.4 | `tests/test_v1_baseline.py` §4 |
| 8 | Overlay ID uniqueness and the three-overlay cap | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §6.4; `make_result` | `tests/test_v1_baseline.py` §4 |
| 9 | Ready rendered as the current Instruction (`"Ready—take the shot."`) | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §12 ("render Ready as the current Instruction") | `tests/test_v1_baseline.py` §5 |
| 10 | Unknown text-message types ignored | Preserved | [PROTOCOL.md](PROTOCOL.md) ("MUST be ignored for forward compatibility and protocol-v2 progressive negotiation"); [PROTOCOL_V2.md](PROTOCOL_V2.md) §10 | `tests/test_schema_contracts.py` |
| 11 | Change detection and settling primitives: confirmations, hard change during inference, stale global/block MAE | Preserved | [SPEC](CAMERA_AGENT_V2_SPEC.md) §4.2; [EVAL](CAMERA_AGENT_V2_EVALUATION.md) "reuses only pure helpers with matching semantics" | `tests/test_coaching.py`, `tests/test_change_detection.py` |
| 12 | Local shutter always available; capture neutrally acknowledged; never interpreted as achievement, refusal, or premature action | Preserved | [SPEC](CAMERA_AGENT_V2_SPEC.md) §1; user stories #18–#19 | v1 invariant |
| 13 | Reconnect without offline buffering or semantic continuity (under v1 fallback) | Preserved | [PROTOCOL_V2.md](PROTOCOL_V2.md) §12 (v1 fallback); [SPEC](CAMERA_AGENT_V2_SPEC.md) §10 (v2 adds bounded detached continuity only under negotiation) | v1 baseline |
| 14 | Fixed-plan instruction wording derived from `PlanningDecision`/`VerificationDecision` over an ordered `ShotPlan` of `PlanStep`s | Strategy-derived wording | [SPEC](CAMERA_AGENT_V2_SPEC.md) §5, §3.4; [EVAL](CAMERA_AGENT_V2_EVALUATION.md) "characterization evidence only where v2 intentionally changes" | `tests/test_coaching.py` |
| 15 | `PlanningRequest`/`VerificationRequest`/`ShotPlan`/`PlanStep` domain shapes | Strategy-derived wording | [SPEC](CAMERA_AGENT_V2_SPEC.md) §5.1, §5.2 (Criterion and Evidence Snapshot) | `tests/test_coaching.py` |
| 16 | Single `result.text` instruction; no separate Activity lane; no derived phase lane; no explicit one-use actions | Instruction-over-Activity projection | [PROTOCOL_V2.md](PROTOCOL_V2.md) §12; [SPEC](CAMERA_AGENT_V2_SPEC.md) §9, §6.1 | `tests/test_v1_baseline.py` §5 |
| 17 | Transient `"Analyzing new shot…"` and failed-recovery text | Instruction-over-Activity projection | [PROTOCOL_V2.md](PROTOCOL_V2.md) §12 ("Activity appears as v1 text only when no Instruction exists") | `tests/test_v1_baseline.py` §5 |
| 18 | Generated-reference `ReferenceWorkflow`: phrase-list consent via `explicit_sample_permission`, proactive `capture_high_resolution`, edit plus result/`result_image` pair, isolation from coaching | disabled v1 Generated Visual Guidance | [PROTOCOL_V2.md](PROTOCOL_V2.md) §12 ("disable Generated Visual Guidance because v1 cannot express identified Generate consent"); [SPEC](CAMERA_AGENT_V2_SPEC.md) §8 | `tests/test_v1_baseline.py` §5; `tests/test_server_integration.py` |

## Migration posture

Rows 1–13 are the frozen v1 baseline: the v2 cutover must not regress them, and
the regression fixtures cited above enforce that. Rows 14–15 (Strategy-derived
wording) and 16–17 (Instruction-over-Activity projection) are the approved
v2-era changes to v1 coaching projection; the v1 wording and single-text
projection remain valid only as the lossy v1 fallback defined in
[PROTOCOL_V2.md](PROTOCOL_V2.md) §12. Row 18 (disabled v1 Generated Visual
Guidance) is the approved v2-era change to generated imagery: the v1
`ReferenceWorkflow` is legacy implementation that v2 removes at the atomic
cutover, and Generated Visual Guidance cannot begin under v1 because v1 lacks
an identified Generate consent action.
