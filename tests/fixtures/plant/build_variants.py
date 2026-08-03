"""Build deterministic preview-sized crops from the generated plant fixture."""

from pathlib import Path

from PIL import Image, ImageFilter


ROOT = Path(__file__).parent
PREVIEW_SIZE = (480, 640)


def save_preview(image: Image.Image, name: str) -> None:
    image.resize(PREVIEW_SIZE).convert("RGB").save(
        ROOT / name,
        format="JPEG",
        quality=75,
    )


with Image.open(ROOT / "wide-centered.png") as source:
    image = source.convert("RGB")
    # Portrait crop with the plant clipped against the right-hand frame edge.
    save_preview(image.crop((0, 0, 768, 1024)), "plant-at-right-edge.jpg")
    # A balanced portrait view with the whole plant visible.
    save_preview(image.crop((384, 0, 1152, 1024)), "plant-medium-centered.jpg")
    # The plant dominates the view without accidental clipping.
    close = image.crop((448, 40, 1088, 893))
    save_preview(close, "plant-close-filled.jpg")
    save_preview(
        close.filter(ImageFilter.GaussianBlur(radius=6)),
        "plant-close-blurry.jpg",
    )
