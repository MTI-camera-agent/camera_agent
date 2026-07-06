#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://127.0.0.1:8010}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_flux_vllm_omni.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_flux_vllm_omni.log}"

echo "FLUX.2 vLLM-Omni server status"
echo "url=${BASE_URL}"

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}")"
  if kill -0 "${PID}" 2>/dev/null; then
    echo "process=running pid=${PID}"
  else
    echo "process=stale pid=${PID}"
  fi
else
  echo "process=unknown pid_file_missing=${PID_FILE}"
fi

HEALTH_BODY="$(mktemp)"
HTTP_CODE="$(curl -sS -o "${HEALTH_BODY}" -w "%{http_code}" "${BASE_URL}/health" 2>/tmp/camera_agent_flux_status.err || true)"
CONNECT_ERROR="$(cat /tmp/camera_agent_flux_status.err 2>/dev/null || true)"
BODY="$(cat "${HEALTH_BODY}" 2>/dev/null || true)"
rm -f "${HEALTH_BODY}" /tmp/camera_agent_flux_status.err

if [[ "${HTTP_CODE}" == "200" ]]; then
  echo "health=ready http_status=200"
else
  echo "health=not_ready http_status=${HTTP_CODE:-none}"
  if [[ -n "${CONNECT_ERROR}" ]]; then
    echo "curl_error=${CONNECT_ERROR}"
  fi
fi

if [[ -n "${BODY}" ]]; then
  echo "health_body=${BODY}"
fi

MODELS_CODE="$(curl -sS -o /tmp/camera_agent_flux_models.out -w "%{http_code}" "${BASE_URL}/v1/models" 2>/dev/null || true)"
if [[ "${MODELS_CODE}" == "200" ]]; then
  echo "models_endpoint=ready"
else
  echo "models_endpoint=not_ready http_status=${MODELS_CODE:-none}"
fi
rm -f /tmp/camera_agent_flux_models.out

if command -v nvidia-smi >/dev/null 2>&1; then
  GPU_MEMORY="$(
    nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader,nounits 2>/dev/null \
      | head -n 1 \
      | awk -F ',' '{gsub(/ /, "", $1); gsub(/ /, "", $2); print $1 "MiB/" $2 "MiB"}'
  )" || GPU_MEMORY=""
  echo "gpu_memory=${GPU_MEMORY:-unknown}"
fi

if [[ "${HTTP_CODE}" != "200" && -f "${LOG_FILE}" ]]; then
  echo "recent_log=${LOG_FILE} (may be from a previous server run)"
  tail -n 30 "${LOG_FILE}" || true
fi
