# Camera Agent Harness v2 Evaluation and Release Contract

Status: normative evaluation contract for the single-user research prototype.

This contract evaluates the implementation described in
[CAMERA_AGENT_V2_SPEC.md](CAMERA_AGENT_V2_SPEC.md) and the wire contracts in
[PROTOCOL_V2.md](PROTOCOL_V2.md). Release requires both functional completeness
and formative usability. Neither can compensate for the other.

This effort does **not** require a labeled visual dataset, a population-level
quality claim, or one aggregate “quality score.” Curated visual walkthroughs and
operational thresholds are required diagnostic evidence. They independently block
release only when they expose incomplete required functionality, a critical trust
failure, or failure of the usability gate.

## 1. Release rule

A candidate release passes only when all are true:

1. every required deterministic scenario passes;
2. seeded interleaving/property runs report zero invariant violations;
3. zero obsolete result is presented as current;
4. the predeclared five-participant formative-usability gate passes;
5. no critical trust failure remains in any replay, walkthrough, smoke run, or
   participant session;
6. provider contract and required live Reasoner/Editor smoke evidence passes;
7. real-phone v1 fallback and v2 cutover smoke passes across all three supported
   journeys;
8. no unresolved release-blocking required-functional failure remains, including
   no major Generated Visual Guidance functional failure; and
9. one complete versioned evidence packet is retained.

A threshold miss marked diagnostic or **uncalibrated** is investigated and recorded
but does not independently fail this research-prototype release unless it causes
one of the failures above.

The release configuration—including participant count, pass ratio, thresholds,
budgets, models, prompts, schema hashes, and scenario-set version—MUST be frozen
before the run. It MUST NOT be weakened retrospectively to make that run pass.

## 2. Evaluation layers

| Layer | Purpose | Release role |
| --- | --- | --- |
| Deterministic runtime replay | State, identity, scheduling, cancellation, memory, and sidecar correctness | Mandatory functional gate |
| Protocol conformance | Schema, semantic validation, fallback, ordering, freshness, and correlation | Mandatory functional gate |
| Seeded interleavings | Races and invariant preservation across completion order | Mandatory functional gate |
| Provider contract/live smoke | Adapter compatibility and basic live execution | Mandatory cutover evidence; nondeterministic content is not a deterministic gate |
| Curated visual walkthrough | Grounding, relevance, clarity, Readiness, and illustration quality | Required diagnostic evidence; blocks through functionality/trust/usability rules |
| First-time participant sessions | Comprehension, control, recovery, and provenance | Mandatory formative-usability gate |
| Real-phone smoke run | End-to-end transport/render/control behavior | Mandatory cutover evidence |

## 3. Deterministic harness

The replay harness MUST use the public `CoachingRuntime` Interface with:

- scripted `CoachingReasoner` and `IllustrationEditor` Adapters;
- a virtual monotonic clock;
- deterministic UUID/identity generation or a recorded identity mapping;
- exact immutable observation/image fixtures;
- controllable success, failure, timeout, and completion order;
- physical calls that can be configured as cancellable or non-cancellable;
- a protocol-v1 and protocol-v2 Adapter over the same runtime; and
- complete state/output/invariant traces.

A scenario declares input events, scripted Adapter outcomes, clock advances,
expected committed projections/effects, forbidden outputs, final bounded-resource
state, and expected metric samples. Tests MUST observe the public Interface and
wire output; private reducer tests MAY supplement but MUST NOT replace this gate.

Each run records exact configuration and random seed. Named scenarios remain
human-readable and are not replaced by generative testing.

## 4. Mandatory invariants

Every scenario and seeded interleaving run checks at least:

1. at most one active Instruction exists;
2. changed Instruction content receives a new identity; `hold` preserves identity;
3. each closed Instruction has exactly one terminal disposition;
4. no Instruction implies truthful Activity or scoped recovery, never a blank;
5. phase and Activity agree with authoritative runtime facts;
6. only a schema-valid current-token completion may change Instruction, Strategy,
   Evidence admission, or Readiness;
7. Ready cites one current compatible Evidence Snapshot that assesses every
   must-have at the configured confidence threshold;
8. nice-to-haves never block Ready;
9. motion/capture alone does not revoke Ready, and reconfirmation does not flicker
   its identity;
10. task, strategy, Instruction, Evidence, camera-context, observation, run/job,
    and purpose tokens are checked wherever applicable;
