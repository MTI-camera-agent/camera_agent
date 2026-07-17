from __future__ import annotations

from PIL import Image, ImageDraw


def centered_ellipse_mask(size: tuple[int, int], padding_ratio: float = 0.16) -> Image.Image:
    width, height = size
    x_pad = int(width * padding_ratio)
    y_pad = int(height * padding_ratio)
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.ellipse((x_pad, y_pad, width - x_pad, height - y_pad), fill=255)
    return mask


def full_subject_mask(size: tuple[int, int]) -> Image.Image:
    """Bootstrap full-body subject mask for centered portrait images."""
    width, height = size
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)

    body_box = (
        int(width * 0.18),
        int(height * 0.02),
        int(width * 0.84),
        int(height * 0.98),
    )
    draw.ellipse(body_box, fill=255)

    # Fill a central torso/leg band so the mask covers standing subjects better
    # than a pure ellipse while still leaving the frame background replaceable.
    torso_box = (
        int(width * 0.26),
        int(height * 0.18),
        int(width * 0.76),
        int(height * 0.98),
    )
    draw.rounded_rectangle(torso_box, radius=max(4, int(width * 0.08)), fill=255)
    return mask


def full_mask(size: tuple[int, int]) -> Image.Image:
    return Image.new("L", size, 255)
