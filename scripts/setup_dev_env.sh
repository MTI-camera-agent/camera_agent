#!/usr/bin/env bash
# Create an isolated conda env for Camera Agent (does not touch base or other envs).
set -euo pipefail

ENV_NAME="${ENV_NAME:-camera_agent}"
PYTHON_VERSION="${PYTHON_VERSION:-3.12}"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Tsinghua mirrors — passed per-command; does not modify global conda/pip config.
CONDA_MAIN="https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main"
CONDA_FORGE="https://mirrors.tuna.tsinghua.edu.cn/anaconda/cloud/conda-forge"
PIP_INDEX="https://pypi.tuna.tsinghua.edu.cn/simple"
PIP_TRUSTED_HOST="pypi.tuna.tsinghua.edu.cn"

if ! command -v conda >/dev/null 2>&1; then
  echo "conda not found. Install Miniconda/Anaconda first." >&2
  exit 1
fi

# shellcheck disable=SC1091
source "$(conda info --base)/etc/profile.d/conda.sh"

if conda env list | awk '{print $1}' | grep -qx "${ENV_NAME}"; then
  echo "Conda env '${ENV_NAME}' already exists. Activate it and re-run pip install if needed:"
  echo "  conda activate ${ENV_NAME}"
  echo "  pip install -r requirements.txt -i ${PIP_INDEX} --trusted-host ${PIP_TRUSTED_HOST}"
  exit 0
fi

echo "Creating conda env '${ENV_NAME}' (Python ${PYTHON_VERSION})..."
conda create -n "${ENV_NAME}" "python=${PYTHON_VERSION}" -y \
  -c "${CONDA_MAIN}" \
  -c "${CONDA_FORGE}"

conda activate "${ENV_NAME}"

echo "Installing core dependencies from requirements.txt..."
pip install -r "${REPO_ROOT}/requirements.txt" \
  -i "${PIP_INDEX}" \
  --trusted-host "${PIP_TRUSTED_HOST}"

echo ""
echo "Done. Activate with:"
echo "  conda activate ${ENV_NAME}"
echo ""
echo "Verify:"
echo "  cd ${REPO_ROOT} && pytest -q"
echo ""
echo "Optional: full GPU stack (PyTorch + vllm-omni) — see docs/development_workflow.md"
