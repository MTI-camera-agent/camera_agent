# Camera Agent Domain Language

## Terms

### Photographer
The person controlling framing, position, zoom, focus, exposure, and capture. Guidance names this recipient when an instruction could otherwise be ambiguous.

### Subject
The person being photographed, who can change pose, expression, gaze, and body position. Guidance names this recipient when an instruction could otherwise be ambiguous.

### Instruction
The single primary, actionable direction currently presented to the user. It persists until achieved, superseded, or no longer relevant; transient activity does not replace it.

### Activity
A transient, user-centered indication of what the camera agent is doing or waiting for. Activity is distinct from the persistent instruction.

### Settled
A period in which camera and scene motion are sufficiently low and consistent for the camera agent to evaluate progress reliably. Settled is an evidence-based condition rather than a timer alone.

### Shot Strategy
The camera agent's revisable interpretation of the user's intention: success criteria, prioritized milestones, current evidence, acceptable alternatives, and conditions for advancing or changing its approach.

### Must-have Criterion
A condition required for the shot to plausibly fulfill the user's intention.

### Nice-to-have Criterion
An optional refinement that can improve the shot but does not prevent readiness.

### Readiness
An evidence-backed, satisficing assessment that the must-have criteria are met with reasonable confidence. Readiness does not require completion of every nice-to-have criterion and never prevents the user from taking a photo.

### Generated Visual Guidance
An illustrative target image produced by editing a current high-resolution still to demonstrate a desired pose or composition. It is distinct from a user-provided external reference image, which is outside the supported domain.
