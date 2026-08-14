# Qwen2511 ComfyUI API workflow (vendored)

Copied from the mm-side skill `image-to-image_qwen2511` for CameraAgent HTTP
clients. **Do not** install packages into `mm-comfyui` from this repo.

- `workflow.api.json` — ComfyUI API prompt graph
- `schema.json` — parameter injection map (`image`, `prompt`, …)

Weights are resolved by the running ComfyUI instance (`extra_model_paths` /
`/mnt/ssd-models`), not by this directory.
