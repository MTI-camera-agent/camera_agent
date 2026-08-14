"""Reference preview skill: frame + editInstruction → target PNG.

Wraps an ``ImageGenerationClient`` (ComfyUI Qwen2511 primary, OpenAI-compatible
FLUX fallback). Enforces the preserve-identity constraint shared with
``skills/qwen3vl_photo.PHOTO_INSTRUCTION_PROMPT`` so the target image never
invents new subjects/background — mirrors the MVP §Phase 3 prompt 约束.

The two Skill IDs in the MVP table (``reference-image-qwen2511`` /
``reference-image-flux``) are one class parameterized by ``generator``.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from models.protocols import ImageGenerationClient

# Mirror the constraint portion of skills/qwen3vl_photo.PHOTO_INSTRUCTION_PROMPT
# (kept stable for Photography SFT alignment) so Qwen2511/FLUX edits stay
# identity/background-preserving even if the planner's editInstruction omits it.
PRESERVE_IDENTITY_SUFFIX = (
    "保持人物身份、服装和场景内容不变，仅通过调整视角、构图、人物姿态等因素提升照片美感。"
    "不得引入、臆造或描述任何新的人物、物体、或背景元素。"
)

REFERENCE_IMAGE_SKILL_ID_QWEN = "reference-image-qwen2511"
REFERENCE_IMAGE_SKILL_ID_FLUX = "reference-image-flux"
_VALID_GENERATORS = ("qwen2511", "flux")


@dataclass(frozen=True)
class ReferenceImageResult:
    output_path: Path
    latency_ms: int
    width: int | None
    height: int | None
    generator: str


class ReferenceImageSkill:
    """Produce a reference_preview PNG from a frame + editInstruction."""

    def __init__(self, *, client: ImageGenerationClient, generator: str) -> None:
        if generator not in _VALID_GENERATORS:
            raise ValueError(
                f"unknown reference image generator {generator!r}; "
                f"expected one of {_VALID_GENERATORS}"
            )
        self._client = client
        self._generator = generator

    @property
    def generator(self) -> str:
        return self._generator

    def compose_prompt(self, edit_instruction: str) -> str:
        edit = (edit_instruction or "").strip()
        if not edit:
            raise ValueError("editInstruction must be non-empty")
        return f"{edit}\n\n{PRESERVE_IDENTITY_SUFFIX}"

    def generate(
        self,
        *,
        frame_path: Path,
        edit_instruction: str,
        output_path: Path,
    ) -> ReferenceImageResult:
        if not frame_path.is_file():
            raise FileNotFoundError(f"reference frame not found: {frame_path}")
        prompt = self.compose_prompt(edit_instruction)
        started = time.perf_counter()
        written = self._client.edit(
            image_path=frame_path,
            prompt=prompt,
            output_path=output_path,
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        width, height = _read_dimensions(written)
        return ReferenceImageResult(
            output_path=written,
            latency_ms=latency_ms,
            width=width,
            height=height,
            generator=self._generator,
        )


def _read_dimensions(path: Path) -> tuple[int | None, int | None]:
    """Prefer a width/height sidecar field; else open with PIL (lazy import)."""
    sidecar = path.with_suffix(".json")
    if sidecar.is_file():
        try:
            data = json.loads(sidecar.read_text(encoding="utf-8"))
            w = data.get("width")
            h = data.get("height")
            if isinstance(w, int) and isinstance(h, int):
                return w, h
        except (OSError, ValueError):
            pass
    try:
        from PIL import Image

        with Image.open(path) as img:
            return img.size
    except Exception:  # noqa: BLE001 — dimensions are best-effort metadata
        return None, None
