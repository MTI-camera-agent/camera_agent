#!/usr/bin/env python3
"""Batched VLM (vLLM HTTP) → instruction → ComfyUI Qwen2511 edit for the 0805 model.

Same single-GPU-friendly pipeline as scripts/vlm_edit_qwen3vl_qwen2511.py, but iterates
over a directory of source images instead of one. Reuses the SFT-aligned
PHOTO_INSTRUCTION_PROMPT and the ComfyUI Qwen2511 image-edit client; it loads no
transformers VLM or diffusers in-process.

The 0805 refresh is served as FP8 by vLLM — same Qwen3-VL + deepstack architecture as
the prior model, so no vLLM-side changes beyond pointing MODEL_PATH at the new checkpoint.

Requires:
  - vLLM Qwen3-VL FP8_0805 on :8000:
      MODEL_PATH=$PWD/assets/models/Qwen3-VL-8B-Photography_FP8_0805 \
        bash scripts/start_qwen3vl_server.sh
  - ComfyUI on :8188 (scripts/start_comfyui_server.sh), unless --instruction-only
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
from pathlib import Path

import httpx
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.qwen3vl_photo import PHOTO_INSTRUCTION_PROMPT  # noqa: E402

DEFAULT_IMAGE_DIR = REPO_ROOT / "test_img"
DEFAULT_EDITED_DIR = REPO_ROOT / "outputs/reference_previews_0805"
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"
DEFAULT_EXTENSIONS = "png,jpg,jpeg"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image-dir", type=Path, default=DEFAULT_IMAGE_DIR)
    parser.add_argument("--edited-dir", type=Path, default=DEFAULT_EDITED_DIR)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument(
        "--vlm-base-url",
        default="http://127.0.0.1:8000",
        help="OpenAI-compatible vLLM base URL",
    )
    parser.add_argument(
        "--vlm-model",
        default="",
        help="Model id from GET /v1/models. Empty = auto-detect first listed model.",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
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
    b64 = base64.b64encode(image_path.read_bytes()).decode()
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    response = httpx.post(
        f"{vlm_base_url.rstrip('/')}/v1/chat/completions",
        json={
            "model": model_id,
            "temperature": 0,
            "max_tokens": max_tokens,
            # Image-first content order matches the Photography SFT chat format.
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


def load_image_client(config_path: Path):
    from models.factory import build_image_generator

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    image_cfg = raw["image_generator"]
    # Resolve relative workflow paths against repo root
    for key in ("workflow_api_path", "schema_path"):
        if key in image_cfg and image_cfg[key] and not Path(image_cfg[key]).is_absolute():
            image_cfg[key] = str(REPO_ROOT / image_cfg[key])
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
        print(f"Loading ComfyUI edit client via config {args.config} ...")
        edit_client = load_image_client(args.config.resolve())

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
