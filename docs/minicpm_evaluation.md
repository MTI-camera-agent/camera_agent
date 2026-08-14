# MiniCPM-V-4.6 evaluation (Reflector)

Dual-image evaluation for the edit-loop Reflector uses **MiniCPM-V-4.6**, aligned with the MVP fine-tuning / coach role (compare original vs current / target frame).

## Current default (local `:8001`)

Configured in `config.yaml` → `structured_evaluation`:

| Field | Value |
|-------|--------|
| provider | `agno.openai_compatible` |
| model_id | `MiniCPM-V-4.6` (must match `transformers serve` FORCE_MODEL / basename) |
| base_url | `http://127.0.0.1:8001/v1` |
| api_key_env | *(omit)* — local serve is unauthenticated |

Weights: `assets/models/MiniCPM-V-4.6`. Runtime: conda `qwen3vl-fp8` + `transformers serve` (do **not** upgrade that env’s vLLM for Qwen).

```bash
# Part of the default three-service stack:
bash scripts/restart_required_services.sh

# Or MiniCPM alone:
bash scripts/start_minicpm_server.sh
# Missing fastapi/uvicorn once:
# INSTALL_SERVING=1 bash scripts/start_minicpm_server.sh

curl -s http://127.0.0.1:8001/v1/models | head
python scripts/probe_minicpm_api.py
```

If `/v1/models` or chat returns a different id than `MiniCPM-V-4.6`, set `structured_evaluation.model_id` to that exact string (transformers pins `force_model`).

**Do not trust `/v1/models` as “which model is loaded”.** `transformers serve` lists HuggingFace **cache** repos; with `force_model=MiniCPM-V-4.6` the pinned model may be absent from that list (you may see unrelated ids such as a cached Qwen variant). Chat must still send `model: MiniCPM-V-4.6`.

Planner stays on DeepSeek + local Qwen3-VL vision bridge (`structured_vision` `:8000`). Evaluation does **not** send dual images to Qwen.

**Qwen single-image bridge can still fatal vLLM 0.20.x** with a deepstack buffer bug (`Requested more deepstack tokens…` → `EngineDead`, `:8000` exits). CameraAgent applies a surgical local patch (upstream [vllm#40932](https://github.com/vllm-project/vllm/pull/40932) equivalent; **does not** upgrade the env’s vLLM):

```bash
bash scripts/patch_vllm_qwen3vl_deepstack.sh   # idempotent; also run from start_qwen3vl_server.sh
bash scripts/restart_required_services.sh      # required after EngineDead
```

Keep evaluation on MiniCPM `:8001`; do not route dual-image Reflector through Qwen.

## JSON output caveat (`response_format` ignored)

Agno `use_json_mode: true` sends OpenAI `response_format: json_object`. **Local `transformers serve` ignores that field** (log: `Ignoring unsupported fields in the request: {'response_format'}`).

Mitigations in this repo:

1. [`prompts/reflection.md`](../prompts/reflection.md) requires a **bare JSON object** matching `EvaluationReport`.
2. [`models/agno_structured_vision.py`](../models/agno_structured_vision.py) recovers an embedded `{...}` when the model wraps JSON in prose; otherwise raises a clear `RuntimeError` (not a vague `TypeError`).

If Evaluation fails with “non-JSON text”, check `/tmp/camera_agent_minicpm.log` and tighten the prompt; do not upgrade vLLM solely for this.

## Cold fallback: public ModelBest API

**Not the default.** A free-trial key was probed and failed (`listed_models=[]`, chat → `lis_route_denied`). Keep this path only if you obtain a key that can actually route MiniCPM-V-4.6.

Upstream reference: [OpenBMB MiniCPM-V `docs/api.md`](https://github.com/OpenBMB/MiniCPM-V/blob/main/docs/api.md).

```yaml
# config.yaml structured_evaluation (override local defaults)
provider: agno.openai_compatible
model_id: MiniCPM-V-4.6-Instruct   # or Thinking, if provisioned
base_url: https://api.modelbest.co/v1
api_key_env: MINICPM_API_KEY
```

```bash
export MINICPM_API_KEY="your-key"   # do not commit
python scripts/probe_minicpm_api.py --base-url https://api.modelbest.co/v1 --api-key-env MINICPM_API_KEY
```

### Troubleshooting public API: `lis_route_denied`

| Symptom | Meaning | Action |
|---------|---------|--------|
| HTTP 404, `type=lis_route_denied` | Key cannot route to the requested `model` | Use a provisioned key, or stay on local `:8001` |
| Instruct fails, Thinking works (or reverse) | Account only provisioned for one id | Set `model_id` to a `WORKING_MODELS` entry from the probe |
| Agno returns Chinese error string | Same routing failure bubbled as string content | Client raises `RuntimeError` with probe / local status guidance |

## Wiring

- [`app.py`](../app.py): Planner uses `structured_vision`; Reflector uses `structured_evaluation` (falls back to `structured_vision` if missing).
- [`models/agno_structured_vision.py`](../models/agno_structured_vision.py): `agno.openai_compatible` → Agno `OpenAILike` with native multi-image; JSON via prompt + parse fallback (`response_format` may be ignored by local serve) → Pydantic `EvaluationReport`. Local: no `api_key_env`.
- Ops: `scripts/start_minicpm_server.sh` / `stop_` / `status_`; included in `scripts/restart_required_services.sh`.
- Logs: HTTP details go to `outputs/logs/camera_agent.log` (console stays quiet; see `config.yaml` `logging`).
- Serve log: `/tmp/camera_agent_minicpm.log` (may show `Ignoring ... response_format` — expected).
