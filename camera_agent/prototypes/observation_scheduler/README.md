# PROTOTYPE — observation gating and inference scheduling

This throwaway logic prototype asks whether a **latest-only, evidence-tokened scheduler** can stay responsive under motion, missed visual changes, slow/non-cancellable model calls, and heartbeat checks without allowing stale work to change the current Instruction or Readiness. It is a decision artifact for [Choose observation gating, heartbeat, and inference scheduling policy](https://github.com/MTI-camera-agent/camera_agent/issues/6), not production code.

Run from the repository root:

```bash
python -m camera_agent.prototypes.observation_scheduler.tui
```

The reducer is isolated in `model.py`; the TUI only dispatches actions and renders its full state.

## Proposed policy embodied by the prototype

1. **Assemble first, then gate.** A candidate is one complete immutable observation context: metadata and its correlated preview image. Never combine fields from different observations.
2. **Cheap tier on every complete preview.** Metadata deltas and the existing thumbnail difference run before expensive work. Optional cheap CV probes publish confidence-crossing signals through the same gate; they may invalidate evidence but can never change Instruction or Readiness directly. Which probes and calibrated thresholds to use is a follow-up measurement decision.
3. **Asymmetric hysteresis.** A hard camera-context change, material preview/metadata delta, or confident probe change invalidates evidence and logical work immediately. A new evidence identity is emitted only after two mutually equivalent post-change frames in this demo. The count/dwell thresholds are configuration calibrated from traces, not normative values from the prototype.
4. **Semantic requests, not frame jobs.** Settled evidence asks for one of `orient`, `evaluate`, or `replan`. Priorities are: missing-Instruction orientation or explicit replanning; material/probe-triggered evaluation; then heartbeat evaluation. Ordinary equivalent frames do not queue work.
5. **Latest-only coalescing.** There is at most one pending semantic request. A newer equal/higher-priority request replaces it; a lower-priority heartbeat cannot displace user- or evidence-driven work.
6. **Tiered heartbeat.** After accepted work, unchanged settled evidence is checked again on a progressively slower cadence. Any material signal, new Instruction, explicit action, failure, or task change resets the cadence. A heartbeat waits for settled evidence and never bypasses higher-priority work. Actual intervals and maximum Instruction age are evaluation-derived latency/cost budgets.
7. **Logical cancellation first.** Invalidation makes run tokens stale immediately and requests best-effort adapter cancellation. The prototype caps physical VLM work at **two total calls**: one authoritative call may overlap one abandoned, non-cancellable call; after a second invalidation, two orphans drain and the newest request waits in the one-slot queue. This buys one immediate replacement without permitting an unbounded cascade. The exact cap remains a deploy-time resource budget.
8. **Freshness is self-identifying token equality plus equivalence.** Every completion carries its actual run identity. It can affect state only when that run is authoritative and its task epoch, strategy revision, source Instruction identity, evidence identity, and camera-context identity still match. Text may act on the latest observation proven equivalent to the immutable analyzed context. Spatial overlays stay bound to the exact source observation and its protocol freshness rules.
9. **Heartbeat is detection, not strategy.** It asks the reasoner to reassess subtle compliance, focus loss, no progress, or a missed gate. The downstream Shot Strategy decides whether to hold, revise, replan, or become Ready.

## Adversarial paths to try

- `m`, `qf`: a material change settles and starts evaluation.
- While it runs: `c`, `qf`: the old run becomes an orphan and a replacement starts from a new camera context.
- Repeat `c`, `qf`: physical overlap reaches its cap, but pending work remains latest-only. Press `l` to drain an orphan and dispatch the current request; later orphan completions remain harmless.
- From a settled idle state, press `t` until heartbeat evaluation starts. Material change preempts it; equivalent frames alone do not.
- `i`, then `qf`, `qf`: a new intention cannot reuse pre-intention evidence and only orients after post-intention settling.
- `p`, `qf`: an optional cheap probe crosses a calibrated confidence boundary and follows the same settle/evaluate path as other material evidence.

## Questions for HITL review

- Is a two-total-call cap (one immediate replacement may overlap one abandoned call) preferable to a strict one-call slot that makes replacement work wait behind a non-cancellable call?
- Should heartbeat cadence back off after repeated holds, or remain fixed under a hard maximum Instruction-age budget?
- Are any event classes allowed to bypass settling? The recommendation here is **no** for model work: explicit actions raise priority, but the model still receives coherent settled evidence.
