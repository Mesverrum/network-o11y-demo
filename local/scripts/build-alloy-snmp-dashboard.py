#!/usr/bin/env python3
"""Build (and optionally import) the Alloy-native SNMP Device Details dashboard.

Curated `snmp_*` names (vital tags + MIB stems) — not kentik_snmp_*.
First import uses the legacy HTTP API (new classic dashboard).
UID: alloy-snmp-device-details.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

from lab_env import ROOT, load_dotenv

OUT = ROOT / ".dash-payloads" / "alloy-snmp"
UID = "alloy-snmp-device-details"
JOB = "alloy-snmp"
SEL = f'job="{JOB}",device_name=~"$device"'

DS = {"type": "prometheus", "uid": "${datasource}"}


def _target(expr: str, ref: str = "A", legend: str = "", instant: bool | None = None) -> dict:
    t: dict = {
        "refId": ref,
        "expr": expr,
        "datasource": DS,
    }
    if legend:
        t["legendFormat"] = legend
    if instant is not None:
        t["instant"] = instant
        t["format"] = "table" if instant else "time_series"
    return t


def _panel(
    pid: int,
    ptype: str,
    title: str,
    x: int,
    y: int,
    w: int,
    h: int,
    targets: list,
    unit: str | None = None,
    markdown: str | None = None,
) -> dict:
    p: dict = {
        "id": pid,
        "type": ptype,
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": DS,
        "targets": targets,
    }
    if unit:
        p["fieldConfig"] = {"defaults": {"unit": unit}, "overrides": []}
    if ptype == "text" and markdown is not None:
        p["options"] = {"mode": "markdown", "content": markdown}
        p["targets"] = []
        p["datasource"] = None
    if ptype == "stat":
        p["options"] = {
            "reduceOptions": {"calcs": ["lastNotNull"]},
            "colorMode": "value",
            "graphMode": "none",
        }
    return p


def dashboard() -> dict:
    proof = """## Proof queries (Explore)

Same stack as `GC_OTLP_*` / `GRAFANA_URL`. Curated `snmp_*` names, `job="alloy-snmp"`.

```promql
count by (device_name) (snmp_CPU{job="alloy-snmp"})
count by (device_name, ifName) (snmp_ifOperStatus{job="alloy-snmp"})
count by (device_name) (snmp_tBgpPeerNgConnState{job="alloy-snmp"})
```

Interface bps (snmp_exporter **counters**):

```promql
rate(snmp_ifHCInOctets{job="alloy-snmp",device_name=~"$device"}[$__rate_interval]) * 8
```

Memory % (Nokia; converter does not emit MemoryUtilization):

```promql
100 * snmp_MemoryUsed{job="alloy-snmp",device_name=~"$device"} / (snmp_MemoryUsed{job="alloy-snmp",device_name=~"$device"} + snmp_MemoryFree{job="alloy-snmp",device_name=~"$device"})
```

