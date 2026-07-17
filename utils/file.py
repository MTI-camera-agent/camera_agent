from __future__ import annotations

from pathlib import Path


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve()
