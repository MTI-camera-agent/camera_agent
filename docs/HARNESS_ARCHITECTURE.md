# Camera Agent Harness Architecture

This is the sole maintained source for Camera Agent Harness v2 module arrangement,
seams, composition, and migration. Product/runtime behavior and public interface
requirements are normative in [CAMERA_AGENT_V2_SPEC.md](CAMERA_AGENT_V2_SPEC.md).
Protocol contracts remain normative in [PROTOCOL.md](PROTOCOL.md),
[protocol-v1.schema.json](protocol-v1.schema.json),
[PROTOCOL_V2.md](PROTOCOL_V2.md), and
[protocol-v2.schema.json](protocol-v2.schema.json). Evaluation and release evidence
are normative in [CAMERA_AGENT_V2_EVALUATION.md](CAMERA_AGENT_V2_EVALUATION.md).

This document describes the target v2 architecture. The current fixed-plan
`CoachingLoop` and independent `ReferenceWorkflow` are legacy implementation to be
replaced atomically; they are not an alternative architecture.

## Architectural contract

One deep, mailbox-style **`CoachingRuntime` Module** is the sole semantic authority
for a live coaching session. A large amount of orchestration behavior sits behind
one small ordered Interface:

```python
class CoachingRuntime:
    async def submit(self, event: RuntimeEvent) -> Receipt: ...
    def outputs(self) -> AsyncIterator[RuntimeOutput]: ...
    async def close(self) -> None: ...
```

Construction receives immutable versioned configuration and the selected
`CoachingReasoner` and `IllustrationEditor` Adapters. Those are the only public
semantic Adapter seams inside the runtime.

The Interface guarantees:

- `submit` acknowledges admission without waiting for remote work;
- concurrent submissions receive one authoritative mailbox order;
- state is committed before effects launch or outputs become deliverable;
- async work never mutates state or writes to a phone directly;
- every completion re-enters the mailbox as a correlated semantic event;
- outputs are emitted in committed order as complete immutable projections or
  correlated phone-bound requests; and
- `close` invalidates authority and releases bounded retention without depending
  on physical cancellation.

Callers and tests use the same Interface. No caller receives writable state lanes,
coordinates reducer steps, or bypasses completion admission.

## Composition

```text
                     ┌──────────────────────────────┐
WebSocket bytes ───▶ │ Protocol Adapter            │
                     │ - v1/v2 validation           │
                     │ - negotiation/session edge   │
                     │ - binary framing             │
                     └──────────────┬───────────────┘
                                    │ fragments / actions
                     ┌──────────────▼───────────────┐
                     │ ObservationAssembler         │
                     │ bounded metadata/image join  │
                     └──────────────┬───────────────┘
                                    │ complete RuntimeEvent
                     ┌──────────────▼───────────────┐
                     │ CoachingRuntime              │
                     │ sole serialized authority    │
                     │                              │
                     │ internal reducer + effects   │
                     │ scheduling, memory, strategy │
                     │ projection, visual sidecar   │
                     └───────┬──────────────┬───────┘
                             │              │
              ┌──────────────▼───┐      ┌──▼────────────────────┐
              │ CoachingReasoner │      │ IllustrationEditor     │
              │ Adapter          │      │ Adapter                │
              └──────────────┬───┘      └──┬────────────────────┘
                             │ completion   │ completion
                             └──────────┬────┘
                                        │ correlated RuntimeEvent
                     ┌──────────────────▼────────────┐
                     │ CoachingRuntime output stream │
                     └──────────────────┬────────────┘
                                        │ canonical RuntimeOutput
                     ┌──────────────────▼────────────┐
                     │ Protocol Adapter + one writer │
                     │ v1 lossy / v2 complete        │
                     └───────────────────────────────┘
```

The protocol, provider, and editor implementations are Adapters at real seams.
Private internal helpers are implementation structure, not separate authorities or
public semantic seams.

## CoachingRuntime implementation

The pure aggregate transition remains internal:

```text
current state + one semantic event -> next state + declarative effects
```

