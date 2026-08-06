# HelloCamera Phone-Client Conformance Kit

Status: normative frontend conformance material for the HelloCamera iPhone
companion client. This document is the handoff kit for
[issue #17](https://github.com/MTI-camera-agent/camera_agent/issues/17) (part of
parent [#15](https://github.com/MTI-camera-agent/camera_agent/issues/15)). It is
derived from the approved v2 contracts landed on `v1.0.0` by
[issue #16](https://github.com/MTI-camera-agent/camera_agent/issues/16).

This is a **conformance kit**, not an iPhone source implementation and not a
second frontend specification. It introduces no phone source code and no protocol
behavior the approved v2 contracts do not already define. The dormant v2 runtime
path stays off the production composition root until the atomic-cutover ticket;
the kit exercises only the already-landed, public schema and wire-contract seam.

The key words **MUST**, **MUST NOT**, **SHOULD**, and **MAY** are normative for
the phone client.

## 1. Scope and authority

A companion iPhone implementation is conforming when it satisfies every rule in
this kit against the pinned schemas. The kit is exercised by the golden
conversations in [golden/](golden/) and the executable self-check
`tests/test_conformance_kit.py`. Where this document and a golden conversation
disagree, the golden conversation plus the referenced schema rule win, because the
trace is what the executable kit checks.

The sole normative sources the kit is derived from are:

- [CAMERA_AGENT_V2_SPEC.md](../CAMERA_AGENT_V2_SPEC.md)
- [HARNESS_ARCHITECTURE.md](../HARNESS_ARCHITECTURE.md)
- [PROTOCOL_V2.md](../PROTOCOL_V2.md) and [protocol-v2.schema.json](../protocol-v2.schema.json)
- [PROTOCOL.md](../PROTOCOL.md) and [protocol-v1.schema.json](../protocol-v1.schema.json)
- [CAMERA_AGENT_V2_EVALUATION.md](../CAMERA_AGENT_V2_EVALUATION.md) (W01–W14 in §5.6)
- [V1_BASELINE_DELTAS.md](../V1_BASELINE_DELTAS.md)

The desktop owns task state, reasoning, scheduling, memory, freshness, and the
coaching projection. The phone owns camera controls, intention entry, the local
shutter, saved photos, reconnect presentation, and rendering. The desktop never
remotely changes lens, zoom, focus, or exposure, and never saves a photo.

## 2. Schema pinning

The companion MUST pin both JSON Schemas and confirm their SHA-256 against
[SCHEMA_HASHES.json](SCHEMA_HASHES.json) before claiming conformance:

| Schema | `$id` | Draft | Path |
| --- | --- | --- | --- |
| protocol-v1 | `https://hellocamera.local/protocol-v1.schema.json` | 2020-12 | `docs/protocol-v1.schema.json` |
| protocol-v2 | `https://hellocamera.local/protocol-v2.schema.json` | 2020-12 | `docs/protocol-v2.schema.json` |

V2 objects are **closed**: unknown fields, wrong types, malformed UUIDs, missing
required fields, and invalid enum values reject the whole object. `null` is valid
only where the schema explicitly permits it. Validation uses JSON Schema Draft
2020-12 with format checking, followed by the semantic checks below. The
executable kit re-computes both hashes on every run, so editing a schema without
re-freezing it here fails the kit.

## 3. Transport and validation

The endpoint is `/camera`, using UTF-8 WebSocket text frames and the existing v1
binary envelope:

```text
4-byte unsigned big-endian JSON-header length
JSON header bytes
raw image bytes
```

A complete WebSocket message is capped at 8 MiB. The phone validates the header
length before allocation or decoding. It validates v1 messages and binary headers
against `protocol-v1.schema.json`, and v2 text messages plus the
`visual_guidance_image_v2` binary header against `protocol-v2.schema.json`, with
format checking. Schema validation is followed by the semantic checks in this
document. A semantic failure is atomic: the phone retains the prior valid
projection and revision.

Unknown **text-message types MUST be ignored** for forward compatibility. Known
invalid v2 messages are not unknown and follow the error rules in §10. Invalid
binary framing, an unsafe header length, oversize input, or an otherwise unusable
transport is a connection-level failure.

Each send direction uses one serialized queue bounded at 32 queued frames or
16 MiB of queued bytes, whichever is reached first. A frame that would exceed the
bound makes the connection unusable: the phone closes it and follows normal
detach/reconnect recovery rather than buffering without limit or silently dropping
an ordered message.

## 4. Negotiation

### 4.1 Phone sequence

On every new WebSocket the phone MUST send, through one ordered writer:

1. the exact closed v1 `hello` and await completion of that send;
2. `protocol_v2_offer`; then
3. unchanged v1 observations and image frames without waiting for acceptance.

The offer MUST be the first text message after `hello` and MUST precede
observations. The phone MUST NOT add v2 capability strings to v1 `hello` or send
`hello` with `version: 2`; either change violates the closed v1 schema. A
conforming v1 server ignores the unknown offer and continues in v1 mode; the phone
MUST continue to accept valid v1 results unless and until it receives a valid v2
acceptance for the current connection.

### 4.2 Acceptance validity

A v2 desktop MUST validate `hello` before the offer and send `protocol_v2_accept`
before processing later observation frames. Acceptance is valid only when:

- `hello` and `offer` were received in that order on this connection;
- accepted capabilities are a subset of the offered set;
- `camera_agent_interaction_v2` is accepted; and
- accepting `generated_visual_guidance_v2` is additionally supported by the v1
  `hello` capabilities `high_resolution_request` and `sample_image`.

Acceptance atomically switches this connection to v2 interaction output. The
desktop suppresses v1 results; the phone ignores any late v1 results. Rejection or
absence of acceptance leaves both sides in v1 mode. A new connection always resets
wire mode to v1 until a new acceptance.

### 4.3 Phone-local disconnect projection

Socket loss cannot be represented by a desktop snapshot. A phone that has accepted
v2 MUST derive a local presentation immediately on close:

- phase is `recovering`;
- retain the accepted intention and Instruction but render Instruction freshness
  as `may_be_outdated`;
- show recovering Activity “Connection lost—reconnecting…”;
- clear overlays, every protocol-owned action, and the complete visual-guidance
  lane/artifact; and
- keep camera controls, intention editing, and the local shutter usable.

This local projection does not allocate or alter `sessionId` or `stateRevision`
and is never sent to the desktop. On a new connection, a valid v1 result received
before v2 acceptance replaces it under v1 rules. After acceptance, the first valid
complete `coaching_state_v2` atomically replaces it. Invalid or stale input leaves
the local disconnected projection intact.

### 4.4 Session continuity

`sessionId` is an opaque random UUID and memory-only continuity handle, not a
device identity, authentication token, or durable session. The phone MAY retain it
for the lifetime of its process and send it as `resumeSessionId` on reconnect. The
desktop retains at most one detached session for 60 seconds and rejects a second
connection while one is active. Resume succeeds only when the offered ID matches
the retained session, the TTL has not expired, and no newer connection or task has
replaced it. On successful resume, `protocol_v2_accept` returns the same
`sessionId` and `resumed: true`; task and Instruction identities and monotonic
state revisions continue. On expired, mismatched, or evicted resume, acceptance
returns a fresh `sessionId` and `resumed: false`. **A state revision MUST NOT
reset within a resumed session.** A state or action naming another session is stale
and MUST NOT affect the current session.

## 5. Complete coaching state

After acceptance, the desktop sends a complete `coaching_state_v2` whenever the
visible projection changes. Every lane is required. `null` or `[]` explicitly
clears a lane; omission never means “unchanged.” The phone atomically replaces all
lanes only when:

1. the object passes schema and semantic validation;
2. `sessionId` matches the accepted connection session; and
3. `stateRevision` is strictly greater than the last applied revision.

A stale, malformed, or contradictory snapshot leaves the last valid state and
revision unchanged.

### 5.1 Phase/lane matrix

Phase is the first matching runtime projection. The phone MUST reject the whole
snapshot for any lane-matrix mismatch while retaining the previous valid
projection. The visual sidecar never changes coaching phase.

| Phase | Task/intention | Instruction | Coaching Activity | Overlays | Visual sidecar |
| --- | --- | --- | --- | --- | --- |
| `needs_intention` | both null | null | required `waiting` | null | null |
| `orienting` | both non-null | null | required `working` or `waiting` | null | null |
| `coaching` | both non-null | required `action`, not `may_be_outdated` | null, `working`, or `waiting` | null or matching Instruction | null or sourced to that Instruction |
| `evaluating` | both non-null | null, `action`, or `ready`; not `may_be_outdated` | required `working` or `waiting` | null or matching retained Instruction | null, or sourced to a retained actionable Instruction |
| `ready` | both non-null | required `ready`, `current` or `needs_revalidation` | null | null | null |
| `recovering` | both non-null | null, `action`, or `ready`; any freshness | required `recovering` | null or matching retained Instruction | null, or sourced to a retained actionable Instruction |
| `paused` | both non-null | null, `action`, or `ready`; `current` or `needs_revalidation` | null only when an Instruction exists, otherwise required `waiting` | null | null |

Cross-cutting: `taskId` and `acceptedIntention` are both null or both non-null.
**Whenever `instruction` is null, Activity is non-null.** `needs_intention` and
`orienting` have no protocol actions except phone-owned intention entry plus, for
Orienting, a valid task `pause_coaching` action. `paused` exposes only
`resume_coaching`.

### 5.2 Instruction immutability

For one `instructionId`, `kind`, `text`, and `addressee` are immutable. Changing
any of them requires a new ID. Only `freshness`
(`current | needs_revalidation | may_be_outdated`) may change without replacing
the Instruction. `kind=ready` is permitted only for evidence-backed Readiness and
uses its own ID.

### 5.3 Overlay suppression

An overlay set names the current `instructionId`, exact `sourceObservationId`, and
one or more v1-compatible primitives. The phone applies other state lanes even
when it suppresses the overlays. The phone MUST suppress an overlay set if:

- the source observation is not in its retained context window;
- the source is more than two seconds old by local receipt history;
- its Instruction is not the current Instruction;
- lens, zoom at 0.001 precision, orientation, dimensions, or crop no longer
  match;
- a user zoom change occurred; or
- an item has expired according to `expiresInMilliseconds`.

Coordinates and geometry follow protocol v1. Overlay IDs MUST be unique within a
set. Persistent text and Activity are not gated by observation age. **A user zoom
change clears current overlays immediately.**

## 6. Explicit one-use actions

Every protocol-owned control is a server-minted `actionId`, semantic `kind`, and
typed target `{kind, id}`. IDs are globally one-use within a session, derived from
a session-scoped monotonically increasing ordinal. An ID MAY persist unchanged
while available, but MUST NOT change meaning, reappear after retirement, or reappear
after consumption. A later equivalent opportunity, including Retry, receives a new
ID.

### 6.1 Action-availability matrix

| Action kind | Required target | Available only when |
| --- | --- | --- |
| `try_another_suggestion` | `instruction` | A current actionable Instruction exists and mode is active; Coaching, Evaluating, and Recovering may expose it |
| `pause_coaching` | `task` | The task is connected and active |
| `resume_coaching` | `task` | The task is connected and paused |
| `generate_visual_guidance`, `decline_visual_guidance` | `visual_offer` | The current visual sidecar is `offer/offered` |
| `cancel_visual_guidance` | `visual_job` | Job status is `waiting_for_settle`, `capturing`, or `generating` |
| `retry_visual_guidance` | `visual_job` | Job status is `failed` |
| `dismiss_visual_guidance` | `visual_job` | Job status is `failed` or `available` |
| `another_visual_example` | `visual_job` | Job status is `available` |

The target ID MUST name the active matching object in the same snapshot. An action
kind MUST be valid for that object’s current state. Action IDs MUST be unique in a
snapshot and MUST NOT be reused across prior accepted snapshots in the session. An
accepted action disappears in the next committed snapshot.

### 6.2 Invocation and dispositions

The phone invokes an offered action with `user_action_v2` carrying `messageId`
(this transmission) and `actionId` (the semantic opportunity). The desktop
immediately acknowledges with `action_result_v2` before slow reasoning, capture,
or editing. Dispositions:

- `accepted`: this opportunity was current and consumed;
- `duplicate`: a new `messageId` invoked an already-consumed `actionId`;
- `stale`: the action retired unconsumed because its target or context ended;
- `unavailable`: the action and target were current, but a scoped precondition or
  resource failure prevented admission. This retires the opportunity; any later
  equivalent opportunity receives a fresh action ID.

Duplicate, stale, and unavailable actions are idempotent no-ops, **not** protocol
errors. For `accepted` or `unavailable`, the acknowledgement is serialized before
any state snapshot caused by the disposition and before slow work. The subsequent
full state—not the acknowledgement—is authoritative UI state. A `user_action_v2`
naming another session produces `protocol_error_v2 unexpected_message`; it never
executes. Exact replay of the same `messageId` with identical payload returns the
cached original disposition without re-execution; reuse of a `messageId` with
different content produces `protocol_error_v2 invalid_message`.

Intention editing and the local shutter remain phone-owned controls represented by
v1 observation reasons, not action IDs.

## 7. Generated Visual Guidance

`visualGuidance` is either an offer or an identity-bearing job. Generated imagery
is rendered outside the live preview and saved-photo flow and MUST NOT be treated
as current live Evidence, Readiness support, a saved user photo, or a live-preview
replacement.

### 7.1 Artifact announcement and image admission

The desktop MUST first announce an available artifact in a committed full state.
The artifact carries:

- UUID `imageMessageId`;
- exact `announcedAtStateRevision`, equal to the first state revision referencing
  this transfer identity;
- nonempty `demonstrates`, exactly equal to the enclosing visual job’s
  `demonstrates`; and
- fixed `provenanceLabel`: **“Edited illustration based on an earlier still — not
  the live preview.”**

The desktop then sends one binary envelope whose header `messageId` MUST equal
artifact `imageMessageId`, `visualJobId` MUST equal its `visualGuidance.visualId`,
and session and announcement revision MUST match the current artifact reference.
**The phone accepts bytes only while its current state references that exact
session, job, image identity, and first-announcement revision.** It MUST also:

- decode the complete payload;
- verify JPEG/PNG media matches `mimeType`;
- verify decoded width/height exactly match the header; and
- enforce the 8 MiB message cap.

Clearing or replacing the reference makes late bytes harmless. On decode, media,
dimension, or integrity failure, the phone does not render the image, retains
unrelated coaching lanes, shows a transient transfer error, and sends
`protocol_error_v2 invalid_message` related to the image `messageId`. On that
current-job error, the desktop commits the visual job to `failed`, clears the
artifact reference, and emits fresh Retry/Dismiss. A stale error for a cleared or
replaced job is a harmless discard.

### 7.2 Exact provenance label

Every delivered generated illustration MUST be labeled, exactly and verbatim:

> Edited illustration based on an earlier still — not the live preview.

The phone MUST render this label with the artifact. An illustration mistaken for
current live Evidence, or missing this provenance, is a critical trust failure.

## 8. Always-available shutter

The local shutter MUST remain available in every harness phase, including
`needs_intention`, `recovering`, and `paused`. Coaching never gates capture. A user
capture proceeds locally, is neutrally acknowledged, invalidates analysis tied to
an older view, and MUST NOT be interpreted as achievement, rejection, refusal, or
“too soon.” After capture, Ready remains displayed until accepted fresh evidence
shows a material regression or the intention changes. A blocked or remotely gated
local shutter is a critical trust failure.

## 9. Errors

`protocol_error_v2` is used for extension faults. Codes:

- `invalid_message`: a known v2 object failed schema or semantic validation;
- `unexpected_message`: a known valid v2 type arrived in an invalid connection
  state or direction (including a wrong-session `user_action_v2`); and
- `unsupported_capability`: negotiation requested or selected an unsupported or
  semantically invalid capability set.

`sessionId` and `relatedMessageId` are nullable when unavailable. A protocol
error MUST NOT clear the last valid state. Stale/duplicate actions use
`action_result_v2`, not a protocol error. Capture failures retain v1 `error`. The
phone MUST NEVER answer an invalid `protocol_error_v2` with another protocol error:
if its framing is safely decoded, log and drop it to prevent an error loop.

## 10. Golden conversations

[golden/](golden/) holds complete valid and invalid conversations for the five
required areas. Each is a machine-readable JSON trace; the executable self-check
validates every step against the pinned schema and runs the named semantic checker.

| Area | Valid | Invalid |
| --- | --- | --- |
| negotiation | `valid-v2-negotiation`, `v1-fallback` | `invalid-offer-before-hello`, `invalid-unoffered-capability`, `invalid-missing-mandatory-bundle`, `invalid-visual-without-prerequisites` |
| state replacement | `valid-complete-snapshot`, `valid-null-clears-lanes` | `invalid-stale-revision`, `invalid-wrong-session`, `invalid-missing-required-field`, `invalid-phase-lane-matrix`, `invalid-instruction-immutability` |
| actions | `valid-accepted`, `valid-duplicate` | `invalid-schema-missing-session`, `invalid-wrong-session`, `invalid-contradictory-reuse` |
| reconnect | `valid-successful-resume`, `valid-failed-resume-fresh-session`, `phone-local-disconnect-projection` | `invalid-revision-reset-on-resume` |
| generated-image transfer | `valid-announcement-then-bytes` | `invalid-bytes-without-announcement`, `invalid-corrupt-bytes`, `invalid-dimension-mismatch`, `invalid-late-bytes-after-clear` |

## 11. Phone-owned W01–W14 evidence contract

For each phone-owned W01–W14 assertion
([CAMERA_AGENT_V2_EVALUATION.md](../CAMERA_AGENT_V2_EVALUATION.md) §5.6), the
companion implementation MUST return the evidence listed below. Evidence is one or
more of: a recorded wire trace matching the cited golden conversation; a
phone-local render artifact (screenshot and/or log) captured on the measured
device using phone monotonic time only; and any `protocol_error_v2`/`action_result_v2`
message the phone sent. All wire traces MUST validate against the pinned schemas
and the semantic checkers in `tests/conformance_semantics.py`.

| ID | Assertion | Phone-owned | Required companion evidence |
| --- | --- | --- | --- |
| W01 | V1 fallback — exact closed hello then unknown offer; v1 server ignores offer; phone continues rendering v1 results. | yes | A wire trace matching `golden/negotiation/v1-fallback.json` (hello → offer → v1 result), plus a phone-local render showing v1 results rendered and no v2 switch. |
| W02 | Valid v2 negotiation — exact v1 hello, offer, acceptance before observation processing; accepted subset and prerequisites. | yes | A wire trace matching `golden/negotiation/valid-v2-negotiation.json` (hello → offer → accept) with the accepted capability subset, mandatory bundle, and visual prerequisites all satisfied. |
| W03 | Invalid negotiation — wrong order, missing mandatory bundle, unoffered selection, or missing visual prerequisites yields scoped error/no switch. | yes | Wire traces matching the four `golden/negotiation/invalid-*.json` conversations, each showing no v2 switch and (where applicable) a `protocol_error_v2` (`unexpected_message` or `unsupported_capability`) sent or received. |
| W04 | Complete snapshot — every lane present; null/empty clears; atomic replace only for matching session and greater revision. | yes | Wire traces matching `golden/state-replacement/valid-complete-snapshot.json` and `valid-null-clears-lanes.json`, plus a phone-local render showing lanes cleared exactly when set to null/`[]`. |
| W05 | Stale/malformed/contradictory snapshot — last valid projection/revision retained, including matrix-violating snapshots. | yes | Wire traces matching `golden/state-replacement/invalid-stale-revision.json`, `invalid-wrong-session.json`, `invalid-missing-required-field.json`, `invalid-phase-lane-matrix.json`, and `invalid-instruction-immutability.json`, each leaving the last valid projection on screen. |
| W06 | Instruction immutability — same ID may change freshness only; changed content/addressee/kind is rejected. | yes | The `invalid-instruction-immutability.json` trace, plus a phone-local render showing the original Instruction retained after the rejected same-ID wording change. |
| W07 | Overlay freshness — state applies while a stale/mismatched overlay is independently suppressed; zoom clears immediately. | yes | A phone-local render captured after a stale/mismatched overlay source (observation aged >2 s, camera-signature mismatch, or expired `expiresInMilliseconds`) showing the overlay suppressed while other lanes apply, plus a separate render showing a user zoom change clearing current overlays at once. |
| W08 | Action lifecycle — permitted/forbidden combinations; ordinal UUIDs never reuse; every disposition leaves the action non-current; exact replay/contradictory reuse/duplicate within the window; wrong-session never executes; acknowledgement precedes resulting state and slow work. | yes | Wire traces matching `golden/actions/valid-accepted.json` (ack before resulting state), `valid-duplicate.json` (duplicate no-op), `invalid-schema-missing-session.json`, `invalid-wrong-session.json`, and `invalid-contradictory-reuse.json`, plus a phone-local render showing the consumed action disappearing from the next snapshot and a wrong-session action not executing. |
| W09 | Generated image ordering — state announcement before bytes; artifact/job demonstration equality; exact session/job/image/first-revision checks; late bytes dropped; corrupt/media/dimension-mismatched current bytes trigger scoped invalid-message then a failed job with fresh Retry/Dismiss; stale errors do nothing. | yes | Wire traces matching `golden/generated-image/valid-announcement-then-bytes.json` and the four `invalid-*.json` traces, plus a phone-local render of the labeled illustration (with the exact provenance label) for the valid case, and a transient transfer error followed by a failed job with fresh Retry/Dismiss for the corrupt/dimension cases. |
| W10 | Disconnect/reconnect negotiation — phone-local disconnect projection requires no server revision; wire resets to v1; valid pre-accept v1 result or first accepted v2 state replaces local projection; sole-session 60-second TTL; active-connection rejection; non-resume eviction; successful/failed resume; no revision reset on success. | yes | The `golden/reconnect/phone-local-disconnect-projection.json` trace with a phone-local render of the recovering projection (Instruction `may_be_outdated`, recovering Activity, cleared overlays/actions/visual, usable shutter, unchanged sessionId/revision), plus `valid-successful-resume.json`, `valid-failed-resume-fresh-session.json`, and `invalid-revision-reset-on-resume.json`. A 60-second-TTL expiry and an active-second-connection rejection trace MUST also be recorded. |
| W11 | Unknown text type — both sides ignore it without state loss or disconnect. | yes | A wire trace in which an unknown text-message type is delivered to the phone and ignored, with a phone-local render showing no state loss and no disconnect. |
| W12 | Known invalid v2 message — `protocol_error_v2` is scoped and last valid state remains; malformed protocol-error input is logged/dropped without an error loop; unsafe framing follows connection-failure policy. | yes | A wire trace in which a known schema-invalid v2 message yields a scoped `protocol_error_v2` `invalid_message` with the last valid state retained, plus a trace in which a malformed `protocol_error_v2` is delivered and logged/dropped (no reply error, no loop). |
| W13 | Binary framing/limits — header bounds, schema, decoded media/header agreement, exact dimensions, integrity, and 8 MiB cap enforced for v1 and visual-guidance images. | yes | Wire traces covering an unsafe header length (rejected as a connection-level failure), a media/signature mismatch, a dimension mismatch (`invalid-dimension-mismatch.json`), and an oversize (>8 MiB) binary message rejected at the cap. |
| W14 | Serialized ordering and backpressure — hello→offer→observation, accept→state, and state→image bytes remain ordered under async completion; the queue never exceeds 32 frames/16 MiB and overflow closes/detaches rather than dropping output. | yes | A wire trace under async completion showing hello→offer→observation and accept→state→image-byte ordering preserved, plus a backpressure trace in which a send queue exceeding 32 frames or 16 MiB closes and detaches the connection rather than silently dropping an ordered message. |

A companion release packet MUST include every trace and render artifact cited
above, each reproducible from the pinned schemas and the recorded device/app
version. Missing evidence for any phone-owned W01–W14 row is a conformance failure.
