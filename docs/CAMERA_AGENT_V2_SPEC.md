# Camera Agent Harness v2 Specification

Status: implementation-ready specification for the single-user research prototype.

This document owns normative product/runtime behavior and public Interface
requirements for the desktop harness. [HARNESS_ARCHITECTURE.md](HARNESS_ARCHITECTURE.md)
is the sole maintained source for module arrangement, composition, and migration.
[PROTOCOL_V2.md](PROTOCOL_V2.md) and
[protocol-v2.schema.json](protocol-v2.schema.json) are normative for the v2 wire
extension. [CAMERA_AGENT_V2_EVALUATION.md](CAMERA_AGENT_V2_EVALUATION.md) is
normative for evaluation and release. Protocol v1 remains normative in
[PROTOCOL.md](PROTOCOL.md) and [protocol-v1.schema.json](protocol-v1.schema.json).

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
to be interpreted as requirements on the v2 implementation.

## 1. Destination and scope

V2 is a responsive, trustworthy, single-user camera-coaching research prototype
for:

1. general composition;
2. portrait composition and posing; and
3. proactively offered **Generated Visual Guidance**, made by editing a current
   high-resolution still.

The iPhone remains a dumb camera and renderer. It owns camera controls, intention
entry, the local shutter, saved photos, reconnect, and rendering. The desktop owns
task state, reasoning, scheduling, memory, freshness, and the coaching projection.
The desktop MUST NOT remotely change lens, zoom, focus, exposure, or save a photo.
The local shutter MUST remain available in every harness state.

One endpoint serves at most one phone and one active user. The deployment assumes
a trusted iPhone–WSL network and task-scoped in-memory continuity. TLS, pairing,
authentication, multi-device operation, durable identity, cross-session history,
external reference-image upload, production distribution, and fully specified
journeys beyond the three above are out of scope.

## 2. User experience contract

### 2.1 Information hierarchy

The renderer MUST present these concepts separately:

1. accepted intention;
2. coaching phase;
3. one persistent **Instruction**;
4. transient coaching **Activity**;
5. contextual explicit actions;
6. freshness-bound overlays; and
7. a separate Generated Visual Guidance area with its own Activity.

An Instruction is one immediate observable action. It MUST identify the
Photographer or Subject when responsibility could be ambiguous, MUST NOT expose
hidden reasoning, and MUST NOT stack follow-up actions. Activity describes what
the harness is doing or waiting for; it MUST NOT replace or silently mutate the
Instruction. When no Instruction exists, the projection MUST contain truthful
primary Activity or a scoped recovery message rather than an unexplained blank.

### 2.2 Derived coaching phases

The runtime derives, rather than independently stores, one of:

| Phase | Required experience |
| --- | --- |
| `needs_intention` | Ask for an intention; do not coach. |
| `orienting` | Keep the accepted intention visible, require post-intention evidence, and show truthful scene-analysis Activity. |
| `coaching` | Show exactly one persistent actionable Instruction. |
| `evaluating` | Keep the prior Instruction visible in a secondary treatment and make “Checking your adjustment—hold still” or equivalent the primary Activity. Continued motion restarts evaluation without scolding. |
| `ready` | Show the evidence-backed Ready Instruction; nice-to-have refinements do not block it or the shutter. |
| `recovering` | State a user-visible problem and one concrete next action while preserving usable guidance when possible. |
| `paused` | Keep retained guidance visibly inactive; perform no new reasoning, reminders, offers, or capture requests. |

Generated Visual Guidance is a concurrent sidecar, not an exclusive phase.

### 2.3 Required controls and behavior

- **Try another suggestion** rejects the targeted Instruction without claiming it
  was achieved. The runtime MUST acknowledge the action, record the rejection as
  a strategy constraint, and seek a non-equivalent action. It MUST NOT repeat the
  rejected action in a materially equivalent situation unless new evidence makes
  the situation non-equivalent.
- **Pause coaching** MUST immediately invalidate pending/running reasoning,
  overlays, reminders, and visual jobs. **Resume coaching** MUST require fresh
  settled evidence before retained guidance becomes current again. Intention
  editing while paused MUST NOT implicitly resume.
- Intention editing and the local shutter remain phone-owned and available in all
  phases.
- Visual offers expose **Generate** and **Not now**. Active or failed visual jobs
  expose only actions appropriate to their current state, such as Cancel, Retry,
  Dismiss, or Another example.