11. duplicate, stale, orphaned, late, and physically uncancelled completions are
    harmless;
12. pending work is latest-only and heartbeat never displaces higher-priority work;
13. total physical VLM calls never exceed two;
14. Task Memory and retained image/fragment collections remain within configured
    bounds;
15. an explicit action ID is one-use, immutable in meaning, and idempotent;
16. pause, disconnect, task change, and cancellation prevent late work from acting;
17. overlays remain bound to one current Instruction and exact source observation;
18. Generated Visual Guidance does not mutate live Evidence, Strategy, Instruction,
    or Readiness;
19. no capture/edit begins without an accepted identified consent action; and
20. no obsolete Instruction, overlay, Activity claim, visual artifact, or generated
    bytes is presented as current.

Any violation fails the functional gate.

## 5. Required deterministic scenario matrix

Every row below is mandatory. One executable scenario may cover several rows only
when the evidence packet reports each requirement separately.

### 5.1 Task, phase, and Instruction

| ID | Scenario | Required assertions |
| --- | --- | --- |
| T01 | No intention | `needs_intention`; no reasoning; truthful prompt; shutter unaffected. |
| T02 | New intention | Old task/work/overlays/visual job invalidated; post-intention Evidence required; immediate Orienting Activity. |
| T03 | Initial strategy and first action | One current settled view; complete must-have proposal; app-authored IDs; one Instruction. |
| T04 | Immediate Ready | Strategy proposal covers every must-have in the same Evidence; deterministic Ready without a second call. |
| T05 | Hold while improving | Instruction identity/text unchanged; Activity may change; trajectory coalesces boundedly. |
| T06 | Achievement and advance | Prior Instruction closed `achieved`; one new action for highest-priority unmet must-have. |
| T07 | All must-haves achieved | Ready derived; nice-to-haves may remain unmet. |
| T08 | Regression after Ready | Motion marks revalidation only; current accepted Evidence may replace Ready with one corrective Instruction. |
| T09 | Intention replacement during inference | Immediate logical invalidation; obsolete completion discarded; latest task starts after Settled. |
| T10 | No Instruction during replanning | Truthful replanning Activity; rejected/irrelevant Instruction never resurrected on failure. |
| T11 | Phase/Activity precedence | Exercise all seven projections and overlapping facts in precedence order: no task; recovery/continuity; paused; evaluating/replanning; Ready; Coaching; Orienting. Reject every forbidden phase/lane combination; visual sidecar never changes phase. |

### 5.2 Evidence, settling, and scheduling

| ID | Scenario | Required assertions |
| --- | --- | --- |
| S01 | Interleaved metadata/image fragments | Join only matching `imageMessageId` and `observationId`; retain at most 16 unmatched entries per side for 5 s; overflow/expiry never mixes contexts. |
| S02 | Equivalent routine frames | No new Evidence identity or queued call; latest equivalent view may update. |
| S03 | Material camera or visual change | Immediate Evidence/run/overlay invalidation; no VLM work before count+dwell settling. |
| S04 | Relative blur/luminance/clipping signals | Logging works; configured crossing may request revalidation only; no semantic achievement. |
| S05 | Decode failure | Quality unknown and fail-open change path; no fabricated value. |
| S06 | Latest-only coalescing | New equal/higher priority replaces pending; no unbounded queue. |
| S07 | Priority arbitration | Orientation/replan > material evaluation > heartbeat. |
| S08 | Heartbeat backoff/reset | Configured 15/30/60-second behavior, maximum call budget, reset triggers, and no displacement. |
| S09 | Non-cancellable overlap | First invalidation starts one replacement; peak calls two; further work remains newest-pending until drain. |
| S10 | Stale and out-of-order success/failure | Every stale outcome discarded without state mutation; current failure remains scoped and recoverable. |
| S11 | Text on equivalent newest view | Text may apply only when equivalence is proven; overlay remains on exact analyzed observation. |

### 5.3 Strategy, progress, and memory

