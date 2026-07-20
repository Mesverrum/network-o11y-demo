#!/usr/bin/env bash
# Import prepared ktranslate v2 dashboards into Grafana Cloud.
# Requires GRAFANA_URL + GRAFANA_TOKEN in local/.env
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
# shellcheck disable=SC1091
set -a
source "${ROOT}/.env"
set +a

: "${GRAFANA_URL:?missing GRAFANA_URL}"
: "${GRAFANA_TOKEN:?missing GRAFANA_TOKEN}"

python3 - "$ROOT" <<'PY'
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

root = Path(sys.argv[1])
base = os.environ["GRAFANA_URL"].rstrip("/")
token = os.environ["GRAFANA_TOKEN"]
ns = "stacks-1061129"
folder = "network-lab"
imp = root / ".dash-payloads" / "ktranslate-import"

# Re-prepare from Commvault exports if present
sys.path.insert(0, str(root / "scripts"))
try:
    import prepare_ktranslate_imports  # type: ignore
except Exception:
    pass

# Always run prepare inline for safety
REPLACEMENTS = {
    "grafanacloud-commvault-prom": "grafanacloud-prom",
    "grafanacloud-commvault-logs": "grafanacloud-logs",
}
FILES = [
    ("dashboard-1784313151319.json", "mavgvqv"),
    ("dashboard-1784313137315.json", "magz6qw1"),
    ("dashboard-1784313167585.json", "be8hpir89dds0a"),
    ("dashboard-1784313199685.json", "masjqrs"),
]
payloads_dir = root / ".dash-payloads"
imp.mkdir(parents=True, exist_ok=True)

def remap(obj):
    text = json.dumps(obj, separators=(",", ":"))
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return json.loads(text)

prepared = []
for src_name, uid in FILES:
    src = payloads_dir / src_name
    if not src.exists():
        # fall back to already-prepared file
        out = imp / f"{uid}.json"
        if not out.exists():
            raise SystemExit(f"missing {src} and {out}")
        prepared.append(out)
        continue
    data = remap(json.loads(src.read_text(encoding="utf-8")))
    meta = data.setdefault("metadata", {})
    meta["name"] = uid
    meta["namespace"] = ns
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = folder
    ann["grafana.app/message"] = f"Import ktranslate dashboard from Commvault ({src_name})"
    out = imp / f"{uid}.json"
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    prepared.append(out)
    print(f"prepared {out.name} title={(data.get('spec') or {}).get('title')}")


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
        with urllib.request.urlopen(r, timeout=120) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


results = []
for path in prepared:
    dash = json.loads(path.read_text(encoding="utf-8"))
    name = dash["metadata"]["name"]
    title = (dash.get("spec") or {}).get("title")
    create_path = f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards"
    status, out = req("POST", create_path, dash)
    action = "created"
    if status in (409, 403) or (isinstance(out, dict) and out.get("code") in (409, 403)):
        # try update path — may be already exists
        get_path = f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{name}"
        gstatus, existing = req("GET", get_path)
        if gstatus == 200 and isinstance(existing, dict):
            rv = (existing.get("metadata") or {}).get("resourceVersion")
            if rv:
                dash["metadata"]["resourceVersion"] = rv
            status, out = req("PUT", get_path, dash)
            action = "updated"
        else:
            # sometimes POST returns conflict with different shape; still try PUT without rv
            status, out = req("PUT", get_path, dash)
            action = "updated"
    ok = 200 <= int(status) < 300
    url = f"{base}/d/{name}"
    results.append((name, title, action if ok else "failed", status, url, out if not ok else None))
    print(f"{name}: {action} http={status} ok={ok} {url}")
    if not ok:
        print(json.dumps(out, indent=2)[:1500])

fails = [r for r in results if r[2] == "failed"]
sys.exit(1 if fails else 0)
PY
