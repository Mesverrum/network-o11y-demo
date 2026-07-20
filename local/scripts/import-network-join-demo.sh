#!/usr/bin/env bash
# Import Network join demo dashboard into Grafana Cloud.
#
# Requires (set in local/.env or environment):
#   GRAFANA_URL
#   GRAFANA_TOKEN   (service account with dashboards:write)
# Optional:
#   FOLDER_UID      (default network-lab)

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DASH="${ROOT}/.dash-payloads/network-join-demo.json"
FOLDER_UID="${FOLDER_UID:-network-lab}"

if [[ -f "${ROOT}/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^(GRAFANA_URL|GRAFANA_TOKEN)=' "${ROOT}/.env" | tr -d '\r')
  set +a
fi

: "${GRAFANA_URL:?set GRAFANA_URL in local/.env or environment}"
: "${GRAFANA_TOKEN:?set GRAFANA_TOKEN (service account for ${GRAFANA_URL})}"

if [[ ! -f "$DASH" ]]; then
  python3 "${ROOT}/scripts/build-network-join-demo.py"
fi

python3 - "$GRAFANA_URL" "$GRAFANA_TOKEN" "$FOLDER_UID" "$DASH" <<'PY'
import json
import sys
import urllib.error
import urllib.request

base, token, folder, path = sys.argv[1:5]
base = base.rstrip("/")

def req(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    r = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        print(e.read().decode(), file=sys.stderr)
        raise

try:
    req("GET", f"/api/folders/{folder}")
except urllib.error.HTTPError as e:
    if e.code == 404:
        req("POST", "/api/folders", {"uid": folder, "title": "Network Lab"})
    else:
        raise

with open(path, encoding="utf-8") as f:
    dash = json.load(f)
dash.pop("id", None)
payload = {
    "dashboard": dash,
    "folderUid": folder,
    "overwrite": True,
    "message": "import network join SIG demo dashboard",
}
out = req("POST", "/api/dashboards/db", payload)
uid = out.get("uid") or dash.get("uid")
url = out.get("url") or f"/d/{uid}"
if url.startswith("/"):
    url = base + url
print(f"imported uid={uid}")
print(f"url={url}")
PY