| ID | Scenario | Required assertions |
| --- | --- | --- |
| P01 | Every must-have reassessed | One Evidence Snapshot covers all must-haves from the same view; each has 1–4 bounded grounding facts, finite `[0,1]` or null confidence, and bounded typed uncertainty; incomplete or malformed output is rejected atomically. |
| P02 | Nice-to-have unmet | Ready is immediate; v2 emits no nice-to-have Instruction before or after Ready. |
| P03 | Repeated insufficient | First action is retained through two accepted Settled `insufficient` assessments spanning ≥10 s; one materially different action follows; after two distinct insufficient actions with no improvement, request a local patch—not endless repetition. |
| P04 | Improving between failures | Failed-action sequence clears; no visual offer from stale insufficient history. |
| P05 | Deviating criterion | Regressed higher-priority must-have may preempt; no stacked instructions. |
| P06 | Blocked action/criterion | `not_observable`/`ambiguous` requests clearer Evidence and scoped recovery; `temporarily_infeasible`/`action_infeasible` may end an irrelevant Instruction and request one-Criterion patch; `blocked` does not trigger visual offer. |
| P07 | Try another suggestion | Accepted action acknowledged; Instruction closes `rejected`; equivalent action constrained; unrelated Criteria preserved. |
| P08 | Replayed or stale rejection | Duplicate/stale no-op; no second strategy mutation. |
| P09 | Full rebuild boundary | Only changed intention or an admitted `broad_discontinuity` applicability result with confidence ≥ the configured threshold rebuilds; `unknown` requests clearer fresh Evidence; deterministic frame signals and ordinary progress never rebuild; compatible explicit constraints survive. |
| P10 | Strategy/memory bounds | At most 6 Criteria (4 must-have, 2 nice-to-have), 3 candidate actions each, 2 recent distinct attempted actions each, and current plus at most one previous compatible snapshot/image; equivalent outcomes coalesced; raw output excluded. |
| P11 | Dependency invalidation | Local patch preserves unaffected Evidence; material change invalidates evidence-scoped records; task change clears task facts. |
| P12 | Context budget pressure | Structured text ≤32 KiB; strategy/revision has ≤1 current preview, progress ≤1 current + 1 previous compatible preview, edit exactly 1 accepted still; stricter Adapter bound wins; mandatory content retained or Strategy is simplified/rejected with visible recovery. |
| P13 | Malformed/stale model output | No partial repair/admission; no raw output in Task Memory; current guidance preserved. |

### 5.4 User controls and recovery

| ID | Scenario | Required assertions |
| --- | --- | --- |
| U01 | Pause during running work | Immediate acknowledgement; no new inference/reminder/offer/capture; late completion harmless; camera/shutter usable. |
| U02 | Resume | Same intention retained; Orienting/fresh Evidence required; retained Instruction not current until revalidated. |
| U03 | Edit intention while paused | New task but remains paused. |
| U04 | User capture before Ready | Neutral acknowledgement; old evaluation invalidated; no criticism or refusal inference. |
| U05 | User capture while Ready | Ready does not flicker; fresh Evidence later determines continuation. |
| U06 | Reasoner failure/retry | 8 s deadline; at most one fresh-pack automatic retry only for deadline/unavailable/throttled/invalid output while purpose remains current; throttle delay capped at 2 s; rejected/misconfigured never auto-retry; exhaustion preserves guidance and requires fresh Evidence or explicit action. |
| U07 | Disconnect | Runtime invalidates work immediately; phone locally projects Recovering, retained `may_be_outdated` Instruction, connection Activity, and cleared overlays/actions/visual lane without changing session/revision; camera/intention/shutter remain usable. |
| U08 | Successful resume | Matching sole detached session within 60 s preserves session/task/Instruction and increasing revision; Recovering until fresh `reconnected` Evidence. |
| U09 | Failed/evicted resume | Expired, mismatched, evicted, or replaced continuity gets a new session; state rebuilds from repeated intention; old IDs/output rejected; an active second connection is rejected. |
| U10 | Reconnect with late old completion | Completion/action/state/image from old authority cannot act. |
| U11 | RuntimeHost lifecycle | Atomic fresh/resume/reject attachment, exactly-once detach, 60-second retention, non-resume eviction, active-connection rejection, and expiry close occur without the host inspecting or mutating coaching state. |
| U12 | Runtime close | Close with pending/running Reasoner and editor work plus pinned bytes; authority invalidates immediately, late outcomes cannot act or emit, output iteration terminates, and retained images/resources are released without physical cancellation. |

### 5.5 Generated Visual Guidance

