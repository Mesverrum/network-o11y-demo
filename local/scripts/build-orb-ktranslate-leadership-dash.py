#!/usr/bin/env python3
"""Leadership dashboard: NetBox/Orb/pktvisor vs ktranslate — entity / KG readiness.

Usage:
  python3 local/scripts/build-orb-ktranslate-leadership-dash.py --import
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "orb-netbox"
FOLDER_UID = "network-lab"

_spec = importlib.util.spec_from_file_location(
    "csp_dash", Path(__file__).parent / "build-aws-csp-dashboards.py"
)
csp = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(csp)

ds = csp.ds
load_env = csp.load_env
dash_meta = csp.dash_meta
text_panel = csp.text_panel
prom_target = csp.prom_target
stat_panel = csp.stat_panel
ts_panel = csp.ts_panel
api_request = csp.api_request

NB_API = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)
INFINITY_DS = {"type": "yesoreyeram-infinity-datasource", "uid": "netbox-api"}


def infinity_count_target(api_path: str, ref: str = "A") -> dict[str, Any]:
    return {
        "refId": ref,
        "datasource": INFINITY_DS,
        "type": "json",
        "source": "url",
        "url": f"{NB_API}{api_path}",
        "parser": "backend",
        "format": "table",
        "root_selector": "",
        "json_options": {"root_is_not_array": True, "columnar": False},
        "columns": [{"selector": "count", "text": "count", "type": "number"}],
        "url_options": {"method": "GET", "data": ""},
        "filters": [],
    }


def infinity_stat_panel(
    pid: int,
    title: str,
    api_path: str,
    y: int,
    x: int,
    w: int,
    description: str = "",
) -> dict[str, Any]:
    p: dict[str, Any] = {
        "id": pid,
        "type": "stat",
        "title": title,
        "gridPos": {"h": 5, "w": w, "x": x, "y": y},
        "datasource": INFINITY_DS,
        "targets": [infinity_count_target(api_path)],
        "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
    }
    if description:
        p["description"] = description
    return p


def ensure_folder(base: str, token: str) -> None:
    code, _ = api_request(base, token, "GET", f"/api/folders/{FOLDER_UID}")
    if code == 200:
        return
    api_request(base, token, "POST", "/api/folders", {"uid": FOLDER_UID, "title": "Network Lab"})


def import_dashboard(base: str, token: str, dash: dict) -> tuple[int, object]:
    return api_request(
        base,
        token,
        "POST",
        "/api/dashboards/db",
        {
            "dashboard": dash,
            "folderUid": FOLDER_UID,
            "overwrite": True,
            "message": "leadership: orb/netbox vs ktranslate entity readiness",
        },
    )


BRIEF = """
### Why this board exists

Engineering leadership needs a clear split:

| Lane | Job | Primary tool in this lab |
|------|-----|--------------------------|
| **Observability (health + traffic)** | Continuous SNMP / flow / syslog / gNMI → dashboards & alerts | **ktranslate + gnmic → Alloy** (KtransToGrafana) |
| **Source of truth (inventory)** | Discover + reconcile network objects into a CMDB | **Orb SNMP discovery → Diode → NetBox** |
| **Edge flow analytics** | Alternate NetFlow/sFlow aggregation (cardinality, top-N) | **Orb pktvisor** — demo/overlap only |
| **Host / process entities (in flight)** | Service + host entities in Knowledge Graph | **Alloy + Beyla** (app/runtime), not SNMP |

### Grafana Labs — pktvisor demand

**pktvisor does not add a capability Grafana customers broadly ask us for versus ktranslate.**

- Flow taps ≈ same L4 conversation problem as ktranslate rollups (duplicate, not upgrade).
- NetBox relationships come from **snmp_discovery → Diode**, not pktvisor.
- PCAP DNS/wire analytics is a DDI/SecOps market (Infoblox/Umbrella-class); rare Grafana AE ask.
- Beyla may enrich app flows with reverse-DNS — that is not pktvisor-style DNS analytics.

