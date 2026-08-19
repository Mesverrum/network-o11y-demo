#!/usr/bin/env python3
"""Upsert the lab Alloy SNMP scrape pipeline into Grafana Fleet Management.

Requires env (from local/.env):
  GC_FM_URL          e.g. https://fleet-management-prod-XXX.grafana.net
  GC_FM_USER         stack instance id (defaults to GC_OTLP_ACCOUNT)
  GC_FM_TOKEN        access policy token with fleet-management:read + write

Optional:
  GC_FM_PIPELINE_NAME        default network_o11y_alloy_snmp
  LAB_ALLOY_FLEET_DISCOVERY  1 (default) = discovery.snmp pipeline;
                             0 = local.file snmp-targets.yml pipeline
  LAB_ALLOY_SNMP_TOPOLOGY=1  append topology scrape (file_sd pipeline only)
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIPELINE_FILE_SD = ROOT / "fixtures" / "alloy-fleet" / "snmp-scrape.pipeline.alloy"
PIPELINE_FILE_DISC = ROOT / "fixtures" / "alloy-fleet" / "snmp-discovery.pipeline.alloy"
TOPO_SNIPPET = ROOT / "fixtures" / "alloy-fleet" / "snmp-topology.pipeline.snippet.alloy"


def load_dotenv(path: Path) -> None:
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def truthy(v: str | None) -> bool:
    return (v or "").strip().lower() in {"1", "true", "yes", "on"}


def fm_post(base: str, path: str, body: dict, user: str, token: str) -> dict:
    url = base.rstrip("/") + "/" + path.lstrip("/")
    data = json.dumps(body).encode()
    # Fleet API accepts Bearer STACK:TOKEN
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


def main() -> int:
    load_dotenv(ROOT / ".env")
    base = os.environ.get("GC_FM_URL", "").rstrip("/")
    user = os.environ.get("GC_FM_USER") or os.environ.get("GC_OTLP_ACCOUNT", "")
    token = os.environ.get("GC_FM_TOKEN", "")
    name = os.environ.get("GC_FM_PIPELINE_NAME", "network_o11y_alloy_snmp")
    if not base or not user or not token:
        print(
            "ERROR: set GC_FM_URL, GC_FM_TOKEN, and GC_FM_USER (or GC_OTLP_ACCOUNT).\n"
            "Copy the remotecfg Base URL from Grafana Cloud → Connections → "
            "Collector → Fleet Management → API tab.\n"
            "Token needs fleet-management:read and fleet-management:write.",
            file=sys.stderr,
        )
        return 2

    use_discovery = truthy(os.environ.get("LAB_ALLOY_FLEET_DISCOVERY", "1"))
    pipeline_file = PIPELINE_FILE_DISC if use_discovery else PIPELINE_FILE_SD
    if not pipeline_file.is_file():
        print(f"ERROR: missing {pipeline_file}", file=sys.stderr)
        return 2
    contents = pipeline_file.read_text(encoding="utf-8")
    if (
        not use_discovery
        and truthy(os.environ.get("LAB_ALLOY_SNMP_TOPOLOGY"))
        and TOPO_SNIPPET.is_file()
    ):
        contents = contents.rstrip() + "\n\n" + TOPO_SNIPPET.read_text(encoding="utf-8")
    print(
        f"==> pipeline file {pipeline_file.name} "
        f"(LAB_ALLOY_FLEET_DISCOVERY={'1' if use_discovery else '0'})",
        file=sys.stderr,
    )

    matchers = [
        'lab="network-o11y-demo"',
        'role="network-snmp"',
    ]
    body = {
        "pipeline": {
            "name": name,
            "contents": contents,
            "matchers": matchers,
            "enabled": True,
        }
    }
    # UpsertPipeline
    out = fm_post(
        base,
        "pipeline.v1.PipelineService/UpsertPipeline",
        body,
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
    print("==> upserted Fleet pipeline", name, file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