The runtime owns effect execution. Starting, succeeding, failing, timing out, or
logically cancelling an effect always produces a correlated event or disposition
through the same mailbox.

### Internal responsibilities

The following responsibilities MAY be split across private files/modules for
locality, but MUST remain behind the one runtime Interface:

- aggregate transition and invariant checking;
- task, mode, connection, Evidence, Instruction, Readiness, analysis, recovery,
  overlays, and Generated Visual Guidance state;
- application-authored identity and token allocation;
- deterministic frame measurements, material-change assessment, asymmetric
  Settled hysteresis, heartbeat, and latest-only scheduling;
- two-call physical-cap enforcement, logical cancellation, and completion
  admission;
- Shot Strategy/Criterion identity, deterministic progress policy, local revision,
  full-rebuild admission, Instruction lifecycle, and Readiness derivation;
- typed Task Memory, dependency invalidation, bounded trajectories, and immutable
  Context Pack assembly;
- complete user-visible projection, state-revision assignment, available-action
  minting, and duplicate-projection suppression;
- Generated Visual Guidance eligibility, consent, capture correlation, editing,
  retry/cancellation, provenance, and delivery admission; and
- bounded metrics, replay facts, diagnostic artifacts, and blob references.

No private helper can expose an independently mutable phase, Activity, Instruction,
Readiness, Strategy, queue, or visual-job state.

Clock driving, diagnostic sinks, blob storage, artifact storage, and deterministic
ID generation MAY have private mechanical substitutions for tests. They are not
public semantic seams.

## External semantic seams

### CoachingReasoner

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

Production Gemini and strict scripted implementations are Adapters at this seam.
The Interface contains domain proposals and Evidence, not provider prompts, SDK
objects, model names, HTTP errors, or authoritative runtime state.

The runtime owns IDs, scheduling, retry, freshness, validation, admission, strategy
revision, Instruction identity, and Readiness. Provider output is inert until a
current-token completion passes atomic admission.

### IllustrationEditor

```python
class IllustrationEditor(Protocol):
    async def render(
        self, request: AuthorizedIllustrationRequest
    ) -> EditedIllustration: ...
```

Production HTTP/editor and strict scripted implementations are Adapters at this
seam. Only the runtime may construct an authorized request after identified
consent and fresh compatible capture. The editor cannot choose whether to offer,
request capture, select an adjustment, change coaching state, or create Evidence.

### Failure values

Both Interfaces return typed dependency outcomes carrying invocation identity:

```text
deadline_exceeded
unavailable
throttled        (optional provider delay)
rejected
invalid_output
misconfigured
```

Adapters do not retry or decide semantic retryability. Provider-specific details
remain inside them. The runtime owns the approved bounds: an 8-second Reasoner
attempt with at most one eligible automatic retry and at most 2 seconds of provider
delay; a 5-second capture deadline; and a 60-second editor attempt with only
explicit user Retry. Every Reasoner retry rebuilds a fresh Context Pack and runs
only if the semantic purpose remains current.

## Protocol Adapter family

Protocol v1 and v2 are Adapters over one runtime, never separate coaching engines.
They validate and translate wire messages to canonical `RuntimeEvent` values, and
translate canonical `RuntimeOutput` values to their wire dialects.

The transport edge owns:

- WebSocket endpoint and size limits;
- text/binary schema validation;
- v2 negotiation and connection-local session mode;
- one bounded `ObservationAssembler` that joins metadata and bytes by both
  `imageMessageId` and `observationId`;
- connection-local high-resolution request correlation;
- one serialized writer preserving protocol order; and
- client-side/wire freshness checks required by the protocol.

It does **not** own task identity, semantic reconnect continuity, settling,
scheduling, Instruction, Activity, Readiness, action eligibility, retry, Strategy,
or visual-job policy.

### Protocol-v1 projection

V1 is intentionally lossy:

- the current persistent Instruction wins over transient Activity;
- Activity renders as result text only when no Instruction exists;
- Ready renders as the current Instruction;
- existing observation correlation and overlay freshness remain;
- v2-only phase, freshness, identified actions, and separate Activity are omitted;
- Generated Visual Guidance is disabled because v1 cannot carry identified
  Generate consent.

