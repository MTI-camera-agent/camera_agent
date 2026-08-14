#!/usr/bin/env python3
"""Batched VLM (vLLM HTTP) → instruction → ComfyUI Flux Klein 9B edit (0805 comparison).

Mirrors scripts/vlm_edit_qwen3vl_qwen2511_0805.py but edits with the Flux2-Klein-9B distilled
model instead of Qwen2511. Loads no transformers/diffusers in-process — it drives ComfyUI via
HTTP. The edit-client config is built inline (does not read or modify config.yaml).

Requires:
  - vLLM Qwen3-VL FP8_0805 on :8000:
      MODEL_PATH=$PWD/assets/models/Qwen3-VL-8B-Photography_FP8_0805 \
        bash scripts/start_qwen3vl_server.sh
  - ComfyUI on :8188 with these models already downloaded:
        flux-2-klein-9b-fp8.safetensors      (diffusion model)
        qwen_3_8b_fp8mixed.safetensors        (CLIP)
        full_encoder_small_decoder.safetensors (VAE)
    and the workflow assets/comfyui/workflows/image_flux2_klein_image_edit_9b_distilled_api.json
    (API-format export; injection points per assets/comfyui/flux9b/schema.json).
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.qwen3vl_photo import PHOTO_INSTRUCTION_PROMPT  # noqa: E402

DEFAULT_IMAGE_DIR = REPO_ROOT / "test_img"
DEFAULT_EDITED_DIR = REPO_ROOT / "outputs/reference_previews_flux9b"
DEFAULT_EXTENSIONS = "png,jpg,jpeg"
DEFAULT_VLM_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_COMFYUI_BASE_URL = "http://127.0.0.1:8188"
FLUX_WORKFLOW_PATH = REPO_ROOT / "assets/comfyui/workflows/image_flux2_klein_image_edit_9b_distilled_api.json"
FLUX_SCHEMA_PATH = REPO_ROOT / "assets/comfyui/flux9b/schema.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--edited-dir", type=Path, default=DEFAULT_EDITED_DIR)
    parser.add_argument(
        "--vlm-base-url",
        default=DEFAULT_VLM_BASE_URL,
        help="OpenAI-compatible vLLM base URL.",
    )
    parser.add_argument(
        "--vlm-model",
        default="",
        help="Model id from GET /v1/models. Empty = auto-detect first listed model.",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument(
        "--comfyui-base-url",
        default=DEFAULT_COMFYUI_BASE_URL,
        help="ComfyUI base URL (Flux2-Klein workflow).",
    )
    parser.add_argument(
        "--instruction-only",
        action="store_true",
        help="Only request/print VLM instructions; skip ComfyUI edit.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Process only the first N images (smoke test).",
    )
    parser.add_argument(
        "--extensions",
        default=DEFAULT_EXTENSIONS,
        help=f"Comma-separated image extensions to include (default: {DEFAULT_EXTENSIONS}).",
    )
    return parser.parse_args()


def resolve_vlm_model(vlm_base_url: str, model: str) -> str:
    """Use explicit model id, or fetch the first id from /v1/models."""
    if model.strip():
        return model.strip()
    response = httpx.get(f"{vlm_base_url.rstrip('/')}/v1/models", timeout=30.0)
    response.raise_for_status()
    data = response.json().get("data") or []
    if not data:
        raise RuntimeError(f"No models listed at {vlm_base_url}/v1/models")
    model_id = str(data[0].get("id") or "").strip()
    if not model_id:
        raise RuntimeError(f"Empty model id in /v1/models response: {data[0]}")
    return model_id


def request_instruction(
    *,
    image_path: Path,
    vlm_base_url: str,
    model_id: str,
    max_tokens: int,
) -> str:
    # Mirrors scripts/vlm_edit_qwen3vl_qwen2511_0805.py — image-first order for SFT alignment.
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    response = httpx.post(
        f"{vlm_base_url.rstrip('/')}/v1/chat/completions",
        json={
            "model": model_id,
            "temperature": 0,
            "max_tokens": max_tokens,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{b64}"},
                        },
                        {"type": "text", "text": PHOTO_INSTRUCTION_PROMPT},
                    ],
                }
            ],
        },
        timeout=180.0,
    )
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        detail = response.text[:500]
        raise RuntimeError(
            f"VLM chat failed HTTP {response.status_code}. "
            f"Check model id matches GET {vlm_base_url}/v1/models. Detail: {detail}"
        ) from exc
    body = response.json()
    return str(body["choices"][0]["message"]["content"]).strip()


def load_flux_client(comfyui_base_url: str):
    from models.factory import build_image_generator

    image_cfg = {
        "provider": "comfyui",
        "base_url": comfyui_base_url,
        "workflow_api_path": str(FLUX_WORKFLOW_PATH),
        "schema_path": str(FLUX_SCHEMA_PATH),
        "timeout_seconds": 600,
        "poll_interval_seconds": 1.0,
    }
    return build_image_generator(image_cfg)


def iter_images(image_dir: Path, extensions: str, limit: int | None) -> list[Path]:
    exts = {f".{e.strip().lower().lstrip('.')}" for e in extensions.split(",") if e.strip()}
    images = sorted(
        p
        for p in image_dir.iterdir()
        if p.is_file() and p.suffix.lower() in exts
    )
    if limit is not None:
        images = images[:limit]
    return images


def main() -> int:
    args = parse_args()
    image_dir = args.image_dir.resolve()
    if not image_dir.is_dir():
        print(f"ERROR: image dir not found: {image_dir}", file=sys.stderr)
        return 1

    images = iter_images(image_dir, args.extensions, args.limit)
    if not images:
        print(
            f"ERROR: no images (ext={args.extensions}) found in {image_dir}",
            file=sys.stderr,
        )
        return 1

    print(f"Image dir: {image_dir} ({len(images)} image(s))")
    print(f"Requesting instructions from VLM at {args.vlm_base_url} ...")
    model_id = resolve_vlm_model(args.vlm_base_url, args.vlm_model)
    print(f"Using VLM model id: {model_id}")

    edit_client = None
    if not args.instruction_only:
        print(f"Loading Flux9B ComfyUI edit client ({args.comfyui_base_url}) ...")
        edit_client = load_flux_client(args.comfyui_base_url)

    edited_dir = args.edited_dir.resolve()
    edited_dir.mkdir(parents=True, exist_ok=True)

    successes: list[str] = []
    failures: list[tuple[str, str]] = []
    for idx, image_path in enumerate(images, start=1):
        tag = f"[{idx}/{len(images)}] {image_path.name}"
        try:
            instruction = request_instruction(
                image_path=image_path,
                vlm_base_url=args.vlm_base_url,
                model_id=model_id,
                max_tokens=args.max_tokens,
            )
            print(f"{tag}\n  instruction: {instruction}")

            if args.instruction_only:
                successes.append(image_path.name)
                continue

            output_path = edited_dir / f"{image_path.stem}_reference_preview.png"
            edit_client.edit(
                image_path=image_path,
                prompt=instruction,
                output_path=output_path,
            )
            meta = {
                "source_image": str(image_path),
                "instruction": instruction,
                "output": str(output_path),
                "generator": "flux2-klein-9b",
            }
            (output_path.with_name(output_path.stem + "_meta.json")).write_text(
                json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"  saved: {output_path}")
            successes.append(image_path.name)
        except Exception as exc:  # noqa: BLE001 - keep the batch alive per-image
            failures.append((image_path.name, str(exc)))
            print(f"{tag}\n  FAILED: {exc}", file=sys.stderr)

    print(
        f"\nDone. success={len(successes)} failed={len(failures)} "
        f"edited_dir={edited_dir if not args.instruction_only else '-'}"
    )
    for name, err in failures:
        print(f"  FAILED {name}: {err}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
