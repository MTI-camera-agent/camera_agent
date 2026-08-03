# PROTOTYPE — Camera Agent v2 runtime state

## Question

Can one serialized reducer over orthogonal runtime facts preserve exactly one persistent **Instruction** while connection, evidence/motion, analysis, readiness, recovery, and **Generated Visual Guidance** evolve independently—without flicker, stale async results, or contradictory user-facing state?

This is a throwaway decision artifact for [Choose the runtime state and instruction lifecycle model](https://github.com/MTI-camera-agent/camera_agent/issues/5), not production harness code. It intentionally uses semantic events such as `SettledObserved`; thresholds, retry counts, queue policy, model strategy, and protocol encoding belong to later decisions.

## Run

From the repository root:

```bash
python -m camera_agent.prototypes.runtime_state.tui
```

The terminal re-renders the full state after each event. A useful first path is:

```text
i  set an intention
s  provide settled evidence and request orienting
w  let the adapter start the requested analysis
 g return an Instruction
m  begin a material adjustment
s  settle and request evaluation
w  let the adapter start the requested analysis
 o offer Generated Visual Guidance while evaluation runs
 v accept the offer
 h hold the current Instruction without changing its identity
 v move visual guidance from capture to generation
m  move again; stale visual work is discarded independently
```

Then try disconnecting during evaluation, rejecting an Instruction before a late result, pausing during generation, or capturing before Ready. The `[a]` and `[z]` commands deliberately inject completions carrying the last analysis or visual identity after cancellation; `[e]` repeats an old rejection to exercise idempotence.

## Accepted decisions under test

- **One reducer owns transitions.** Adapters send domain events and execute returned effects. Callers cannot set individual state lanes.
- **Phase and Activity are projections.** The reducer stores authoritative facts; it does not store an independently mutable phase or activity string. This prevents impossible combinations. `Visualizing` is not an exclusive phase: the separate visual-guidance lane can generate while live coaching is Coaching or Evaluating. This deliberately refines the earlier six-phase wording, as approved in the ticket's HITL review.
- **Instruction has identity and lifecycle.** Activity, overlays, motion, and `hold` never change Instruction identity or text. Changed actionable text creates a new identity; the previous Instruction is recorded as achieved, superseded, rejected, irrelevant, or task-ended.
- **Ready is represented as a new Instruction.** `Ready—take the shot.` receives its own Instruction identity and evidence-backed readiness record. Repeated confirmation preserves that identity.
- **Readiness is not revoked by motion or capture alone.** Only an accepted, current analysis result can establish or remove it. Disconnect/resume can mark it unverified pending fresh evidence.
- **Async work is tokened.** Analysis moves through `requested` and `running`; completion must match run, task, and evidence identities. Generated visual output must additionally match its visual job and source Instruction. Late work is ignored.
- **Generated Visual Guidance is a sidecar.** It can offer, capture, generate, fail, or become available without mutating coaching Instruction/readiness. Material scene change, supersession, rejection, pause, disconnect, or a new task discards stale work.
- **Explicit actions target identities.** Duplicate or delayed rejection, generation, and cancellation actions are idempotent no-ops.
- **Reconnect has two semantic paths.** Trusted continuity retains guidance as unverified and requires fresh evidence; untrusted continuity rebuilds from the repeated intention.

## Scenarios that should feel boring

1. Evaluation starts, motion resumes, then a stale result arrives: the Instruction remains and the late result is ignored.
2. An illustration generates while live coaching evaluates: coaching has its own derived phase/activity and the visual panel has a separate truthful activity.
3. Replanning after rejection fails: the rejected Instruction does not reappear; recovery activity fills the gap.
4. Disconnect cancels analysis/generation, retains guidance as “may be outdated,” and reconnect requires fresh evidence.
5. Ready survives user capture and harmless variation, then exits only when current evidence yields a replacement Instruction.