A user capture MUST proceed locally. It is neutrally acknowledged, invalidates
analysis tied to an older view, and requires fresh live evidence. It MUST NOT be
interpreted as achievement, rejection, refusal, or “too soon.” After capture,
Ready remains displayed until accepted fresh evidence shows a material regression
or the intention changes.

### 2.4 Journey-specific rules

**General composition.** Prioritize the highest-impact controllable framing
problem, normally address the Photographer, and use sparse overlays only when
they materially clarify the action. When a requested composition is infeasible,
offer a practical alternative rather than repeating the same action.

**Portrait composition and posing.** Name the Photographer or Subject when
ambiguous and direct only one actor at a time. Use neutral, physically modest,
observable movement. Do not judge attractiveness, body shape, identity, or
emotion, and do not infer comfort or consent from visual achievability.

**Generated Visual Guidance.** A generated image is an edited illustration of
one adjustment, never a live preview, saved user photo, or source of live-shot
Evidence or Readiness. The UI MUST label it exactly as specified in the v2
protocol and keep it separate from the live view.

## 3. Runtime Module and authority

### 3.1 Public Interface

One deep mailbox-style `CoachingRuntime` Module is the sole session authority:

```python
class CoachingRuntime:
    async def submit(self, event: RuntimeEvent) -> Receipt: ...
    def outputs(self) -> AsyncIterator[RuntimeOutput]: ...
    async def close(self) -> None: ...
```

Construction supplies immutable versioned configuration and selected
`CoachingReasoner` and `IllustrationEditor` Adapters.

`submit` MUST acknowledge admission without waiting for remote work. Concurrent
submissions receive one authoritative order. The runtime MUST commit state before
launching effects or emitting resulting outputs. Async work MUST NOT mutate state
or write to a phone directly; every completion re-enters the same mailbox as a
correlated event. `outputs` yields complete immutable semantic projections or
correlated phone-bound requests in committed order. `close` immediately invalidates
outstanding authority and releases bounded retained images without depending on
physical cancellation.

The internal transition contract is pure:

```text
current state + one semantic event -> next state + declarative effects
```

Protocol Adapters, tests, and callers MUST NOT receive mutable state lanes or
coordinate reducer steps themselves.

### 3.2 Authoritative state

The runtime stores orthogonal facts and derives phase and Activity from them:

- **Task**: absent, or `{task_epoch, task_id, accepted_intention,
  strategy_revision}`.
- **Mode**: `active | paused`.
- **Connection**: `connected | disconnected |
  connected_needs_fresh_evidence`.
- **Evidence state**: `missing | moving | settling | settled`. Settled state
  identifies evidence, camera context, source observation, and exact source bytes.
- **Instruction**: zero or one immutable active Instruction with identity, kind,
  text, addressee, task/strategy provenance, source Evidence, and freshness
  `current | needs_revalidation | may_be_outdated`.
- **Readiness**: `not_ready | ready | needs_revalidation`, with supporting Evidence.
- **Analysis**: `idle | requested | running`, with purpose `orient | evaluate |
  replan` and all authority tokens.
- **Recovery**: independently scoped coaching, connection, capture, reasoner, or
  editor failures.
- **Generated Visual Guidance**: `idle | offered | waiting_for_settle | capturing |
  generating | available | failed`, with visual-job provenance.
- **Overlays**: transient render artifacts bound to one Instruction and Evidence.

The required semantic authority and facts are specified here. Their private module
arrangement is defined only in
[HARNESS_ARCHITECTURE.md](HARNESS_ARCHITECTURE.md).

### 3.3 Identities and tokens

Application-authored UUIDs identify task, strategy revision, Criterion,
Instruction, Evidence, camera context, reasoning run, visual offer/job/attempt,
capture request, action opportunity, and generated transfer as applicable.
Observation identity remains the v1 positive process-local `observationId`.

Every remote invocation and completion MUST carry an out-of-band provenance
envelope containing its purpose and all applicable identities. Model-controlled
output MUST NOT author or alter those identities. A completion may affect state
only if its run remains authoritative and every applicable token is current.
Duplicate, late, stale, orphaned, physically uncancelled, or malformed completions
are harmless dispositions.

### 3.4 Instruction lifecycle and Readiness

Any user-visible change to actionable text, kind, or addressee creates a new
immutable Instruction identity. An equivalent `hold` preserves the exact identity
and text. Closing an Instruction records exactly one disposition:
`achieved | superseded | rejected | irrelevant | task_ended`.

