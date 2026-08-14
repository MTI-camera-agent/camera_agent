#!/usr/bin/env python3
"""ComfyUI HTTP client for image edit (Qwen2511 workflow.api.json + schema)."""

from __future__ import annotations

import copy
import json
import time
import uuid
from pathlib import Path
from typing import Any

import httpx


class ComfyUIImageEditClient:
    """ImageGenerationClient backed by ComfyUI prompt / upload / history APIs.

    Primary CameraAgent path for Qwen-Image-Edit-2511. Text-only ``generate``
    is not supported by the default Qwen2511 i2i workflow.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        base_url = config.get("base_url")
        if not base_url:
            raise ValueError("ComfyUI image config requires base_url")
        self._base_url = str(base_url).rstrip("/")
        timeout = config.get("timeout_seconds", 600)
        self._timeout = float(timeout) if timeout is not None else 600.0
        self._poll_interval = float(config.get("poll_interval_seconds", 1.0))
        workflow_path = config.get("workflow_api_path")
        schema_path = config.get("schema_path")
        if not workflow_path or not schema_path:
            raise ValueError(
                "ComfyUI image config requires workflow_api_path and schema_path"
            )
        self._workflow_path = _resolve_repo_path(Path(str(workflow_path)))
        self._schema_path = _resolve_repo_path(Path(str(schema_path)))
        if not self._workflow_path.is_file():
            raise FileNotFoundError(f"workflow_api_path not found: {self._workflow_path}")
        if not self._schema_path.is_file():
            raise FileNotFoundError(f"schema_path not found: {self._schema_path}")
        self._workflow_template = json.loads(
            self._workflow_path.read_text(encoding="utf-8")
        )
        self._schema = json.loads(self._schema_path.read_text(encoding="utf-8"))
        self._client_id = str(config.get("client_id") or uuid.uuid4())

    def generate(self, *, prompt: str, output_path: Path, size: str = "1024x1024") -> Path:
        raise RuntimeError(
            "ComfyUI Qwen2511 provider is image-edit only; call edit() with an input frame. "
            f"(generate requested size={size!r}, prompt_len={len(prompt)})"
        )

    def edit(
        self,
        *,
        image_path: Path,
        prompt: str,
        output_path: Path,
        size: str = "auto",
    ) -> Path:
        del size  # workflow controls geometry
        if not image_path.is_file():
            raise FileNotFoundError(f"Input image not found: {image_path}")
        started = time.perf_counter()
        uploaded_name = self._upload_image(image_path)
        workflow = self._inject_params(uploaded_name=uploaded_name, prompt=prompt)
        prompt_id = self._queue_prompt(workflow)
        images = self._wait_for_images(prompt_id)
        if not images:
            raise RuntimeError(f"ComfyUI prompt {prompt_id} finished with no images")
        first = images[0]
        data = self._download_image(
            filename=first["filename"],
            subfolder=first.get("subfolder") or "",
            folder_type=first.get("type") or "output",
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(data)
        elapsed = time.perf_counter() - started
        sidecar = output_path.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {
                    "latency_seconds": elapsed,
                    "prompt_id": prompt_id,
                    "comfy_filename": first.get("filename"),
                    "provider": "comfyui",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return output_path

    def healthcheck(self) -> bool:
        try:
            response = httpx.get(f"{self._base_url}/system_stats", timeout=5.0)
        except httpx.HTTPError:
            return False
        return response.status_code == 200

    def _upload_image(self, image_path: Path) -> str:
        mime = _guess_mime_type(image_path)
        with image_path.open("rb") as handle:
            response = httpx.post(
                f"{self._base_url}/upload/image",
                files={"image": (image_path.name, handle, mime)},
                timeout=min(60.0, self._timeout),
            )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"ComfyUI upload failed HTTP {response.status_code}: {response.text[:500]}"
            ) from exc
        body = response.json()
        name = body.get("name") or image_path.name
        subfolder = body.get("subfolder") or ""
        return f"{subfolder}/{name}" if subfolder else str(name)

    def _inject_params(self, *, uploaded_name: str, prompt: str) -> dict[str, Any]:
        workflow = copy.deepcopy(self._workflow_template)
        parameters = self._schema.get("parameters") or {}
        values = {"image": uploaded_name, "prompt": prompt}
        for key, value in values.items():
            spec = parameters.get(key)
            if not spec:
                continue
            node_id = str(spec["node_id"])
            field = str(spec["field"])
            node = workflow.get(node_id)
            if not isinstance(node, dict):
                raise KeyError(f"Workflow missing node_id {node_id!r} for param {key!r}")
            inputs = node.setdefault("inputs", {})
            inputs[field] = value
        # Keep TextEncode nodes that take prompt in sync when present
        for node in workflow.values():
            if not isinstance(node, dict):
                continue
            if node.get("class_type") != "TextEncodeQwenImageEditPlus":
                continue
            inputs = node.get("inputs") or {}
            if "prompt" in inputs and inputs.get("prompt") not in (None, ""):
                # Only overwrite empty or placeholder positive prompts that mirror schema default path
                pass
        # Explicitly set node 435 prompt via schema; also push into encode nodes that use empty prompt
        # linked from PrimitiveString — already wired in graph. Done.
        return workflow

    def _queue_prompt(self, workflow: dict[str, Any]) -> str:
        response = httpx.post(
            f"{self._base_url}/prompt",
            json={"prompt": workflow, "client_id": self._client_id},
            timeout=min(60.0, self._timeout),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"ComfyUI /prompt failed HTTP {response.status_code}: {response.text[:800]}"
            ) from exc
        body = response.json()
        prompt_id = body.get("prompt_id")
        if not prompt_id:
            raise RuntimeError(f"ComfyUI /prompt missing prompt_id: {body}")
        return str(prompt_id)

    def _wait_for_images(self, prompt_id: str) -> list[dict[str, Any]]:
        deadline = time.perf_counter() + self._timeout
        while time.perf_counter() < deadline:
            response = httpx.get(
                f"{self._base_url}/history/{prompt_id}",
                timeout=min(30.0, self._timeout),
            )
            if response.status_code == 200:
                history = response.json()
                entry = history.get(prompt_id) if isinstance(history, dict) else None
                if entry:
                    status = entry.get("status") or {}
                    if status.get("status_str") == "error" or status.get("completed") is False:
                        messages = status.get("messages") or []
                        raise RuntimeError(f"ComfyUI job error for {prompt_id}: {messages}")
                    outputs = entry.get("outputs") or {}
                    images = _collect_images(outputs)
                    if images:
                        return images
                    if status.get("completed"):
                        return []
            time.sleep(self._poll_interval)
        raise TimeoutError(
            f"Timed out waiting for ComfyUI prompt_id={prompt_id} after {self._timeout}s"
        )

    def _download_image(self, *, filename: str, subfolder: str, folder_type: str) -> bytes:
        response = httpx.get(
            f"{self._base_url}/view",
            params={"filename": filename, "subfolder": subfolder, "type": folder_type},
            timeout=min(120.0, self._timeout),
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"ComfyUI /view failed HTTP {response.status_code}: {response.text[:300]}"
            ) from exc
        return response.content


def _collect_images(outputs: dict[str, Any]) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for node_output in outputs.values():
        if not isinstance(node_output, dict):
            continue
        for item in node_output.get("images") or []:
            if isinstance(item, dict) and item.get("filename"):
                collected.append(item)
    return collected


def _resolve_repo_path(path: Path) -> Path:
    if path.is_absolute():
        return path
    cwd_candidate = (Path.cwd() / path).resolve()
    if cwd_candidate.is_file():
        return cwd_candidate
    repo_root = Path(__file__).resolve().parents[1]
    return (repo_root / path).resolve()


def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    raise ValueError(f"Unsupported image type: {path}")
