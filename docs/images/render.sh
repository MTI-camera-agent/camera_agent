#!/usr/bin/env bash
# Re-render the 3 mermaid diagrams from docs/02-框架及流程图.md into PNGs.
# Prereq: node + npx (mermaid-cli is auto-fetched on first run; chromium downloaded once).
# Usage:  bash docs/images/render.sh
# Tip:    npm i -g @mermaid-js/mermaid-cli  → then replace `npx -y @mermaid-js/mermaid-cli@latest` with `mmdc`.
set -euo pipefail
# script lives in docs/images/ → repo root is two levels up
cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." || exit 1

DOC="docs/02-框架及流程图.md"
CFG="docs/images/mmdc-config.json"

# 1) extract each ```mermaid block to docs/images/<name>.mmd
python3 - "$DOC" <<'PY'
import re, pathlib, sys
doc = pathlib.Path(sys.argv[1])
blocks = re.findall(r"```mermaid\n(.*?)```", doc.read_text(encoding="utf-8"), re.S)
names = ["02-macro", "02-edge-cloud", "02-clone-self"]
if len(blocks) != len(names):
    raise SystemExit(f"expected {len(names)} mermaid blocks, found {len(blocks)}")
for name, b in zip(names, blocks):
    pathlib.Path(f"docs/images/{name}.mmd").write_text(b, encoding="utf-8")
    print(f"extracted {name}.mmd ({b.count(chr(10))} lines)")
PY

# 2) render each .mmd → .png (ELK frontmatter in 02-macro is honored automatically)
for n in 02-macro 02-edge-cloud 02-clone-self; do
  echo "rendering $n ..."
  npx -y @mermaid-js/mermaid-cli@latest -i "docs/images/$n.mmd" -o "docs/images/$n.png" -p "$CFG"
done

echo "done → docs/images/*.png"