| ID | Scenario | Required assertions |
| --- | --- | --- |
| G01 | Not yet eligible | Time, motion, capture, one insufficient result, or blocked alone does not offer. |
| G02 | Eligible proactive offer | Two materially different actions each have current accepted `insufficient` Evidence with no intervening improvement, the Criterion is visualizable, and capabilities are present; a concurrent local patch does not erase the episode; offer once. |
| G03 | Explicit request ingress | Accepted intention/`intention_updated` text is interpreted through typed grounded Strategy output, not a phrase allowlist or new v2 message; suitable offer may appear immediately; no capture before separate Generate. |
| G04 | Not now | Action acknowledged; same-context proactive offer suppressed. |
| G05 | Generate while unsettled | One job; waiting Activity; no capture until compatible Settled. |
| G06 | Generate while settled | One fresh transient capture request bound to job/attempt and source tokens. |
| G07 | Motion during capture | Request invalidated; late still discarded; fresh request only after settling. |
| G08 | Capture failure and Retry | 5 s deadline; no automatic retry; coaching preserved; scoped failure with new Retry ID; accepted Retry obtains a fresh still. |
| G09 | Edit failure and Retry | 60 s deadline; no automatic retry; coaching preserved; accepted Retry may reuse the still only while all source tokens remain valid. |
| G10 | Successful generation | Available artifact announced before bytes; exact provenance and demonstrated action; no live Evidence mutation. |
| G11 | Cancel/new task/scene change/source closure/pause/disconnect | Logical invalidation immediate; late still/failure/image/bytes harmless; ordinary coaching isolated. |
| G12 | Dismiss | Artifact alone clears; same-context proactive suppression remains. |
| G13 | Another example | New identified consent, new job/attempt, and fresh still; never automatic. |
| G14 | Improvement then regression | Improvement clears failed sequence; later regression starts a new episode that must fully requalify. |

### 5.6 Protocol

| ID | Scenario | Required assertions |
| --- | --- | --- |
| W01 | V1 fallback | Exact closed hello then unknown offer; v1 server ignores offer; phone continues rendering v1 results. |
| W02 | Valid v2 negotiation | Exact v1 hello, offer, acceptance before observation processing; accepted subset and prerequisites. |
| W03 | Invalid negotiation | Wrong order, missing mandatory bundle, unoffered selection, or missing visual prerequisites yields scoped error/no switch. |
| W04 | Complete snapshot | Every lane present; null/empty clears; atomic replace only for matching session and greater revision. |
| W05 | Stale/malformed/contradictory snapshot | Last valid projection/revision retained, including for phase/task/Instruction/action/visual-lane combinations that violate the normative projection matrix. |
| W06 | Instruction immutability | Same ID may change freshness only; changed content/addressee/kind is rejected. |
| W07 | Overlay freshness | State applies while stale/mismatched overlay is independently suppressed; zoom clears immediately. |
| W08 | Action lifecycle | Exercise every permitted/forbidden action combination; monotonic-ordinal UUIDs never reuse; accepted action disappears; exact replay/contradictory reuse/duplicate work within the 256+256 receipt and 10-minute window; expiry/capacity eviction returns non-executing stale; wrong-session never executes; acknowledgement precedes resulting state and slow work. |
| W09 | Generated image ordering | State announcement before bytes; artifact/job demonstration equality; exact session/job/image/first-revision checks; late bytes dropped; corrupt/media/dimension-mismatched current bytes trigger scoped invalid-message error then failed job with fresh Retry/Dismiss, while stale errors do nothing. |
| W10 | Disconnect/reconnect negotiation | Phone-local disconnect projection requires no server revision; wire resets to v1; valid pre-accept v1 result or first accepted complete v2 state replaces local projection; exercise sole-session 60-second TTL, active-connection rejection, non-resume eviction, successful/failed resume, and no revision reset on success. |
| W11 | Unknown text type | Both sides ignore it without state loss or disconnect. |
| W12 | Known invalid v2 message | `protocol_error_v2` is scoped and last valid state remains; malformed protocol-error input is logged/dropped without an error loop, while unsafe framing follows connection-failure policy. |
| W13 | Binary framing/limits | Header bounds, schema, decoded media/header agreement, exact dimensions, integrity, and 8 MiB cap enforced for v1 and visual-guidance images. |
| W14 | Serialized ordering and backpressure | hello→offer→observation, accept→state, and state→image bytes remain ordered under async completion; queue never exceeds 32 frames/16 MiB and overflow closes/detaches rather than dropping output. |

