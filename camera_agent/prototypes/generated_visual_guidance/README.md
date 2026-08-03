# PROTOTYPE — Generated Visual Guidance policy

## Question

When should unsuccessful text coaching produce a single proactive **Generated Visual Guidance** offer, and does the resulting consent/capture/edit/delivery flow remain helpful without nagging, stale output, hidden work, or accidental changes to the live Shot Strategy?

This is a throwaway logic prototype for [Choose when and how to offer generated visual guidance](https://github.com/MTI-camera-agent/camera_agent/issues/9), not production harness code. It uses an illustrative two-distinct-action no-progress budget only to make the interaction easy to drive. The real count, dwell, latency, and retry gates remain measurement-derived decisions for the evaluation ticket.

## Run

From the repository root on this branch:

```bash
python -m camera_agent.prototypes.generated_visual_guidance.tui
```

The terminal re-renders the full coaching and visual-job state after every event.

A useful first path is:

```text
e  first settled evaluation says the current action is insufficient
n  issue a materially different text action for the same Criterion
e  second distinct action is insufficient; one visual offer appears
y  explicitly accept Generate
g  try a premature image completion; it is discarded
h  deliver the fresh transient high-resolution still
g  complete editing; inspect demonstration text and provenance
p  live evidence improves; the generated image does not claim progress
x  dismiss only the image
```

Then try `d` (Not now), `c` (Cancel), or `m` (material scene change) followed by `l` (late image). Also try `u` to model an explicit user request, which may offer immediately when the active Instruction is visualizable.

## Proposed decision under test

### Detecting unsuccessful text coaching

- Do not infer frustration from time, movement, a user capture, facial expression, or one failed adjustment.
- Reuse accepted Shot Strategy evidence. A proactive offer becomes eligible only for a visualizable pose/composition Criterion after a bounded sequence of **semantically distinct text actions** each receives compatible settled evidence classified `insufficient`, with no intervening `improving` result. Progress events that do not carry the current Instruction and scene identities, or arrive while evidence is unsettled, are ignored.
- The prototype budget is two failed actions. Production must tune the budget from replay and live tests.
- `blocked` does not automatically trigger generation: infeasibility or missing evidence should cause a strategy patch or recovery, not a prettier version of an impossible instruction.
- An explicit request for an example can make an eligible offer immediately. It still does not grant permission to capture until the user chooses **Generate**.

### Offering without nagging

- Keep the current Instruction primary. The offer is a separate card: “Would an edited example help?” with **Generate** and **Not now**.
- Offer once per source Instruction and materially equivalent scene. Recording the offer itself prevents it from reappearing after **Not now**, cancellation, failure dismissal, or artifact dismissal. A later explicit request remains allowed.
- A materially different action for the same Criterion may inherit the compatible prior failed-action trajectory, but it must receive its own settled `insufficient` result before an offer. Improvement, a different Criterion, or a materially changed scene resets eligibility.
- Do not offer while Ready, paused, disconnected, recovering, another visual job is active, the Criterion is not usefully editable/illustrable, or the required client capabilities are absent.

### Explicit consent and a fresh still

- Only **Generate**, **Retry**, or **Another example** authorizes one attempt. An offer alone never sends `capture_high_resolution` and never starts an editor.
- Acceptance binds an immutable visual-job identity to task, Instruction, Criterion, and scene/evidence identities.
- If compatible evidence is settled, request one transient high-resolution still immediately. Otherwise show “Hold still for the visual example…” and capture only after settling. Motion during capture invalidates that capture-request identity and requires a new settled request, so its late still cannot be admitted. The still is not a saved user photo.
- Edit only the accepted job's fresh still and demonstrate exactly the source Instruction. Do not pass a coaching transcript or ask the editor to improve the image generally.

### Activity, cancellation, failure, and freshness

- Report separate truthful visual Activity: waiting for settle, capturing, generating, or a scoped failure. Ordinary coaching and the persistent Instruction continue.
- Cancel logically and immediately. Best-effort physical cancellation is optional for correctness; every late still, failure, or generated image is discarded by job/source tokens.
- New intention, source-Instruction closure or replacement, material scene change, pause, disconnect, rejection, or cancellation invalidates pending work and delivered visual guidance.
- Capture and edit failures preserve coaching and offer **Retry** and **Dismiss**. Retrying an edit may reuse its accepted still while still valid; retrying capture requests a fresh still.

### Inherited runtime gates

The earlier runtime-state prototype already exercises new intention, Instruction closure/replacement, rejection, pause, disconnect, Ready, recovery, and capability-driven availability. This focused reducer replays only replacement and material scene invalidation; production composes all of those authoritative gates before admitting an offer or visual-job event. Their semantics are inherited, not re-decided here.

### Delivery and reconnection to live coaching

- Display the output outside the live preview with both:
  - the one action it demonstrates; and
  - “Edited illustration based on an earlier still — not the live preview.”
- A generated image never updates Criterion evidence, Instruction, Shot Strategy, or Readiness. The user applies it, then ordinary fresh observations and the normal progress evaluator judge the live scene.
- **Dismiss** clears only the artifact. **Another example** is fresh explicit consent for a new job and still; it is never launched automatically.

## Scenarios that should feel boring

1. The first insufficient evaluation keeps coaching in text; no offer appears.
2. The user selects **Not now**; unchanged evidence never produces another offer for the same Instruction/scene.
3. The user accepts while moving; no still is requested until the scene settles.
4. Material change during editing invalidates the job; its late output is silently discarded while coaching continues.
5. Editing fails; the Instruction remains, failure is visible only in the visual area, and Retry/Dismiss are explicit.
6. A plausible generated image arrives; nothing becomes Ready until fresh live evidence satisfies every must-have Criterion.
