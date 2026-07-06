from __future__ import annotations

import argparse
import base64
import time
from pathlib import Path

import httpx


DEFAULT_BASE_URL = "http://127.0.0.1:8010"
DEFAULT_PROMPT = "A cat holding a sign that says hello world"
DEFAULT_EDIT_PROMPT = (
    "Change the main subject's pose from standing to sitting while preserving "
    "identity, clothing, and background."
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Example client for a vLLM-Omni FLUX.2 server.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    subparsers = parser.add_subparsers(dest="command")

    generate = subparsers.add_parser("generate")
    generate.add_argument("--prompt", default=DEFAULT_PROMPT)
    generate.add_argument("--out", type=Path, default=Path("outputs/flux_vllm_omni/text_to_image.png"))
    generate.add_argument("--size", default="1024x1024")
    generate.add_argument("--guidance-scale", type=float, default=1.0)
    generate.add_argument("--num-inference-steps", type=int, default=4)
    generate.add_argument("--seed", type=int, default=0)

    edit = subparsers.add_parser("edit")
    edit.add_argument("--prompt", default=DEFAULT_EDIT_PROMPT)
    edit.add_argument("--image", type=Path, default=Path("test_img/stand_female_1.jpg"))
    edit.add_argument("--out", type=Path, default=Path("outputs/flux_vllm_omni/edit_auto.png"))
    edit.add_argument("--size", default="auto")
    edit.add_argument("--guidance-scale", type=float, default=1.0)
    edit.add_argument("--num-inference-steps", type=int, default=4)
    edit.add_argument("--seed", type=int, default=0)
    return parser


def save_response_image(response: httpx.Response, out: Path) -> None:
    response.raise_for_status()
    body = response.json()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(body["data"][0]["b64_json"]))


def generate_image(args: argparse.Namespace) -> None:
    payload = {
        "prompt": args.prompt,
        "size": args.size,
        "num_inference_steps": args.num_inference_steps,
        "guidance_scale": args.guidance_scale,
        "seed": args.seed,
        "response_format": "b64_json",
    }
    started = time.perf_counter()
    response = httpx.post(f"{args.base_url}/v1/images/generations", json=payload, timeout=None)
    elapsed = time.perf_counter() - started
    save_response_image(response, args.out)
    print(f"generated={args.out} latency_seconds={elapsed:.6f}")


def edit_image(args: argparse.Namespace) -> None:
    data = {
        "prompt": args.prompt,
        "size": args.size,
        "num_inference_steps": str(args.num_inference_steps),
        "guidance_scale": str(args.guidance_scale),
        "seed": str(args.seed),
        "response_format": "b64_json",
        "output_format": "png",
    }
    with args.image.open("rb") as handle:
        files = {"image": (args.image.name, handle, "image/jpeg")}
        started = time.perf_counter()
        response = httpx.post(f"{args.base_url}/v1/images/edits", data=data, files=files, timeout=None)
        elapsed = time.perf_counter() - started
    save_response_image(response, args.out)
    print(f"edited={args.out} latency_seconds={elapsed:.6f} response_size={response.json().get('size')}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "generate":
        generate_image(args)
        return
    if args.command == "edit":
        edit_image(args)
        return

    generate_args = argparse.Namespace(
        base_url=args.base_url,
        prompt=DEFAULT_PROMPT,
        out=Path("outputs/flux_vllm_omni/text_to_image.png"),
        size="1024x1024",
        guidance_scale=1.0,
        num_inference_steps=4,
        seed=0,
    )
    edit_args = argparse.Namespace(
        base_url=args.base_url,
        prompt=DEFAULT_EDIT_PROMPT,
        image=Path("test_img/stand_female_0.jpg"),
        out=Path("outputs/flux_vllm_omni/edit_auto.png"),
        size="auto",
        guidance_scale=1.0,
        num_inference_steps=4,
        seed=0,
    )
    generate_image(generate_args)
    edit_image(edit_args)


if __name__ == "__main__":
    main()