### Cloud economics — rollups vs raw flows

| Path | What ships to Grafana Cloud | When it wins | When it breaks |
|------|----------------------------|--------------|----------------|
| **ktranslate rollups** (default) | Bounded top-K gauges (`network_io_by_flow_*`, ~60s) | Fleet NOC, alerts, long Metrics retention | Needle not in top-K; need exact 5-tuple history |
| **pktvisor flow_*** | Edge aggregates (still not raw) | Orb demos | Paying twice for overlapping series |
| **Raw / full-fidelity flow logs** | Every record → Loki/warehouse (or uncapped Prom) | Short forensics, security sample, tiny labs | Enterprise flow rates → cardinality & bill explosion in Metrics |

**Rule:** default Cloud customers to ktranslate rollups into Metrics; raw only as scoped Logs/warehouse — never unbounded Prom per 5-tuple.

### Knowledge Graph — where each tool fits

| Candidate entity | Best identity source today | Telemetry that attaches | Gap |
|------------------|----------------------------|-------------------------|-----|
| **Host** (servers) | Alloy resource attrs + Beyla | RED/USE, traces, profiles | In flight — not network gear |
| **Network device** | NetBox device UUID / name (SoT) | `kentik_snmp_*` by `device_name` | Need explicit **entity mapping** NetBox ↔ SNMP name/IP |
| **Interface** | NetBox interface + `ifIndex`/`ifName` | `kentik_snmp_ifHC*` | Same join problem; ifName renames |
| **L2 adjacency** | LLDP (`network_topology_edge_info`) | Topology subway / path | Edges exist; not KG-native yet |
| **Conversation / flow** | 5-tuple (+ catalog hostnames) | `network_io_by_flow_*` rollups | Ephemeral — edges, not durable entities |
| **Service** | OTel `service.name` | Traces + metrics | Join to network via peer IP/port (clos-join demo) |

**Bottom line**

1. **ktranslate** = production device health + **rollup** traffic plane (Cloud-economical).
2. **Orb + NetBox** = inventory / SoT → seed **network.device** KG entities.
3. **pktvisor** = optional Orb edge packaging — **not** a Grafana demand gap vs ktranslate.
4. **Alloy + Beyla** = host/service entities; network gear should **link**, not be invented by Beyla.
5. Treat Orb `discovered_hosts` as **crawl entities** (device+ifaces), not host inventory — compare devices to NetBox/ktranslate (~5), interfaces to NetBox iface count.
""".strip()


MATRIX = """
### Capability matrix (this lab)

| Capability | ktranslate stack | Orb / NetBox / pktvisor |
|------------|------------------|-------------------------|
| Continuous SNMP health (CPU, ifOctets, BGP…) | **Strong** — `kentik_snmp_*` | Weak — discovery only, not poll health |
| Device inventory SoT | Weak — YAML/catalog from discovery | **Strong** — NetBox + Diode |
| Wide SNMP discovery | Per-group CIDR discover | **Strong** — Orb snmp_discovery |
| NetFlow / sFlow for Cloud Metrics | **Strong** — **top-K rollups** | pktvisor `flow_*` (overlap; not a demand gap) |
| Raw flow forensics | Optional sidecar to Logs — not default | Same economics problem if you ship raw |
| Syslog / traps | **Strong** | Not in this sidecar |
| gNMI / LLDP topology | gnmic → `network_topology_edge_info` | Not Orb |
| Host/process KG entities | Indirect (join via IP) | Indirect (NetBox may hold server IPs) |
| First-class network KG entities | **Not yet** — labels only | **Closest** — NetBox UUID via Infinity REST |
| Deep DNS wire analytics | No | pktvisor PCAP — **low Grafana ICP demand** |

