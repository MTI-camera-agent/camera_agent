#!/usr/bin/env bash
set -euo pipefail
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8188}"
BASE_URL="${BASE_URL:-http://${HOST}:${PORT}}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_comfyui.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_comfyui.log}"

echo "url=${BASE_URL}"
echo "pid_file=${PID_FILE}"
echo "log=${LOG_FILE}"
if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}")"
  if kill -0 "${PID}" 2>/dev/null; then
    echo "pid=${PID} running=yes"
  else
    echo "pid=${PID} running=no"
  fi
fi

CODE="$(curl -sS -o /tmp/camera_agent_comfy_stats.out -w "%{http_code}" "${BASE_URL}/system_stats" 2>/dev/null || true)"
echo "http_status=${CODE:-none}"
rm -f /tmp/camera_agent_comfy_stats.out

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null \
    | awk '{print "gpu_memory="$0}' || true
fi
echo "NOTE: do not modify conda env mm-comfyui from CameraAgent."
