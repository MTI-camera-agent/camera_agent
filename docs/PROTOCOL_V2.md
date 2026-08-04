# HelloCamera protocol-v2 interaction extension

This document is the normative behavioral contract for protocol v2. The
machine-readable object definitions are in
[protocol-v2.schema.json](protocol-v2.schema.json), using JSON Schema Draft
2020-12. Existing camera transport remains protocol v1 and is defined by
[PROTOCOL.md](PROTOCOL.md) and [protocol-v1.schema.json](protocol-v1.schema.json).

The key words **MUST**, **MUST NOT**, **SHOULD**, **SHOULD NOT**, and **MAY** are
normative.

## 1. Scope

Protocol v2 is a progressively negotiated interaction extension. It adds:

- a complete revisioned coaching projection;
- persistent identity-bearing Instruction separate from transient Activity;
- explicit one-use actions;
- memory-only reconnect continuity; and
- Generated Visual Guidance progress and image correlation.

It does not replace the v1 WebSocket endpoint, text/binary framing, hello,
observation stream, preview/still transport, capture request, or client capture
errors. A connection always starts in v1 mode.

## 2. Transport and validation

Use `/camera`, UTF-8 WebSocket text frames, and the existing v1 binary envelope:

```text
4-byte unsigned big-endian JSON-header length
JSON header bytes
raw image bytes
```

The complete WebSocket message remains capped at 8 MiB. Validate header length
before allocation or decoding. V2 objects are closed: unknown fields, wrong types,
malformed UUIDs, missing required fields, and invalid enum values reject the whole
object. `null` is valid only where the schema explicitly permits it.

Validate v1 messages and binary headers against `protocol-v1.schema.json`; validate
v2 text messages and the `visual_guidance_image_v2` binary header against
`protocol-v2.schema.json`, with format checking enabled. Schema validation is
followed by the semantic checks in this document. A semantic failure is an atomic
failure: retain the prior valid phone projection and revision.

Unknown **text-message types MUST be ignored** for forward compatibility. Known
invalid messages are not unknown and follow the error rules below. Invalid binary
framing, size-limit violations, or an unusable socket are connection-level errors.

Phone and desktop each use one serialized send queue. Correctness uses IDs,
revisions, receive order, and desktop monotonic time—not synchronized wall clocks.
`timestampMs` is diagnostic Unix epoch milliseconds.

## 3. Message inventory

| Direction | Message | Schema | Purpose |
| --- | --- | --- | --- |
| phone → desktop | exact `hello` v1 | v1 | First message and camera capabilities |
| phone → desktop | `protocol_v2_offer` | v2 | Offer extension bundles and optional resume handle |
| desktop → phone | `protocol_v2_accept` | v2 | Select v2 output and establish continuity |
| existing directions | v1 observations, image headers, capture request, and capture errors | v1 | Unchanged camera transport |
| desktop → phone | `coaching_state_v2` | v2 | Complete atomic renderer projection |
| phone → desktop | `user_action_v2` | v2 | Invoke one offered action opportunity |
| desktop → phone | `action_result_v2` | v2 | Immediate idempotent acknowledgement |
| desktop → phone | `visual_guidance_image_v2` + bytes | v2 | Generated illustration bytes |
| either direction | `protocol_error_v2` | v2 | Scoped extension fault |

After v2 acceptance the desktop suppresses v1 `result` and `result_image` output.
It may still send unchanged v1 `capture_high_resolution`; the phone may still send
all accepted v1 client messages.

## 4. Negotiation

### 4.1 Phone sequence

On every new WebSocket the phone MUST send through one ordered writer:

1. the exact closed v1 `hello` and await completion of that send;
2. `protocol_v2_offer`; then
3. unchanged v1 observations and image frames without waiting for acceptance.

The offer MUST be the first text message after hello and MUST precede observations.
The phone MUST NOT add v2 capability strings to v1 hello or send hello with
`version: 2`; either change violates the closed v1 schema.

Example offer:

```json
{
  "type": "protocol_v2_offer",
  "version": 2,
  "messageId": "11111111-1111-4111-8111-111111111112",
  "capabilities": [
    "camera_agent_interaction_v2",
    "generated_visual_guidance_v2"
  ],
  "resumeSessionId": null
}
```

`camera_agent_interaction_v2` is mandatory in every offer. The only optional
bundle is `generated_visual_guidance_v2`.

A conforming v1 server ignores the unknown offer and continues in v1 mode. The
phone MUST continue to accept valid v1 results unless and until it receives a valid
v2 acceptance for the current connection.

### 4.2 Desktop acceptance

A v2 desktop MUST validate hello before the offer. It MUST send
`protocol_v2_accept` before processing later observation frames from its receive
queue. Acceptance is valid only when:

