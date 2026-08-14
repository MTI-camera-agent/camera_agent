#!/usr/bin/env bash
# Stop ComfyUI. Prefer MirrorMe launcher; never pip-uninstall from mm-comfyui.
set -euo pipefail

MIRRORME_COMFYUI_SH="${MIRRORME_COMFYUI_SH:-/home/pathfinder/business/projects/MirrorMe/bin/comfyui.sh}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_comfyui.pid}"

if [[ -n "${COMFYUI_STOP_CMD:-}" ]]; then
  bash -lc "${COMFYUI_STOP_CMD}"
  exit 0
fi

if [[ -x "${MIRRORME_COMFYUI_SH}" ]]; then
  "${MIRRORME_COMFYUI_SH}" stop
  exit 0
fi

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}")"
  if kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}"
    echo "stopping pid=${PID}"
  fi
  rm -f "${PID_FILE}"
  exit 0
fi

echo "No ComfyUI stop method found (set MIRRORME_COMFYUI_SH or PID_FILE)."
exit 0
