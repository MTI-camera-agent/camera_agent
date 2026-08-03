# Camera Agent Harness Architecture

This is the maintained description of the desktop harness. Protocol v1 remains
normative in [protocol-v1.schema.json](protocol-v1.schema.json); the iPhone
handoff is [DESKTOP_AGENT_GUIDE.md](DESKTOP_AGENT_GUIDE.md).

## Contract

The iPhone alone controls camera direction, zoom, focus, exposure, shutter, and
saving photos. The harness can only return text, overlays, and an optional
generated reference image. The harness is deterministic orchestration; Gemini
and the image editor are tools behind typed interfaces.

One connection owns one fresh coaching task. A disconnect discards that task,
and a concurrent second iPhone is rejected.

## Core interaction

`CoachingLoop` is the single owner of task, plan, step, instruction, readiness,
baseline frame, settling candidate, and inference serialization.

```text
new nonempty intention
  → clear old state and show “Analyzing new shot…”
  → Gemini creates one fixed ordered plan (one to five steps)
  → show the first instruction
  → compare each observation with the last analyzed frame
  → ignore insignificant change
  → require two mutually similar changed frames
  → Gemini verifies only the active fixed step
       hold    → preserve the displayed instruction exactly
       revise  → refine the instruction for the same observable criterion
       advance → move to the next fixed step and show its instruction
       ready   → show “Ready—take the shot.”
       resume  → after readiness, reopen the first failed fixed step
```

The fixed plan is replaced only by a new intention. There are no no-progress
timers, reminders, refusal detection, dormant states, rolling action histories,
periodic polling, or readiness streaks.

At most one VLM call runs at once. Frames received during a call update the
latest view. Ordinary held-preview drift does not invalidate a useful answer
and the newest equivalent frame becomes the baseline. A lens/zoom/control event
or a much larger visual change makes the result stale; the newest view must then
pass the same two-frame settling rule before another call. No camera or visual
change bypasses settling: inference starts only after the changed view is held
stable.

While later verification is running, the phone receives no pending text and
the existing instruction stays visible. Pending text appears only when a new
task has no instruction yet.

## Modules

| Module | Responsibility |
| --- | --- |
| `coaching.py` | Deep state machine: `start`, `submit`, `flush`, `close` |
| `change_detection.py` | Cheap metadata and visual difference assessment |
| `domain.py` | Fixed-plan requests, decisions, events, and images |
| `ports.py` | `Reasoner.create_plan`, `Reasoner.verify_step`, `ImageEditor.edit` |
| `adapters/gemini.py` | Structured prompts, schemas, and strict parsing |
| `server.py` | Protocol session, capabilities, and event rendering |
| `reference.py` | Isolated, optional generated-reference workflow |
| `artifacts.py` | Bounded exact input/outcome evidence |

Observation metadata and images can arrive in either order.
`ObservationAssembler` joins them using both `imageMessageId` and
`observationId`, expires unmatched entries after five seconds, and retains at
most 16 unmatched entries per side.

## Change detection

The baseline is the frame most recently analyzed. Automatic ISO, exposure
duration, and white-balance changes are ignored. The detector combines:

- lens, orientation, dimensions, zoom, crop, focus/exposure points, and attitude;
- a mean-centered and blurred 64×64 grayscale thumbnail;
- translation-tolerant global and block-local mean absolute error;
- a difference hash that requires pixel-difference support.

Two changed observations must also be similar to each other. This distinguishes
a deliberate settled composition from one frame captured during movement.
Zoom/focus/exposure events and large visual changes use the same settling rule;
continued operation during inference invalidates that result, then the newest
view must settle before retrying. Decode failure fails open and reaches the
ordinary analysis/error path.

All tuning values live in
[`camera_agent/config.py`](../camera_agent/config.py) and have matching CLI
flags:

