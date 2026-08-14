#!/usr/bin/env python3
"""VLM (vLLM HTTP) → instruction → ComfyUI Qwen2511 → reference preview.

Does NOT load transformers VLM or diffusers in-process (single-GPU friendly).
Requires:
  - vLLM Qwen3-VL on :8000 (scripts/start_qwen3vl_server.sh)
  - ComfyUI on :8188 (scripts/start_comfyui_server.sh)

On 24GB, run serially: generate instruction, optionally stop VLM, then edit.
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

DEFAULT_IMAGE = REPO_ROOT / "test_img/input_frame.png"
DEFAULT_EDITED_DIR = REPO_ROOT / "outputs/reference_previews"
DEFAULT_CONFIG = REPO_ROOT / "config.yaml"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, default=DEFAULT_IMAGE)
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
    parser.add_argument("--instruction-only", action="store_true")
    parser.add_argument(
        "--instruction",
        default="",
        help="Skip VLM and use this instruction for ComfyUI edit",
    )
    parser.add_argument("--max-tokens", type=int, default=512)
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
    model: str,
    max_tokens: int,
) -> str:
    model_id = resolve_vlm_model(vlm_base_url, model)
    print(f"Using VLM model id: {model_id}")
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


def load_image_client(config_path: Path):
    from models.factory import build_image_generator

    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    image_cfg = raw["image_generator"]
    # Resolve relative workflow paths against repo root
    for key in ("workflow_api_path", "schema_path"):
        if key in image_cfg and image_cfg[key] and not Path(image_cfg[key]).is_absolute():
            image_cfg[key] = str(REPO_ROOT / image_cfg[key])
    return build_image_generator(image_cfg)


def main() -> int:
    args = parse_args()
    image_path = args.image.resolve()
    if not image_path.is_file():
        print(f"ERROR: image not found: {image_path}", file=sys.stderr)
        return 1

    if args.instruction:
        instruction = args.instruction.strip()
    else:
        print(f"Requesting instruction from VLM at {args.vlm_base_url} ...")
        instruction = request_instruction(
            image_path=image_path,
            vlm_base_url=args.vlm_base_url,
            model=args.vlm_model,
            max_tokens=args.max_tokens,
        )
    print("instruction:")
    print(instruction)

    if args.instruction_only:
        return 0

    edited_dir = args.edited_dir.resolve()
    edited_dir.mkdir(parents=True, exist_ok=True)
    output_path = edited_dir / f"{image_path.stem}_reference_preview.png"

    print(f"Running ComfyUI edit via config {args.config} ...")
    client = load_image_client(args.config.resolve())
    client.edit(image_path=image_path, prompt=instruction, output_path=output_path)
    meta = {
        "source_image": str(image_path),
        "instruction": instruction,
        "output": str(output_path),
    }
    (output_path.with_name(output_path.stem + "_meta.json")).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"saved: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
