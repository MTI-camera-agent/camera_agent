"""HTTP adapter for the already-running ComfyUI image editing endpoint."""

from __future__ import annotations

from io import BytesIO

import httpx
from PIL import Image, UnidentifiedImageError

from ..domain import EditedImage, ImageData


class ImageEditError(RuntimeError):
    pass


class HttpImageEditor:
    def __init__(
        self,
        url: str = "http://127.0.0.1:8000/edit",
        *,
        timeout_seconds: float = 180.0,
        max_result_bytes: int = 7_500_000,
    ) -> None:
        self._url = url
        self._timeout = timeout_seconds
        self._max_result_bytes = max_result_bytes

    async def edit(self, image: ImageData, instruction: str) -> EditedImage:
        timeout = httpx.Timeout(self._timeout)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                self._url,
                files={"image": ("camera-input.jpg", image.data, image.mime_type)},
                data={"instruction": instruction},
            )
        response.raise_for_status()
        data = response.content
        if not data or len(data) > self._max_result_bytes:
            raise ImageEditError("editing endpoint returned an empty or oversized image")
        try:
            with Image.open(BytesIO(data)) as decoded:
                width, height = decoded.size
                image_format = (decoded.format or "").upper()
                decoded.verify()
        except (UnidentifiedImageError, OSError) as error:
            raise ImageEditError(f"editing endpoint returned an invalid image: {error}") from error
        mime_type = {"JPEG": "image/jpeg", "PNG": "image/png"}.get(image_format)
        if mime_type is None:
            raise ImageEditError(f"unsupported edited image format: {image_format}")
        return EditedImage(ImageData(data=data, mime_type=mime_type, width=width, height=height))
