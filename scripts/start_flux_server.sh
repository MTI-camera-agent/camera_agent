#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:?Set MODEL_PATH to the local model directory. Example: /home/liujinyuan/DATA/models/FLUX.2-klein-4B}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8010}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_flux_vllm_omni.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_flux_vllm_omni.log}"
EXTRA_ARGS="${EXTRA_ARGS:-}"

if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  echo "vllm-omni server already running pid=$(cat "${PID_FILE}")"
  exit 0
fi

VLLM_TARGET_DEVICE=cuda nohup vllm-omni serve "${MODEL_PATH}" \
  --omni \
  --host "${HOST}" \
  --port "${PORT}" \
  --dtype bfloat16 \
  --performance-mode interactivity \
  --max-num-seqs 1 \
  --disable-log-stats \
  ${EXTRA_ARGS} >"${LOG_FILE}" 2>&1 &

echo "$!" >"${PID_FILE}"
echo "started pid=$(cat "${PID_FILE}") url=http://${HOST}:${PORT} log=${LOG_FILE}"

