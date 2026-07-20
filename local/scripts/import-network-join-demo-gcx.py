#!/usr/bin/env python3
"""Import network-join-demo dashboard via gcx (optional) or GRAFANA_TOKEN."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH = ROOT / ".dash-payloads" / "network-join-demo.json"
PAYLOAD = ROOT / ".dash-payloads" / "network-join-demo.upload.json"
FOLDER = os.environ.get("GRAFANA_FOLDER_UID", "network-lab")


def load_dotenv() -> None:
    env = ROOT / ".env"
    if not env.is_file():
        return
    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def tester_id() -> str:
    load_dotenv()
    for key in ("LAB_TESTER_ID", "KTRANS_HOST"):
        v = os.environ.get(key, "").strip()
        if v:
            return v
    return "network-lab"


def find_gcx() -> Path | None:
    for key in ("GCX_BIN", "GCX"):
        raw = os.environ.get(key, "").strip()
        if raw:
            p = Path(raw)
            if p.is_file():
                return p
    for name in ("gcx.exe", "gcx"):
        found = shutil.which(name)
        if found:
            return Path(found)
    return None


def grafana_url() -> str:
    load_dotenv()
    return os.environ.get("GRAFANA_URL", "").rstrip("/")


def parse_json(raw: str):
    lines = [ln for ln in raw.splitlines() if not ln.startswith('{"class":"hint"')]
    body = "\n".join(lines).strip()
    if not body:
        return None
    return json.loads(body)


def import_via_http(base: str, token: str) -> int:
    import urllib.error
    import urllib.request

    def req(method: str, path: str, body: dict | None = None):
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
        with urllib.request.urlopen(r, timeout=60) as resp:
            return json.load(resp)

    try:
        req("GET", f"/api/folders/{FOLDER}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            req("POST", "/api/folders", {"uid": FOLDER, "title": "Network Lab"})
        else:
            raise

    dash = json.loads(DASH.read_text(encoding="utf-8"))
    dash.pop("id", None)
    out = req(
        "POST",
        "/api/dashboards/db",
        {
            "dashboard": dash,
            "folderUid": FOLDER,
            "overwrite": True,
            "message": "import network join SIG demo dashboard",
        },
    )
    uid = out.get("uid") or dash.get("uid")
    url = out.get("url") or f"/d/{uid}"
    if url.startswith("/"):
        url = base + url
    print("DEEPLINK", url)
    return 0


def gcx_api(gcx: Path, context: str, *args: str) -> subprocess.CompletedProcess:
    cmd = [str(gcx), "--context", context, *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def import_via_gcx(gcx: Path, context: str) -> int:
    if not DASH.exists():
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build-network-join-demo.py")])

    tid = tester_id()
    probes = [
        ("flows", "count(network_io_by_flow_bytes)"),
        ("topo_dev", f'count(network_topology_device_info{{tester_id="{tid}"}})'),
        ("topo_edge", f'count(network_topology_edge_info{{tester_id="{tid}"}})'),
        ("uptime", 'count(kentik_snmp_Uptime{device_name=~"spine1|leaf1|leaf2"})'),
    ]
    for name, expr in probes:
        from urllib.parse import quote

        path = f"/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?query={quote(expr)}"
        pr = gcx_api(gcx, context, "api", path, "-o", "json")
        try:
            data = parse_json(pr.stdout or "")
            n = len((data or {}).get("data", {}).get("result", []))
            print(f"signal {name}: n={n}")
        except Exception as e:
            print(f"signal {name}: FAIL {e}")

    dash = json.loads(DASH.read_text(encoding="utf-8"))
    dash.pop("id", None)
    payload = {
        "dashboard": dash,
        "folderUid": FOLDER,
        "overwrite": True,
        "message": "import network join SIG demo dashboard",
    }
    PAYLOAD.write_text(json.dumps(payload), encoding="utf-8")
    upload_path = str(PAYLOAD.resolve())
    ur = gcx_api(gcx, context, "api", "/api/dashboards/db", "-d", f"@{upload_path}", "-o", "json")
    print("upload rc", ur.returncode)
    if ur.stdout:
        print(ur.stdout[:1000])
    data = parse_json(ur.stdout or "")
    if not data:
        print(ur.stderr or "", file=sys.stderr)
        return 1
    uid = data.get("uid") or "lab-network-join-demo"
    base = grafana_url()
    url = data.get("url") or f"/d/{uid}"
    if url.startswith("/") and base:
        url = base + url
    print("DEEPLINK", url)
    return 0 if ur.returncode == 0 else 1


def main() -> int:
    load_dotenv()
    token = os.environ.get("GRAFANA_TOKEN", "").strip()
    base = grafana_url()
    if token and base:
        return import_via_http(base, token)

    gcx = find_gcx()
    context = os.environ.get("GCX_CONTEXT", "").strip()
    if gcx and context:
        return import_via_gcx(gcx, context)

    print(
        "Set GRAFANA_URL + GRAFANA_TOKEN in local/.env, or GCX_BIN + GCX_CONTEXT for gcx.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
