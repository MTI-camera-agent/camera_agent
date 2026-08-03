from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import replace

from camera_agent.adapters.fake import ScriptedReasoner
from camera_agent.artifacts import ArtifactRecorder
from camera_agent.coaching import CoachingLoop
from camera_agent.config import ChangeDetectionConfig
from camera_agent.domain import CoachingEventKind, VerificationOutcome
from tests.helpers import context, fixture, planning, shot_plan, verification


async def _started_loop(reasoner, *, artifacts=None):
    events = []

    async def emit(event):
        events.append(event)

    loop = CoachingLoop(
        reasoner,
        ChangeDetectionConfig(),
        emit,
        artifacts=artifacts,
    )
    await loop.start()
    return loop, events


async def test_initial_plan_uses_exact_submitted_image_and_emits_first_step() -> None:
    image = fixture("plant-medium-centered.jpg")
    reasoner = ScriptedReasoner(plans=[planning("Move closer.")])
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, intention="A close shot of the plant", image=image))
        await loop.flush()
        assert [event.kind for event in events] == [
            CoachingEventKind.TASK_STARTED,
            CoachingEventKind.GUIDANCE,
        ]
        assert reasoner.planning_requests[0].current_image.data == image
        assert reasoner.planning_requests[0].intention == "A close shot of the plant"
        assert loop.current_instruction == "Move closer."
    finally:
        await loop.close()


async def test_unchanged_frames_do_not_call_vlm_and_changed_view_must_settle() -> None:
    baseline = fixture("plant-medium-centered.jpg")
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.")],
        verifications=[verification(VerificationOutcome.READY)],
    )
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, image=baseline))
        await loop.flush()
        for observation_id in range(2, 8):
            await loop.submit(context(observation_id, image=baseline))
        await loop.flush()
        assert not reasoner.verification_requests

        changed = context(8, image=baseline)
        changed = replace(
            changed,
            camera={**changed.camera, "rollRadians": 0.05},
        )
        await loop.submit(changed)
        await loop.flush()
        assert not reasoner.verification_requests
        settled = replace(
            context(9, image=baseline),
            camera={**changed.camera},
        )
        await loop.submit(settled)
        await loop.flush()
        assert len(reasoner.verification_requests) == 1
        request = reasoner.verification_requests[0]
        assert request.baseline_image.data == baseline
        assert request.current_image.data == baseline
        assert events[-1].kind == CoachingEventKind.READY
    finally:
        await loop.close()


async def test_explicit_camera_change_waits_for_settled_confirmation() -> None:
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.")],
        verifications=[verification(VerificationOutcome.READY)],
    )
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, image=fixture("plant-medium-centered.jpg")))
        await loop.flush()
        zoomed = context(
            2,
            reason="zoom_changed",
            image=fixture("plant-close-filled.jpg"),
        )
        zoomed = replace(
            zoomed,
            camera={**zoomed.camera, "zoomFactor": 1.5},
        )
        await loop.submit(zoomed)
        await loop.flush()
        assert not reasoner.verification_requests

        settled = replace(
            context(
                3,
                reason="stream",
                image=fixture("plant-close-filled.jpg"),
            ),
            camera={**zoomed.camera},
        )
        await loop.submit(settled)
        await loop.flush()
        assert len(reasoner.verification_requests) == 1
        assert events[-1].kind == CoachingEventKind.READY
    finally:
        await loop.close()


async def test_obvious_visual_change_waits_for_settled_confirmation() -> None:
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.")],
        verifications=[verification(VerificationOutcome.READY)],
    )
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, image=fixture("plant-medium-centered.jpg")))
        await loop.flush()
        await loop.submit(context(2, image=fixture("plant-close-filled.jpg")))
        await loop.flush()
        assert not reasoner.verification_requests

        await loop.submit(context(3, image=fixture("plant-close-filled.jpg")))
        await loop.flush()
        assert len(reasoner.verification_requests) == 1
        assert events[-1].kind == CoachingEventKind.READY
    finally:
        await loop.close()


async def test_hold_preserves_instruction_exactly_and_advances_fixed_plan_later() -> None:
    plan = shot_plan("Plant fills the frame", "Plant is sharp")
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.", plan=plan)],
        verifications=[
            verification(VerificationOutcome.HOLD),
            verification(VerificationOutcome.ADVANCE, instruction="Tap the plant to focus."),
        ],
    )
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, image=fixture("plant-medium-centered.jpg")))
        await loop.flush()
        await loop.submit(context(2, image=fixture("plant-at-right-edge.jpg")))
        await loop.submit(context(3, image=fixture("plant-at-right-edge.jpg")))
        await loop.flush()
        assert loop.current_instruction == "Move closer."
        assert len(events) == 2  # no UI event for hold

        await loop.submit(context(4, image=fixture("plant-close-filled.jpg")))
        await loop.submit(context(5, image=fixture("plant-close-filled.jpg")))
        await loop.flush()
        assert reasoner.verification_requests[-1].plan is plan
        assert reasoner.verification_requests[-1].active_step_index == 0
        assert loop.active_step_id == "step-1"
        assert loop.current_instruction == "Tap the plant to focus."
    finally:
        await loop.close()