ktranslate A/B (lab still ships both): `count by (device_name) (kentik_snmp_CPU)`
"""
    return {
        "uid": UID,
        "title": "Alloy SNMP Device Details",
        "tags": ["alloy", "snmp", "network-lab"],
        "timezone": "browser",
        "schemaVersion": 42,
        "refresh": "1m",
        "time": {"from": "now-1h", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "datasource",
                    "type": "datasource",
                    "query": "prometheus",
                    "current": {"text": "grafanacloud-prom", "value": "grafanacloud-prom"},
                    "label": "Datasource",
                },
                {
                    "name": "device",
                    "type": "query",
                    "datasource": DS,
                    "definition": f'label_values(snmp_CPU{{job="{JOB}"}}, device_name)',
                    "query": {
                        "query": f'label_values(snmp_CPU{{job="{JOB}"}}, device_name)',
                        "refId": "StandardVariableQuery",
                    },
                    "includeAll": True,
                    "multi": True,
                    "allValue": ".*",
                    "current": {"text": "All", "value": "$__all"},
                    "label": "Device",
                    "refresh": 1,
                    "sort": 1,
                },
            ]
        },
        "panels": [
            _panel(
                1,
                "text",
                "Alloy SNMP (curated snmp_* names)",
                0,
                0,
                24,
                8,
                [],
                markdown=proof,
            ),
            _panel(
                2,
                "stat",
                "Devices (CPU present)",
                0,
                8,
                6,
                5,
                [_target(f'count by (device_name) (snmp_CPU{{job="{JOB}"}}) OR vector(0)', instant=True)],
            ),
            _panel(
                3,
                "gauge",
                "CPU %",
                6,
                8,
                6,
                5,
                [_target(f'snmp_CPU{{{SEL}}}', "A", "{{device_name}}")],
                unit="percent",
            ),
            _panel(
                4,
                "stat",
                "Memory used (KB)",
                12,
                8,
                6,
                5,
                [_target(f'snmp_MemoryUsed{{{SEL}}}', "A", "{{device_name}}")],
                unit="short",
            ),
            _panel(
                5,
                "stat",
                "Memory available (KB)",
                18,
                8,
                6,
                5,
                [_target(f'snmp_MemoryFree{{{SEL}}}', "A", "{{device_name}}")],
                unit="short",
            ),
            _panel(
                6,
                "timeseries",
                "CPU",
                0,
                13,
                12,
                8,
                [_target(f'snmp_CPU{{{SEL}}}', "A", "{{device_name}}")],
                unit="percent",
            ),
            _panel(
                7,
                "timeseries",
                "Memory used / available",
                12,
                13,
                12,
                8,
                [
                    _target(f'snmp_MemoryUsed{{{SEL}}}', "A", "{{device_name}} used"),
                    _target(f'snmp_MemoryFree{{{SEL}}}', "B", "{{device_name}} avail"),
                ],
                unit="short",
            ),
            _panel(
                8,
                "timeseries",
                "Interface bps (rate × 8)",
                0,
                21,
                24,
                10,
                [
                    _target(
                        f'rate(snmp_ifHCInOctets{{{SEL}}}[$__rate_interval]) * 8',
                        "A",
                        "{{device_name}} {{ifName}} in",
                    ),
                    _target(
                        f'rate(snmp_ifHCOutOctets{{{SEL}}}[$__rate_interval]) * 8',
                        "B",
                        "{{device_name}} {{ifName}} out",
                    ),
                ],
                unit="bps",
            ),
            _panel(
                9,
                "table",
                "Interface oper status",
                0,
                31,
                12,
                10,
                [_target(f'snmp_ifOperStatus{{{SEL}}}', instant=True)],
            ),
            _panel(
                10,
                "table",
                "BGP peer conn state",
                12,
                31,
                12,
                10,
                [_target(f'snmp_tBgpPeerNgConnState{{{SEL}}}', instant=True)],
            ),
            _panel(
                11,
                "table",
                "Hardware oper state",
                0,
                41,
                12,
                8,
                [_target(f'snmp_tmnxHwOperState{{{SEL}}}', instant=True)],
            ),
            _panel(
                12,
                "table",
                "Fan / PSU",
                12,
                41,
                12,
                8,
                [
                    _target(f'snmp_tmnxPhysChassisFanOperStatus{{{SEL}}}', "A", instant=True),
                    _target(f'snmp_tmnxPhysChassisPMOutputStatus{{{SEL}}}', "B", instant=True),
                ],
            ),
        ],
    }


def import_dashboard(dash: dict) -> None:
    load_dotenv()
    base = os.environ.get("GRAFANA_URL", "").rstrip("/")
    token = os.environ.get("GRAFANA_TOKEN", "")
    folder = os.environ.get("GRAFANA_FOLDER_UID", "network-lab")
    if not base or not token:
        raise SystemExit("set GRAFANA_URL and GRAFANA_TOKEN in local/.env to import")
    payload = {
        "dashboard": {k: v for k, v in dash.items() if k != "id"},
        "folderUid": folder,
        "overwrite": True,
        "message": "import alloy-snmp-device-details (curated snmp_* names)",
    }
    req = urllib.request.Request(
        base + "/api/dashboards/db",
        data=json.dumps(payload).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            out = json.load(resp)
    except urllib.error.HTTPError as exc:
        print(exc.read().decode(), file=sys.stderr)
        raise
    print(f"imported uid={out.get('uid')} url={out.get('url')}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="do_import", action="store_true")
    args = ap.parse_args()
    dash = dashboard()
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{UID}.json"
    path.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    if args.do_import:
        import_dashboard(dash)


if __name__ == "__main__":
    main()