## 6. Seeded interleaving runs

For each candidate, execute a predeclared seed set that permutes:

- metadata and image-fragment arrival;
- intention/action/capture/disconnect events;
- Settled invalidation and heartbeat timers;
- success, typed failure, timeout, and physical cancellation completion;
- two-slot occupancy and newest-pending replacement;
- state send and generated-byte send timing; and
- exact duplicate message/action delivery.

Every seed checks the mandatory invariants, expected collection bounds, and no
obsolete-current output. Store failing seeds and minimized traces. The candidate
fails until every required seed passes; changing the seed set creates a new
versioned run rather than deleting failures.

## 7. Curated visual walkthrough

Maintain a compact manual catalogue spanning all three journeys and:

- subject/framing scale and position;
- clutter, lighting, clipping, blur, occlusion, and motion;
- feasible and infeasible adjustments;
- general composition and portrait actor ambiguity;
- intention replacement, rejection, no progress, capture, Ready regression, and
  recovery; and
- Generated Visual Guidance offer, generation, instructional success/failure, and
  preservation of unrelated content.

Variation must be visually relevant. Do not infer or score demographics, identity,
body shape, attractiveness, personality, health, or emotion.

For each trajectory, record cited frame/output artifacts and qualitative findings
for:

1. grounding in the current compatible view;
2. one-action clarity and correct Photographer/Subject addressee;
3. relevance and priority to the intention;
4. contradiction, oscillation, or repeated equivalent action;
5. must-have coverage and Readiness consistency;
6. practical alternatives after rejection, blockage, or infeasibility; and
7. generated illustration usefulness, single-adjustment fidelity, preservation of
   unrelated content, and correct provenance.

Use severity `critical | major | minor | note`; do not compute an aggregate score.
A generated illustration that fails or contradicts its requested single adjustment,
or corrupts unrelated content enough to defeat the demonstration, is a **major
functional failure** and blocks release until fixed and rerun. Cosmetic imperfections
that do not impair the demonstration are non-blocking. Missing provenance or an
illustration mistaken for live Evidence is a critical trust failure. Other findings
block only when they show required functionality incomplete or cause the usability
gate to fail.

## 8. Formative-usability gate

### 8.1 Participants and journeys

Use five first-time participants. Each completes:

- one general-composition journey; and
- one portrait-composition/posing journey.

All five participants MUST receive a Generated Visual Guidance recognition task,
and at least three MUST additionally complete the full Generate-to-delivery
interaction. A facilitator may set up equipment and explain the study, but MUST NOT
explain the meaning of Instruction versus Activity, teach the required controls,
identify Ready/shutter behavior, or explain generated-image provenance during a
measured task.

### 8.2 Required participant outcomes

At least four of five participants MUST complete **each** outcome without
facilitator intervention:

1. identify the persistent current action separately from transient Activity;
2. reject a suggestion and obtain a non-equivalent alternative;
3. pause and resume coaching;
4. understand that Ready does not gate the local shutter; and
5. recognize Generated Visual Guidance as an edited illustration based on an
   earlier still, not the live preview or live-shot Evidence.

Outcome 5 is measured across all five recognition tasks; at least four must pass
without intervention. Completing recognition does not count toward the separate
requirement that at least three participants exercise actual Generate-to-delivery.

Record every intervention against the attempted task/control. Explaining generated
provenance or the recognition distinction counts as intervention. Repeating a task
after intervention does not convert it into an unassisted pass.

### 8.3 Critical trust failures

Any occurrence blocks release:

- obsolete guidance presented as current;
- Ready without accepted compatible Evidence for every must-have;
- ignored or reversed cancellation;
- a blocked or remotely gated local shutter;
- an unexplained indefinite wait; or
- a generated illustration mistaken for current live Evidence.

A facilitator misunderstanding, logging defect that prevents classification, or
ambiguous UI that cannot establish whether one occurred is unresolved evidence and
also blocks until rerun or otherwise resolved.

## 9. Operational measurements and uncalibrated defaults

The following are editable empirical starting points and MUST be visibly marked
**uncalibrated** in configuration and evidence output.

