#!/usr/bin/env python3
"""Upsert the lab Alloy network pipeline into Grafana Fleet Management.

One pipeline (SNMP + traps/syslog + netflow). remotecfg cannot share the
local ConfigMap exporter, so this file ships its own OTLP sink.

Requires env (from local/.env):
  GC_FM_URL          e.g. https://fleet-management-prod-XXX.grafana.net
  GC_FM_USER         stack instance id (defaults to GC_OTLP_ACCOUNT)
  GC_FM_TOKEN        access policy token with fleet-management:read + write
                     (defaults to GC_OTLP_KEY)

Optional:
  GC_FM_PIPELINE_NAME   default network_o11y_alloy
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_FILE = ROOT / "fixtures" / "alloy-fleet" / "network.pipeline.alloy"
PIPELINE_FILE_SD = ROOT / "fixtures" / "alloy-fleet" / "snmp-scrape.pipeline.alloy"
LEGACY_PIPELINE_NAMES = (
    "network_o11y_alloy_snmp",
    "network_o11y_alloy_events",
    "network_o11y_alloy_netflow",
)


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def truthy(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


def detect_fm_url() -> str:
    """Collector app jsonData.agmClusterUrl — same as alloy-fleet-up.sh."""
    grafana = os.environ.get("GRAFANA_URL", "").rstrip("/")
    token = os.environ.get("GRAFANA_TOKEN", "")
    if not grafana or not token:
        return ""
    req = urllib.request.Request(
        grafana + "/api/plugins/grafana-collector-app/settings",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, json.JSONDecodeError):
        return ""
    return str((data.get("jsonData") or {}).get("agmClusterUrl") or "").rstrip("/")


def fm_post(base: str, path: str, body: dict, user: str, token: str) -> dict:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode()
    auth = f"Bearer {user}:{token}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise SystemExit(f"Fleet API {path} HTTP {e.code}: {err[:500]}") from e


def fm_post_ok(base: str, path: str, body: dict, user: str, token: str) -> dict | None:
    """Like fm_post but return None on HTTP error (legacy cleanup)."""
    url = base.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode()
    auth = f"Bearer {user}:{token}"
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": auth,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        print(f"WARN: Fleet API {path} HTTP {e.code}: {err[:240]}", file=sys.stderr)
        return None


def upsert(base: str, user: str, token: str, name: str, contents: str, matchers: list[str]) -> dict:
    out = fm_post(
        base,
        "pipeline.v1.PipelineService/UpsertPipeline",
        {
            "pipeline": {
                "name": name,
                "contents": contents,
                "matchers": matchers,
                "enabled": True,
            }
        },
        user,
        token,
    )
    pipe = out.get("pipeline") or out
    print(
        json.dumps(
            {
                "name": pipe.get("name") or name,
                "id": pipe.get("id"),
                "enabled": pipe.get("enabled"),
                "matchers": pipe.get("matchers") or matchers,
            },
            indent=2,
        )
    )
    return pipe


def delete_legacy(base: str, user: str, token: str) -> None:
    """Remove the old split pipelines so they cannot double-bind UDP or double-scrape."""
    ids: list[str] = []
    for name in LEGACY_PIPELINE_NAMES:
        out = fm_post_ok(
            base,
            "pipeline.v1.PipelineService/GetPipelineID",
            {"name": name},
            user,
            token,
        )
        pid = (out or {}).get("id") or (out or {}).get("pipeline_id")
        if not pid:
            print(f"==> no legacy pipeline {name}", file=sys.stderr)
            continue
        ids.append(str(pid))
        print(f"==> delete legacy {name} id={pid}", file=sys.stderr)
        fm_post_ok(
            base,
            "pipeline.v1.PipelineService/DeletePipeline",
            {"id": str(pid)},
            user,
            token,
        )


def main() -> int:
    load_dotenv(ROOT / ".env")
    base = os.environ.get("GC_FM_URL", "").rstrip("/")
    if not base:
        detected = detect_fm_url()
        if detected:
            base = detected
            os.environ["GC_FM_URL"] = detected
            print(f"==> detected GC_FM_URL={detected}", file=sys.stderr)
    user = os.environ.get("GC_FM_USER") or os.environ.get("GC_OTLP_ACCOUNT", "")
    token = os.environ.get("GC_FM_TOKEN") or os.environ.get("GC_OTLP_KEY", "")
    if not base or not user or not token:
        print(
            "ERROR: set GC_FM_URL, GC_FM_TOKEN (or GC_OTLP_KEY), and GC_FM_USER "
            "(or GC_OTLP_ACCOUNT).\n"
            "Copy the remotecfg Base URL from Grafana Cloud → Connections → "
            "Collector → Fleet Management → API tab.\n"
            "Token needs fleet-management:read and fleet-management:write.",
            file=sys.stderr,
        )
        return 2

    matchers = [
        'lab="network-o11y-demo"',
        'role="network-snmp"',
    ]
    use_discovery = truthy(os.environ.get("LAB_ALLOY_FLEET_DISCOVERY", "1"))
    pipeline_file = PIPELINE_FILE if use_discovery else PIPELINE_FILE_SD
    if not pipeline_file.is_file():
        print(f"ERROR: missing {pipeline_file}", file=sys.stderr)
        return 2
    if not use_discovery:
        print(
            "WARN: LAB_ALLOY_FLEET_DISCOVERY=0 upserts SNMP file_sd only "
            f"({pipeline_file.name}); traps/netflow stay out of Fleet.",
            file=sys.stderr,
        )

    name = os.environ.get("GC_FM_PIPELINE_NAME", "network_o11y_alloy")
    print(f"==> {name} from {pipeline_file.name}", file=sys.stderr)
    upsert(base, user, token, name, pipeline_file.read_text(encoding="utf-8"), matchers)
    delete_legacy(base, user, token)
    print("==> upserted Fleet pipeline", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
