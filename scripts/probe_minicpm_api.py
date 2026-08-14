#!/usr/bin/env python3
"""Probe MiniCPM OpenAI-compatible API (local default or public cold fallback)."""

from __future__ import annotations

import argparse
import os
import sys
from typing import Any

import httpx
import yaml

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_MODELS = (
    "MiniCPM-V-4.6",
    "MiniCPM-V-4.6-Instruct",
    "MiniCPM-V-4.6-Thinking",
)
PUBLIC_BASE_URL = "https://api.modelbest.co/v1"


def _mask_key(key: str) -> str:
    if len(key) <= 12:
        return "***"
    return f"{key[:8]}...{key[-4:]} (len={len(key)})"


def _load_eval_defaults() -> dict[str, Any]:
    path = os.path.join(REPO_ROOT, "config.yaml")
    try:
        raw = yaml.safe_load(open(path, encoding="utf-8")) or {}
    except OSError:
        return {}
    cfg = raw.get("structured_evaluation") or {}
    return cfg if isinstance(cfg, dict) else {}


def _error_summary(body: Any) -> str:
    if not isinstance(body, dict):
        return str(body)[:300]
    err = body.get("error")
    if isinstance(err, dict):
        return (
            f"type={err.get('type')!r} code={err.get('code')!r} "
            f"message={err.get('message')!r}"
        )
    return str(body)[:300]


def main() -> int:
    defaults = _load_eval_defaults()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default=str(defaults.get("base_url") or "http://127.0.0.1:8001/v1"),
        help=(
            "OpenAI-compatible base URL. Default reads config.yaml "
            f"(local :8001). Public cold fallback: {PUBLIC_BASE_URL}"
        ),
    )
    parser.add_argument(
        "--api-key-env",
        default=str(defaults.get("api_key_env") or "") or None,
        help=(
            "Env var holding API key. Omit for unauthenticated local serve. "
            "Public API typically needs MINICPM_API_KEY."
        ),
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=None,
        help="Model ids to probe (default: config model_id + known variants)",
    )
    args = parser.parse_args()

    base_url = str(args.base_url).rstrip("/")
    env_name = args.api_key_env
    api_key = ""
    if env_name:
        api_key = os.environ.get(str(env_name), "").strip()
        if not api_key:
            print(f"ERROR: {env_name} is not set", file=sys.stderr)
            print(
                "For local :8001, omit --api-key-env (config has no api_key_env). "
                "For public ModelBest API, export MINICPM_API_KEY.",
                file=sys.stderr,
            )
            return 1

    model_defaults = list(DEFAULT_MODELS)
    cfg_model = defaults.get("model_id")
    if cfg_model and str(cfg_model) not in model_defaults:
        model_defaults.insert(0, str(cfg_model))
    elif cfg_model:
        model_defaults = [str(cfg_model)] + [
            m for m in model_defaults if m != str(cfg_model)
        ]
    models = list(args.models) if args.models else model_defaults

    print(f"base_url={base_url}")
    if env_name and api_key:
        print(f"api_key_env={env_name} value={_mask_key(api_key)}")
    else:
        print("api_key=none (local / unauthenticated)")

    headers: dict[str, str] = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    models_url = f"{base_url}/models"
    listed_ids: list[str] = []
    try:
        response = httpx.get(models_url, headers=headers, timeout=30.0)
        print(f"GET {models_url} -> HTTP {response.status_code}")
        if response.status_code == 200:
            data = response.json().get("data") or []
            listed_ids = [
                str(item.get("id")) for item in data if isinstance(item, dict)
            ]
            print(f"listed_models={listed_ids[:20]}")
        else:
            print(f"body={_error_summary(response.json() if response.content else {})}")
    except Exception as exc:  # noqa: BLE001 - diagnostic tool
        print(f"GET {models_url} failed: {exc}")

    # Prefer probing ids actually advertised by the server.
    probe_models = listed_ids[:5] if listed_ids else models
    for mid in models:
        if mid not in probe_models:
            probe_models.append(mid)

    ok_models: list[str] = []
    for model_id in probe_models:
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "Reply with OK only."}],
            "max_tokens": 8,
            "temperature": 0,
        }
        try:
            response = httpx.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=60.0,
            )
        except Exception as exc:  # noqa: BLE001
            print(f"POST chat model={model_id!r} failed: {exc}")
            continue
        print(f"POST chat model={model_id!r} -> HTTP {response.status_code}")
        try:
            body = response.json()
        except Exception:  # noqa: BLE001
            print(f"  raw={response.text[:300]!r}")
            continue
        if response.status_code == 200:
            content = (
                ((body.get("choices") or [{}])[0].get("message") or {}).get("content")
            )
            print(f"  ok content_preview={str(content)[:80]!r}")
            ok_models.append(model_id)
        else:
            print(f"  {_error_summary(body)}")

    print()
    if ok_models:
        print(f"WORKING_MODELS={ok_models}")
        print(
            f"Set structured_evaluation.model_id to {ok_models[0]!r} in config.yaml "
            "if different from current default."
        )
        return 0

    print("No probed model succeeded.")
    if "modelbest.co" in base_url:
        print(
            "Public API note: trial keys often return lis_route_denied / empty "
            "models. Prefer local :8001 "
            "(bash scripts/start_minicpm_server.sh)."
        )
    else:
        print(
            "Local tip: bash scripts/status_minicpm_server.sh "
            "and confirm model_id from GET /v1/models."
        )
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