`Ready—take the shot.` is an Instruction with `kind=ready` and a separate
Readiness record citing accepted current Evidence. Reconfirmation preserves the
Ready Instruction identity. Motion and user capture mark its support as needing
revalidation but do not revoke or flicker Ready. Only an accepted current-token
evaluation may reconfirm Ready or replace it with a new actionable Instruction.

The following invariants are mandatory:

1. At most one active Instruction exists.
2. Phase and Activity are projections of authoritative facts.
3. Only an accepted current-token result may change Instruction or Readiness.
4. Activity, overlays, motion, capture, and visual guidance cannot silently
   change Instruction or Readiness.
5. Pause, task change, disconnect, evidence invalidation, and explicit
   cancellation make late work harmless.
6. Explicit identified actions are idempotent and one-use.
7. Generated Visual Guidance never changes live Evidence, Shot Strategy,
   Instruction, or Readiness.

## 4. Observation, Evidence, and scheduling

### 4.1 Immutable assembly

The transport-edge `ObservationAssembler` MUST correlate observation metadata and
preview bytes using both `imageMessageId` and `observationId`. It MUST bound and
expire unmatched fragments. No detector, prompt, or result may combine fields or
bytes from different observations.

Each complete context contains exact camera metadata, oriented preview bytes,
arrival timing, v1 observation reason, and correlation identities.

### 4.2 Deterministic frame signals

Every complete preview is assessed with CPU-cheap deterministic signals:

- compatible camera-context metadata deltas;
- existing thumbnail, global/local difference, and hash-supported change signals;
- mutual equivalence of post-change frames;
- relative sharpness/blur regression against compatible Evidence; and
- luminance and highlight/shadow clipping measurements.

Automatic exposure and white-balance shimmer is ignored unless a calibrated
quality signal shows a meaningful change. Blur is comparative and MAY be unknown;
it is not proof of missed focus. Decode failure yields unavailable quality data
and conservative fail-open change handling.

V2 MUST NOT add learned pose, face, person, object, open-vocabulary, or framing
probes. Deterministic signals may invalidate Evidence, influence Settled, request
reasoning, or enter a Context Pack. They MUST NOT establish semantic achievement,
subject presence, framing correctness, or Readiness.

### 4.3 Settled hysteresis

A hard camera-context change, material preview/metadata delta, or calibrated
quality crossing immediately invalidates settled Evidence, spatial overlays,
queued work, and authoritative run tokens. The runtime emits a new Evidence
identity only when configurable mutually equivalent post-change observations meet
both a confirmation count and dwell duration.

No event bypasses settling for VLM work. Intention change, rejection, reconnect,
capture, and other explicit actions may invalidate and reprioritize immediately,
but reasoning still receives one coherent settled view.

### 4.4 Semantic requests and queue policy

One settled Evidence bundle may create one request in this priority order:

1. orientation or explicit replanning when no Instruction exists or a revision is
   explicitly required;
2. material evaluation after meaningful scene/camera/quality change; then
3. heartbeat evaluation when unchanged settled Evidence reaches its recheck
   deadline.

Maintain at most one authoritative VLM run and one newest pending semantic request.
A newer equal- or higher-priority request replaces pending work. Heartbeat MUST NOT
displace user- or evidence-driven work. Equivalent frames update the latest view
without changing Evidence identity or adding queue entries.

Heartbeat is a bounded safety net for subtle compliance, missed quality changes,
no progress, and stale readiness. Repeated unchanged `hold` outcomes back off its
cadence up to an Instruction-age budget. Material change, new Instruction,
explicit action, adapter failure, and task change reset the cadence.

Logical cancellation is immediate. The runtime requests best-effort physical
cancellation, then MAY start one replacement alongside one abandoned
non-cancellable call. Total physical VLM concurrency MUST NOT exceed two. If both
slots are occupied, retain only the newest pending request until a slot drains.

Text may be projected against the newest observation proven equivalent to the
analyzed Evidence. Spatial overlays remain bound to the exact analyzed observation
and must pass protocol freshness checks.

## 5. Shot Strategy and deterministic progress policy

### 5.1 Strategy shape

A Shot Strategy is a small, priority-ordered set of at most six observable
Criteria—at most four must-haves and two nice-to-haves—not a fixed step list. The
strategy and every Criterion have stable application-authored identities. A
Criterion contains at most three candidate actions and:

