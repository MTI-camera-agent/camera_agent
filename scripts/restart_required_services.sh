#!/usr/bin/env bash
# One-shot control for CameraAgent default stack (3 services):
#   1) Qwen3-VL vision bridge  → :8000
#   2) MiniCPM-V-4.6 evaluation → :8001
#   3) ComfyUI image gen        → :8188
#
# FLUX :8010 is cold fallback and is NOT started here (stopped on restart if up).
#
# Usage:
#   bash scripts/restart_required_services.sh           # restart (default)
#   bash scripts/restart_required_services.sh restart
#   bash scripts/restart_required_services.sh start
#   bash scripts/restart_required_services.sh stop
#   bash scripts/restart_required_services.sh status
#
# Env knobs are forwarded to the underlying start_* scripts (HOST/PORT/MODEL_PATH/...).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACTION="${1:-restart}"

log() { printf '[stack] %s\n' "$*"; }

stop_flux_if_present() {
  if [[ -x "${SCRIPT_DIR}/stop_flux_server.sh" ]]; then
    # Best-effort: ignore failures when FLUX was never started.
    "${SCRIPT_DIR}/stop_flux_server.sh" >/dev/null 2>&1 || true
  fi
}

do_stop() {
  log "Stopping ComfyUI (:8188) ..."
  "${SCRIPT_DIR}/stop_comfyui_server.sh" || true
  log "Stopping MiniCPM (:8001) ..."
  "${SCRIPT_DIR}/stop_minicpm_server.sh" || true
  log "Stopping Qwen3-VL (:8000) ..."
  "${SCRIPT_DIR}/stop_qwen3vl_server.sh" || true
  stop_flux_if_present
  log "Stop done."
}

do_start() {
  log "NOTE: On 24GB GPUs, Qwen + MiniCPM + ComfyUI all resident may OOM; use serially if needed."
  log "Starting Qwen3-VL vision bridge (:8000) ..."
  "${SCRIPT_DIR}/start_qwen3vl_server.sh"
  log "Starting MiniCPM evaluation (:8001) ..."
  "${SCRIPT_DIR}/start_minicpm_server.sh"
  log "Starting ComfyUI (:8188) ..."
  "${SCRIPT_DIR}/start_comfyui_server.sh"
  log "Start done."
}

do_status() {
  if [[ "${VERBOSE:-0}" == "1" ]]; then
    log "=== Qwen3-VL (:8000) ==="
    "${SCRIPT_DIR}/status_qwen3vl_server.sh" || true
    echo
    log "=== MiniCPM (:8001) ==="
    "${SCRIPT_DIR}/status_minicpm_server.sh" || true
    echo
    log "=== ComfyUI (:8188) ==="
    "${SCRIPT_DIR}/status_comfyui_server.sh" || true
    return
  fi
  # Quiet summary: HTTP only
  local vlm_code mcp_code comfy_code
  vlm_code="$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8000/v1/models" 2>/dev/null || true)"
  mcp_code="$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8001/v1/models" 2>/dev/null || true)"
  comfy_code="$(curl -sS -o /dev/null -w "%{http_code}" "http://127.0.0.1:8188/system_stats" 2>/dev/null || true)"
  log "Qwen3-VL :8000 http=${vlm_code:-none}"
  log "MiniCPM  :8001 http=${mcp_code:-none}"
  log "ComfyUI  :8188 http=${comfy_code:-none}"
  log "VERBOSE=1 for full status; logs: /tmp/camera_agent_qwen3vl_vllm.log /tmp/camera_agent_minicpm.log /tmp/camera_agent_comfyui.log"
}

do_restart() {
  do_stop
  # Give CUDA a moment to release after process exit.
  sleep 2
  do_start
  echo
  do_status
}

case "${ACTION}" in
  restart) do_restart ;;
  start) do_start; echo; do_status ;;
  stop) do_stop ;;
  status) do_status ;;
  -h|--help|help)
    sed -n '2,16p' "$0"
    exit 0
    ;;
  *)
    echo "ERROR: unknown action '${ACTION}'. Use: restart|start|stop|status" >&2
    exit 1
    ;;
esac