| Config / flag | Default | Increasing it |
| --- | ---: | --- |
| `zoom_relative_delta` / `--zoom-relative-delta` | `0.01` | Requires more zoom change |
| `focus_point_distance` / `--focus-point-distance` | `0.03` | Requires more normalized movement |
| `exposure_point_distance` / `--exposure-point-distance` | `0.03` | Requires more normalized movement |
| `exposure_bias_delta_ev` / `--exposure-bias-delta-ev` | `0.10` | Requires more EV change |
| `crop_aspect_ratio_delta` / `--crop-aspect-ratio-delta` | `0.001` | Requires more crop change |
| `attitude_delta_degrees` / `--attitude-delta-degrees` | `2.0` | Requires more roll/pitch |
| `visual_global_mae` / `--visual-global-mae` | `0.04` | Requires more whole-frame change |
| `visual_block_mae` / `--visual-block-mae` | `0.10` | Requires more local change |
| `visual_hash_distance` / `--visual-hash-distance` | `6` | Requires more structural change |
| `visual_thumbnail_size` / `--visual-thumbnail-size` | `64` | Uses more detail and CPU |
| `visual_blur_radius` / `--visual-blur-radius` | `1.0` | Ignores more fine shimmer |
| `visual_alignment_radius` / `--visual-alignment-radius` | `2` | Ignores more tiny translation |
| `routine_change_confirmations` / `--routine-change-confirmations` | `2` | Waits for more settled frames |
| `inference_stale_global_mae` / `--inference-stale-global-mae` | `0.12` | Tolerates more whole-frame drift during inference |
| `inference_stale_block_mae` / `--inference-stale-block-mae` | `0.24` | Tolerates more local drift during inference |

Run with `--log-level DEBUG` to see the measured reasons and scores.

## Model rules

Initial planning prioritizes finding and centering the named target before shot
scale or focus. A target at the left edge means pan/turn left; a target at the
right edge means right. A close shot is satisfied once the target dominates the
frame without unwanted clipping. Unless the intention explicitly requests a
detail, texture, macro, pattern, or named part, every meaningful boundary of
the complete object must remain visible with a small margin. A `focus_changed`
observation is evidence of a tap and focus advice must not repeat without clear
visual evidence.

Verification receives exactly two images: the analyzed baseline and current
settled frame. It also receives the immutable plan, active index, current
instruction, intention, observation reason, and current camera metadata.
`revise` updates guidance without replacing the criterion. Harmless model
variations are normalized: an instructed `hold` becomes `revise`, an `advance`
from the final step becomes `ready`, and irrelevant step indices are ignored.
Only ready-state verification can `resume`; a premature instructed `resume`
becomes same-step revised guidance.

On initial VLM failure, the phone shows a temporary-unavailable result. It does
not tight-loop. A later clearly changed, settled frame may retry. Failures and
stale results never alter an existing instruction.

## Generated references

Editing is allowed only when the intention explicitly asks for a reference,
example, sample, pose visualization, or result visualization—including wording
such as “with a reference image”—and the phone advertises both required
capabilities. Explicit permission guarantees an edit instruction even if the
model omits its optional wording.

After ordinary guidance is displayed, `ReferenceWorkflow` may request one
correlated high-resolution still, edit it asynchronously, and return the image
with the same guidance text. It sends no “generating” pending text and never
changes the coaching plan, baseline, step, or readiness. A new task,
disconnect, timeout, client error, stale step, or edit failure silently cancels
delivery while ordinary coaching continues.

## Debug evidence

`--debug-artifacts DIR` creates one bounded run directory. Every attempted VLM
call records:

- the exact current image bytes and SHA-256;
- phase, task ID, normalized intention, observation/image IDs;
- baseline image ID, reason, camera metadata;
- accepted, stale, superseded, or failed disposition;
- the parsed result or error.

At most 200 files are written. This makes it possible to prove which image and
intention were paired without relying on log timing.

## Network and security

The listener matches the verified mock server:

```text
WSL 0.0.0.0:8765/camera
← Windows portproxy 192.168.137.1:8766
← iPhone ws://192.168.137.1:8766/camera
```

See [IPHONE_WSL_CONNECTION_GUIDE.md](IPHONE_WSL_CONNECTION_GUIDE.md). This is
an unauthenticated, unencrypted trusted-LAN development service.
