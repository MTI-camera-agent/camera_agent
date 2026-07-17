from __future__ import annotations

from pathlib import Path


class FileCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str) -> Path:
        safe = "".join(char if char.isalnum() or char in {"-", "_"} else "_" for char in key)
        return self.root / safe
