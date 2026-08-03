"""External seams used by the coaching and reference-image modules."""

from __future__ import annotations

from typing import Protocol

from .domain import (
    EditedImage,
    ImageData,
    PlanningDecision,
    PlanningRequest,
    VerificationDecision,
    VerificationRequest,
)


class Reasoner(Protocol):
    """Vision adapter. It proposes plans and verifies one fixed step."""

    async def create_plan(self, request: PlanningRequest) -> PlanningDecision: ...

    async def verify_step(
        self,
        request: VerificationRequest,
    ) -> VerificationDecision: ...


class ImageEditor(Protocol):
    async def edit(self, image: ImageData, instruction: str) -> EditedImage: ...
