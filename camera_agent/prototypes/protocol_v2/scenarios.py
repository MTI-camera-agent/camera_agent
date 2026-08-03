"""Static wire traces for the protocol-v2 decision prototype."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import NAMESPACE_URL, uuid5


@dataclass(frozen=True)
class Frame:
    direction: str
    message: dict[str, Any]
    note: str
    binary: bool = False


def uid(name: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"camera-agent-protocol-v2-prototype/{name}"))


TS = 1_785_123_456_000
SESSION = uid("session")
TASK = uid("task")
INSTRUCTION = uid("instruction-move-left")
READY_INSTRUCTION = uid("instruction-ready")
VISUAL_OFFER = uid("visual-offer")
VISUAL_JOB = uid("visual-job")
VISUAL_IMAGE = uid("visual-image")


def envelope(kind: str, name: str, **fields: Any) -> dict[str, Any]:
    return {
        "type": kind,
        "version": 2,
        "messageId": uid(f"message-{name}"),
        **fields,
    }


def hello(name: str = "hello") -> dict[str, Any]:
    return {
        "type": "hello",
        "version": 1,
        "messageId": uid(f"message-{name}"),
        "client": "HelloCamera-iOS",
        "capabilities": [
            "preview_jpeg",
            "high_resolution_request",
            "overlay_primitives",
            "sample_image",
            "motion_attitude",
        ],
    }


def offer(name: str = "offer", resume: str | None = None) -> dict[str, Any]:
    return envelope(
        "protocol_v2_offer",
        name,
        capabilities=["camera_agent_interaction_v2", "generated_visual_guidance_v2"],
        resumeSessionId=resume,
    )


def accept(name: str = "accept", resumed: bool = False) -> dict[str, Any]:
    return envelope(
        "protocol_v2_accept",
        name,
        timestampMs=TS,
        sessionId=SESSION,
        resumed=resumed,
        capabilities=["camera_agent_interaction_v2", "generated_visual_guidance_v2"],
    )


def observation(
    observation_id: int,
    reason: str = "stream",
    *,
    zoom_factor: float = 1.0,
) -> dict[str, Any]:
    return {
        "type": "observation",
        "version": 1,
        "messageId": uid(f"message-observation-{observation_id}-{reason}"),
        "observationId": observation_id,
        "timestampMs": TS + observation_id * 100,
        "reason": reason,
        "intention": "A confident full-body portrait at sunset",
        "camera": {
            "lensID": "back-wide",
            "lensName": "Back Camera",
            "zoomFactor": zoom_factor,
            "focalLength35mm": 24.0 * zoom_factor,
            "focusPoint": {"x": 0.5, "y": 0.5},
            "exposurePoint": {"x": 0.5, "y": 0.5},
            "exposureBias": 0.0,
            "iso": 64.0,
            "exposureDurationSeconds": 0.0083,
            "whiteBalanceRedGain": 2.1,
            "whiteBalanceGreenGain": 1.0,
            "whiteBalanceBlueGain": 1.7,
            "flashMode": "off",
            "orientation": "portrait",
            "frameWidth": 480,
            "frameHeight": 640,
            "cropAspectRatio": 0.75,
            "rollRadians": 0.01,
            "pitchRadians": -0.08,
        },
        "imageMessageId": uid(f"preview-{observation_id}"),
    }


def instruction(
    instruction_id: str = INSTRUCTION,
    *,
    kind: str = "action",
    text: str = "Photographer: move a half-step left.",
    addressee: str | None = "photographer",
    freshness: str = "current",
) -> dict[str, Any]:
    return {
        "instructionId": instruction_id,
        "kind": kind,
        "text": text,
        "addressee": addressee,
        "freshness": freshness,
    }


def action(name: str, kind: str, target_kind: str, target_id: str) -> dict[str, Any]:
    return {
        "actionId": uid(f"action-{name}"),
        "kind": kind,
        "target": {"kind": target_kind, "id": target_id},
    }


def overlay_set(source_observation_id: int = 42) -> dict[str, Any]:
    return {
        "instructionId": INSTRUCTION,
        "sourceObservationId": source_observation_id,
        "items": [
            {
                "id": "move-left",
                "kind": "arrow",
                "points": [{"x": 0.70, "y": 0.54}, {"x": 0.54, "y": 0.54}],
                "color": "#62E6FF",
                "lineWidth": 4,
                "expiresInMilliseconds": 1800,
            }
        ],
    }


def state(
    revision: int,
    *,
    phase: str,
    current_instruction: dict[str, Any] | None,
    activity: dict[str, Any] | None,
    actions: list[dict[str, Any]] | None = None,
    overlays: dict[str, Any] | None = None,
    visual: dict[str, Any] | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    return envelope(
        "coaching_state_v2",
        name or f"state-{revision}",
        timestampMs=TS + revision * 10,
        sessionId=SESSION,
        stateRevision=revision,
        taskId=TASK,
        acceptedIntention="A confident full-body portrait at sunset",
        phase=phase,
        instruction=current_instruction,
        activity=activity,
        overlays=overlays,
        availableActions=actions or [],
        visualGuidance=visual,
    )


def user_action(name: str, action_id: str, message_name: str | None = None) -> dict[str, Any]:
    return envelope(
        "user_action_v2",
        message_name or f"user-action-{name}",
        timestampMs=TS,
        sessionId=SESSION,
        actionId=action_id,
    )


def action_result(
    name: str,
    action_id: str,
    action_message_id: str,
    disposition: str,
    detail: str | None = None,
) -> dict[str, Any]:
    return envelope(
        "action_result_v2",
        f"action-result-{name}-{disposition}",
        timestampMs=TS + 1,
        sessionId=SESSION,
        actionMessageId=action_message_id,
        actionId=action_id,
        disposition=disposition,
        detail=detail,
    )


def visual_offer() -> dict[str, Any]:
    return {
        "visualId": VISUAL_OFFER,
        "kind": "offer",
        "status": "offered",
        "sourceInstructionId": INSTRUCTION,
        "demonstrates": "Angle the subject's near shoulder slightly toward the camera.",
        "activity": None,
        "artifact": None,
        "failure": None,
    }


def visual_job(status: str, *, artifact: bool = False) -> dict[str, Any]:
    activity_text = {
        "capturing": "Capturing a fresh still…",
        "generating": "Creating the edited illustration…",
        "waiting_for_settle": "Hold still for the visual example…",
    }.get(status)
    return {
        "visualId": VISUAL_JOB,
        "kind": "job",
        "status": status,
        "sourceInstructionId": INSTRUCTION,
        "demonstrates": "Angle the subject's near shoulder slightly toward the camera.",
        "activity": {"kind": "working", "text": activity_text} if activity_text else None,
        "artifact": {
            "imageMessageId": VISUAL_IMAGE,
            "announcedAtStateRevision": 4,
            "demonstrates": "Angle the subject's near shoulder slightly toward the camera.",
            "provenanceLabel": "Edited illustration based on an earlier still — not the live preview.",
        }
        if artifact
        else None,
        "failure": None,
    }


def high_resolution_request() -> dict[str, Any]:
    return {
        "type": "capture_high_resolution",
        "version": 1,
        "requestId": uid("capture-request"),
    }


def high_resolution_image() -> dict[str, Any]:
    return {
        "type": "high_resolution_image",
        "version": 1,
        "messageId": uid("capture-image"),
        "observationId": None,
        "requestId": uid("capture-request"),
        "timestampMs": TS,
        "mimeType": "image/jpeg",
        "width": 768,
        "height": 1024,
        "initiation": "agent",
    }


def visual_image() -> dict[str, Any]:
    return envelope(
        "visual_guidance_image_v2",
        "visual-image",
        timestampMs=TS,
        sessionId=SESSION,
        visualJobId=VISUAL_JOB,
        announcedAtStateRevision=4,
        mimeType="image/png",
        width=768,
        height=1024,
    ) | {"messageId": VISUAL_IMAGE}


PAUSE = action("pause", "pause_coaching", "task", TASK)
REJECT = action("reject", "try_another_suggestion", "instruction", INSTRUCTION)
GENERATE = action("generate", "generate_visual_guidance", "visual_offer", VISUAL_OFFER)
DECLINE = action("decline", "decline_visual_guidance", "visual_offer", VISUAL_OFFER)
CANCEL = action("cancel", "cancel_visual_guidance", "visual_job", VISUAL_JOB)
DISMISS = action("dismiss", "dismiss_visual_guidance", "visual_job", VISUAL_JOB)
ANOTHER = action("another", "another_visual_example", "visual_job", VISUAL_JOB)


def _negotiation_and_state() -> list[Frame]:
    active = instruction()
    return [
        Frame("phone → desktop", hello(), "The first frame remains the exact closed v1 hello."),
        Frame("phone → desktop", offer(), "The offer is a new unknown text type, ordered before observations."),
        Frame("desktop → phone", accept(), "Acceptance atomically selects v2 and establishes a memory-only session."),
        Frame("phone → desktop", observation(42, "intention_updated"), "Observations remain unchanged protocol-v1 messages."),
        Frame(
            "desktop → phone",
            state(1, phase="orienting", current_instruction=None, activity={"kind": "working", "text": "Looking at the scene…"}, actions=[PAUSE]),
            "A complete snapshot uses null/empty values to clear lanes; omission never means unchanged.",
        ),
        Frame(
            "desktop → phone",
            state(2, phase="coaching", current_instruction=active, activity=None, actions=[REJECT, PAUSE], overlays=overlay_set()),
            "One immutable Instruction appears. Its exact-observation overlay is independently freshness-gated.",
        ),
        Frame(
            "phone → desktop",
            observation(43, "zoom_changed", zoom_factor=1.1),
            "The phone records a new camera context and immediately suppresses the old overlay locally.",
        ),
        Frame(
            "desktop → phone",
            state(3, phase="evaluating", current_instruction=active, activity={"kind": "waiting", "text": "Checking your adjustment—hold still."}, actions=[REJECT, PAUSE], overlays=overlay_set()),
            "The complete state applies, but the stale-camera-context overlay stays suppressed.",
        ),
        Frame(
            "desktop → phone",
            state(2, phase="coaching", current_instruction=active, activity=None, actions=[REJECT, PAUSE], name="late-state-2"),
            "An old stateRevision is ignored even if asynchronous work sends it late.",
        ),
        Frame(
            "desktop → phone",
            state(
                4,
                phase="ready",
                current_instruction=instruction(
                    READY_INSTRUCTION,
                    kind="ready",
                    text="Ready—take the shot.",
                    addressee=None,
                ),
                activity=None,
                actions=[
                    PAUSE,
                    {
                        "actionId": PAUSE["actionId"],
                        "kind": "resume_coaching",
                        "target": {"kind": "task", "id": TASK},
                    },
                ],
                name="ambiguous-action-state",
            ),
            "Schema-valid but semantically ambiguous duplicate actionId: reject the whole snapshot.",
        ),
        Frame(
            "desktop → phone",
            state(
                4,
                phase="ready",
                current_instruction=instruction(
                    READY_INSTRUCTION,
                    kind="ready",
                    text="Ready—take the shot.",
                    addressee=None,
                ),
                activity=None,
                actions=[PAUSE],
                name="valid-ready-state",
            ),
            "The corrected same-next revision is accepted because the invalid snapshot never advanced state.",
        ),
    ]


def _identified_actions() -> list[Frame]:
    action_message = user_action("reject", REJECT["actionId"])
    return [
        Frame("phone → desktop", hello("actions-hello"), "Start with the exact v1 hello."),
        Frame("phone → desktop", offer("actions-offer"), "Offer v2 before observations."),
        Frame("desktop → phone", accept("actions-accept"), "Select v2."),
        Frame(
            "desktop → phone",
            state(1, phase="coaching", current_instruction=instruction(), activity=None, actions=[REJECT, PAUSE], name="actions-state-1"),
            "Every displayed control has a server-minted one-use actionId and typed target.",
        ),
        Frame("phone → desktop", action_message, "The phone echoes only that actionId; messageId identifies this transmission."),
        Frame(
            "desktop → phone",
            action_result("reject", REJECT["actionId"], action_message["messageId"], "accepted"),
            "The desktop acknowledges the tap before slow replanning.",
        ),
        Frame(
            "desktop → phone",
            state(2, phase="coaching", current_instruction=None, activity={"kind": "working", "text": "Finding another suggestion…"}, actions=[PAUSE], name="actions-state-2"),
            "The rejected Instruction ends; truthful Activity prevents a blank while replanning.",
        ),
        Frame("phone → desktop", action_message, "A transport retry repeats the same messageId and actionId."),
        Frame(
            "desktop → phone",
            action_result("reject-repeated", REJECT["actionId"], action_message["messageId"], "duplicate"),
            "Exact replay is acknowledged as duplicate and cannot repeat the decision.",
        ),
        Frame(
            "phone → desktop",
            user_action("reject-late", REJECT["actionId"], "user-action-reject-late"),
            "A delayed tap can have a new transmission ID but still names the retired action."),
        Frame(
            "desktop → phone",
            action_result("reject-late", REJECT["actionId"], uid("message-user-action-reject-late"), "stale"),
            "A retired action is a harmless stale domain event, not a protocol error.",
        ),
    ]


def _visual_guidance() -> list[Frame]:
    generate_message = user_action("generate", GENERATE["actionId"])
    available = state(
        4,
        phase="coaching",
        current_instruction=instruction(),
        activity=None,
        actions=[REJECT, PAUSE, DISMISS, ANOTHER],
        visual=visual_job("available", artifact=True),
        name="visual-state-available",
    )
    return [
        Frame("phone → desktop", hello("visual-hello"), "The v1 hello still advertises capture and sample-image primitives."),
        Frame("phone → desktop", offer("visual-offer-negotiation"), "Generated Visual Guidance is the only optional v2 capability."),
        Frame("desktop → phone", accept("visual-accept"), "Both sides accept the optional visual-guidance lane."),
        Frame(
            "desktop → phone",
            state(1, phase="coaching", current_instruction=instruction(), activity=None, actions=[REJECT, PAUSE, GENERATE, DECLINE], visual=visual_offer(), name="visual-state-offer"),
            "An offer is separate from the persistent Instruction and does not capture anything.",
        ),
        Frame("phone → desktop", generate_message, "Generate is explicit consent for exactly one identified attempt."),
        Frame(
            "desktop → phone",
            action_result("generate", GENERATE["actionId"], generate_message["messageId"], "accepted"),
            "Consent is acknowledged immediately."),
        Frame(
            "desktop → phone",
            state(2, phase="coaching", current_instruction=instruction(), activity=None, actions=[REJECT, PAUSE, CANCEL], visual=visual_job("capturing"), name="visual-state-capturing"),
            "Visual Activity advances in its own sidecar while ordinary coaching continues."),
        Frame("desktop → phone", high_resolution_request(), "Reuse the existing v1 request: requestId already gives exact correlation."),
        Frame("phone → desktop", high_resolution_image(), "Reuse the existing transient v1 still response; orchestration binds requestId to the job."),
        Frame(
            "desktop → phone",
            state(3, phase="coaching", current_instruction=instruction(), activity=None, actions=[REJECT, PAUSE, CANCEL], visual=visual_job("generating"), name="visual-state-generating"),
            "Capture Activity becomes generation Activity without touching the Instruction."),
        Frame("desktop → phone", available, "A full snapshot announces one exact image transfer and its required provenance label."),
        Frame("desktop → phone", visual_image(), "A dedicated binary header binds bytes to session, visual job, and announced snapshot.", binary=True),
        Frame(
            "desktop → phone",
            state(5, phase="coaching", current_instruction=instruction(freshness="needs_revalidation"), activity={"kind": "waiting", "text": "Checking the changed scene…"}, actions=[REJECT, PAUSE], visual=None, name="visual-state-invalidated"),
            "Material change clears the visual lane but retains the Instruction for revalidation."),
        Frame("desktop → phone", visual_image(), "The same bytes arriving late no longer match the current full snapshot and are dropped.", binary=True),
    ]


def _reconnect() -> list[Frame]:
    return [
        Frame("phone → desktop", hello("resume-initial-hello"), "Initial connection."),
        Frame("phone → desktop", offer("resume-initial-offer"), "No prior session on first connect."),
        Frame("desktop → phone", accept("resume-initial-accept"), "Session established."),
        Frame(
            "desktop → phone",
            state(7, phase="coaching", current_instruction=instruction(), activity=None, actions=[REJECT, PAUSE], name="resume-state-before-drop"),
            "The last valid full state remains rendered when transport drops."),
        Frame("phone → desktop", hello("resume-second-hello"), "Every WebSocket still begins with exact v1 hello."),
        Frame("phone → desktop", offer("resume-offer", SESSION), "The in-memory opaque sessionId is offered only as a continuity handle, never authentication."),
        Frame("desktop → phone", accept("resume-accept", resumed=True), "The desktop confirms whether continuity was actually retained."),
        Frame(
            "desktop → phone",
            state(8, phase="recovering", current_instruction=instruction(freshness="may_be_outdated"), activity={"kind": "recovering", "text": "Reconnected—checking the current scene…"}, actions=[PAUSE], name="resume-state-recovering"),
            "Resumption preserves semantic display but never claims its evidence is fresh."),
        Frame("phone → desktop", observation(90, "reconnected"), "A fresh post-reconnect observation is still required."),
        Frame(
            "desktop → phone",
            state(9, phase="evaluating", current_instruction=instruction(freshness="needs_revalidation"), activity={"kind": "waiting", "text": "Checking your current framing—hold still."}, actions=[REJECT, PAUSE], name="resume-state-evaluating"),
            "Fresh evidence can now revalidate or replace the retained Instruction."),
    ]


def _v1_fallback() -> list[Frame]:
    return [
        Frame("phone → desktop", hello("fallback-hello"), "The new phone begins in v1 mode."),
        Frame("phone → desktop", offer("fallback-offer"), "The repository's v1 server ignores this unknown text type."),
        Frame("phone → desktop", observation(1, "intention_updated"), "The phone does not wait for acceptance before sending ordinary v1 observations."),
        Frame(
            "desktop → phone",
            {
                "type": "result",
                "version": 1,
                "messageId": uid("fallback-result"),
                "observationId": 1,
                "timestampMs": TS,
                "text": "Move the subject slightly left.",
            },
            "Without protocol_v2_accept, the phone continues rendering v1 results exactly as today.",
        ),
    ]


SCENARIOS = {
    "1": ("Negotiation and orthogonal state", _negotiation_and_state()),
    "2": ("One-use identified actions", _identified_actions()),
    "3": ("Generated Visual Guidance", _visual_guidance()),
    "4": ("Reconnect and freshness", _reconnect()),
    "5": ("Fallback to a v1 server", _v1_fallback()),
}