- an observable target;
- `must_have | nice_to_have` importance;
- priority;
- responsible actor when relevant;
- feasible incremental actions; and
- explicit user/reality constraints.

Current focus and Instruction are runtime facts, not a cursor embedded in the
strategy. In v2, nice-to-haves are diagnostic context only: they MUST NOT produce
an Instruction, delay Ready, or replace Ready after it is reached.

### 5.2 Evidence Snapshot

Each accepted settled view produces one strategy-indexed Evidence Snapshot with:

- task, strategy, Evidence, camera-context, observation, and image identities;
- one grounded assessment for every must-have against that same view;
- relevant nice-to-have assessments;
- task-relevant observable facts and cheap deterministic signals;
- the observed response to the active Instruction; and
- bounded confidence, uncertainty, and blocked-condition records.

Every assessed Criterion has exactly one classification:

- `achieved`: plausibly satisfied;
- `improving`: materially closer but unmet;
- `insufficient`: observable and unmet without meaningful progress;
- `deviating`: materially farther away or regressed;
- `blocked`: cannot currently be judged or completed.

A `CriterionAssessment` contains:

- current `criterion_id` and one classification above;
- `confidence`: a finite number in `[0, 1]`, or `null` when confidence is unknown;
- `grounding`: one to four observable-fact records, each at most 160 characters,
  tagged `current` or `previous`; chain-of-thought and hidden reasoning are
  prohibited;
- `uncertainty_reasons`: zero to three values from `occluded`, `blurred`,
  `poor_lighting`, `out_of_frame`, `ambiguous_subject`, `insufficient_change`,
  `conflicting_cues`, or `other`; and
- `blocked_reason`: required only for `blocked`, one of `not_observable`,
  `temporarily_infeasible`, `action_infeasible`, or `ambiguous`.

Every must-have assessment MUST contain at least one `current` grounding fact.
The progress output also contains one `StrategyApplicability` record with
`status: applicable | broad_discontinuity | unknown`, finite `[0,1]` or null
confidence, and one to four bounded current-view grounding facts. Deterministic
frame signals may request this semantic check but cannot author its result.

`null` confidence cannot support Ready. Confidence is internal evidence, never a
user-facing percentage. Ready is derived only when every must-have is `achieved`
with non-null confidence at or above the configured threshold in one current
compatible Evidence Snapshot. The initial threshold is **0.75**, versioned and
explicitly **uncalibrated** until the evaluation procedure promotes or changes it.

### 5.3 Progress response

After atomically admitting an Evidence update:

- **Achieved**: close the focused Instruction as achieved, then issue one action
  for the highest-priority unmet must-have, or derive Ready.
- **Improving**: preserve the exact Instruction identity and text.
- **Insufficient**: preserve the first action until it has received two accepted
  Settled `insufficient` assessments spanning at least 10 seconds by desktop
  monotonic time. Then select one materially different action for the same
  Criterion. Once two distinct actions have each received accepted `insufficient`
  Evidence with no intervening `improving`, request a local patch. These values are
  versioned and initially uncalibrated.
- **Deviating**: a regressed must-have may preempt focus and receive one corrective
  Instruction; never stack old and corrective actions.
- **Blocked**: `not_observable` or `ambiguous` enters scoped recovery and requests
  fresh/clearer Evidence without claiming infeasibility. `temporarily_infeasible`
  or `action_infeasible` closes an irrelevant Instruction and requests a local
  patch for only the affected Criterion while displaying replanning Activity.
- **Rejected**: close the targeted Instruction as rejected, record a constraint,
  and request a non-equivalent alternative.

There are three revision scopes:

1. Instruction refinement changes the action for the same Criterion.
2. Local strategy patch changes only one affected Criterion, priority,
   alternative, or constraint and preserves compatible unrelated Evidence.
3. Full strategy rebuild is reserved for a changed intention or an accepted
   `StrategyApplicability(status=broad_discontinuity)` with non-null confidence at
   or above the configured Ready threshold.

`StrategyApplicability(status=unknown)` requests clearer fresh Evidence and scoped
recovery; it does not rebuild. Ordinary motion, achievement, regression, heartbeat,
deterministic frame-signal change, or model wording variation MUST NOT rebuild the
whole strategy.

## 6. Task Memory and Context Packs

### 6.1 Memory ownership and lifetimes

Task Memory is typed application state, not a conversation transcript or
model-authored summary.

