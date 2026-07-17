from __future__ import annotations

from pathlib import Path
from typing import Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class StructuredVisionClient(Protocol):
    def generate(
        self,
        *,
        prompt: str,
        output_schema: type[T],
        image_paths: list[Path],
    ) -> T:
        ...


class ImageGenerationClient(Protocol):
    def generate(self, *, prompt: str, output_path: Path, size: str = "1024x1024") -> Path:
        ...

    def edit(self, *, image_path: Path, prompt: str, output_path: Path, size: str = "auto") -> Path:
        ...
