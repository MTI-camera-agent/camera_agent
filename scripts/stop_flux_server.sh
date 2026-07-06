#!/usr/bin/env bash
set -euo pipefail

PID_FILE="${PID_FILE:-/tmp/camera_agent_flux_vllm_omni.pid}"

if [[ ! -f "${PID_FILE}" ]]; then
  echo "vllm-omni server not running: missing ${PID_FILE}"
  exit 0
fi

PID="$(cat "${PID_FILE}")"
if kill -0 "${PID}" 2>/dev/null; then
  kill "${PID}"
  echo "stopped pid=${PID}"
else
  echo "vllm-omni server not running pid=${PID}"
fi
rm -f "${PID_FILE}"

