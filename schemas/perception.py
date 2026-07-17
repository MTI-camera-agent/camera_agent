from __future__ import annotations

from pydantic import BaseModel, Field


class PerceptionReport(BaseModel):
    scene_summary: str = Field(..., min_length=1)
    main_subjects: list[str] = Field(default_factory=list)
    visual_attributes: list[str] = Field(default_factory=list)
    editing_risks: list[str] = Field(default_factory=list)
    user_intent: str = Field(..., min_length=1)
