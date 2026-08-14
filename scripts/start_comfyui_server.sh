#!/usr/bin/env bash
# Start ComfyUI image stack (default service #2). Does NOT modify mm-comfyui packages.
#
# Prefer delegating to an existing launcher (MirrorMe bin/comfyui.sh) when present.
# Override with COMFYUI_START_CMD or COMFYUI_ROOT + COMFYUI_MAIN.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-8188}"
BASE_URL="http://${HOST}:${PORT}"
PID_FILE="${PID_FILE:-/tmp/camera_agent_comfyui.pid}"
LOG_FILE="${LOG_FILE:-/tmp/camera_agent_comfyui.log}"
READY_TIMEOUT_SECONDS="${READY_TIMEOUT_SECONDS:-180}"
PROGRESS_EVERY_SECONDS="${PROGRESS_EVERY_SECONDS:-15}"
VERBOSE="${VERBOSE:-0}"
MIRRORME_COMFYUI_SH="${MIRRORME_COMFYUI_SH:-/home/pathfinder/business/projects/MirrorMe/bin/comfyui.sh}"
CONDA_ENV="${CONDA_ENV:-mm-comfyui}"

progress() {
  local msg="$1"
  printf '%s\n' "${msg}" >>"${LOG_FILE}" 2>/dev/null || true
  if [[ "${VERBOSE}" == "1" ]]; then
    echo "${msg}"
  fi
}

echo "NOTE: CameraAgent must not pip/conda-modify ${CONDA_ENV}. This script only starts the process."

if curl -sS -o /dev/null --max-time 3 "${BASE_URL}/system_stats"; then
  echo "ComfyUI already ready at ${BASE_URL}"
  if [[ "${VERBOSE}" == "1" ]]; then
    BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" \
      "${SCRIPT_DIR}/status_comfyui_server.sh"
  fi
  exit 0
fi

if [[ -n "${COMFYUI_START_CMD:-}" ]]; then
  echo "Using COMFYUI_START_CMD"
  bash -lc "${COMFYUI_START_CMD}"
elif [[ -x "${MIRRORME_COMFYUI_SH}" ]]; then
  echo "Delegating to ${MIRRORME_COMFYUI_SH} start"
  "${MIRRORME_COMFYUI_SH}" start
else
  COMFYUI_ROOT="${COMFYUI_ROOT:?Set COMFYUI_ROOT to ComfyUI runtime dir, or install MirrorMe launcher}"
  COMFYUI_MAIN="${COMFYUI_MAIN:?Set COMFYUI_MAIN to ComfyUI main.py}"
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "${CONDA_ENV}"
  rm -f "${LOG_FILE}"
  nohup python "${COMFYUI_MAIN}" \
    --listen "${HOST}" \
    --port "${PORT}" \
    --base-directory "${COMFYUI_ROOT}" \
    >"${LOG_FILE}" 2>&1 &
  echo "$!" >"${PID_FILE}"
  echo "pid=$(cat "${PID_FILE}") log=${LOG_FILE}"
fi

echo "Waiting for ComfyUI readiness (up to ${READY_TIMEOUT_SECONDS}s; VERBOSE=1 for per-tick logs)..."
STARTED_AT="$(date +%s)"
LAST_PROGRESS_AT=0
while true; do
  if curl -sS -o /dev/null --max-time 3 "${BASE_URL}/system_stats"; then
    echo "Ready. elapsed=$(( $(date +%s) - STARTED_AT ))s url=${BASE_URL}"
    if [[ "${VERBOSE}" == "1" ]]; then
      BASE_URL="${BASE_URL}" PID_FILE="${PID_FILE}" LOG_FILE="${LOG_FILE}" \
        "${SCRIPT_DIR}/status_comfyui_server.sh"
    fi
    exit 0
  fi
  ELAPSED="$(( $(date +%s) - STARTED_AT ))"
  if (( ELAPSED >= READY_TIMEOUT_SECONDS )); then
    echo "Timeout waiting for ${BASE_URL}/system_stats"
    exit 1
  fi
  progress "not_ready elapsed=${ELAPSED}s"
  if (( ELAPSED - LAST_PROGRESS_AT >= PROGRESS_EVERY_SECONDS )); then
    echo "still starting... elapsed=${ELAPSED}s (details in ${LOG_FILE})"
    LAST_PROGRESS_AT="${ELAPSED}"
  fi
  sleep 3
done