### Protocol-v2 projection

V2 renders the complete immutable user-visible projection after negotiated
acceptance. The runtime decides semantic state; the Adapter enforces session,
revision, schema, ordering, action-message, and generated-transfer wire contracts.

## Authority and data flow

For one accepted input:

1. The Protocol Adapter validates framing and wire shape.
2. The ObservationAssembler emits only a complete immutable observation context;
   action and connection events need no image join.
3. `CoachingRuntime.submit` admits the semantic event in mailbox order.
4. The internal reducer commits next state and declarative effects.
5. The runtime emits committed projections/requests and launches effects.
6. Reasoner/editor outcomes are translated to typed correlated events and submitted
   to the same mailbox.
7. The runtime admits or harmlessly discards each completion by current provenance.
8. The Protocol Adapter renders canonical output and one writer serializes bytes.

This ordering prevents async workers, providers, and protocol handlers from
allocating state revisions, mutating memory, or racing to update the phone.

## Resource ownership

The runtime owns explicit bounds for:

- one authoritative reasoning run, one newest pending request, and at most two
  physical VLM calls;
- a Strategy of at most six Criteria with three candidate actions each;
- current plus one previous compatible Evidence Snapshot and preview;
- at most two recent distinct attempted actions per Criterion;
- Context Pack structured text capped at 32 KiB plus purpose-specific image counts;
- active visual job, accepted still, and generated output;
- run/job pinning of exact image bytes;
- replay/diagnostic records; and
- at most one memory-only detached session retained for 60 seconds.

The transport edge separately bounds unmatched observation metadata/images,
message size, connection-local request state, and send buffering. Configuration
values and calibration status are versioned and recorded by the evaluation
contract.

## Rejected architecture shapes

- Do not wrap `CoachingLoop` or `ReferenceWorkflow` inside v2.
- Do not run legacy and v2 orchestration simultaneously for one session.
- Do not turn Generated Visual Guidance into another workflow authority.
- Do not expose reducer lanes or private schedulers as public Interfaces.
- Do not add a generic transport seam while WebSocket is the only transport.
- Do not add a learned-probe seam without two justified Adapters.
- Do not wrap deterministic policies in fakeable public Interfaces only to enable
  narrow unit tests.

One Adapter can be a useful implementation, but it does not justify a speculative
seam. `CoachingReasoner` and `IllustrationEditor` each have production and scripted
Adapters and therefore earn their seams.

## Migration and atomic cutover

1. Freeze the current v1 wire and observable behavior as deterministic
   characterization traces and integration fixtures.
2. Build `CoachingRuntime` as dormant code with the final state, scheduling,
   memory, Reasoner/Editor, projection, and visual-job contracts.
3. Reuse only pure helpers whose semantics remain valid: wire framing, bounded
   observation assembly, deterministic frame measurements, image validation, and
   artifact primitives.
4. Implement production and scripted Reasoner/Editor Adapters against the final
   Interfaces.
5. Replay recorded input and controlled Adapter outcomes offline. This path sends
   no client output and makes no duplicate live provider calls.
6. Exercise protocol v1 and v2 Adapters against the same runtime scenarios,
   including exact fallback, negotiation, ordering, and generated-image behavior.
7. Pass the deterministic functional matrix and real-phone cutover smoke run in
   [CAMERA_AGENT_V2_EVALUATION.md](CAMERA_AGENT_V2_EVALUATION.md).
8. Perform one composition-root cutover so every newly accepted connection uses
   `CoachingRuntime`. Roll back by deployment version, not a live dual-engine flag.
9. Delete `CoachingLoop`, `ReferenceWorkflow`, fixed-plan request/result contracts,
   server-owned coaching state, and implementation-coupled tests.

Exact model wording and fixed-plan choices do not need parity. Runtime, protocol,
safety, ordering, freshness, cancellation, bounded-resource, and evaluation
contracts do.
