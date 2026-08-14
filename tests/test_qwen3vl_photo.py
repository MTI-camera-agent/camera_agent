from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from schemas.shooting import AestheticInstructionDraft, SceneFacts
from skills.qwen3vl_photo import (
    PHOTO_INSTRUCTION_PROMPT,
    SCENE_DESCRIBE_PROMPT,
    Qwen3VLPhotoClient,
)


def test_draft_aesthetic_rejects_user_intent() -> None:
    client = Qwen3VLPhotoClient.__new__(Qwen3VLPhotoClient)
    client._vlm = MagicMock()
    with pytest.raises(ValueError, match="must not receive user_intent"):
        client.draft_aesthetic_instruction(
            Path("x.jpg"),
            user_intent="人物在右侧",
        )
    client._vlm.describe_images.assert_not_called()


def test_draft_aesthetic_uses_fixed_prompt_only(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake")
    client = Qwen3VLPhotoClient.__new__(Qwen3VLPhotoClient)
    client._vlm = MagicMock()
    client._vlm.describe_images.return_value = "将人物调整至画面中心。"
    draft = client.draft_aesthetic_instruction(image)
    assert isinstance(draft, AestheticInstructionDraft)
    assert draft.instruction.startswith("将人物")
    kwargs = client._vlm.describe_images.call_args.kwargs
    assert kwargs["prompt"] == PHOTO_INSTRUCTION_PROMPT
    assert "人物在右侧" not in kwargs["prompt"]
    assert "userIntent" not in kwargs["prompt"]


def test_describe_scene_uses_describe_prompt(tmp_path: Path) -> None:
    image = tmp_path / "frame.jpg"
    image.write_bytes(b"fake")
    client = Qwen3VLPhotoClient.__new__(Qwen3VLPhotoClient)
    client._vlm = MagicMock()
    client._vlm.describe_images.return_value = "人物偏左，未见远山。"
    facts = client.describe_scene(image)
    assert isinstance(facts, SceneFacts)
    assert "偏左" in facts.narrative
    assert (
        client._vlm.describe_images.call_args.kwargs["prompt"] == SCENE_DESCRIBE_PROMPT
    )
