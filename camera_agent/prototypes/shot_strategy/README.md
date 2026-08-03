# PROTOTYPE — Shot Strategy and Progress Decision

## Question

Can a stable, priority-ordered set of observable criteria absorb whole-shot evidence updates, distinguish achieved, improving, insufficient, deviating, and blocked progress, keep exactly one incremental Instruction, and use local strategy patches before rebuilding the whole Shot Strategy?

This is a throwaway logic prototype for **Choose the shot strategy and progress-decision model**. It is not production code.

## Run

From the repository root on this branch:

```bash
python -m camera_agent.prototypes.shot_strategy.tui
```

No dependencies beyond Python 3.12 are required.

## Proposed model

- A **Shot Strategy** revision is a small priority-ordered set of observable criteria. Each criterion says whether it is a must-have, and carries candidate actions. It is not a fixed step cursor.
- An accepted evaluation reassesses **every must-have from one current evidence identity**. This prevents Ready from being assembled from unrelated old frames. Optional criteria may be updated when useful but never block Ready.
- Progress belongs to criterion evidence: `achieved`, `improving`, `insufficient`, `deviating`, or `blocked`. **Ready is derived**, not a model-authored criterion state: all must-haves are achieved at sufficient confidence on the current evidence identity.
- The deterministic decision policy chooses one response:
  - improving → hold the exact Instruction identity and text;
  - achieved → advance to the highest-priority unmet must-have;
  - insufficient once → hold; repeatedly insufficient → try another action for the same criterion;
  - deviating → preempt with a correction for the regressed must-have;
  - blocked, exhausted alternatives, or rejection → patch only the affected criterion and preserve unaffected criteria/evidence;
  - intention change or broad scene discontinuity → rebuild the Shot Strategy.
- Changed actionable text always creates a new Instruction identity. Patching and rebuilding show truthful Activity rather than leaving a blank.
- The prototype uses `2` repeated insufficient evaluations and `0.70` readiness confidence only to make paths driveable. The evaluation ticket must set measured values.

## Adversarial paths to drive

1. Press `p`, then `a`: improvement holds the same Instruction; achievement advances.
2. Press `a`, then `d`: a previously achieved must-have regresses and preempts the newer focus.
3. Press `i` repeatedly: the same criterion first holds, then tries an alternative, then requests a local patch.
4. Press `r`: rejection removes that action from the current strategy revision and selects an alternative without a full rebuild.
5. Press `b`, then `l`: blockage patches one criterion while preserving the rest of the strategy.
6. Achieve both must-haves while leaving the nice-to-have insufficient: Ready is derived anyway.
7. Press `m`: only a broad discontinuity requests a full rebuild.

## Key HITL decision

Approve the central split: **the reasoner updates all must-have criterion evidence for the current settled view, while deterministic policy derives Ready and chooses hold/advance/refine/local-patch/full-rebuild; the model does not emit Ready or freely regenerate a plan on each call.**
