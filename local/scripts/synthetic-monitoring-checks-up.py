#!/usr/bin/env python3
"""Create Synthetic Monitoring checks via SM REST API (local/synthetic-monitoring/checks/*.yaml)."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
CHECKS = ROOT / "local" / "synthetic-monitoring" / "checks"
STATE = ROOT / "local" / "state"
SM_API = os.environ.get(
    "GRAFANA_SM_API_URL",
    "https://synthetic-monitoring-api-us-east-0.grafana.net/api/v1",
).rstrip("/")

import importlib.util

_spec = importlib.util.spec_from_file_location("sm_creds", Path(__file__).parent / "sm_creds.py")
_sm = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(_sm)

try:
    import yaml
except ImportError:
    yaml = None  # type: ignore


def api_request(method: str, path: str, token: str, body: dict | None = None) -> Any:
    url = f"{SM_API}/{path.lstrip('/')}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read()
        return json.loads(raw) if raw else None


def probe_map(token: str) -> dict[str, int]:
    out = api_request("GET", "probe", token)
    probes = out if isinstance(out, list) else out.get("probes", [])
    return {p["name"]: int(p["id"]) for p in probes}


def existing_jobs(token: str) -> set[str]:
    out = api_request("GET", "check", token)
    checks = out if isinstance(out, list) else out.get("checks", [])
    return {c["job"] for c in checks}


def yaml_to_payload(doc: dict[str, Any], probes_by_name: dict[str, int]) -> dict[str, Any]:
    spec = doc.get("spec") or {}
    probe_ids = []
    for name in spec.get("probes") or []:
        pid = probes_by_name.get(name)
        if pid is None:
            raise ValueError(f"unknown probe name: {name}")
        probe_ids.append(pid)
    labels = spec.get("labels") or []
    if isinstance(labels, dict):
        labels = [{"name": k, "value": v} for k, v in labels.items()]
    payload: dict[str, Any] = {
        "job": spec["job"],
        "target": spec["target"],
        "frequency": int(spec.get("frequency", 60000)),
        "timeout": int(spec.get("timeout", 10000)),
        "enabled": bool(spec.get("enabled", True)),
        "probes": probe_ids,
        "labels": labels,
        "settings": spec.get("settings") or {},
    }
    return payload


def main() -> int:
    if yaml is None:
        print("pip install pyyaml", file=sys.stderr)
        return 1

    token = os.environ.get("GRAFANA_SM_ACCESS_TOKEN", "").strip() or _sm.sm_api_access_token()
    if not token:
        print("Save SM management API token to local/state/sm-api.token", file=sys.stderr)
        return 1

    probes_by_name = probe_map(token)
    jobs = existing_jobs(token)
    ok = 0
    for path in sorted(CHECKS.glob("*.yaml")):
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        job = (doc.get("spec") or {}).get("job", path.stem)
        if job in jobs:
            print(f"skip {path.name} (job {job} already exists)")
            ok += 1
            continue
        print(f"Creating {path.name} ({job})...")
        try:
            payload = yaml_to_payload(doc, probes_by_name)
            api_request("POST", "check", token, payload)
            ok += 1
            jobs.add(job)
        except urllib.error.HTTPError as e:
            print(f"  failed: {e.code} {e.read().decode()[:300]}", file=sys.stderr)
        except ValueError as e:
            print(f"  failed: {e}", file=sys.stderr)
    total = len(list(CHECKS.glob("*.yaml")))
    print(f"Ready: {ok}/{total} checks")
    return 0 if ok == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
