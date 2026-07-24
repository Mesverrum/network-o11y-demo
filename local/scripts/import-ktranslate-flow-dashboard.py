#!/usr/bin/env python3
"""Import lab-ktranslate-flow v2 dashboard into Grafana Cloud (network-lab folder)."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / ".dash-payloads" / "ktranslate-import" / "lab-ktranslate-flow.json"
NAMESPACE = "stacks-1544961"
UID = "lab-ktranslate-flow"


def load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def find_gcx() -> Path | None:
    for key in ("GCX_BIN", "GCX"):
        raw = os.environ.get(key, "").strip()
        if raw and Path(raw).is_file():
            return Path(raw)
    for name in ("gcx.exe", "gcx"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def req(base: str, token: str, method: str, path: str, body=None):
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
        with urllib.request.urlopen(r, timeout=180) as resp:
            return resp.status, json.load(resp)
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def upsert_http(base: str, token: str, dash: dict) -> str:
    folder = os.environ.get("GRAFANA_FOLDER_UID", "network-lab")
    status, out = req(base, token, "GET", f"/api/folders/{folder}")
    if status == 404:
        req(base, token, "POST", "/api/folders", {"uid": folder, "title": "Network Lab"})

    create = f"/apis/dashboard.grafana.app/v2/namespaces/{NAMESPACE}/dashboards"
    status, out = req(base, token, "POST", create, dash)
    if 200 <= int(status) < 300:
        return f"{base}/d/{UID}"

    get_path = f"/apis/dashboard.grafana.app/v2/namespaces/{NAMESPACE}/dashboards/{UID}"
    gstatus, existing = req(base, token, "GET", get_path)
    if gstatus == 200:
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash["metadata"]["resourceVersion"] = rv
    status, out = req(base, token, "PUT", get_path, dash)
    if not (200 <= int(status) < 300):
        raise SystemExit(f"import failed http={status} {json.dumps(out)[:1200]}")
    return f"{base}/d/{UID}"


def import_via_gcx(gcx: Path, context: str) -> int:
    build = ROOT / "scripts" / "build-ktranslate-flow-dashboard.py"
    if not DASH.is_file():
        subprocess.check_call([sys.executable, str(build)])

    # Probe flow signal
    from urllib.parse import quote

    path = f"/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?query={quote('count(network_io_by_flow_bytes)')}"
    pr = subprocess.run(
        [str(gcx), "--context", context, "api", path, "-o", "json"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    lines = [ln for ln in (pr.stdout or "").splitlines() if not ln.startswith('{"class":"hint"')]
    try:
        data = json.loads("\n".join(lines))
        n = len((data or {}).get("data", {}).get("result", []))
        print(f"signal flows: n={n}")
    except Exception as e:
        print(f"signal flows: probe skipped ({e})")

    cr = subprocess.run(
        [str(gcx), "--context", context, "dashboards", "create", "-f", str(DASH)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if cr.returncode != 0 and "already exists" not in (cr.stderr or "").lower():
        # try update via PUT through api
        load_dotenv()
        base = os.environ.get("GRAFANA_URL", "https://networko11ydev.grafana.net").rstrip("/")
        token = os.environ.get("GRAFANA_TOKEN", "").strip()
        if token:
            dash = json.loads(DASH.read_text(encoding="utf-8"))
            url = upsert_http(base, token, dash)
            print("DEEPLINK", url)
            return 0
        print(cr.stdout or "", cr.stderr or "", file=sys.stderr)
        return cr.returncode

    base = os.environ.get("GRAFANA_URL", "https://networko11ydev.grafana.net").rstrip("/")
    print("DEEPLINK", f"{base}/d/{UID}")
    return 0


def main() -> int:
    load_dotenv()
    build = ROOT / "scripts" / "build-ktranslate-flow-dashboard.py"
    subprocess.check_call([sys.executable, str(build)])

    gcx = find_gcx()
    context = os.environ.get("GCX_CONTEXT", "networko11ydev").strip()
    if gcx:
        return import_via_gcx(gcx, context)

    token = os.environ.get("GRAFANA_TOKEN", "").strip()
    base = os.environ.get("GRAFANA_URL", "").rstrip("/")
    if token and base:
        dash = json.loads(DASH.read_text(encoding="utf-8"))
        url = upsert_http(base, token, dash)
        print("DEEPLINK", url)
        return 0

    raise SystemExit("Install gcx with networko11ydev context, or set GRAFANA_URL + GRAFANA_TOKEN in local/.env.")


if __name__ == "__main__":
    raise SystemExit(main())