- **Task-scoped** records: intention, current Strategy, applicable constraints,
  current mode/continuity, compact Instruction/outcome trajectory, and current
  visual sidecar.
- **Evidence-scoped** records: scene facts and Criterion assessments valid only
  for compatible task/strategy/Evidence/camera identities.
- **Run/job-scoped** records: exact source images and raw adapter output retained
  only until completion, invalidation, or cancellation, except opt-in diagnostics.

Retain the current Evidence Snapshot and at most one previous compatible accepted
snapshot for improving/deviating comparison. Coalesce equivalent holds and
no-progress outcomes into counters. Per Criterion, retain only the latest
assessment and at most the two most recent distinct attempted actions required by
the policy. Promote rejection and infeasibility into typed constraints; drop
unreferenced history.

Do not retain or infer identity, demographics, attractiveness, health,
personality, or emotion. Scene facts do not cross tasks.

### 6.2 Explicit-choice scopes

- Rejection persists while the same Criterion and materially equivalent situation
  remain; time or compression alone cannot erase it.
- Not now or visual cancellation suppresses proactive offers for the same stable
  offer context.
- Pause is current runtime mode; Resume requires fresh Evidence.
- Dismiss clears only its generated artifact.
- User capture carries no inferred preference.

### 6.3 Context Pack contracts

Every remote call receives an immutable, allowlisted, provenance-tokened pack:

- **Strategy**: intention, current settled Evidence/image, camera facts, journey,
  creation/rebuild reason, and surviving constraints.
- **Progress**: current Strategy and every must-have, active Instruction, current
  Evidence/image, one previous compatible summary, relevant trajectory counters,
  and cheap deterministic signals.
- **Revision**: one affected Criterion, current/rejected action, relevant Evidence,
  bounded attempts, and constraints.
- **Offer decision**: source Instruction/Criterion, compatible Evidence, and
  suppression choices.
- **Edit**: one explicitly authorized high-resolution still, one demonstration
  instruction, preservation constraints, and media limits; never the coaching
  transcript.
- **Retry**: a newly assembled pack from current authoritative memory, not replay
  of a failed prompt.

Mandatory content—intention/provenance, all current must-haves, active Instruction,
applicable constraints, required Evidence/image, and freshness—MUST NOT be dropped.
A Context Pack's structured text is capped at 32 KiB UTF-8, excluding image bytes.
Strategy and revision calls receive at most one current preview; progress receives
at most one current plus one previous compatible preview; editing receives exactly
one accepted high-resolution still. An Adapter MAY publish a stricter limit, and
the runtime MUST use the lower bound.

Under budget pressure, remove unrelated optional facts first, replace the prior
image with its summary, then coalesce old attempts. If mandatory content cannot
fit, simplify or reject the Strategy or fail visibly; never silently truncate a
required field.

Task Memory retains at most the current settled preview and one previous compatible
preview. A run pins its exact bytes only for its lifetime. High-resolution and
generated images exist only for a valid visual job unless explicitly retained as
diagnostic artifacts. All Strategy/Context bounds are versioned and initially
uncalibrated.

## 7. External reasoning and editing seams

### 7.1 CoachingReasoner

```python
class CoachingReasoner(Protocol):
    async def propose_strategy(
        self, context: StrategyContextPack
    ) -> StrategyProposal: ...

    async def assess_progress(
        self, context: ProgressContextPack
    ) -> ProgressEvidence: ...

    async def propose_revision(
        self, context: RevisionContextPack
    ) -> RevisionProposal: ...
```

The VLM supplies semantic Evidence and proposals. It MAY propose Criteria,
priorities, actors, feasible actions, grounded assessments, uncertainty, one
candidate action/overlay, or one explicitly scoped revision. It MUST NOT author
Ready, authoritative IDs, state transitions, Activity, retry policy, consent, or
final Strategy/Instruction state.

`propose_strategy` returns proposed Criteria, grounded current-view assessments for
every proposed must-have, feasible actions, and at most one candidate first action.
Deterministic admission assigns IDs and may derive immediate Ready without a second
call. `assess_progress` covers every current must-have once against the same
Evidence, returns one bounded `StrategyApplicability` record, and may include at
most one candidate action. Only an admitted high-confidence
`broad_discontinuity` may request a full rebuild. `propose_revision` is limited to
an alternative for one Criterion or a one-Criterion patch.