| Policy/metric | Initial default or diagnostic target |
| --- | --- |
| Material change | Current protocol-v1 thresholds |
| Settled | At least 2 mutually equivalent post-change observations spanning at least 500 ms; immediate invalidation on material change |
| Relative sharpness, luminance, clipping | Logging-only until traces justify a versioned threshold |
| Heartbeat | 15 s, then 30 s, then 60 s; no more than 3 heartbeat calls in 2 minutes |
| Detached continuity | At most 1 memory-only session retained for 60 s; reject a second active connection |
| Reasoner retry/deadline | 8 s per attempt; at most 1 automatic retry; provider delay capped at 2 s |
| High-resolution capture deadline | 5 s; no automatic retry |
| Illustration editor deadline | 60 s; no automatic retry |
| Strategy size | At most 6 Criteria: 4 must-have and 2 nice-to-have; at most 3 candidate actions each |
| Context structured text | 32 KiB UTF-8 maximum, excluding images; stricter Adapter bound wins |
| Context images | Strategy/revision 1 current preview; progress 1 current + 1 previous compatible preview; edit exactly 1 accepted still |
| Action replay | Monotonic-ordinal UUIDs; 256 action + 256 message receipts retained 10 min; evicted/expired input is stale |
| Observation fragments | 16 unmatched entries per side, 5-second expiry |
| Serialized send queue | 32 frames or 16 MiB; overflow closes/detaches |
| Diagnostic artifacts | 200 files or 256 MiB per run, then one truncation marker |
| No-progress alternative | 2 accepted Settled `insufficient` assessments for one action spanning ≥10 s |
| Criterion patch / visual-offer eligibility | 2 materially different actions each with accepted `insufficient`, no intervening `improving` |
| Optional-refinement budget | 0 nice-to-have Instructions in v2 |
| Physical VLM concurrency | Maximum 2 total calls |
| Ready confidence | Every must-have `achieved` with non-null confidence ≥ 0.75 in one current compatible Evidence Snapshot |
| Explicit action acknowledgement | Diagnostic p95 ≤ 250 ms |
| Event to new truthful Activity | Diagnostic p95 ≤ 250 ms |
| Settled Evidence to useful guidance | Diagnostic p95 ≤ 6 s |
| Accepted still to available generated image | Diagnostic warm-path p95 ≤ 15 s |
| Known failure to visible recovery | Diagnostic p95 ≤ 1 s |

Use this metric dictionary; all starts/ends use monotonic time in the named owner:

| Metric | Start | End and eligibility |
| --- | --- | --- |
| `action_to_ack_ms` | Protocol Adapter receives one schema-valid current-session `user_action_v2` | Corresponding `action_result_v2` is enqueued; partition accepted/duplicate/stale/unavailable and never pool with Activity |
| `event_to_activity_ms` | Runtime admits an eligible intention, explicit-action, material-invalidation, reconnect/recovery, or current typed-failure event | First committed snapshot with new truthful coaching Activity; partition by event class; phone-local disconnect Activity is measured separately on phone close callback |
| `event_to_first_instruction_ms` | Runtime admits a new/changed accepted intention | First committed current actionable or Ready Instruction for that task |
| `settled_to_useful_instruction_ms` | Runtime commits Settled Evidence that creates an orientation/evaluation/replan request | First admitted current-token Instruction/Ready output for that Evidence/purpose that meets the usefulness rule below |
| `failure_to_recovery_ms` | Runtime admits a current typed failure or phone detects a current generated-byte failure | First committed Recovering/failed-sidecar projection with a concrete next action |
| `accepted_still_to_available_ms` | Runtime admits the compatible high-resolution still for one visual attempt | First committed available artifact announcement for that attempt |
| `artifact_to_bytes_ms` | Available artifact announcement is committed | Matching bytes finish transmission and phone integrity admission |
| `preemption_ms` | A newer event invalidates an authoritative run | Invalidation commit; record replacement-start separately when a physical slot starts the replacement |

In deterministic replay, “useful” means the scripted expected output is schema-valid,
current-token, admitted by deterministic policy, and satisfies the scenario's
expected Criterion/action or Ready result. In live/walkthrough samples, a
predeclared rubric reviewer marks the output useful only when it is grounded in the
current compatible view, relevant to the intention, and contains exactly one
observable action or valid Ready. An emitted non-useful result does not stop the
sample; it records a qualitative finding and the latency remains censored until a
useful result or terminal policy deadline.

Eligible events that reach a configured terminal deadline without the named end are
reported as right-censored/time-out failures at that deadline. Exclude only events
that never create the relevant semantic purpose (for example duplicate/stale
actions or equivalent frames), record the exclusion reason, and never drop failures.
Partition distributions by operation, semantic purpose, event class, disposition,
and cold/warm state as applicable.

