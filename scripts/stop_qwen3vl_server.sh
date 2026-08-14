#!/usr/bin/env bash
set -euo pipefail
PID_FILE="${PID_FILE:-/tmp/camera_agent_qwen3vl_vllm.pid}"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "qwen3vl vLLM not running: missing ${PID_FILE}"
  exit 0
fi

PID="$(cat "${PID_FILE}")"
if kill -0 "${PID}" 2>/dev/null; then
  kill "${PID}"
  echo "stopping pid=${PID}"
  for _ in $(seq 1 30); do
    if ! kill -0 "${PID}" 2>/dev/null; then
      echo "stopped pid=${PID}"
      rm -f "${PID_FILE}"
      exit 0
    fi
    sleep 1
  done
  echo "still running after 30s pid=${PID}; send SIGKILL if needed"
else
  echo "not running pid=${PID}"
fi
rm -f "${PID_FILE}"
