#!/usr/bin/env python3
"""Smoke-test Qwen3-VL photography VLM via vLLM OpenAI API."""

from __future__ import annotations

import base64
import sys
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from skills.qwen3vl_photo import PHOTO_INSTRUCTION_PROMPT  # noqa: E402

BASE_URL = "http://127.0.0.1:8000"
IMG = REPO_ROOT / "test_img" / "01-input_frame.png"
PROMPT = PHOTO_INSTRUCTION_PROMPT


def main() -> int:
    models = httpx.get(f"{BASE_URL}/v1/models", timeout=30.0)
    models.raise_for_status()
    data = models.json().get("data") or []
    if not data:
        print("ERROR: no models at /v1/models", file=sys.stderr)
        return 1
    model_id = str(data[0]["id"])
    print(f"Using model id: {model_id}")

    b64 = base64.b64encode(open(IMG, "rb").read()).decode()
    response = httpx.post(
        f"{BASE_URL}/v1/chat/completions",
        json={
            "model": model_id,
            "temperature": 0,
            "max_tokens": 512,
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/png;base64,{b64}"},
                        },
                        {"type": "text", "text": PROMPT},
                    ],
                }
            ],
        },
        timeout=180.0,
    )
    response.raise_for_status()
    print(response.json()["choices"][0]["message"]["content"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
