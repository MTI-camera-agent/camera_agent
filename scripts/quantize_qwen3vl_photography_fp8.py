#!/usr/bin/env python3
"""Offline BF16 -> FP8 (FP8_BLOCK) conversion for Qwen3-VL photography model.

Uses llm-compressor oneshot (data-free) to produce a compressed-tensors
checkpoint compatible with vLLM. Vision tower and lm_head stay high precision.

Environment: conda activate qwen3vl-fp8

Example:
  python scripts/quantize_qwen3vl_photography_fp8.py
  python scripts/quantize_qwen3vl_photography_fp8.py \\
    --model-dir assets/models/Qwen3-VL-8B-Photography_BF16 \\
    --output-dir assets/models/Qwen3-VL-8B-Photography_FP8 \\
    --gpu-memory-gib 20
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MODEL = REPO_ROOT / "assets/models/Qwen3-VL-8B-Photography_BF16"
DEFAULT_OUTPUT = REPO_ROOT / "assets/models/Qwen3-VL-8B-Photography_FP8"

# Extra processor / tokenizer files that processor.save_pretrained may miss.
EXTRA_ASSET_NAMES = (
    "chat_template.jinja",
    "generation_config.json",
    "preprocessor_config.json",
    "video_preprocessor_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "merges.txt",
    "vocab.json",
    "tokenizer.json",
    "tokenizer_config.json",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Quantize Qwen3-VL photography BF16 weights to FP8_BLOCK."
    )
    parser.add_argument(
        "--model-dir",
        type=Path,
        default=DEFAULT_MODEL,
        help="Path to BF16 HuggingFace checkpoint.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT,
        help="Destination for FP8 compressed-tensors checkpoint.",
    )
    parser.add_argument(
        "--gpu-memory-gib",
        type=float,
        default=20.0,
        help="Max GPU memory for device_map (RTX 5090 24GB: leave headroom).",
    )
    parser.add_argument(
        "--cpu-memory-gib",
        type=float,
        default=64.0,
        help="CPU offload budget when GPU is tight.",
    )
    parser.add_argument(
        "--scheme",
        default="FP8_BLOCK",
        choices=("FP8_BLOCK", "FP8_DYNAMIC"),
        help="llm-compressor quantization scheme (default: FP8_BLOCK).",
    )
    return parser.parse_args()


def copy_extra_assets(src: Path, dst: Path) -> None:
    for name in EXTRA_ASSET_NAMES:
        src_path = src / name
        dst_path = dst / name
        if src_path.is_file() and not dst_path.exists():
            shutil.copy2(src_path, dst_path)
            print(f"Copied extra asset: {name}")


def verify_quantization_config(output_dir: Path) -> None:
    import json

    config_path = output_dir / "config.json"
    if not config_path.is_file():
        raise FileNotFoundError(f"Missing config.json under {output_dir}")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    qcfg = config.get("quantization_config")
    if not qcfg:
        # compressed-tensors may nest under different keys depending on version
        raise RuntimeError(
            f"No quantization_config in {config_path}; conversion may have failed."
        )
    print(f"quantization_config keys: {sorted(qcfg.keys())}")
    print(f"quantization_config: {qcfg}")


def main() -> int:
    args = parse_args()
    model_dir = args.model_dir.resolve()
    output_dir = args.output_dir.resolve()

    if not model_dir.is_dir():
        print(f"ERROR: model dir not found: {model_dir}", file=sys.stderr)
        return 1

    print(f"Loading BF16 model from {model_dir}")
    print(f"Output FP8 dir: {output_dir}")
    print(
        f"device_map max_memory: GPU={args.gpu_memory_gib}GiB, "
        f"CPU={args.cpu_memory_gib}GiB, scheme={args.scheme}"
    )

    import torch
    from llmcompressor import oneshot
    from llmcompressor.modifiers.quantization import QuantizationModifier
    from transformers import AutoProcessor, Qwen3VLForConditionalGeneration

    max_memory = {
        0: f"{args.gpu_memory_gib}GiB",
        "cpu": f"{args.cpu_memory_gib}GiB",
    }

    model = Qwen3VLForConditionalGeneration.from_pretrained(
        str(model_dir),
        torch_dtype="auto",
        device_map="auto",
        max_memory=max_memory,
        low_cpu_mem_usage=True,
    )
    processor = AutoProcessor.from_pretrained(str(model_dir))

    recipe = QuantizationModifier(
        targets="Linear",
        scheme=args.scheme,
        ignore=[
            "re:.*lm_head",
            "re:visual.*",
            "re:model.visual.*",
        ],
    )

    print("Running data-free oneshot quantization...")
    oneshot(model=model, recipe=recipe)

    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"Saving quantized model to {output_dir}")
    model.save_pretrained(str(output_dir))
    processor.save_pretrained(str(output_dir))
    copy_extra_assets(model_dir, output_dir)
    verify_quantization_config(output_dir)

    # Free GPU before exit
    del model
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    print("Done.")
    print(f"FP8 checkpoint: {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
