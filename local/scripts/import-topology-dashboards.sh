#!/usr/bin/env bash
# Import lab topology dashboards into a Grafana Cloud stack.
# Requires: GRAFANA_URL and GRAFANA_TOKEN in local/.env
# (service account with dashboards:write).

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIR="${ROOT}/.dash-payloads/topology"
FOLDER_UID="${FOLDER_UID:-network-lab}"

: "${GRAFANA_URL:?set GRAFANA_URL}"
: "${GRAFANA_TOKEN:?set GRAFANA_TOKEN}"

python3 - "$GRAFANA_URL" "$GRAFANA_TOKEN" "$FOLDER_UID" "$DIR" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request

base, token, folder, directory = sys.argv[1:5]
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
        with urllib.request.urlopen(r) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        print(e.read().decode(), file=sys.stderr)
        raise


for name in ("lab-topology-graph.json", "lab-topology-health.json"):
    path = os.path.join(directory, name)
    with open(path, encoding="utf-8") as f:
        dash = json.load(f)
    dash.pop("id", None)
    payload = {
        "dashboard": dash,
        "folderUid": folder,
        "overwrite": True,
        "message": "import topology lab dashboards",
    }
    out = req("POST", "/api/dashboards/db", payload)
    print(f"{name} -> {out.get('url')} uid={out.get('uid')}")
PY
