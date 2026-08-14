"""Qwen3-VL Photography dual calls: scene facts + aesthetic edit draft.

Aesthetic generation MUST use the fixed fine-tune prompt and MUST NOT receive
userIntent (would fight the Photography SFT objective).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from models.openai_compatible_vlm import OpenAICompatibleVLMClient
from schemas.shooting import AestheticInstructionDraft, SceneFacts

# Photography aesthetic-edit instruction prompt. Shared with
# scripts/vlm_edit_qwen3vl_qwen2511{,_0805}.py and the shooting/gateway pipeline — keep wording
# stable for SFT alignment. The prompt LANGUAGE must match the served model's SFT training: the
# 0805 model is English-trained (English question from scripts/vlm_edit_0805-bk.py); the prior
# model used a Chinese prompt. On any wording change, version-bump PHOTO_INSTRUCTION_PROMPT_ID
# (v1→v2→…) and the schemas/shooting.py AestheticInstructionDraft.prompt_id default so runs are
# traceable. See the "VLM model-update checklist" in the 0805 plan.
PHOTO_INSTRUCTION_PROMPT = (
    "Based on this photo, generate one image editing instruction for aesthetic reconstruction. "
    "Keep the subject's appearance and scene content unchanged, and improve the photo's "
    "aesthetics only by adjusting factors such as viewpoint, composition, and human pose. "
    "You may only operate on elements already present in the photo, and must not introduce, "
    "assume, or describe any new people, objects, or scene elements."
)

PHOTO_INSTRUCTION_PROMPT_ID = "photo_aesthetic_v2"

SCENE_DESCRIBE_PROMPT = (
    "你是摄影取景分析助手。请客观描述这张照片中的可见事实，不要给出编辑指令，"
    "不要按用户拍摄意图改写画面。用中文简要说明："
    "主体是谁/什么、位置与朝向、景别、构图（偏左/居中/偏右）、"
    "可见背景与地标、光照，以及画面中明显缺失或不清晰的元素。"
    "不要臆造未出现的物体或远景。"
)


class Qwen3VLPhotoClient:
    """Two HTTP calls to local OpenAI-compatible Qwen3-VL (:8000)."""

    def __init__(self, config: dict[str, Any]) -> None:
        # Reuse vision_bridge-shaped config (base_url, model_id, timeouts, ...).
        self._vlm = OpenAICompatibleVLMClient(config)

    def describe_scene(self, image_path: Path) -> SceneFacts:
        narrative = self._vlm.describe_images(
            image_paths=[image_path],
            prompt=SCENE_DESCRIBE_PROMPT,
        )
        if not narrative:
            raise RuntimeError("Qwen3-VL scene description returned empty text")
        return SceneFacts(narrative=narrative)

    def draft_aesthetic_instruction(
        self,
        image_path: Path,
        *,
        user_intent: str | None = None,
    ) -> AestheticInstructionDraft:
        """Generate aesthetic edit draft. ``user_intent`` must not be supplied."""
        if user_intent is not None:
            raise ValueError(
                "draft_aesthetic_instruction must not receive user_intent; "
                "pass intent only to the main Agent for Question/Plan reconciliation."
            )
        instruction = self._vlm.describe_images(
            image_paths=[image_path],
            prompt=PHOTO_INSTRUCTION_PROMPT,
        )
        if not instruction:
            raise RuntimeError("Qwen3-VL aesthetic instruction returned empty text")
        return AestheticInstructionDraft(
            instruction=instruction,
            prompt_id=PHOTO_INSTRUCTION_PROMPT_ID,
        )