async def test_revision_updates_instruction_without_replacing_plan() -> None:
    plan = shot_plan("Shirt fills the frame")
    reasoner = ScriptedReasoner(
        plans=[planning("Move closer.", plan=plan)],
        verifications=[
            verification(
                VerificationOutcome.REVISE,
                instruction="You are close—zoom in just a little more.",
            )
        ],
    )
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, image=fixture("plant-medium-centered.jpg")))
        await loop.flush()
        await loop.submit(context(2, image=fixture("plant-close-filled.jpg")))
        await loop.submit(context(3, image=fixture("plant-close-filled.jpg")))
        await loop.flush()
        assert reasoner.verification_requests[0].plan is plan
        assert loop.active_step_id == "step-0"
        assert loop.current_instruction == (
            "You are close—zoom in just a little more."
        )
        assert events[-1].kind == CoachingEventKind.GUIDANCE
    finally:
        await loop.close()


class _DelayedReasoner:
    def __init__(self) -> None:
        self.requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def create_plan(self, request):
        self.requests.append(request)
        if len(self.requests) == 1:
            self.entered.set()
            await self.release.wait()
            return planning("Old plant instruction.")
        return planning("Frame the computer screen.")

    async def verify_step(self, request):
        raise AssertionError("verification is not expected")


async def test_new_intention_supersedes_old_inference_and_resets_display_state() -> None:
    reasoner = _DelayedReasoner()
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(
            context(
                1,
                reason="intention_updated",
                intention="A close shot of the plant",
                image=fixture("plant-medium-centered.jpg"),
            )
        )
        await reasoner.entered.wait()
        screen = fixture("wide-centered.png")
        await loop.submit(
            context(
                2,
                reason="intention_updated",
                intention="A wide shot of the screen",
                image=screen,
            )
        )
        assert events[-1].kind == CoachingEventKind.TASK_STARTED
        assert loop.current_instruction is None
        reasoner.release.set()
        await loop.flush()
        guidance = [event for event in events if event.kind == CoachingEventKind.GUIDANCE]
        assert [event.instruction for event in guidance] == ["Frame the computer screen."]
        assert reasoner.requests[-1].current_image.data == screen
        assert reasoner.requests[-1].intention == "A wide shot of the screen"
    finally:
        await loop.close()


class _DelayedVerificationReasoner:
    def __init__(self) -> None:
        self.verification_requests = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def create_plan(self, request):
        return planning("Move closer.")

    async def verify_step(self, request):
        self.verification_requests.append(request)
        if len(self.verification_requests) == 1:
            self.entered.set()
            await self.release.wait()
            return verification(VerificationOutcome.READY)
        return verification(VerificationOutcome.READY)


async def test_normal_preview_drift_during_inference_does_not_discard_result() -> None:
    reasoner = _DelayedVerificationReasoner()
    loop, events = await _started_loop(reasoner)
    medium = fixture("plant-medium-centered.jpg")
    edge = fixture("plant-at-right-edge.jpg")
    try:
        await loop.submit(context(1, image=medium))
        await loop.flush()
        await loop.submit(context(2, image=edge))
        await loop.submit(context(3, image=edge))
        await reasoner.entered.wait()
        drifted = context(4, image=edge)
        drifted = replace(
            drifted,
            camera={**drifted.camera, "rollRadians": 0.05},
        )
        await loop.submit(drifted)
        reasoner.release.set()
        await loop.flush()
        assert events[-1].kind == CoachingEventKind.READY
        assert len(reasoner.verification_requests) == 1
    finally:
        await loop.close()


async def test_movement_during_inference_retries_only_after_view_settles() -> None:
    reasoner = _DelayedVerificationReasoner()
    loop, events = await _started_loop(reasoner)
    try:
        await loop.submit(context(1, image=fixture("plant-medium-centered.jpg")))
        await loop.flush()
        await loop.submit(context(2, image=fixture("plant-at-right-edge.jpg")))
        await loop.submit(context(3, image=fixture("plant-at-right-edge.jpg")))
        await reasoner.entered.wait()
        zoomed = context(
            4,
            reason="zoom_changed",
            image=fixture("plant-close-filled.jpg"),
        )
        zoomed = replace(
            zoomed,
            camera={**zoomed.camera, "zoomFactor": 1.5},
        )
        await loop.submit(zoomed)
        reasoner.release.set()
        await loop.flush()
        assert len(reasoner.verification_requests) == 1
        assert events[-1].kind == CoachingEventKind.GUIDANCE

        settled = replace(
            context(
                5,
                reason="stream",
                image=fixture("plant-close-filled.jpg"),
            ),
            camera={**zoomed.camera},
        )
        await loop.submit(settled)
        await loop.flush()
        assert len(reasoner.verification_requests) == 2
        assert (
            reasoner.verification_requests[-1].current_image.data
            == fixture("plant-close-filled.jpg")
        )
        assert events[-1].kind == CoachingEventKind.READY
    finally:
        await loop.close()


async def test_debug_artifact_pairs_exact_jpeg_intention_and_outcome(tmp_path) -> None:
    image = fixture("plant-medium-centered.jpg")
    recorder = ArtifactRecorder(tmp_path)
    reasoner = ScriptedReasoner(plans=[planning("Move closer.")])
    loop, _ = await _started_loop(reasoner, artifacts=recorder)
    try:
        await loop.submit(context(7, intention="A close plant", image=image))
        await loop.flush()
    finally:
        await loop.close()
    metadata_path = next(recorder.directory.glob("*.json"))
    saved_image_path = next(recorder.directory.glob("*.jpg"))
    metadata = json.loads(metadata_path.read_text())
    assert saved_image_path.read_bytes() == image
    assert metadata["intention"] == "A close plant"
    assert metadata["imageSha256"] == hashlib.sha256(image).hexdigest()
    assert metadata["disposition"] == "accepted"