- hello and offer were received in that order on this connection;
- accepted capabilities are a subset of the offered set;
- `camera_agent_interaction_v2` is accepted; and
- accepting `generated_visual_guidance_v2` is additionally supported by v1 hello
  capabilities `high_resolution_request` and `sample_image`.

Example:

```json
{
  "type": "protocol_v2_accept",
  "version": 2,
  "messageId": "22222222-2222-4222-8222-222222222222",
  "timestampMs": 1785123456000,
  "sessionId": "33333333-3333-4333-8333-333333333333",
  "resumed": false,
  "capabilities": [
    "camera_agent_interaction_v2",
    "generated_visual_guidance_v2"
  ]
}
```

Acceptance atomically switches this connection to v2 interaction output. The
desktop suppresses v1 results; the phone ignores any late v1 results. Rejection or
absence of acceptance leaves both sides in v1 mode.

A new connection always resets wire mode to v1 until a new acceptance. Retained
phone display is read-only during negotiation.

## 5. Session continuity

`sessionId` is an opaque random UUID and memory-only continuity handle. It is not a
device identity, authentication token, or durable session. The phone MAY retain it
for the lifetime of its process and send it as `resumeSessionId` on reconnect.

The desktop retains at most one detached session for 60 seconds by monotonic time
and rejects a second connection while one is active. Resume succeeds only when the
offered ID matches the retained session, the TTL has not expired, and no newer
connection or task has replaced it. A new non-resume connection evicts detached
continuity. The 60-second value is versioned and initially uncalibrated.

- On successful resume, `protocol_v2_accept` returns the same `sessionId` and
  `resumed: true`. Task and Instruction identities and monotonic state revisions
  continue. The first state marks retained guidance `may_be_outdated`, uses
  `recovering`, and requires a fresh v1 `reconnected` observation before evidence
  may become current.
- On expired, mismatched, or evicted resume, acceptance returns a fresh `sessionId`
  and `resumed: false`. The desktop rebuilds from the intention repeated by a later
  v1 observation.
- A state revision MUST NOT reset within a resumed session.
- A state or action naming another session is stale and MUST NOT affect the current
  session.

## 6. Complete coaching state

After acceptance, the desktop sends a complete `coaching_state_v2` whenever the
visible projection changes. Async workers MUST NOT allocate revisions or write
messages; the serialized runtime commits state, assigns the next revision, and
enqueues output.

Every lane is required. `null` or `[]` explicitly clears a lane; omission never
means “unchanged.” The phone atomically replaces all lanes only when:

1. the object passes schema and semantic validation;
2. `sessionId` matches the accepted connection session; and
3. `stateRevision` is greater than the last applied revision.

A stale, malformed, or contradictory snapshot leaves the last valid state and
revision unchanged.

Example:

```json
{
  "type": "coaching_state_v2",
  "version": 2,
  "messageId": "44444444-4444-4444-8444-444444444444",
  "timestampMs": 1785123456200,
  "sessionId": "33333333-3333-4333-8333-333333333333",
  "stateRevision": 7,
  "taskId": "55555555-5555-4555-8555-555555555555",
  "acceptedIntention": "A confident full-body portrait at sunset",
  "phase": "evaluating",
  "instruction": {
    "instructionId": "66666666-6666-4666-8666-666666666666",
    "kind": "action",
    "text": "Photographer: move one step to your left.",
    "addressee": "photographer",
    "freshness": "needs_revalidation"
  },
  "activity": {
    "kind": "working",
    "text": "Checking your adjustment—hold still."
  },
  "overlays": null,
  "availableActions": [
    {
      "actionId": "77777777-7777-4777-8777-777777777777",
      "kind": "try_another_suggestion",
      "target": {
        "kind": "instruction",
        "id": "66666666-6666-4666-8666-666666666666"
      }
    },
    {
      "actionId": "88888888-8888-4888-8888-888888888888",
      "kind": "pause_coaching",
      "target": {
        "kind": "task",
        "id": "55555555-5555-4555-8555-555555555555"
      }
    }
  ],
  "visualGuidance": null
}
```

### 6.1 State lanes

- `taskId` and `acceptedIntention` are both null when no task exists. When a task
  exists, both are non-null.
- `phase` is one of `needs_intention`, `orienting`, `coaching`, `evaluating`,
  `ready`, `recovering`, or `paused`.
- `instruction` is null or the single persistent Instruction.
- `activity` is null or transient coaching Activity.
- `overlays` is null or one complete observation-bound overlay set.
- `availableActions` is the complete currently valid set.
- `visualGuidance` is null or the complete offer/job sidecar.

### 6.2 Instruction

An Instruction contains:

