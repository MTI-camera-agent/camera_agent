#!/usr/bin/env bash
set -euo pipefail

MODEL_PATH="${MODEL_PATH:?Set MODEL_PATH to the local model directory. Example: /home/liujinyuan/DATA/models/FLUX.2-klein-4B}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8010}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_flux_vllm_omni.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_flux_vllm_omni.log}"
EXTRA_ARGS="${EXTRA_ARGS:-}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-180}"
READY_INTERVAL_SECONDS="${READY_INTERVAL_SECONDS:-3}"
BASE_URL="http://${HOST}:${PORT}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  PID="$(cat "${PID_FILE}")"
  echo "vLLM-Omni FLUX.2 server process is already running."
  echo "pid=${PID}"
  echo "url=${BASE_URL}"
  echo "log=${LOG_FILE}"
  BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" "${SCRIPT_DIR}/status_flux_server.sh"
  exit 0
fi

EXISTING_HTTP_CODE="$(curl -sS -o /tmp/camera_agent_flux_existing_health.out -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null || true)"
rm -f /tmp/camera_agent_flux_existing_health.out
if [[ "${EXISTING_HTTP_CODE}" == "200" ]]; then
  echo "A FLUX.2 API is already ready at ${BASE_URL}, but no live PID file was found."
  echo "pid_file=${PID_FILE}"
  BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" "${SCRIPT_DIR}/status_flux_server.sh"
  exit 0
fi

if [[ -f "${PID_FILE}" ]]; then
  echo "Removing stale PID file: ${PID_FILE}"
  rm -f "${PID_FILE}"
fi

rm -f "${LOG_FILE}"
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
PID="$(cat "${PID_FILE}")"
echo "Started vLLM-Omni FLUX.2 server process."
echo "pid=${PID}"
echo "url=${BASE_URL}"
echo "log=${LOG_FILE}"
echo "Waiting for API readiness for up to ${READY_TIMEOUT_SECONDS}s..."

STARTED_AT="$(date +%s)"
while true; do
  if ! kill -0 "${PID}" 2>/dev/null; then
    echo "Server process exited before becoming ready."
    echo "Recent log lines:"
    tail -n 80 "${LOG_FILE}" 2>/dev/null || true
    rm -f "${PID_FILE}"
    exit 1
  fi

  HTTP_CODE="$(curl -sS -o /tmp/camera_agent_flux_health.out -w "%{http_code}" "${BASE_URL}/health" 2>/dev/null || true)"
  rm -f /tmp/camera_agent_flux_health.out
  if [[ "${HTTP_CODE}" == "200" ]]; then
    ELAPSED="$(( $(date +%s) - STARTED_AT ))"
    echo "Server is ready. elapsed_seconds=${ELAPSED}"
    BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" "${SCRIPT_DIR}/status_flux_server.sh"
    exit 0
  fi

  ELAPSED="$(( $(date +%s) - STARTED_AT ))"
  if (( ELAPSED >= READY_TIMEOUT_SECONDS )); then
    echo "Timed out waiting for server readiness. elapsed_seconds=${ELAPSED} last_http_status=${HTTP_CODE:-none}"
    echo "Recent log lines:"
    tail -n 80 "${LOG_FILE}" 2>/dev/null || true
    exit 1
  fi

  echo "not_ready elapsed_seconds=${ELAPSED} http_status=${HTTP_CODE:-none}"
  sleep "${READY_INTERVAL_SECONDS}"
done