Admission MUST validate schema, complete must-have coverage, known unique Criterion
references, finite confidence, grounding, output bounds, and revision scope
atomically. Malformed or incomplete output is rejected, not partially repaired or
normalized.

### 7.2 IllustrationEditor

```python
class IllustrationEditor(Protocol):
    async def render(
        self, request: AuthorizedIllustrationRequest
    ) -> EditedIllustration: ...
```

Only an accepted Generate, Retry, or Another example action plus a fresh compatible
still permits construction of `AuthorizedIllustrationRequest`. The request binds
all task, Instruction, Criterion, Evidence, camera, visual-job/attempt, action,
capture, and source-image identities; contains one demonstrated adjustment and
fixed preservation/media constraints; and excludes the coaching transcript.

The Adapter validates media bytes, type, dimensions, decode integrity, and bounds.
V2 performs no additional runtime VLM inspection of edited output. Instructional
usefulness and preservation are evaluation concerns; generated output never enters
live Evidence.

### 7.3 Failure contract

Both seams return typed outcomes carrying invocation identity:

`deadline_exceeded | unavailable | throttled | rejected | invalid_output |
misconfigured`.

`throttled` MAY include provider delay. Provider exceptions, HTTP codes, raw error
text, SDK types, model names, prompts, and provider schemas remain inside Adapters.
Adapters MUST NOT retry or decide semantic retryability. The runtime applies an
8-second Reasoner attempt deadline and at most one automatic retry while the
semantic purpose and all provenance remain current. Only `deadline_exceeded`,
`unavailable`, `throttled`, and `invalid_output` are automatically retryable;
provider throttling delay is honored up to 2 seconds. `rejected` and
`misconfigured` are never automatically retried. Every retry uses a freshly
assembled Context Pack.

After exhaustion, preserve any usable Instruction/Ready projection, enter visible
scoped recovery, and require fresh Evidence or an explicit action before more work.
Stale failures are discarded like stale successes. Editing failure stays scoped to
visual guidance. These deadlines/counts are versioned and initially uncalibrated.

Production Gemini/editor Adapters and strict scripted Adapters implement the same
interfaces. Scripted Adapters drive deterministic state tests. Provider contract
checks and live calls are smoke evidence, not deterministic release gates.

## 8. Generated Visual Guidance

### 8.1 Offer eligibility and suppression

A proactive offer is eligible only when:

- the active Criterion is a visualizable pose or composition adjustment;
- two materially different text actions for that Criterion have each received
  current accepted `insufficient` Evidence under the no-progress policy;
- no accepted `improving` Evidence intervened; and
- v2 visual-guidance, v1 high-resolution-request, and v1 sample-image capabilities
  are all negotiated.

The same threshold requests a local Criterion patch. If that patch creates a new
current Instruction for the same materially stable Criterion/context, the retained
failed-action episode may make an offer for that new source Instruction eligible;
patching does not erase the evidence. The offer remains a sidecar and does not
delay the patch.

Elapsed time, ordinary motion, user capture, facial expression, presumed
frustration, one failed action, or `blocked` alone MUST NOT trigger an offer.

Offer “Would an edited example help?” at most once per materially stable
`task/goal + Criterion + equivalent scene` episode. Rewording an action does not
reset suppression. Not now, cancellation, failure dismissal, and artifact dismissal
suppress another proactive offer in that episode. A new task, different Criterion,
materially changed scene, or accepted improvement followed later by accepted
regression may begin a new episode; regression must satisfy the full eligibility
rule again.

An explicit user request MAY make a suitable offer immediately, but is not capture
consent. Only Generate authorizes the first attempt.

### 8.2 Capture, generation, and delivery

Generate creates a visual job bound to current task, source Instruction, Criterion,
and compatible scene/Evidence. If compatibly Settled, request one fresh transient
high-resolution still; otherwise report waiting-for-settle Activity. Motion during
capture invalidates the request; late stills are discarded. A new request requires
new compatible settling.

Edit exactly one adjustment. Preserve unrelated identity, content, lighting,
background, and framing unless the demonstration itself requires a change. Do not
request general beautification.

The sidecar reports waiting, capturing, generating, available, or scoped failure
without blocking camera use or ordinary coaching. New task, source-Instruction
closure/rejection, material scene change, pause, disconnect, or cancellation
immediately invalidates pending and delivered visual state. High-resolution
capture has a 5-second deadline. The editor has a 60-second attempt deadline and no
automatic retry. Capture/edit failure preserves coaching and exposes new identified
Retry/Dismiss actions. Edit Retry may reuse the accepted still only while all
provenance remains valid; capture Retry always obtains a fresh still. Each explicit
Retry authorizes one new attempt under the same deadline.