- application-authored UUID `instructionId`;
- `kind: action | ready`;
- nonempty `text`;
- nullable `addressee: photographer | subject`; and
- `freshness: current | needs_revalidation | may_be_outdated`.

For one `instructionId`, `kind`, `text`, and `addressee` are immutable. Changing
any of them requires a new ID. Freshness, phase, Activity, overlays, available
actions, and visual progress may change without replacing the Instruction.
`kind=ready` is permitted only for evidence-backed Readiness and uses its own ID.

### 6.3 Activity

Coaching and visual Activity each contain `kind: working | waiting | recovering`
and nonempty user-facing `text`. They are independently nullable. Activity reports
what is happening or what the user can do; it MUST NOT expose model/provider names,
queues, hidden reasoning, or invented confidence percentages.

### 6.4 Overlays

An overlay set names the current `instructionId`, exact `sourceObservationId`, and
one or more v1-compatible primitives. The phone applies other state lanes even when
it suppresses the overlays.

The phone MUST suppress an overlay set if:

- the source observation is not in its retained context window;
- the source is more than two seconds old by local receipt history;
- its Instruction is not the current Instruction;
- lens, zoom at 0.001 precision, orientation, dimensions, or crop no longer match;
- a user zoom change occurred; or
- an item has expired according to `expiresInMilliseconds`.

Coordinates and geometry follow protocol v1. Overlay IDs MUST be unique within a
set. Persistent text and Activity are not gated by observation age.

## 7. Explicit one-use actions

Every protocol-owned control is represented by a server-minted `actionId`, semantic
`kind`, and typed target `{kind, id}`. IDs are globally one-use within a session.
An ID may persist unchanged while available, but MUST NOT change meaning, reappear
after retirement, or reappear after consumption. A later equivalent opportunity,
including Retry, receives a new ID.

| Action kind | Required target |
| --- | --- |
| `try_another_suggestion` | `instruction` |
| `pause_coaching`, `resume_coaching` | `task` |
| `generate_visual_guidance`, `decline_visual_guidance` | `visual_offer` |
| `cancel_visual_guidance`, `retry_visual_guidance`, `dismiss_visual_guidance`, `another_visual_example` | `visual_job` |

The target ID MUST name the active matching object in the same snapshot. An action
kind MUST be valid for that object's current state. Action IDs MUST be unique in a
snapshot and MUST NOT be reused across prior accepted snapshots in the session.

The phone invokes an offered action:

```json
{
  "type": "user_action_v2",
  "version": 2,
  "messageId": "99999999-9999-4999-8999-999999999999",
  "timestampMs": 1785123456300,
  "sessionId": "33333333-3333-4333-8333-333333333333",
  "actionId": "77777777-7777-4777-8777-777777777777"
}
```

`messageId` identifies this transmission; `actionId` identifies the semantic
opportunity. The desktop immediately acknowledges before slow reasoning, capture,
or editing:

```json
{
  "type": "action_result_v2",
  "version": 2,
  "messageId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "timestampMs": 1785123456310,
  "sessionId": "33333333-3333-4333-8333-333333333333",
  "actionMessageId": "99999999-9999-4999-8999-999999999999",
  "actionId": "77777777-7777-4777-8777-777777777777",
  "disposition": "accepted",
  "detail": null
}
```

Dispositions:

- `accepted`: this opportunity was current and consumed;
- `duplicate`: the same one-use action was already consumed;
- `stale`: its session or target/opportunity is no longer current;
- `unavailable`: the action is known but cannot currently execute for a scoped
  reason.

Duplicate, stale, and unavailable actions are idempotent no-ops, not protocol
errors. A later full state reflects the result of an accepted action. Intention
editing and local shutter remain phone-owned controls represented by v1 observation
reasons rather than action IDs.

## 8. Generated Visual Guidance

`visualGuidance` is either an offer or an identity-bearing job. Required fields are
`visualId`, `kind`, `status`, `sourceInstructionId`, `demonstrates`, `activity`,
`artifact`, and `failure`.

Semantic combinations:

| Kind/status | Activity | Artifact | Failure |
| --- | --- | --- | --- |
| `offer/offered` | null | null | null |
| `job/waiting_for_settle` | required | null | null |
| `job/capturing` | required | null | null |
| `job/generating` | required | null | null |
| `job/available` | null | required | null |
| `job/failed` | null | null | required user-facing text |

`sourceInstructionId` MUST name the current Instruction. `demonstrates` is one
nonempty adjustment. An offer alone MUST NOT request capture. Accepted Generate,
Retry, or Another example authorizes one job attempt.

### 8.1 High-resolution capture

