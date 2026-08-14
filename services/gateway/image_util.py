from __future__ import annotations

import io
from pathlib import Path

from PIL import Image

ALLOWED_CONTENT_TYPES = frozenset({"image/jpeg", "image/jpg", "image/png"})
ALLOWED_SUFFIXES = frozenset({".jpg", ".jpeg", ".png"})


class FrameValidationError(ValueError):
    """Raised when an uploaded frame is not an acceptable image."""


def validate_frame_content_type(content_type: str | None, filename: str | None) -> None:
    ctype = (content_type or "").split(";")[0].strip().lower()
    suffix = Path(filename or "").suffix.lower()
    if ctype in ALLOWED_CONTENT_TYPES:
        return
    if not ctype and suffix in ALLOWED_SUFFIXES:
        return
    if ctype in {"application/octet-stream", ""} and suffix in ALLOWED_SUFFIXES:
        return
    raise FrameValidationError(
        f"Unsupported frame type {content_type!r} ({filename!r}); use JPEG or PNG"
    )


def save_resized_frame(
    raw: bytes,
    dest: Path,
    *,
    max_long_edge: int = 1280,
) -> Path:
    """Decode JPEG/PNG, clamp long edge, write JPEG to dest."""
    if not raw:
        raise FrameValidationError("Empty frame upload")
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001 — surface as 4xx
        raise FrameValidationError(f"Invalid image bytes: {exc}") from exc

    if image.mode not in ("RGB", "L"):
        image = image.convert("RGB")
    elif image.mode == "L":
        image = image.convert("RGB")

    width, height = image.size
    long_edge = max(width, height)
    if long_edge > max_long_edge:
        scale = max_long_edge / float(long_edge)
        new_size = (max(1, int(width * scale)), max(1, int(height * scale)))
        image = image.resize(new_size, Image.Resampling.LANCZOS)

    dest.parent.mkdir(parents=True, exist_ok=True)
    image.save(dest, format="JPEG", quality=85, optimize=True)
    return dest