Drill: [Overview](/d/orb-netbox-overview) · [Orb discovery](/d/orb-snmp-discovery) · [NetBox SoT](/d/netbox-inventory-sot) · [pktvisor](/d/orb-pktvisor-edge) · [Device Summary](/d/ktranslate-device-summary) · [Flow Summary](/d/ktranslate-flow-summary)
""".strip()


def build() -> dict[str, Any]:
    d = dash_meta(
        "orb-ktranslate-entity-readiness",
        "24. Network SoT vs telemetry (leadership)",
        tags=["leadership", "orb", "netbox", "ktranslate", "knowledge-graph", "network-lab"],
    )
    d["templating"] = {
        "list": [
            {
                "name": "datasource",
                "type": "datasource",
                "query": "prometheus",
                "current": {"text": "grafanacloud-prom", "value": "grafanacloud-prom"},
                "label": "Datasource",
            }
        ]
    }
    d["time"] = {"from": "now-6h", "to": "now"}
    y = 0
    panels: list[dict] = []

    panels.append(text_panel(1, "Executive brief — Knowledge Graph & network objects", BRIEF, y, h=16))
    y += 16

    panels.append(text_panel(2, "Live lab — what each plane is counting", MATRIX, y, h=10))
    y += 10

    # Live scorecards
    panels.extend(
        [
            {
                **stat_panel(
                    3,
                    "ktranslate SNMP devices",
                    'count(count by (device_name) (kentik_snmp_CPU)) OR vector(0)',
                    y,
                    0,
                    4,
                ),
                "description": "Health plane — continuous poll. Identity = device_name label.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    4,
                    "kentik_snmp series",
                    'count({__name__=~"kentik_snmp.*"}) OR vector(0)',
                    y,
                    4,
                    4,
                ),
                "description": "Telemetry richness — not entity count.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    5,
                    "ktranslate flow conversations",
                    "count(network_io_by_flow_bytes) OR vector(0)",
                    y,
                    8,
                    4,
                ),
                "description": "Traffic plane rollups (softflowd → ktranslate).",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    6,
                    "Orb crawl entities (NOT hosts)",
                    'max(discovered_hosts{deployment_host="aws-colocated-lab"}) OR vector(0)',
                    y,
                    12,
                    4,
                ),
                "description": "Misnamed discovered_hosts ≈ SNMP crawl entities per device (device+interfaces), not distinct hosts. Logs: responsive_target_count≈5.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            infinity_stat_panel(
                7,
                "NetBox devices (SoT)",
                "/api/dcim/devices/?limit=1",
                y,
                16,
                4,
                "Live NetBox REST via Infinity — align with ktranslate / Orb responsive targets.",
            ),
            infinity_stat_panel(
                8,
                "NetBox interfaces (SoT)",
                "/api/dcim/interfaces/?limit=1",
                y,
                20,
                4,
                "Live NetBox REST via Infinity — interface fan-out after Diode.",
            ),
        ]
    )
    y += 5

    panels.append(
        ts_panel(
            9,
            "Orb crawl entities vs ktranslate SNMP devices",
            [
                {
                    **prom_target(
                        'max(discovered_hosts{deployment_host="aws-colocated-lab"})',
                        "Orb crawl entities (discovered_hosts)",
                    ),
                    "refId": "C",
                },
                {
                    **prom_target(
                        "count(count by (device_name) (kentik_snmp_CPU))",
                        "ktranslate SNMP devices",
                    ),
                    "refId": "D",
                },
            ],
            y,
            unit="none",
            h=9,
        )
    )
    panels[-1]["description"] = (
        "Orb crawl entities vs ktranslate SNMP devices. NetBox counts are live Infinity stats "
        "(not timeseries). Inventory audit history stays in NetBox changelog/journal."
    )
    y += 9

    panels.append(
        ts_panel(
            10,
            "Traffic planes — ktranslate rollups vs pktvisor bytes",
            [
                {
                    **prom_target(
                        "sum(network_io_by_flow_bytes) * 8 / 60",
                        "ktranslate flow bps (rollup)",
                    ),
                    "refId": "A",
                },
                {
                    **prom_target("sum(flow_in_bytes + flow_out_bytes)", "pktvisor in+out bytes"),
                    "refId": "B",
                },
            ],
            y,
            unit="none",
            h=8,
            w=12,
        )
    )
    panels.append(
        ts_panel(
            11,
            "Topology edges (LLDP via gnmic) — path for device↔device KG",
            [
                {
                    **prom_target("count(network_topology_edge_info)", "LLDP edges"),
                    "refId": "A",
                },
                {
                    **prom_target(
                        "count(network_topology_device_info) OR on() vector(0)",
                        "topology_exporter devices",
                    ),
                    "refId": "B",
                },
            ],
            y,
            unit="none",
            h=8,
            w=12,
            x=12,
        )
    )
    y += 8

    panels.extend(
        [
            {
                **stat_panel(
                    12,
                    "Entity demo (join-app) devices",
                    "count(entity_demo_device_info) OR vector(0)",
                    y,
                    0,
                    8,
                ),
                "description": "Lab prove/disprove identity models — 0 if join-app not running.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    13,
                    "clos_join entity overlay",
                    "count(clos_join_entity_info) OR vector(0)",
                    y,
                    8,
                    8,
                ),
                "description": "Service↔host↔leaf overlay for subway nodeGraph.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                "id": 14,
                "type": "stat",
                "title": "NetBox ifaces - devices (fan-out)",
                "gridPos": {"h": 5, "w": 8, "x": 16, "y": y},
                "datasource": {"type": "__expr__", "uid": "__expr__"},
                "targets": [
                    {**infinity_count_target("/api/dcim/interfaces/?limit=1", "A"), "hide": True},
                    {**infinity_count_target("/api/dcim/devices/?limit=1", "B"), "hide": True},
                    {
                        "refId": "C",
                        "datasource": {"type": "__expr__", "uid": "__expr__"},
                        "type": "sql",
                        "expression": 'SELECT A.count - B.count AS "Fan-out"',
                        "hide": False,
                    },
                ],
                "description": (
                    "Infinity: interface count minus device count. Expected Orb→Diode fan-out, "
                    "not a missing-host gap. Inventory audit history stays in NetBox."
                ),
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
        ]
    )
    y += 5

    panels.append(
        text_panel(
            15,
            "Decisions for engineering leadership",
            """
