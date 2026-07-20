#!/usr/bin/env bash
# One-shot: vendor KtransToGrafana golden-path pieces into local/ and adapt them.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
REF="${ROOT}/.ref-KtransToGrafana"
[[ -d "$REF" ]] || { echo "missing $REF — clone KtransToGrafana first"; exit 1; }

mkdir -p "${ROOT}/templates" "${ROOT}/groups" "${ROOT}/config" "${ROOT}/state"
cp "${REF}/templates/"*.tmpl "${ROOT}/templates/"
cp "${REF}/scripts/generate-groups.sh" \
   "${REF}/scripts/run-discovery.sh" \
   "${REF}/scripts/host-id.sh" \
   "${REF}/scripts/compute-limits.sh" \
   "${REF}/scripts/preflight.sh" \
   "${ROOT}/scripts/"
chmod +x "${ROOT}/scripts/generate-groups.sh" \
         "${ROOT}/scripts/run-discovery.sh" \
         "${ROOT}/scripts/host-id.sh" \
         "${ROOT}/scripts/compute-limits.sh" \
         "${ROOT}/scripts/preflight.sh"

cd "${ROOT}"
python3 - <<'PY'
from pathlib import Path
root = Path.cwd()
p = root / "templates" / "compose-snippet.yaml.tmpl"
t = p.read_text()
t = t.replace("${REPO_PATH}/config/", "./config/")
t = t.replace("${REPO_PATH}/state/", "./state/")
p.write_text(t)

g = root / "scripts" / "generate-groups.sh"
gt = g.read_text()
old = 'RESERVED_PORTS_TCP="9995 9996 9998 4317 12346"'
new = 'RESERVED_PORTS_TCP="9995 9996 9998 4317 12346 9100 9101"'
if old not in gt:
    raise SystemExit(f"reserved ports string not found in generate-groups.sh")
g.write_text(gt.replace(old, new, 1))

# preflight: local uses alloy/config.alloy and compose-base.yaml (not config.alloy at root)
pf = root / "scripts" / "preflight.sh"
pt = pf.read_text()
pt = pt.replace(
    'for f in .env config.alloy compose-base.yaml; do',
    'for f in .env alloy/config.alloy compose-base.yaml; do',
)
pt = pt.replace(
    '_fail "${f} is missing — run: cp ${f}.sample ${f}"',
    '_fail "${f} is missing — see local/README.md setup"',
)
# discovery compose files for run-discovery — already compose-base + groups
pf.write_text(pt)
print("adapted templates + scripts")
PY

echo "done under ${ROOT}"
