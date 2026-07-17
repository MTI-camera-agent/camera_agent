from __future__ import annotations

from pathlib import Path

from PIL import Image


def open_image(path: Path) -> Image.Image:
    if not path.exists():
        raise FileNotFoundError(f"Image file does not exist: {path}")
    return Image.open(path)


def save_png(image: Image.Image, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    image.save(path, format="PNG")
    return path


def image_size(path: Path) -> tuple[int, int]:
    with open_image(path) as image:
        return image.size
