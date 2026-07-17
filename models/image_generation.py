from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx


class OpenAICompatibleImageClient:
    """Client for OpenAI-compatible image generation and edit endpoints."""

    def __init__(self, config: dict[str, Any]) -> None:
        base_url = config.get("base_url")
        if not base_url:
            raise ValueError("Image generator config requires base_url")
        self._base_url = str(base_url).rstrip("/")
        self._timeout = config.get("timeout_seconds")
        self._defaults = {
            "num_inference_steps": int(config.get("num_inference_steps", 4)),
            "guidance_scale": float(config.get("guidance_scale", 1.0)),
            "seed": int(config.get("seed", 0)),
            "response_format": "b64_json",
        }

    def generate(self, *, prompt: str, output_path: Path, size: str = "1024x1024") -> Path:
        payload = {"prompt": prompt, "size": size, **self._defaults}
        started = time.perf_counter()
        response = httpx.post(
            f"{self._base_url}/v1/images/generations",
            json=payload,
            timeout=self._timeout,
        )
        return self._save_response(response, output_path, started)

    def edit(self, *, image_path: Path, prompt: str, output_path: Path, size: str = "auto") -> Path:
        data = {
            "prompt": prompt,
            "size": size,
            "num_inference_steps": str(self._defaults["num_inference_steps"]),
            "guidance_scale": str(self._defaults["guidance_scale"]),
            "seed": str(self._defaults["seed"]),
            "response_format": "b64_json",
            "output_format": "png",
        }
        mime_type = _guess_mime_type(image_path)
        started = time.perf_counter()
        with image_path.open("rb") as handle:
            files = {"image": (image_path.name, handle, mime_type)}
            response = httpx.post(
                f"{self._base_url}/v1/images/edits",
                data=data,
                files=files,
                timeout=self._timeout,
            )
        return self._save_response(response, output_path, started)

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(f"{self._base_url}/health", timeout=5)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    @staticmethod
    def _save_response(response: httpx.Response, output_path: Path, started: float) -> Path:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            detail = response.text[:1000]
            raise RuntimeError(
                f"Image service request failed with HTTP {response.status_code}: {detail}"
            ) from exc
        body = response.json()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(body["data"][0]["b64_json"]))
        elapsed = time.perf_counter() - started
        sidecar = output_path.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {"latency_seconds": elapsed, "response_size": body.get("size")},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return output_path


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    raise ValueError(f"Unsupported image type: {path}")
