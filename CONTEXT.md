# Camera Agent Domain Language

## Terms

### Photographer
The person controlling framing, position, zoom, focus, exposure, and capture. Guidance names this recipient when an Instruction could otherwise be ambiguous.

### Subject
The person being photographed, who can change pose, expression, gaze, and body position. Guidance names this recipient when an Instruction could otherwise be ambiguous.

### Instruction
The single primary, actionable direction currently presented to the user. It persists until achieved, superseded, rejected, made irrelevant, or its task ends; transient Activity does not replace it.

### Activity
A transient, user-centered indication of what the camera agent is doing or waiting for. Activity is distinct from the persistent Instruction.

### Settled
A period in which camera and scene motion are sufficiently low and consistent for the camera agent to evaluate progress reliably. Settled is an evidence-based condition rather than a timer alone.

### Shot Strategy
The camera agent's revisable interpretation of the user's intention: prioritized Criteria, acceptable alternatives, and user or scene constraints. Current progress Evidence is evaluated against the Strategy but is not part of the Strategy itself.

### Criterion
One observable condition in a Shot Strategy, with stable identity, priority, importance, and feasible incremental actions.

### Must-have Criterion
A condition required for the shot to plausibly fulfill the user's intention.

### Nice-to-have Criterion
An optional refinement that may inform diagnostics but never produces a v2 Instruction or prevents Readiness.

### Evidence
Task-relevant observable support from one compatible camera view, including grounded visual facts and bounded uncertainty. Evidence never includes a generated illustration.

### Evidence Snapshot
The complete assessment of every Must-have Criterion against one current compatible item of Evidence. It may also assess relevant Nice-to-have Criteria.

### Readiness
An evidence-backed, satisficing assessment that every Must-have Criterion is achieved with reasonable confidence in one current compatible Evidence Snapshot. Readiness does not require completion of any Nice-to-have Criterion and never prevents the user from taking a photo.

### Generated Visual Guidance
An illustrative target image produced by editing a high-resolution still that is fresh and compatible when accepted for the job. At delivery it is necessarily based on an earlier still, not the live preview or live Evidence. It is distinct from a user-provided external reference image, which is outside the supported domain.
