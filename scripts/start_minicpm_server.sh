#!/usr/bin/env bash
# Start MiniCPM-V-4.6 via transformers serve (default evaluation service :8001).
# Reuses conda env qwen3vl-fp8 (transformers 5.x); does NOT upgrade vLLM.
#
# Usage:
#   bash scripts/start_minicpm_server.sh
#   INSTALL_SERVING=1 bash scripts/start_minicpm_server.sh   # pip install transformers[serving] if missing
#   VERBOSE=1 bash scripts/start_minicpm_server.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
MODEL_PATH="${MODEL_PATH:-${REPO_ROOT}/assets/models/MiniCPM-V-4.6}"
# Served OpenAI model id must equal the transformers serve FORCE_MODEL string.
# Launch from the parent dir with the directory basename so config can use MiniCPM-V-4.6.
SERVED_MODEL_NAME="${SERVED_MODEL_NAME:-$(basename "${MODEL_PATH}")}"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8001}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_minicpm.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_minicpm.log}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-300}"
READY_INTERVAL_SECONDS="${READY_INTERVAL_SECONDS:-3}"
PROGRESS_EVERY_SECONDS="${PROGRESS_EVERY_SECONDS:-15}"
VERBOSE="${VERBOSE:-0}"
INSTALL_SERVING="${INSTALL_SERVING:-0}"
BASE_URL="http://${HOST}:${PORT}"
CONDA_ENV="${CONDA_ENV:-qwen3vl-fp8}"
PIP_INDEX="${PIP_INDEX:-https://pypi.tuna.tsinghua.edu.cn/simple}"

progress() {
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

# Drop Windows download ADS leftovers if present.
find "${MODEL_PATH}" -maxdepth 1 -name '*:Zone.Identifier' -type f -delete 2>/dev/null || true

if [[ -f "${PID_FILE}" ]] && kill -0 "$(cat "${PID_FILE}")" 2>/dev/null; then
  echo "MiniCPM already running pid=$(cat "${PID_FILE}") url=${BASE_URL}"
  BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" \
    "${SCRIPT_DIR}/status_minicpm_server.sh"
  exit 0
fi

EXISTING="$(curl -sS -o /dev/null -w "%{http_code}" "${BASE_URL}/v1/models" 2>/dev/null || true)"
if [[ "${EXISTING}" == "200" ]]; then
  echo "API already ready at ${BASE_URL} (no live PID file)."
  exit 0
fi

rm -f "${PID_FILE}" "${LOG_FILE}"

if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "${CONDA_ENV}"
fi

if ! command -v transformers >/dev/null 2>&1; then
  echo "ERROR: transformers CLI not on PATH. Activate ${CONDA_ENV} first."
  exit 1
fi

# transformers serve needs FastAPI + Uvicorn (transformers[serving]).
if ! python -c "import fastapi, uvicorn" >/dev/null 2>&1; then
  if [[ "${INSTALL_SERVING}" == "1" ]]; then
    echo "Installing transformers[serving] into ${CONDA_ENV} ..."
    pip install "transformers[serving]>=5.7.0" \
      -i "${PIP_INDEX}" --trusted-host pypi.tuna.tsinghua.edu.cn
  else
    echo "ERROR: fastapi/uvicorn missing for transformers serve."
    echo "  INSTALL_SERVING=1 bash scripts/start_minicpm_server.sh"
    echo "  # or: conda activate ${CONDA_ENV} && pip install 'transformers[serving]>=5.7.0'"
    exit 1
  fi
fi

MODEL_PARENT="$(cd "$(dirname "${MODEL_PATH}")" && pwd)"
if [[ ! -d "${MODEL_PARENT}/${SERVED_MODEL_NAME}" ]]; then
  echo "ERROR: expected ${MODEL_PARENT}/${SERVED_MODEL_NAME} (served id must match basename)."
  exit 1
fi

echo "Starting MiniCPM-V-4.6 transformers serve from ${MODEL_PATH}"
echo "served_model_id=${SERVED_MODEL_NAME} (set structured_evaluation.model_id to this)"
(
  cd "${MODEL_PARENT}"
  # Force-model string becomes the OpenAI model id clients must send.
  nohup transformers serve "${SERVED_MODEL_NAME}" \
    --host "${HOST}" \
    --port "${PORT}" \
    --continuous-batching \
    --trust-remote-code \
    --log-level warning \
    >"${LOG_FILE}" 2>&1 &
  echo $! >"${PID_FILE}"
)

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
        "${SCRIPT_DIR}/status_minicpm_server.sh"
    else
      echo "url=${BASE_URL} model_id=${SERVED_MODEL_NAME} pid=${PID} log=${LOG_FILE}"
    fi
    exit 0
  fi
  ELAPSED="$(( $(date +%s) - STARTED_AT ))"
  if (( ELAPSED >= READY_TIMEOUT_SECONDS )); then
    echo "Timeout. last_http=${CODE:-none}"
    tail -n 80 "${LOG_FILE}" || true
    exit 1
  fi
  LAST_LOG="$(tail -n 1 "${LOG_FILE}" 2>/dev/null | tr -d '\r' | cut -c1-160 || true)"
  MSG="not_ready elapsed=${ELAPSED}s http=${CODE:-none} | ${LAST_LOG}"
  progress "${MSG}"
  if (( ELAPSED - LAST_PROGRESS_AT >= PROGRESS_EVERY_SECONDS )); then
    echo "still starting... elapsed=${ELAPSED}s http=${CODE:-none} (details in ${LOG_FILE})"
    LAST_PROGRESS_AT="${ELAPSED}"
  fi
  sleep "${READY_INTERVAL_SECONDS}"
done
