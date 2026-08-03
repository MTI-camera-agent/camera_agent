"""Tiny phone-side projection for the protocol-v2 wire-trace prototype."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker

V2_TYPES = {
    "protocol_v2_offer",
    "protocol_v2_accept",
    "coaching_state_v2",
    "user_action_v2",
    "action_result_v2",
    "protocol_error_v2",
    "visual_guidance_image_v2",
}
V1_TYPES = {
    "hello",
    "observation",
    "error",
    "result",
    "capture_high_resolution",
    "preview_image",
    "high_resolution_image",
    "result_image",
}
ACTION_TARGETS = {
    "try_another_suggestion": "instruction",
    "pause_coaching": "task",
    "resume_coaching": "task",
    "generate_visual_guidance": "visual_offer",
    "decline_visual_guidance": "visual_offer",
    "cancel_visual_guidance": "visual_job",
    "retry_visual_guidance": "visual_job",
    "dismiss_visual_guidance": "visual_job",
    "another_visual_example": "visual_job",
}
CAMERA_FRESHNESS_FIELDS = (
    "lensID",
    "orientation",
    "frameWidth",
    "frameHeight",
    "cropAspectRatio",
)


@dataclass
class PhoneProjection:
    session_id: str | None = None
    negotiated_v2: bool = False
    capabilities: tuple[str, ...] = ()
    offered_capabilities: tuple[str, ...] = ()
    hello_seen_on_connection: bool = False
    offer_seen_on_connection: bool = False
    v1_capabilities: tuple[str, ...] = ()
    connection_number: int = 0
    revision: int = 0
    snapshot: dict[str, Any] | None = None
    latest_observation_id: int | None = None
    observations: dict[int, tuple[int, dict[str, Any]]] = field(default_factory=dict)
    local_monotonic_ms: int = 0
    legacy_text: str | None = None
    visual_image_received: bool = False
    overlay_visible: bool = False
    overlay_suppression: str | None = None
    overlay_announced_at_ms: int | None = None
    action_result: str | None = None
    instruction_registry: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    current_actions: dict[str, dict[str, Any]] = field(default_factory=dict)
    action_registry: dict[str, tuple[Any, ...]] = field(default_factory=dict)
    consumed_actions: set[str] = field(default_factory=set)
    retired_actions: set[str] = field(default_factory=set)
    seen_action_messages: dict[str, str] = field(default_factory=dict)
    expected_action_results: dict[str, tuple[str, str]] = field(default_factory=dict)
    image_announcement_registry: dict[str, tuple[str, int]] = field(default_factory=dict)
    retired_image_messages: set[str] = field(default_factory=set)

    def apply(self, direction: str, message: dict[str, Any]) -> str:
        self.local_monotonic_ms += 500
        self._refresh_overlay_visibility()
        kind = message["type"]

        if direction == "phone → desktop":
            if kind == "hello":
                self.connection_number += 1
                self.negotiated_v2 = False
                self.capabilities = ()
                self.offered_capabilities = ()
                self.hello_seen_on_connection = True
                self.offer_seen_on_connection = False
                self.v1_capabilities = tuple(message["capabilities"])
                self.current_actions.clear()
                current_image = self._current_image_reference()
                if current_image is not None:
                    self.retired_image_messages.add(current_image)
                    self.visual_image_received = False
                return "Opened a new negotiation epoch in v1 mode; retained display is read-only until negotiation completes."
            if kind == "protocol_v2_offer":
                if not self.hello_seen_on_connection:
                    return "Rejected v2 offer because exact v1 hello has not opened this connection."
                self.offer_seen_on_connection = True
                self.offered_capabilities = tuple(message["capabilities"])
                return "Phone remains in v1 mode until an explicit protocol_v2_accept arrives."
            if kind == "observation":
                observation_id = message["observationId"]
                self.latest_observation_id = observation_id
                self.observations[observation_id] = (self.local_monotonic_ms, message["camera"])
                self._refresh_overlay_visibility()
                return f"Desktop receives observation {observation_id}; local overlay freshness is rechecked."
            if kind == "user_action_v2":
                if not self.negotiated_v2 or message["sessionId"] != self.session_id:
                    return "Dropped user action outside the negotiated current session."
                return self._record_user_action(message)
            return "Client-origin frame does not mutate the rendered projection."

        if kind == "protocol_v2_accept":
            problem = self._accept_problem(message)
            if problem is not None:
                return f"Rejected protocol acceptance: {problem}"
            same_resumed_session = message["resumed"] and message["sessionId"] == self.session_id
            self.negotiated_v2 = True
            self.session_id = message["sessionId"]
            self.capabilities = tuple(message["capabilities"])
            if not same_resumed_session:
                self.revision = 0
                self.snapshot = None
                self.visual_image_received = False
                self.overlay_visible = False
                self.instruction_registry.clear()
                self.current_actions.clear()
                self.action_registry.clear()
                self.consumed_actions.clear()
                self.retired_actions.clear()
                self.image_announcement_registry.clear()
                self.retired_image_messages.clear()
            return (
                "Resumed current v2 session; revision ordering continues."
                if same_resumed_session
                else "Selected v2 atomically; new session waits for its first full snapshot."
            )

        if kind == "coaching_state_v2":
            if not self.negotiated_v2 or message["sessionId"] != self.session_id:
                return "Dropped state for an unselected or different session."
            if message["stateRevision"] <= self.revision:
                return f"Dropped stale/duplicate state revision {message['stateRevision']}; current is {self.revision}."
            problem = self._state_problem(message)
            if problem is not None:
                return f"Rejected whole snapshot on semantic validation: {problem}"

            current_instruction = message["instruction"]
            if current_instruction is not None:
                instruction_id = current_instruction["instructionId"]
                self.instruction_registry[instruction_id] = self._immutable_instruction(current_instruction)

            old_reference = self._current_image_reference()
            old_action_ids = set(self.current_actions)
            incoming_actions = {
                item["actionId"]: item for item in message["availableActions"]
            }
            self.retired_actions.update(old_action_ids - set(incoming_actions))
            for action_id, item in incoming_actions.items():
                self.action_registry[action_id] = self._action_identity(item)

            self.snapshot = message
            self.revision = message["stateRevision"]
            self.current_actions = incoming_actions
            new_reference = self._current_image_reference()
            if old_reference != new_reference:
                self.visual_image_received = False
                if old_reference is not None:
                    self.retired_image_messages.add(old_reference)
            visual = message["visualGuidance"] or {}
            artifact = visual.get("artifact") or {}
            if artifact:
                self.image_announcement_registry[artifact["imageMessageId"]] = (
                    visual["visualId"], artifact["announcedAtStateRevision"]
                )
            self.overlay_announced_at_ms = (
                self.local_monotonic_ms if message["overlays"] is not None else None
            )
            self.legacy_text = None
            self._refresh_overlay_visibility()
            return f"Applied complete state revision {self.revision}; every lane was replaced atomically."

        if kind == "visual_guidance_image_v2":
            if "generated_visual_guidance_v2" not in self.capabilities:
                return "Dropped visual bytes because the optional capability was not negotiated."
            current = self.snapshot or {}
            visual = current.get("visualGuidance") or {}
            artifact = visual.get("artifact") or {}
            matches = (
                self.negotiated_v2
                and message["sessionId"] == self.session_id
                and message["visualJobId"] == visual.get("visualId")
                and message["messageId"] == artifact.get("imageMessageId")
                and message["announcedAtStateRevision"]
                == artifact.get("announcedAtStateRevision")
                and message["announcedAtStateRevision"] <= self.revision
            )
            if not matches:
                return "Dropped image bytes: current job, transfer, or exact announcement revision does not match."
            self.visual_image_received = True
            return "Accepted image bytes for the currently referenced visual job and exact announcement."

        if kind == "action_result_v2":
            if message["sessionId"] != self.session_id:
                return "Dropped action result for a different session."
            expected = self.expected_action_results.get(message["actionMessageId"])
            actual = (message["actionId"], message["disposition"])
            if expected is not None and expected != actual:
                return f"Rejected contradictory action result: expected {expected[1]}, got {actual[1]}."
            detail = f": {message['detail']}" if message["detail"] else ""
            self.action_result = f"{message['disposition']} {short(message['actionId'])}{detail}"
            return f"Rendered/handled immediate action acknowledgement: {self.action_result}."

        if kind == "protocol_error_v2":
            return "Reported a protocol fault without clearing the last valid coaching state."

        if kind == "result":
            if self.negotiated_v2:
                return "Ignored late v1 result after atomic switch to v2."
            self.legacy_text = message.get("text", self.legacy_text)
            self.snapshot = None
            self.overlay_visible = False
            self.current_actions.clear()
            return "No v2 acceptance arrived on this connection; rendered the legacy v1 result."

        return "Frame is transport/capture data; coaching projection is unchanged."

    def _accept_problem(self, message: dict[str, Any]) -> str | None:
        accepted = set(message["capabilities"])
        offered = set(self.offered_capabilities)
        if not self.hello_seen_on_connection:
            return "exact v1 hello did not open this connection"
        if not self.offer_seen_on_connection:
            return "no offer was sent on this connection"
        if not accepted <= offered:
            return "accepted capabilities were not a subset of the current offer"
        if "camera_agent_interaction_v2" not in accepted:
            return "the mandatory interaction bundle is absent"
        if "generated_visual_guidance_v2" in accepted and not {
            "high_resolution_request",
            "sample_image",
        } <= set(self.v1_capabilities):
            return "visual guidance lacks required v1 capture/image capabilities"
        if message["resumed"] and message["sessionId"] != self.session_id:
            return "resumed=true names an unknown session"
        return None

    def _state_problem(self, message: dict[str, Any]) -> str | None:
        instruction = message["instruction"]
        if instruction is not None:
            prior = self.instruction_registry.get(instruction["instructionId"])
            if prior is not None and prior != self._immutable_instruction(instruction):
                return "an existing instructionId changed immutable kind/text/addressee"

        actions = message["availableActions"]
        action_ids = [item["actionId"] for item in actions]
        if len(action_ids) != len(set(action_ids)):
            return "available actionId values are not unique"
        for item in actions:
            action_id = item["actionId"]
            prior_action = self.action_registry.get(action_id)
            if prior_action is not None and prior_action != self._action_identity(item):
                return "an existing actionId changed kind or target"
            if action_id in self.consumed_actions:
                return "a consumed one-use actionId reappeared"
            if action_id in self.retired_actions:
                return "a retired one-use actionId reappeared"
        visual = message["visualGuidance"]
        if visual is not None and "generated_visual_guidance_v2" not in self.capabilities:
            return "visual lane appeared without its negotiated capability"
        if visual is not None and (
            instruction is None or visual["sourceInstructionId"] != instruction["instructionId"]
        ):
            return "visual lane does not name the current source Instruction"
        if visual is not None and visual["artifact"] is not None:
            artifact = visual["artifact"]
            image_id = artifact["imageMessageId"]
            announcement = artifact["announcedAtStateRevision"]
            prior_announcement = self.image_announcement_registry.get(image_id)
            if image_id in self.retired_image_messages:
                return "a retired image transfer identity reappeared"
            if prior_announcement is None and announcement != message["stateRevision"]:
                return "a new image transfer did not name its first announcing revision"
            if prior_announcement is not None and prior_announcement != (
                visual["visualId"], announcement
            ):
                return "an image transfer changed visual job or announcement revision"

        for item in actions:
            kind = item["kind"]
            target = item["target"]
            if ACTION_TARGETS[kind] != target["kind"]:
                return f"{kind} has incompatible target kind {target['kind']}"
            if target["kind"] == "task" and target["id"] != message["taskId"]:
                return f"{kind} does not target the current task"
            if target["kind"] == "instruction" and (
                instruction is None or target["id"] != instruction["instructionId"]
            ):
                return f"{kind} does not target the current Instruction"
            if target["kind"] in {"visual_offer", "visual_job"} and (
                visual is None or target["id"] != visual["visualId"]
            ):
                return f"{kind} does not target the current visual state"
            if target["kind"] == "visual_offer" and visual.get("kind") != "offer":
                return f"{kind} requires a visual offer"
            if target["kind"] == "visual_job" and visual.get("kind") != "job":
                return f"{kind} requires a visual job"
        return None

    def _record_user_action(self, message: dict[str, Any]) -> str:
        message_id = message["messageId"]
        action_id = message["actionId"]
        previous_action = self.seen_action_messages.get(message_id)
        if previous_action is not None:
            disposition = "duplicate"
        elif action_id in self.consumed_actions or action_id not in self.current_actions:
            disposition = "stale"
        else:
            disposition = "accepted"
            self.consumed_actions.add(action_id)
        self.seen_action_messages[message_id] = action_id
        self.expected_action_results[message_id] = (action_id, disposition)
        return f"Action {short(action_id)} expects immediate {disposition!r} acknowledgement."

    @staticmethod
    def _action_identity(action: dict[str, Any]) -> tuple[Any, ...]:
        target = action["target"]
        return (action["kind"], target["kind"], target["id"])

    @staticmethod
    def _immutable_instruction(instruction: dict[str, Any]) -> tuple[Any, ...]:
        return (instruction["kind"], instruction["text"], instruction["addressee"])

    def _refresh_overlay_visibility(self) -> None:
        overlays = (self.snapshot or {}).get("overlays")
        instruction = (self.snapshot or {}).get("instruction")
        if overlays is None:
            self.overlay_visible = False
            self.overlay_suppression = None
            return
        if instruction is None or overlays["instructionId"] != instruction["instructionId"]:
            self.overlay_visible = False
            self.overlay_suppression = "Instruction identity mismatch"
            return
        source = self.observations.get(overlays["sourceObservationId"])
        latest = self.observations.get(self.latest_observation_id or -1)
        if source is None or latest is None:
            self.overlay_visible = False
            self.overlay_suppression = "source observation not retained"
            return
        source_arrival, source_camera = source
        _, latest_camera = latest
        if self.local_monotonic_ms - source_arrival > 2_000:
            self.overlay_visible = False
            self.overlay_suppression = "source observation older than two seconds"
            return
        if any(source_camera[field] != latest_camera[field] for field in CAMERA_FRESHNESS_FIELDS):
            self.overlay_visible = False
            self.overlay_suppression = "camera context changed"
            return
        if round(source_camera["zoomFactor"], 3) != round(latest_camera["zoomFactor"], 3):
            self.overlay_visible = False
            self.overlay_suppression = "zoom changed"
            return
        expiries = [
            item.get("expiresInMilliseconds") for item in overlays["items"]
        ]
        if (
            self.overlay_announced_at_ms is not None
            and all(expiry is not None for expiry in expiries)
            and self.local_monotonic_ms - self.overlay_announced_at_ms > max(expiries)
        ):
            self.overlay_visible = False
            self.overlay_suppression = "every overlay item expired"
            return
        self.overlay_visible = True
        self.overlay_suppression = None

    def _current_image_reference(self) -> str | None:
        visual = (self.snapshot or {}).get("visualGuidance") or {}
        artifact = visual.get("artifact") or {}
        return artifact.get("imageMessageId")


def load_validators() -> tuple[Draft202012Validator, Draft202012Validator]:
    here = Path(__file__).resolve().parent
    v2_schema = json.loads((here / "protocol-v2-extension.schema.json").read_text())
    v1_schema = json.loads((here.parents[2] / "docs" / "protocol-v1.schema.json").read_text())
    checker = FormatChecker()
    return (
        Draft202012Validator(v1_schema, format_checker=checker),
        Draft202012Validator(v2_schema, format_checker=checker),
    )


def validate_message(
    message: dict[str, Any],
    validators: tuple[Draft202012Validator, Draft202012Validator],
) -> str:
    kind = message.get("type")
    if kind not in V1_TYPES | V2_TYPES:
        return "unknown-text-type-ignored"
    validator = validators[1] if kind in V2_TYPES else validators[0]
    errors = sorted(validator.iter_errors(message), key=lambda error: list(error.path))
    if not errors:
        return "schema-valid"
    leaves: list[str] = []
    for error in errors:
        if error.context:
            leaves.extend(child.message for child in error.context if not child.context)
        else:
            leaves.append(error.message)
    raise ValueError("; ".join(leaves[:5]))


def short(value: str | None) -> str:
    return "—" if value is None else value.split("-")[0]
