from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import httpx


class OpenAICompatibleVLMClient:
    """Minimal OpenAI-compatible chat client for local VLMs (e.g. vLLM Qwen3-VL)."""

    def __init__(self, config: dict[str, Any]) -> None:
        base_url = config.get("base_url")
        if not base_url:
            raise ValueError("vision_bridge requires base_url")
        self._base_url = str(base_url).rstrip("/")
        self._model_id = config.get("model_id")
        self._timeout = float(config.get("timeout_seconds", 180.0))
        self._max_tokens = int(config.get("max_tokens", 1024))
        self._temperature = float(config.get("temperature", 0.0))

    def describe_images(
        self,
        *,
        image_paths: list[Path],
        prompt: str,
    ) -> str:
        if not image_paths:
            raise ValueError("describe_images requires at least one image path")
        model_id = self._resolve_model_id()
        content: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for path in image_paths:
            resolved = Path(path)
            if not resolved.is_file():
                raise FileNotFoundError(f"Vision bridge image not found: {resolved}")
            mime = "image/png" if resolved.suffix.lower() == ".png" else "image/jpeg"
            b64 = base64.b64encode(resolved.read_bytes()).decode()
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"},
                }
            )
        response = httpx.post(
            f"{self._base_url}/v1/chat/completions",
            json={
                "model": model_id,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
                "messages": [{"role": "user", "content": content}],
            },
            timeout=self._timeout,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise self._http_error(response) from exc
        body = response.json()
        try:
            text = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(
                f"Vision bridge returned unexpected payload: {body!r}"
            ) from exc
        return str(text).strip()

    def _http_error(self, response: httpx.Response) -> RuntimeError:
        body = (response.text or "")[:500]
        lowered = body.lower()
        if (
            response.status_code >= 500
            or "enginecore" in lowered
            or "enginedead" in lowered
            or "deepstack" in lowered
        ):
            return RuntimeError(
                "Vision bridge engine failed "
                f"(HTTP {response.status_code} at {self._base_url}). "
                "Qwen3-VL on vLLM 0.20.x can fatal on a deepstack buffer bug. "
                "Apply `bash scripts/patch_vllm_qwen3vl_deepstack.sh`, then "
                "`bash scripts/restart_required_services.sh` (or at least "
                "restart :8000). Detail: "
                f"{body}"
            )
        return RuntimeError(
            f"Vision bridge chat failed HTTP {response.status_code} at "
            f"{self._base_url}: {body}"
        )

    def _resolve_model_id(self) -> str:
        if self._model_id:
            return str(self._model_id)
        response = httpx.get(f"{self._base_url}/v1/models", timeout=min(30.0, self._timeout))
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Vision bridge /v1/models failed HTTP {response.status_code} at "
                f"{self._base_url}: {response.text[:500]}"
            ) from exc
        data = response.json().get("data") or []
        if not data:
            raise RuntimeError(f"No models listed at {self._base_url}/v1/models")
        model_id = str(data[0].get("id") or "").strip()
        if not model_id:
            raise RuntimeError(f"Empty model id in /v1/models response: {data[0]}")
        return model_id
