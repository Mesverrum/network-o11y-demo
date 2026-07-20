#!/usr/bin/env python3
"""Upload regenerated net-o11y dashboards that contain BGP panels."""
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCAL = ROOT / "local"
DASH_DIR = ROOT / "grafana" / "dashboards"

FILES = {
    "bgp-status.json": "net-o11y-bgp-status",
    "device-details.json": "net-o11y-device-details",
    "network-topology.json": "net-o11y-topology",
}


def load_env():
    env = {}
    for line in (LOCAL / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def api(env, method, path, body=None):
    url = env["GRAFANA_URL"].rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{method} {path} -> {e.code}: {e.read().decode()[:800]}") from e


def main():
    env = load_env()
    for fname, uid in FILES.items():
        dash = json.loads((DASH_DIR / fname).read_text())
        meta = api(env, "GET", f"/api/dashboards/uid/{uid}")
        folder = meta.get("meta", {}).get("folderUid") or ""
        # preserve id/version for overwrite
        dash["id"] = meta["dashboard"]["id"]
        dash["uid"] = uid
        dash["version"] = meta["dashboard"].get("version")
        api(
            env,
            "POST",
            "/api/dashboards/db",
            {
                "dashboard": dash,
                "folderUid": folder,
                "message": "BGP panels: use gnmic OTEL metric names (job=gnmic)",
                "overwrite": True,
            },
        )
        print(f"uploaded {fname} -> {uid}")


if __name__ == "__main__":
    main()
