"""Deterministic adapters for tests and offline development."""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable

from ..domain import (
    EditedImage,
    ImageData,
    PlanningDecision,
    PlanningRequest,
    VerificationDecision,
    VerificationRequest,
)


class ScriptedReasoner:
    def __init__(
        self,
        plans: Iterable[PlanningDecision] = (),
        verifications: Iterable[VerificationDecision] = (),
    ) -> None:
        self._plans = deque(plans)
        self._verifications = deque(verifications)
        self.planning_requests: list[PlanningRequest] = []
        self.verification_requests: list[VerificationRequest] = []

    async def create_plan(self, request: PlanningRequest) -> PlanningDecision:
        self.planning_requests.append(request)
        if not self._plans:
            raise RuntimeError("scripted reasoner has no remaining plans")
        return self._plans.popleft()

    async def verify_step(
        self,
        request: VerificationRequest,
    ) -> VerificationDecision:
        self.verification_requests.append(request)
        if not self._verifications:
            raise RuntimeError("scripted reasoner has no remaining verifications")
        return self._verifications.popleft()


class FakeEditor:
    def __init__(self, result: ImageData | None = None) -> None:
        self.result = result
        self.calls: list[tuple[ImageData, str]] = []

    async def edit(self, image: ImageData, instruction: str) -> EditedImage:
        self.calls.append((image, instruction))
        return EditedImage(self.result or image)
