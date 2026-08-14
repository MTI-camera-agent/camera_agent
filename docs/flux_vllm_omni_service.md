# FLUX.2 Local Service With vLLM-Omni (cold fallback)

> **Role in CameraAgent:** cold **fallback** for `reference_preview` when ComfyUI
> (`:8188`, Qwen2511) is unavailable. **Do not start this service by default.**
> Default image stack is ComfyUI; see [development_workflow.md](development_workflow.md) §3.5
> and [01-MVP期-方案设计及计划.md](01-MVP期-方案设计及计划.md).

This repository can serve a local FLUX.2 checkpoint with vLLM-Omni. The server
keeps the model loaded and exposes OpenAI-compatible image endpoints on `:8010`.

Default comparison parameters used by the example client:

- `guidance_scale=1.0`
- `num_inference_steps=4`
- `seed=0`
- text-to-image size: `1024x1024`
- image edit size: `auto`, preserving the input image aspect ratio

## Start

```bash
MODEL_PATH=/home/liujinyuan/DATA/models/FLUX.2-klein-4B \
  scripts/start_flux_server.sh
```

`start_flux_server.sh` starts the process, then polls `/health` until the API is
ready. The default readiness timeout is 180 seconds. Override it if needed:

```bash
READY_TIMEOUT_SECONDS=300 \
MODEL_PATH=/home/liujinyuan/DATA/models/FLUX.2-klein-4B \
  scripts/start_flux_server.sh
```

Foreground equivalent:

```bash
VLLM_TARGET_DEVICE=cuda vllm-omni serve /home/liujinyuan/DATA/models/FLUX.2-klein-4B \
  --omni \
  --host 127.0.0.1 \
  --port 8010 \
  --dtype bfloat16 \
  --performance-mode interactivity \
  --max-num-seqs 1 \
  --disable-log-stats
```

## Status And Stop

```bash
scripts/status_flux_server.sh
scripts/stop_flux_server.sh
```

`status_flux_server.sh` reports process state, HTTP health status, `/v1/models`
availability, GPU memory, and recent log lines when the API is not ready.

## Generate And Edit Images

Run both example requests:

```bash
python scripts/flux_vllm_omni_example.py
```

Text-to-image only:

```bash
python scripts/flux_vllm_omni_example.py generate \
  --prompt "A cat holding a sign that says hello world" \
  --out outputs/flux_vllm_omni/text_to_image.png
```

Image editing:

```bash
python scripts/flux_vllm_omni_example.py edit \
  --prompt "Change the main subject's pose from standing to sitting while preserving identity, clothing, and background." \
  --image test_img/stand_female_0.jpg \
  --out outputs/flux_vllm_omni/edit_auto.png
```

The edit request sends `size=auto` to vLLM-Omni. This uses the input image size
as the requested output size and lets FLUX round to valid model dimensions.

## Measured Results

Observed on this RTX 3090 with vLLM-Omni, CUDA, bfloat16,
`--performance-mode interactivity`, and `--max-num-seqs 1`:

- Startup to ready server: about 27 seconds.
- Model runner load: 8.74 seconds.
- Model memory: about 14.9 GiB reported by vLLM-Omni.
- Warm text-to-image latency: 2.9 seconds at 1024x1024.
- Image edit latency with `size=auto`: 3.6 seconds.
- vLLM-Omni selected FlashAttention and compiled the transformer with `torch.compile`.