1. **Keep ktranslate** as the network observability standard (SNMP + **rollup** flows) — Cloud-economical NOC path.
2. **Keep Orb → Diode → NetBox** as inventory / SoT — seed **network.device** KG entities.
3. **Do not sell pktvisor as a Grafana demand gap vs ktranslate** — flow overlap; PCAP DNS is not a common ICP ask.
4. **Raw flow logs** only as scoped Loki/warehouse forensics — never unbounded Prom per 5-tuple.
5. **Alloy + Beyla** for host/service entities; link to fabric via NetBox + LLDP.
6. Do **not** treat Orb `discovered_hosts` as missing hosts — it is crawl entities; NetBox interface count is the SoT fan-out.
7. Inventory **audit history** lives in NetBox changelog/journal. Grafana Infinity is latest SoT only; a recording rule is optional later.

Open NetBox UI: http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000/
""".strip(),
            y,
            h=10,
        )
    )

    d["panels"] = panels
    return d


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import", dest="do_import", action="store_true")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    dash = build()
    path = OUT / "24-orb-ktranslate-entity-readiness.json"
    path.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    if not args.do_import:
        return 0
    env = load_env()
    base = env.get("GRAFANA_URL", "").rstrip("/")
    token = env.get("GRAFANA_TOKEN", "")
    if not base or not token:
        print("ERROR: GRAFANA_URL + GRAFANA_TOKEN required", file=sys.stderr)
        return 1
    ensure_folder(base, token)
    code, out = import_dashboard(base, token, dash)
    url = out.get("url") if isinstance(out, dict) else out
    print(f"import HTTP {code} {url}")
    return 0 if code in (200, 201) else 1


if __name__ == "__main__":
    raise SystemExit(main())
