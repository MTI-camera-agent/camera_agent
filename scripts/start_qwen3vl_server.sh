#!/usr/bin/env bash
# Start Qwen3-VL FP8 via vLLM (default service #1).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODEL_PATH="${MODEL_PATH:-${REPO_ROOT}/assets/models/Qwen3-VL-8B-Photography_FP8_0805}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8000}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_qwen3vl_vllm.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_qwen3vl_vllm.log}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-300}"
READY_INTERVAL_SECONDS="${READY_INTERVAL_SECONDS:-3}"
PROGRESS_EVERY_SECONDS="${PROGRESS_EVERY_SECONDS:-15}"
VERBOSE="${VERBOSE:-0}"
GPU_MEMORY_UTILIZATION="${GPU_MEMORY_UTILIZATION:-0.85}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-8192}"
# Stable OpenAI model id (avoid absolute-path ids that break clients).
# Default derives from the served MODEL_PATH basename (e.g. Qwen3-VL-8B-Photography_FP8_0805)
# so /v1/models honestly reports which checkpoint is loaded.
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-$(basename "${MODEL_PATH}")}"
BASE_URL="http://${HOST}:${PORT}"
CONDA_ENV="${CONDA_ENV:-qwen3vl-fp8}"

progress() {
  # Always append wait progress to service log; terminal only when VERBOSE or milestone.
  local msg="$1"
  printf '%s\n' "${msg}" >>"${LOG_FILE}" 2>/dev/null || true
  if [[ "${VERBOSE}" == "1" ]]; then
    echo "${msg}"
  fi
}

if [[ ! -d "${MODEL_PATH}" ]]; then
  echo "ERROR: model path not found: ${MODEL_PATH}"
  exit 1
fi

if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  echo "Qwen3-VL vLLM already running pid=$(cat "${PID_FILE}") url=${BASE_URL}"
  BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" \
    "${SCRIPT_DIR}/status_qwen3vl_server.sh"
  exit 0
fi

EXISTING="$(curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/models" 2>/dev/null || true)"
if [[ "${EXISTING}" == "200" ]]; then
  echo "API already ready at ${BASE_URL} (no live PID file)."
  exit 0
fi

rm -f "${PID_FILE}" "${LOG_FILE}"

# Prefer conda env without mutating packages.
if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "${CONDA_ENV}"
fi

if ! command -v vllm >/dev/null 2>&1; then
  echo "ERROR: vllm not on PATH. Activate ${CONDA_ENV} first."
  exit 1
fi

# Surgical hotfix for Qwen3-VL deepstack EngineDead (vLLM 0.20.x); does not upgrade vLLM.
echo "Applying Qwen3-VL deepstack patch (idempotent) ..."
bash "${SCRIPT_DIR}/patch_vllm_qwen3vl_deepstack.sh"

echo "Starting vLLM Qwen3-VL from ${MODEL_PATH}"
nohup vllm serve "${MODEL_PATH}" \
  --host "${HOST}" \
  --port "${PORT}" \
  --served-model-name "${SERVED_MODEL_NAME}" \
  --trust-remote-code \
  --dtype auto \
  --max-model-len "${MAX_MODEL_LEN}" \
  --gpu-memory-utilization "${GPU_MEMORY_UTILIZATION}" \
  --limit-mm-per-prompt.image 4 \
  >"${LOG_FILE}" 2>&1 &

echo "$!" >"${PID_FILE}"
PID="$(cat "${PID_FILE}")"
echo "pid=${PID} url=${BASE_URL} log=${LOG_FILE}"
echo "Waiting for readiness (up to ${READY_TIMEOUT_SECONDS}s; VERBOSE=1 for per-tick logs)..."

STARTED_AT="$(date +%s)"
LAST_PROGRESS_AT=0
while true; do
  if ! kill -0 "${PID}" 2>/dev/null; then
    echo "Process exited before ready. Recent log:"
    tail -n 80 "${LOG_FILE}" || true
    rm -f "${PID_FILE}"
    exit 1
  fi
  CODE="$(curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/models" 2>/dev/null || true)"
  if [[ "${CODE}" == "200" ]]; then
    echo "Ready. elapsed=$(( $(date +%s) - STARTED_AT ))s"
    if [[ "${VERBOSE}" == "1" ]]; then
      BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" \
        "${SCRIPT_DIR}/status_qwen3vl_server.sh"
    else
      echo "url=${BASE_URL} pid=${PID} log=${LOG_FILE}"
    fi
    exit 0
  fi
  ELAPSED="$(( $(date +%s) - STARTED_AT ))"
  if (( ELAPSED >= READY_TIMEOUT_SECONDS )); then
    echo "Timeout. last_http=${CODE:-none}"
    tail -n 80 "${LOG_FILE}" || true
    exit 1
  fi
  # First cold start often needs 1–3+ minutes (load weights + torch.compile).
  LAST_LOG="$(tail -n 1 "${LOG_FILE}" 2>/dev/null | tr -d '\r' | cut -c1-160 || true)"
  MSG="not_ready elapsed=${ELAPSED}s http=${CODE:-none} | ${LAST_LOG}"
  progress "${MSG}"
  if (( ELAPSED - LAST_PROGRESS_AT >= PROGRESS_EVERY_SECONDS )); then
    echo "still starting... elapsed=${ELAPSED}s http=${CODE:-none} (details in ${LOG_FILE})"
    LAST_PROGRESS_AT="${ELAPSED}"
  fi
  sleep "${READY_INTERVAL_SECONDS}"
done
