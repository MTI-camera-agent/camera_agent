# HelloCamera Phone-Client Conformance Kit

This directory is the **normative frontend conformance kit** for the HelloCamera
iPhone companion client. It turns the approved protocol-v2 handoff (issue
[MTI-camera-agent/camera_agent#17](https://github.com/MTI-camera-agent/camera_agent/issues/17),
part of parent [#15](https://github.com/MTI-camera-agent/camera_agent/issues/15))
into executable and reviewable material that a companion implementation can be
checked against.

This is a **conformance kit**, not an iPhone source implementation and not a second
frontend specification. It introduces no phone source code and no protocol
behavior that the approved v2 contracts do not already define. The dormant v2
runtime path stays off the production composition root until the atomic-cutover
ticket; the kit exercises only the already-landed, public schema and wire-contract
seam (see [HARNESS_ARCHITECTURE.md](../HARNESS_ARCHITECTURE.md), "Migration and
atomic cutover").

## What the kit contains

| Artifact | Purpose |
| --- | --- |
| [PHONE_CLIENT_CONFORMANCE_KIT.md](PHONE_CLIENT_CONFORMANCE_KIT.md) | Normative handoff document: schema pinning, phase/lane and action-availability matrices, phone-local disconnect projection, overlay suppression, image admission, exact provenance label, always-available shutter, and the phone-owned W01–W14 evidence contract. |
| [SCHEMA_HASHES.json](SCHEMA_HASHES.json) | Pinned SHA-256 hashes of `protocol-v1.schema.json` and `protocol-v2.schema.json`. |
| [golden/](golden/) | Complete valid and invalid golden conversations for negotiation, state replacement, actions, reconnect, and generated-image transfer. Each conversation is a machine-readable JSON trace. |
| `tests/test_conformance_kit.py` | The executable self-check. It validates that recorded hashes match the live schemas, that every valid golden conversation is schema-admissible, and that every invalid golden conversation is rejected exactly as documented (schema or semantic). |

## How a companion implementation uses the kit

1. Pin the two schema files and confirm their SHA-256 against
   [SCHEMA_HASHES.json](SCHEMA_HASHES.json).
2. Implement the phone-side behavior described in
   [PHONE_CLIENT_CONFORMANCE_KIT.md](PHONE_CLIENT_CONFORMANCE_KIT.md), including
   the matrices, the phone-local disconnect projection, overlay suppression,
   image admission, the exact provenance label, and the always-available shutter.
3. For each phone-owned W01–W14 assertion, produce the evidence listed in the
   kit's W01–W14 table.
4. Run every golden conversation in [golden/](golden/) through the implementation.
   Valid conversations must be admitted; invalid conversations must be rejected
   with the documented disposition and must leave the last valid projection intact.

The golden conversations are wire-level traces. They are authoritative for
conformance: where prose and a golden trace disagree, the golden trace plus the
referenced schema rule win, because the trace is what the executable kit checks.

## Source of truth

The kit is derived from and must stay consistent with the approved v2 contracts
landed on `v1.0.0` by issue [#16](https://github.com/MTI-camera-agent/camera_agent/issues/16):

- [CAMERA_AGENT_V2_SPEC.md](../CAMERA_AGENT_V2_SPEC.md)
- [HARNESS_ARCHITECTURE.md](../HARNESS_ARCHITECTURE.md)
- [PROTOCOL_V2.md](../PROTOCOL_V2.md) and [protocol-v2.schema.json](../protocol-v2.schema.json)
- [PROTOCOL.md](../PROTOCOL.md) and [protocol-v1.schema.json](../protocol-v1.schema.json)
- [CAMERA_AGENT_V2_EVALUATION.md](../CAMERA_AGENT_V2_EVALUATION.md) (W01–W14 in §5.6)
- [V1_BASELINE_DELTAS.md](../V1_BASELINE_DELTAS.md)

The kit does not redefine those contracts. Where this README or a golden file
appears to, treat it as a pointer and follow the referenced normative section.
