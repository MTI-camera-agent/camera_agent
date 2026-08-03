# PROTOTYPE — protocol-v2 interaction extension

## Question

Can the future iPhone remain a dumb camera/renderer while protocol v2 adds persistent identity-bearing **Instruction**, independent transient **Activity**, explicit idempotent user actions, resumable continuity, and nonblocking **Generated Visual Guidance** without breaking the repository's protocol-v1 phone or harness?

This is a throwaway logic/wire prototype for [Specify the protocol-v2 interaction extension](https://github.com/MTI-camera-agent/camera_agent/issues/11), not a production protocol implementation. The draft schema deliberately lives beside the prototype. A validated decision should be rewritten as the normative `docs/PROTOCOL_V2.md` and `docs/protocol-v2.schema.json` during specification integration; do not merge this prototype to the production branch.

## Run

From the repository root on this branch:

```bash
python -m camera_agent.prototypes.protocol_v2.tui
```

The terminal validates every frame against either the existing normative v1 schema or the prototype v2-extension schema, then replays five flows one frame at a time:

1. negotiation and orthogonal state;
2. one-use identified actions;
3. Generated Visual Guidance;
4. reconnect and freshness; and
5. fallback to the repository's v1 server.

After every frame it prints the full relevant phone projection, admission result, and exact JSON/header. Use the stale-state, duplicate-action, late-image, and reconnect steps to inspect the cases that are hard to reason about on paper.

## Proposed decision under test

### 1. Negotiate as an extension after the exact v1 `hello`

A future phone sends, in one ordered writer:

1. the **exact closed protocol-v1 `hello`**;
2. a new `protocol_v2_offer` text message; then
3. ordinary v1 observations and image headers.

The offer must precede observations, but the phone does not wait for a response before operating. The repository's v1 server ignores the unknown text type and continues sending v1 `result` messages. A v2 server replies with `protocol_v2_accept` before processing later observation frames. Acceptance atomically selects v2 output for that connection; the server then suppresses v1 results and the phone ignores any late v1 result.

This compatibility promise targets the repository's documented/reference behavior. It also sharpens “unknown text-message types may be ignored” to **must be ignored** for forward compatibility. A hypothetical nonconforming v1 server that closes on unknown types cannot be progressively upgraded this way.

Negotiate one mandatory `camera_agent_interaction_v2` bundle, not combinatorial lane subsets. `generated_visual_guidance_v2` is the only optional bundle and is accepted only when the v1 `hello` also advertises `high_resolution_request` and `sample_image`.

Do **not** send `hello` with `version: 2`: an existing strict v1 implementation recognizes the type, rejects the wrong version, and may close.

### 2. Project one complete phone state

After acceptance, the desktop sends one `coaching_state_v2` **full snapshot** whenever the user-visible projection changes. Every lane is required; `null` or an empty array clears it. Omission never means “unchanged.” The interface is one deep projection rather than several shallow, independently ordered update messages.

The snapshot contains:

- opaque `sessionId` and monotonically increasing `stateRevision`;
- nullable task identity and accepted intention;
- derived coaching phase;
- nullable persistent Instruction with immutable identity/content and mutable freshness;
- nullable transient coaching Activity;
- nullable overlays bound to exact Instruction and observation identities;
- every currently available, server-minted one-use action; and
- nullable Generated Visual Guidance offer/job state with its own Activity or artifact.

The phone replaces all lanes atomically only when `sessionId` matches and `stateRevision` is greater than the last applied revision. Revision never resets in a resumed session. Schema validation is followed by semantic validation of Instruction immutability, unique action IDs, action-kind/target compatibility, and visual-lane capability/source identity; failure rejects the whole snapshot without advancing the revision. A malformed or stale snapshot leaves the previous valid projection intact.

Instruction `text`, `kind`, and `addressee` are immutable for one `instructionId`. Freshness may move among `current`, `needs_revalidation`, and `may_be_outdated` without changing identity. Any actionable-text or addressee change requires a new identity. Phase and Activity can change without replacing the Instruction. Ready is an evidence-backed Instruction with `kind: ready` and its own identity.

### 3. Scope freshness to the lane that needs it

Do not freshness-gate the entire snapshot by observation age. Persistent guidance and truthful Activity may remain useful while a source image ages.

An overlay set identifies one exact `sourceObservationId` and Instruction and retains v1's optional per-item expiry. The phone applies the rest of the snapshot even when its local two-second age, lens, zoom, orientation, dimensions, crop, or Instruction checks suppress stale overlays. Generated-image bytes match the current visual job and transfer identity, not the live observation stream. A late image is dropped when the current full snapshot no longer references it.

### 4. Make actions explicit, targeted, and one-use

Every displayed protocol-owned control carries a server-minted `actionId`, semantic kind, and typed target. The phone maps known kinds to localized labels and sends `user_action_v2` containing a unique transmission `messageId` plus the offered `actionId`.

- `messageId` deduplicates an exact transport replay.
- One-use `actionId` prevents an old Retry, Generate, Reject, or Cancel from triggering a later opportunity against the same target.
- Target identity makes delayed actions harmless after the underlying Instruction, task, visual offer, or visual job ends.
- A newly available Retry receives a new action ID.

The desktop immediately returns `action_result_v2` with `accepted`, `duplicate`, `stale`, or `unavailable`. `accepted` acknowledges the explicit choice before any slow reasoning/editing. Duplicate and stale actions are normal idempotent no-ops, not protocol faults. A later full snapshot shows the resulting state.

Protocol-owned actions are Try another suggestion, Pause/Resume coaching, Generate/Not now, Cancel, Retry, Dismiss, and Another example. Intention editing and the local shutter remain always-available phone controls and continue to use existing v1 observation reasons.

### 5. Keep Generated Visual Guidance a sidecar

The full snapshot carries either an offer identity or a visual-job identity. Its status is `offered`, `waiting_for_settle`, `capturing`, `generating`, `available`, or `failed`. Waiting/capture/generation text lives in the visual lane's own Activity; it never replaces the ordinary Instruction or coaching Activity.

The offer itself does not capture. Generate acknowledges one offered action and creates a new visual-job identity. The prototype reuses unchanged v1 `capture_high_resolution` and `high_resolution_image` messages: `requestId` already gives exact transport correlation, while deterministic orchestration binds the request to the current visual-job/task/Instruction/evidence tokens and rejects late stills.

Available output is announced in a full snapshot before bytes are sent. Both the artifact reference and a dedicated `visual_guidance_image_v2` binary header carry the same `sessionId`/`visualJobId` context, `messageId`, and exact revision that first announced the transfer. The phone accepts the bytes only while its current snapshot still references that job, transfer, and announcement revision. On reconnect, an available artifact is retransmitted with a fresh image `messageId`, or the resumed snapshot no longer claims it is available.

Every available artifact includes both the demonstrated adjustment and the fixed label: **“Edited illustration based on an earlier still — not the live preview.”**

### 6. Treat reconnect continuity as correlation, not freshness or security

`protocol_v2_accept` creates an opaque random `sessionId` retained only in phone and desktop memory. Every new WebSocket resets the wire mode to v1 while leaving the last valid display visible. On reconnect the phone repeats exact v1 `hello`, then offers its previous `resumeSessionId`; until a new acceptance arrives, v1 results are valid again. The desktop alone decides whether the detached state is still resumable and reports `resumed: true|false`. Acceptance is rejected unless it follows an offer on that connection, selects the mandatory bundle, selects only offered capabilities, and satisfies the optional visual lane's v1 capability prerequisites.

The handle is not authentication and is never persisted. A successful resume preserves task/Instruction identity and state revision, but first marks retained guidance `may_be_outdated`, enters Recovering, and requires a fresh post-reconnect observation before evidence can become current. A failed resume gets a new session and rebuilds from the intention repeated in the next observation.

### 7. Serialize sends and keep errors scoped

Each side uses one ordered WebSocket send queue. This preserves v1 hello → offer → observations, accept → state, and state → generated-image bytes. Async model/editor completions may propose state, but only the serialized reducer allocates revisions and enqueues snapshots.

Known invalid v2 messages produce `protocol_error_v2` with `invalid_message`, `unexpected_message`, or `unsupported_capability` and retain the last valid state. Unknown text types are ignored for forward compatibility. Semantic stale actions use `action_result_v2`, not protocol errors. Existing v1 `error` remains the capture/request error surface. Invalid binary framing, size-limit violations, and an unusable WebSocket remain connection-level failures.

## Message inventory

| Direction | Message | Role |
| --- | --- | --- |
| phone → desktop | exact v1 `hello` | First frame and existing camera capabilities |
| phone → desktop | `protocol_v2_offer` | Progressive enhancement and optional resume handle |
| desktop → phone | `protocol_v2_accept` | Atomic mode selection, capability acceptance, session continuity result |
| both existing directions | exact v1 `observation`, preview/still headers, `capture_high_resolution`, `error` | Unchanged camera transport |
| desktop → phone | `coaching_state_v2` | Complete ordered renderer projection |
| phone → desktop | `user_action_v2` | Invoke one currently offered one-use action |
| desktop → phone | `action_result_v2` | Immediate idempotent acknowledgement |
| desktop → phone | `visual_guidance_image_v2` + bytes | Generated artifact correlated beyond v1 result semantics |
| either | `protocol_error_v2` | Scoped extension/schema fault |

The exact draft object definitions are executable in [`protocol-v2-extension.schema.json`](protocol-v2-extension.schema.json).

## Rejected shapes

- **`hello` version 2:** breaks strict v1 known-message validation.
- **Add v2 capability strings to v1 `hello`:** v1 capabilities are a closed enum.
- **Independent Instruction/Activity/action/visual delta messages:** creates cross-lane ordering, partial-clear, and resynchronization states on a dumb renderer.
- **Reuse only v1 `result`:** cannot express stable Instruction identity, separate Activity, explicit actions, session ordering, or visual-job correlation without changing a closed object.
- **Target-only actions:** an old Retry could accidentally trigger a later retry opportunity for the same job; one-use action identity closes that race.
- **Reuse v1 `result_image` unchanged for generated guidance:** its `observationId` correlation describes an ephemeral v1 result, not a resumable visual job.
- **Treat resume as fresh or authenticated:** a memory-only correlation handle proves neither.

## Scenarios that should feel boring

1. Evaluating shows “Checking your adjustment—hold still.” while the same Instruction remains visible.
2. A late lower revision cannot restore obsolete coaching.
3. An accepted Reject immediately acknowledges, retires that one-use control, and shows replanning Activity; exact replay and delayed taps do nothing.
4. Capture and generation Activity advance beside uninterrupted live coaching.
5. Material scene change clears a pending artifact reference, so late bytes are dropped without touching the Instruction.
6. Reconnect keeps a useful Instruction visibly marked outdated and requires fresh evidence.
7. A repository v1 server ignores the offer and the future phone continues rendering v1 results.
