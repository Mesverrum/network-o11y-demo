#!/usr/bin/env python3
"""Create the SE-demo NetPath traceroute check on networko11ydev.

Mints an SM access token via the Grafana plugin install proxy (publisher
token never leaves Grafana), then POSTs the check to SM us-east-3.
Token is written to gitignored local/state/sm-api-networko11ydev.token.

Usage:
  python3 local/scripts/provision-se-netpath-check.py
"""
from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "local" / "state"
TOKEN_PATH = STATE / "sm-api-networko11ydev.token"
SM_API = "https://synthetic-monitoring-api-us-east-3.grafana.net/api/v1"
JOB = "se-demo-netpath-traceroute"
TARGET = "grafana.com"
PROBE_NAMES = ("Ohio", "NorthVirginia")
UI = "https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / "local" / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def req(url: str, token: str, method: str = "GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(request, context=ctx, timeout=45) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw[:400].decode("utf-8", "replace")
        raise RuntimeError(f"{e.code} {url}: {parsed}") from e


def grafana_token() -> str:
    env = load_env()
    tok = env.get("GRAFANA_TOKEN_2", "").strip()
    if not tok:
        raise SystemExit("GRAFANA_TOKEN_2 missing in local/.env")
    return tok


def mint_sm_token(g_token: str) -> str:
    env = load_env()
    base = env["GRAFANA_URL_2"].rstrip("/")
    code, body = req(
        base + "/api/plugin-proxy/grafana-synthetic-monitoring-app/install",
        g_token,
        method="POST",
        body={
            "stackId": 1544961,
            "metricsInstanceId": 3014150,
            "logsInstanceId": 1502750,
        },
    )
    if code != 200 or not isinstance(body, dict) or not body.get("accessToken"):
        raise SystemExit(f"install proxy did not return accessToken (status {code})")
    STATE.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(body["accessToken"] + "\n", encoding="utf-8")
    print(f"wrote {TOKEN_PATH} len={len(body['accessToken'])}")
    return body["accessToken"]


def sm_get(path: str, sm_tok: str):
    _, body = req(f"{SM_API}/{path.lstrip('/')}", sm_tok)
    return body


def sm_post(path: str, sm_tok: str, payload: dict):
    _, body = req(f"{SM_API}/{path.lstrip('/')}", sm_tok, method="POST", body=payload)
    return body


def main() -> int:
    g_token = grafana_token()
    sm_tok = mint_sm_token(g_token)
    probes = sm_get("probe", sm_tok)
    plist = probes if isinstance(probes, list) else (probes or {}).get("probes", [])
    by_name = {p["name"]: int(p["id"]) for p in plist}
    probe_ids = []
    for name in PROBE_NAMES:
        if name not in by_name:
            raise SystemExit(f"probe {name} not found; have {sorted(by_name)[:20]}")
        probe_ids.append(by_name[name])
        print(f"probe {name} id={by_name[name]} online={next(p.get('online') for p in plist if p['name']==name)}")

    checks = sm_get("check", sm_tok)
    clist = checks if isinstance(checks, list) else (checks or {}).get("checks", [])
    existing = next((c for c in clist if c.get("job") == JOB), None)
    if existing:
        print(f"already exists id={existing.get('id')} job={JOB} target={existing.get('target')}")
        print(f"UI {UI}/{existing.get('id')}")
        return 0

    payload = {
        "job": JOB,
        "target": TARGET,
        "frequency": 120000,
        "timeout": 30000,
        "enabled": True,
        "probes": probe_ids,
        "labels": [
            {"name": "project", "value": "se-demo"},
            {"name": "check_type", "value": "traceroute"},
            {"name": "story", "value": "netpath"},
        ],
        "settings": {
            "traceroute": {
                "maxHops": 25,
                "maxUnknownHops": 10,
                "ptrLookup": True,
            }
        },
    }
    created = sm_post("check", sm_tok, payload)
    cid = created.get("id") if isinstance(created, dict) else None
    print(f"created job={JOB} target={TARGET} id={cid}")
    print(f"UI {UI}" + (f"/{cid}" if cid else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