Record at least:

- event-to-truthful-Activity;
- event-to-first-useful-Instruction;
- settled-change-to-next-useful-Instruction;
- logical cancellation, replacement-start, and stale-discard timing;
- time to recover after motion, intention change, disconnect, and typed failure;
- Instruction age and settled no-progress duration;
- Generated Visual Guidance offer eligibility/acceptance, capture request/still,
  accepted-still-to-artifact, and byte-completion timing;
- calls by `strategy | progress | revision`, heartbeat calls, cancellations,
  physically late completions, retries, failures, and peak physical concurrency;
- false/missed/unstable Ready findings against explicit must-haves; and
- memory/queue/fragment/image high-water marks.

Use desktop monotonic timestamps for latency. Report distributions with count,
median, p90, p95, maximum, and censored/time-out count where sample size permits;
never silently drop failures.

The image editor's first invocation may incur cold start beyond 15 seconds. Record
cold-start and warm-path samples separately. Exclude only the first invocation from
the warm p95 and state that exclusion explicitly; never average cold and warm
paths. Both paths require continuous truthful Activity and remain subject to
functional and trust gates.

## 10. Calibration procedure

A threshold or budget may move from uncalibrated to calibrated only through a
versioned calibration record containing:

1. the decision being calibrated and failure trade-off;
2. exact hardware, software, model/adapter, fixtures/sessions, and configuration;
3. raw distributions/traces, including misses and failures;
4. false-positive and false-negative examples for gating/readiness decisions;
5. the selected value and rationale;
6. comparison with the prior value; and
7. the scenarios and live observations rerun after selection.

Tune material-change, quality-signal, settling, confidence, no-progress,
heartbeat, retry/deadline, context, and visual-offer values independently where
possible. A tuned value MUST NOT suppress required useful guidance, violate the
physical-call cap, create unexplained waits, or weaken deterministic invariants.
Changing a value after release-run start invalidates that run and requires a new
candidate evidence packet.

## 11. Provider and real-phone evidence

Before atomic cutover, run:

- provider-specific contract tests for schema/strict parsing, media validation, and
  typed failure translation;
- opt-in live Reasoner calls for strategy, progress, and revision;
- cold and warm Editor smoke calls;
- a real-phone v1 fallback connection; and
- real-phone v2 sessions that collectively complete general composition, portrait
  composition/posing, and Generate-to-delivery Generated Visual Guidance, including
  negotiation, one action, pause/resume, one local capture, and disconnect/resume.

Live content need not match deterministic fixture wording. It MUST obey the
runtime/protocol contracts, remain grounded enough for the walkthrough rubric, and
produce the required metrics/artifacts. Provider unavailability is recorded and
reschedules the candidate; the candidate cannot pass until the required provider
and real-phone evidence completes successfully.

## 12. Release evidence packet

Each candidate packet contains:

- candidate/version/commit, date, environment, hardware, phone/app, models and
  Adapter versions;
- exact immutable configuration with every uncalibrated annotation;
- hashes/versions of both protocol schemas, prompts, scenario matrix, fixture
  catalogue, and participant protocol;
- deterministic scenario results by ID with traces and invariant counts;
- seeded interleaving seeds/results and minimized failures;
- protocol conformance and v1 fallback results;
- provider contract/live smoke and real-phone smoke evidence;
- curated walkthrough findings with cited source/output artifacts and severity;
- participant notes, task outcomes, intervention counts, comprehension answers,
  and trust failures;
- latency distributions separated by operation and cold/warm state;
- call, heartbeat, cancellation, stale-discard, retry, failure, concurrency, and
  resource-bound measurements; and
- every unresolved finding with owner, severity, release disposition, and link.

The packet ends with a mechanical decision table:

```text
all required deterministic scenarios pass: yes/no
all required seeded runs pass:             yes/no
obsolete results presented as current:     count
formative usability gate passes:           yes/no
provider contract/live smoke passes:        yes/no
real-phone v1/v2 cutover smoke passes:      yes/no
critical trust failures:                    count
unresolved release-blocking functional:     count
  of which major GVG failures:              count
complete evidence packet:                   yes/no
RELEASE:                                    PASS only if all above permit it
```

A narrative recommendation MUST NOT override this table.
