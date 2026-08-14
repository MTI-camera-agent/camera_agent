#!/usr/bin/env bash
# Idempotent local hotfix for vLLM 0.20.x Qwen3-VL deepstack EngineDead.
# Equivalent to upstream https://github.com/vllm-project/vllm/pull/40932
# (remove invalid deepstack buffer boundary raises). Does NOT upgrade vLLM.
#
# Usage:
#   bash scripts/patch_vllm_qwen3vl_deepstack.sh
#   CONDA_ENV=qwen3vl-fp8 bash scripts/patch_vllm_qwen3vl_deepstack.sh
set -euo pipefail

CONDA_ENV="${CONDA_ENV:-qwen3vl-fp8}"

if command -v conda >/dev/null 2>&1; then
  # shellcheck disable=SC1091
  source "$(conda info --base)/etc/profile.d/conda.sh"
  conda activate "${CONDA_ENV}"
fi

TARGET="$(
  python - <<'PY'
import importlib.util
spec = importlib.util.find_spec("vllm.model_executor.models.qwen3_vl")
if spec is None or not spec.origin:
    raise SystemExit("qwen3_vl module not found; activate qwen3vl-fp8 first")
print(spec.origin)
PY
)"

echo "target=${TARGET}"

python - "${TARGET}" <<'PY'
from __future__ import annotations

import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
original = text

# Marker left after a successful CameraAgent patch (idempotency).
MARKER = "# camera_agent: deepstack boundary raises removed (vllm#40932)"

if MARKER in text or (
    "Requested more deepstack tokens than available in buffer" not in text
    and "Requested to clear more deepstack tokens than available" not in text
):
    print("already_patched=yes")
    raise SystemExit(0)

get_raise = re.compile(
    r"\n[ \t]*if num_tokens > self\.deepstack_input_embeds_num_tokens:\n"
    r"[ \t]*raise ValueError\(\n"
    r"[ \t]*\"Requested more deepstack tokens than available in buffer: \"\n"
    r"[ \t]*f\"\{num_tokens=\} > \{self\.deepstack_input_embeds_num_tokens=\}\"\n"
    r"[ \t]*\)\n",
    re.MULTILINE,
)
clear_raise = re.compile(
    r"\n[ \t]*if num_tokens > self\.deepstack_input_embeds_num_tokens:\n"
    r"[ \t]*raise ValueError\(\n"
    r"[ \t]*\"Requested to clear more deepstack tokens than available in \"\n"
    r"[ \t]*\"buffer: \"\n"
    r"[ \t]*f\"\{num_tokens=\} > \{self\.deepstack_input_embeds_num_tokens=\}\"\n"
    r"[ \t]*\)\n",
    re.MULTILINE,
)

text2, n_get = get_raise.subn("\n", text, count=1)
text3, n_clear = clear_raise.subn("\n", text2, count=1)

if n_get != 1 or n_clear != 1:
    print(
        f"ERROR: expected to remove 1 get-raise and 1 clear-raise; "
        f"got get={n_get} clear={n_clear}",
        file=sys.stderr,
    )
    raise SystemExit(1)

# Insert marker near top of file (after module docstring if present).
if text3.lstrip().startswith('"""'):
    end = text3.find('"""', 3)
    if end != -1:
        insert_at = end + 3
        text3 = text3[:insert_at] + f"\n{MARKER}\n" + text3[insert_at:]
    else:
        text3 = MARKER + "\n" + text3
else:
    text3 = MARKER + "\n" + text3

bak = path.with_suffix(path.suffix + ".camera_agent_deepstack.bak")
if not bak.exists():
    bak.write_text(original, encoding="utf-8")
    print(f"backup={bak}")

path.write_text(text3, encoding="utf-8")
print("patched=yes")
print("already_patched=no")
PY
