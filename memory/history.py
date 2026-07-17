from __future__ import annotations

from pathlib import Path
from typing import Any
import json


class JsonHistoryStore:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, item: dict[str, Any]) -> None:
        with self._path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=True) + "\n")