Use unchanged v1 `capture_high_resolution` and `high_resolution_image` messages.
The v1 `requestId` correlates transport. The runtime separately binds the request
to session, task, source Instruction, Evidence, visual job, and attempt. Late or
incompatible stills are discarded. Existing v1 `error` remains the capture error
surface.

### 8.2 Artifact announcement and bytes

The desktop MUST first announce an available artifact in a committed full state.
The artifact carries:

- UUID `imageMessageId`;
- exact `announcedAtStateRevision`, equal to the first state revision that
  references this transfer identity;
- nonempty `demonstrates`; and
- fixed `provenanceLabel`: **“Edited illustration based on an earlier still — not
  the live preview.”**

It then sends one binary envelope whose header is:

```json
{
  "type": "visual_guidance_image_v2",
  "version": 2,
  "messageId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  "timestampMs": 1785123462000,
  "sessionId": "33333333-3333-4333-8333-333333333333",
  "visualJobId": "cccccccc-cccc-4ccc-8ccc-cccccccccccc",
  "announcedAtStateRevision": 12,
  "mimeType": "image/png",
  "width": 768,
  "height": 1024
}
```

Header `messageId` MUST equal artifact `imageMessageId`; `visualJobId` MUST equal
its `visualGuidance.visualId`; session and announcement revision MUST match the
current artifact reference. The phone accepts bytes only while its current state
references that exact session, job, image ID, and first-announcement revision.
Clearing or replacing the reference makes late bytes harmless.

After reconnect, the desktop MUST either retransmit an available artifact using a
fresh `imageMessageId` and new first-announcement revision or clear/replace the
available claim. It MUST NOT reuse an old transfer identity.

Generated imagery is rendered outside the live preview and saved-photo flow. It
MUST NOT be treated as current live Evidence.

## 9. Ordering and freshness

Required send ordering:

```text
phone:   hello v1 -> protocol_v2_offer -> v1 observations/images
server:  protocol_v2_accept -> first coaching_state_v2
server:  artifact-announcing coaching_state_v2 -> visual_guidance_image_v2 bytes
```

Results are admitted by session and state revision, not timestamps. Actions are
admitted by session, one-use action ID, and active target. Generated bytes are
admitted by session, job, image ID, and first-announcement revision. Spatial
overlays additionally use v1 observation context and local camera/age checks.

Persistent guidance may be useful while an overlay or generated transfer is stale;
therefore stale image-bound content MUST NOT reject or clear unrelated state lanes.

## 10. Errors

Use `protocol_error_v2` for extension faults:

```json
{
  "type": "protocol_error_v2",
  "version": 2,
  "messageId": "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
  "timestampMs": 1785123456400,
  "sessionId": "33333333-3333-4333-8333-333333333333",
  "relatedMessageId": "99999999-9999-4999-8999-999999999999",
  "code": "invalid_message",
  "detail": "The action message failed schema validation."
}
```

Codes are:

- `invalid_message`: a known v2 object failed schema or semantic validation;
- `unexpected_message`: a known valid v2 type arrived in an invalid connection
  state or direction; and
- `unsupported_capability`: negotiation requested or selected an unsupported or
  semantically invalid capability set.

`sessionId` and `relatedMessageId` are nullable when unavailable. A protocol error
MUST NOT clear the last valid state. Stale/duplicate actions use
`action_result_v2`, not protocol error. Capture failures retain v1 `error`.

## 11. Semantic validation checklist

JSON Schema cannot express all cross-message/session rules. Implementations MUST
also enforce:

- exact v1 hello before offer; offer before v2 acceptance;
- accepted capability subset, mandatory bundle, and visual prerequisites;
- current session and strictly increasing state revision;
- task ID/intention nullability consistency;
- one immutable content tuple per Instruction identity;
- overlay Instruction identity and unique primitive IDs;
- globally non-reused action IDs and action-kind/target compatibility;
- current source Instruction for visual offer/job;
- visual kind/status/activity/artifact/failure combinations;
- negotiated visual capability before any visual state or image header;
- artifact image ID, job ID, session, and first-announcement consistency;
- one serialized writer and state-before-image ordering; and
- retained-but-unfresh behavior after resume.

The phone MUST retain its previous valid projection after any failed state check.
The desktop MUST treat rejected, stale, duplicate, late, or invalid input as scoped
and MUST NOT mutate unrelated coaching state.

## 12. V1 fallback projection

A v1-only connection uses the same coaching runtime through a lossy Adapter:

- render the current persistent Instruction as v1 `result.text`;
- render Activity as text only when no Instruction exists;
- render Ready as the current Instruction;
- preserve v1 overlay and observation freshness;
- omit v2 phase, freshness, actions, and separate Activity; and
- disable Generated Visual Guidance because v1 cannot express identified Generate
  consent.

Negotiation selects a renderer projection, never a separate coaching engine.
