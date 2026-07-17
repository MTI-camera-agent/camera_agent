from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ToolLayer(StrEnum):
    TRADITIONAL = "traditional"
    VISION = "vision"
    GENERATIVE = "generative"
    COMPOSITE = "composite"


class ToolParameter(BaseModel):
    name: str
    type: str = "string"
    required: bool = False
    description: str | None = None
    default: Any = None


class ToolSpec(BaseModel):
    name: str
    layer: ToolLayer
    description: str
    parameters: list[ToolParameter] = Field(default_factory=list)
    produces: str = "image"

    @property
    def required_parameters(self) -> set[str]:
        return {parameter.name for parameter in self.parameters if parameter.required}
