from __future__ import annotations

from pathlib import Path


class PromptLoader:
    def __init__(self, prompt_dir: Path) -> None:
        self._prompt_dir = prompt_dir

    def load(self, name: str) -> str:
        path = self._prompt_dir / name
        if not path.exists():
            raise FileNotFoundError(f"Prompt file does not exist: {path}")
        return path.read_text(encoding="utf-8")
