#!/usr/bin/env bash
set -euo pipefail
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
BASE_URL="${BASE_URL:-http://${HOST}:${PORT}}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_qwen3vl_vllm.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_qwen3vl_vllm.log}"

echo "url=${BASE_URL}"
echo "pid_file=${PID_FILE}"
echo "log=${LOG_FILE}"
if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}")"
  if kill -0 "${PID}" 2>/dev/null; then
    echo "pid=${PID} running=yes"
  else
    echo "pid=${PID} running=no (stale pid file)"
  fi
else
  echo "pid=none"
fi

CODE="$(curl -sS -o /tmp/camera_agent_qwen3vl_models.out -w "%{http_code}" "${BASE_URL}/v1/models" 2>/dev/null || true)"
echo "http_status=${CODE:-none}"
if [[ "${CODE}" == "200" ]]; then
  head -c 400 /tmp/camera_agent_qwen3vl_models.out 2>/dev/null || true
  echo
fi
rm -f /tmp/camera_agent_qwen3vl_models.out

if command -v nvidia-smi >/dev/null 2>&1; then
  nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader 2>/dev/null \
    | awk '{print "gpu_memory="$0}' || true
fi