Delivery MUST state the demonstrated action and the fixed protocol provenance
label. Dismiss clears the artifact. Another example is new explicit consent for a
new job and fresh still; it is never automatic.

## 9. Protocol projections

Protocol negotiation, schemas, ordering, actions, and image correlation are defined
in [PROTOCOL_V2.md](PROTOCOL_V2.md).

- Protocol v2 receives the complete runtime projection.
- Protocol v1 is an intentionally lossy projection of the same runtime, not a
  second engine. It renders the current Instruction when present; Activity appears
  as v1 text only when no Instruction exists. It omits phase, freshness, identified
  actions, and the separate Activity lane. Generated Visual Guidance is disabled
  under v1 because v1 cannot express identified Generate consent.
- Protocol Adapters translate validated wire input to canonical `RuntimeEvent`
  values and canonical `RuntimeOutput` values to wire messages. They MUST NOT own
  task identity, settling, scheduling, Instruction, Readiness, retry, or visual-job
  policy.

## 10. Recovery and observability

Every wait MUST end in useful guidance, truthful continued Activity, or a specific
recoverable failure. Connection loss immediately marks retained Instruction
`may_be_outdated`, clears overlays and pending visual work, and invalidates async
work.

Retain at most one detached session in memory for 60 seconds by desktop monotonic
time. Reject a second connection while one is active. Resume only when the offered
session ID matches that retained session, its TTL has not expired, and no newer
connection or task has replaced it. A new non-resume connection evicts detached
continuity and starts fresh. Successful resume preserves semantic task and
Instruction identities, enters Recovering, and cannot restore current Evidence
until a fresh v1 `reconnected` observation becomes Settled and is accepted.
Expired, mismatched, or evicted continuity receives a new session and rebuilds from
the intention repeated by v1 observation. The 60-second bound is versioned and
initially uncalibrated.

Diagnostics are bounded and opt-in. Every attempted remote call records exact
source-byte hashes, provenance identities, purpose, timing, accepted/stale/
superseded/failed disposition, typed outcome, and configured threshold version.
Generated-image diagnostics additionally record consent/action, capture, still,
job/attempt, and output identities. Full images and raw provider payloads follow
run/job retention unless an explicit artifact directory is configured.

The runtime MUST expose metrics required by the evaluation contract: event-to-
Activity, settled-to-useful-Instruction, preemption/replacement, stale discard,
recovery, capture-to-image and byte completion; calls by purpose; heartbeat calls;
cancellations; stale completions; retries; failures; and peak physical concurrency.
Phone/desktop timestamps are diagnostic only; desktop monotonic time establishes
latency and ordering.

## 11. Configuration and empirical defaults

All threshold-bearing configuration is immutable for one runtime instance,
versioned in evidence, and marked calibrated or **uncalibrated**. Initial values
are specified in [CAMERA_AGENT_V2_EVALUATION.md](CAMERA_AGENT_V2_EVALUATION.md),
including inherited v1 material-change thresholds, Settled confirmation/dwell,
heartbeat cadence, two-call concurrency, latency diagnostics, adapter deadlines,
retry/no-progress budgets, confidence thresholds, context limits, and visual-offer
eligibility. Values may change only through a documented calibration run; release
criteria cannot be weakened retrospectively for an active release run.

## 12. Migration and cutover

The sole migration and module-composition plan is
[HARNESS_ARCHITECTURE.md](HARNESS_ARCHITECTURE.md). The implementation MUST use its
single-runtime, offline-characterization, atomic-cutover path; this semantic
specification does not define a competing file tree or migration sequence.

## 13. Implementation acceptance

The specification is implemented only when:

- `CoachingRuntime` is the sole authority and all invariants above are covered by
  deterministic replay;
- protocol v1 fallback and protocol v2 negotiation/projection pass their normative
  schemas and semantic checks;
- all required scenarios and evidence production in
  [CAMERA_AGENT_V2_EVALUATION.md](CAMERA_AGENT_V2_EVALUATION.md) exist;
- both scripted and production Adapter contracts are exercised;
- a real phone can complete all three supported journeys without a second runtime
  or hidden frontend state machine; and
- release passes the conjunctive functional-completeness and formative-usability
  gates.
