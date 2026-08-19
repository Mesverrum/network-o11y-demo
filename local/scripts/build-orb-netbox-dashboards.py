#!/usr/bin/env python3
"""Build + import Orb / NetBox / pktvisor dashboards on Grafana Cloud.

Usage:
  python3 local/scripts/build-orb-netbox-dashboards.py --import

Folder: Network Lab (uid network-lab). Classic JSON API (new boards).
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
FOLDER_TITLE = "Network Lab"

_spec = importlib.util.spec_from_file_location(
    "csp_dash", Path(__file__).parent / "build-aws-csp-dashboards.py"
)
csp = importlib.util.module_from_spec(_spec)
assert _spec.loader
_spec.loader.exec_module(csp)

ds = csp.ds
load_env = csp.load_env
dash_meta = csp.dash_meta
row = csp.row
text_panel = csp.text_panel
prom_target = csp.prom_target
stat_panel = csp.stat_panel
ts_panel = csp.ts_panel
table_panel = csp.table_panel
api_request = csp.api_request

# Live Orb snmp_discovery OTLP (seen on marcnetterfield1)
ORB = 'deployment_host=~"$host", service_name=~".*snmp-discovery.*"'
ORB_POL = f'{ORB}, policy=~"$policy"'
NB_API = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)
INFINITY_DS = {"type": "yesoreyeram-infinity-datasource", "uid": "netbox-api"}
# pktvisor / edge analytics (populate when ORB_PKTVISOR=1)
PV = 'deployment_host=~"$host"'


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


def infinity_devices_table(pid: int, title: str, y: int, h: int = 10) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "gridPos": {"h": h, "w": 24, "x": 0, "y": y},
        "datasource": INFINITY_DS,
        "targets": [
            {
                "refId": "A",
                "datasource": INFINITY_DS,
                "type": "json",
                "source": "url",
                "url": f"{NB_API}/api/dcim/devices/?limit=200",
                "url_options": {"method": "GET", "data": ""},
                "parser": "backend",
                "format": "table",
                "root_selector": "results",
                "columns": [
                    {"selector": "name", "text": "device_name", "type": "string"},
                    {"selector": "primary_ip.address", "text": "primary_ip", "type": "string"},
                    {"selector": "site.name", "text": "site", "type": "string"},
                    {"selector": "role.name", "text": "role", "type": "string"},
                    {"selector": "device_type.manufacturer.name", "text": "vendor", "type": "string"},
                    {"selector": "device_type.model", "text": "model", "type": "string"},
                    {"selector": "status.value", "text": "status", "type": "string"},
                    {"selector": "id", "text": "netbox_id", "type": "number"},
                ],
                "filters": [],
            }
        ],
        "options": {"showHeader": True, "cellHeight": "sm"},
        "fieldConfig": {"defaults": {}, "overrides": []},
        "description": (
            "Live NetBox REST via Infinity. Audit history lives in NetBox changelog/journal, "
            "not Grafana. Optional: a recording rule if someone later wants Grafana-side history "
            "of these latest counts."
        ),
    }


def host_vars(*, with_policy: bool = True) -> list[dict[str, Any]]:
    vars_: list[dict[str, Any]] = [
        {
            "name": "datasource",
            "type": "datasource",
            "query": "prometheus",
            "current": {"text": "grafanacloud-prom", "value": "grafanacloud-prom"},
            "label": "Datasource",
        },
        {
            "name": "host",
            "type": "custom",
            "label": "deployment_host",
            "query": "aws-colocated-lab,.*",
            "current": {"text": "aws-colocated-lab", "value": "aws-colocated-lab"},
            "options": [
                {"text": "aws-colocated-lab", "value": "aws-colocated-lab", "selected": True},
                {"text": "All", "value": ".*", "selected": False},
            ],
        },
    ]
    if with_policy:
        vars_.append(
            {
                "name": "policy",
                "type": "query",
                "datasource": ds(),
                "label": "Orb policy",
                "definition": f'label_values(discovered_hosts{{{ORB}}}, policy)',
                "query": {
                    "query": f'label_values(discovered_hosts{{{ORB}}}, policy)',
                    "refId": "A",
                },
                "includeAll": True,
                "allValue": ".*",
                "multi": True,
                "refresh": 2,
                "current": {"text": "All", "value": "$__all"},
            }
        )
    return vars_


def ensure_folder(base: str, token: str) -> None:
    code, _ = api_request(base, token, "GET", f"/api/folders/{FOLDER_UID}")
    if code == 200:
        return
    code, out = api_request(
        base, token, "POST", "/api/folders", {"uid": FOLDER_UID, "title": FOLDER_TITLE}
    )
    if code not in (200, 409, 412):
        raise RuntimeError(f"create folder failed HTTP {code}: {out}")


def import_dashboard(base: str, token: str, dash: dict) -> tuple[int, object]:
    payload = {"dashboard": dash, "folderUid": FOLDER_UID, "overwrite": True, "message": "orb/netbox/pktvisor boards"}
    return api_request(base, token, "POST", "/api/dashboards/db", payload)


def build_overview() -> dict[str, Any]:
    d = dash_meta(
        "orb-netbox-overview",
        "20. Orb + NetBox overview",
        tags=["orb", "netbox", "pktvisor", "network-lab"],
    )
    d["templating"] = {"list": host_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "What this stack proves — read metrics carefully",
            (
                "NetBox Labs path on **AWS colocated** (not a ktranslate replacement).\n\n"
                "**Important:** Orb Prom metric `discovered_hosts` is **misnamed**. "
                "In this lab it tracks **SNMP crawl entities per device** (device + interfaces + related objects, ~65–67), "
                "**not** distinct hosts. Orb logs show `responsive_target_count: 5` — that is the real device count "
                "(aligned with NetBox devices and ktranslate SNMP).\n\n"
                "| Stream | Source | Grafana signal |\n"
                "|--------|--------|----------------|\n"
                "| **Devices (SoT)** | Orb probe → Diode → NetBox | Infinity `netbox-api` `/api/dcim/devices/` |\n"
                "| **Interfaces (SoT)** | same crawl, reconciled | Infinity `netbox-api` `/api/dcim/interfaces/` |\n"
                "| Crawl entity fan-out | Orb `snmp_discovery` OTLP | `discovered_hosts` ≈ entities/device (NOT hosts) |\n"
                "| Device health | **ktranslate** | `kentik_snmp_*` |\n"
                "| Edge flow analytics | pktvisor (optional) | `flow_*` |\n\n"
                "UI: [NetBox](http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000/) · "
                "Drill: [Discovery](/d/orb-snmp-discovery) · [Inventory](/d/netbox-inventory-sot) · [pktvisor](/d/orb-pktvisor-edge)"
            ),
            y,
            h=10,
        )
    )
    y += 10
    panels.extend(
        [
            infinity_stat_panel(
                2,
                "NetBox devices (SoT)",
                "/api/dcim/devices/?limit=1",
                y,
                0,
                6,
                "Live NetBox REST via Infinity — compare to ktranslate SNMP device count.",
            ),
            infinity_stat_panel(
                3,
                "NetBox interfaces (SoT)",
                "/api/dcim/interfaces/?limit=1",
                y,
                6,
                6,
                "Live NetBox REST via Infinity — where Orb entity fan-out lands.",
            ),
            {
                **stat_panel(
                    4,
                    "Orb crawl entities (NOT hosts)",
                    f'max(discovered_hosts{{{ORB_POL}}}) OR vector(0)',
                    y,
                    12,
                    6,
                ),
                "description": "Misnamed metric: ~entities from last SNMP crawl on a device (device+ifaces+…), not distinct hosts. Logs: responsive_target_count≈5.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    5,
                    "ktranslate SNMP devices",
                    'count(count by (device_name) (kentik_snmp_CPU)) OR vector(0)',
                    y,
                    18,
                    6,
                ),
                "description": "Continuously polled devices — should align with NetBox device count / Orb responsive targets.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
        ]
    )
    y += 5
    panels.append(
        ts_panel(
            6,
            "Devices vs interfaces vs crawl entities (do not treat entities as hosts)",
            [
                {
                    **prom_target(
                        f'max(discovered_hosts{{{ORB_POL}}})',
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
        "Orb crawl entities vs ktranslate SNMP devices. NetBox device/interface counts are "
        "live Infinity stats on this board (not timeseries). Inventory audit history stays in "
        "NetBox changelog/journal."
    )
    d["panels"] = panels
    return d


def build_discovery() -> dict[str, Any]:
    d = dash_meta(
        "orb-snmp-discovery",
        "21. Orb SNMP discovery",
        tags=["orb", "snmp-discovery", "network-lab"],
    )
    d["templating"] = {"list": host_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "Orb snmp_discovery → Diode → NetBox",
            (
                "OTLP from Orb (`service_name=~snmp-discovery`). Payloads go to **Diode/NetBox**, not `kentik_snmp_*`.\n\n"
                "**How to read the numbers (lab):**\n"
                "1. Probe `172.20.20.0/24` (~256 addresses).\n"
                "2. Logs: `responsive_target_count: 5` → **5 SNMP devices** (same set as NetBox/ktranslate).\n"
                "3. Per device, crawl emits ~**65–67 entities** (device + interfaces + related).\n"
                "4. Prom `discovered_hosts` ≈ that **entity fan-out** — **not** 65 hosts.\n"
                "5. NetBox ends up with ~5 devices and hundreds of **interfaces** after reconcile.\n\n"
                "Filter: `deployment_host` + `policy` (default `lab_clos_snmp`)."
            ),
            y,
            h=8,
        )
    )
    y += 8
    panels.append(row("Health", y, 10))
    y += 1
    panels.extend(
        [
            {
                **stat_panel(
                    2,
                    "Crawl entities (discovered_hosts)",
                    f'max(discovered_hosts{{{ORB_POL}}}) OR vector(0)',
                    y,
                    0,
                    6,
                ),
                "description": "NOT host count. ~entities from last SNMP crawl (device+interfaces+…). Compare to NetBox interface count.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    3,
                    "SNMP devices (ktranslate proxy)",
                    'count(count by (device_name) (kentik_snmp_CPU)) OR vector(0)',
                    y,
                    6,
                    6,
                ),
                "description": "Proxy for Orb responsive_target_count (not exported as Prom yet). Should be ~5 in this lab.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    4,
                    "Success /s",
                    f'sum(rate(discovery_success_total{{{ORB_POL}}}[$__rate_interval])) OR vector(0)',
                    y,
                    12,
                    6,
                ),
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    5,
                    "Failure /s",
                    f'sum(rate(discovery_failure_total{{{ORB_POL}}}[$__rate_interval])) OR vector(0)',
                    y,
                    18,
                    6,
                ),
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
        ]
    )
    y += 5
    panels.append(
        ts_panel(
            6,
            "Crawl entities over time (metric name discovered_hosts — not hosts)",
            [
                {
                    **prom_target(
                        f'max by (policy) (discovered_hosts{{{ORB_POL}}})', "{{policy}}"
                    ),
                    "refId": "A",
                }
            ],
            y,
            unit="none",
            h=8,
        )
    )
    y += 8
    panels.append(
        ts_panel(
            7,
            "Discovery attempts / success / failure",
            [
                {**prom_target(f'sum(rate(discovery_attempts_total{{{ORB_POL}}}[$__rate_interval]))', "attempts"), "refId": "A"},
                {**prom_target(f'sum(rate(discovery_success_total{{{ORB_POL}}}[$__rate_interval]))', "success"), "refId": "B"},
                {**prom_target(f'sum(rate(discovery_failure_total{{{ORB_POL}}}[$__rate_interval]))', "failure"), "refId": "C"},
            ],
            y,
            unit="ops",
            h=8,
        )
    )
    y += 8
    panels.append(
        ts_panel(
            8,
            "Discovery latency (p95)",
            [
                {
                    **prom_target(
                        f'histogram_quantile(0.95, sum by (le) (rate(discovery_latency_bucket{{{ORB_POL}}}[$__rate_interval])))',
                        "p95",
                    ),
                    "refId": "A",
                }
            ],
            y,
            unit="s",
            h=8,
            w=12,
        )
    )
    panels.append(
        ts_panel(
            9,
            "Diode API latency (p95)",
            [
                {
                    **prom_target(
                        f'histogram_quantile(0.95, sum by (le) (rate(api_response_latency_bucket{{{ORB}}}[$__rate_interval])))',
                        "p95",
                    ),
                    "refId": "A",
                }
            ],
            y,
            unit="s",
            h=8,
            w=12,
            x=12,
        )
    )
    y += 8
    panels.append(
        ts_panel(
            11,
            "API requests /s",
            [{**prom_target(f'sum(rate(api_requests_total{{{ORB}}}[$__rate_interval]))', "api_requests"), "refId": "A"}],
            y,
            unit="reqps",
            h=7,
        )
    )
    d["panels"] = panels
    return d


def build_netbox() -> dict[str, Any]:
    d = dash_meta(
        "netbox-inventory-sot",
        "22. NetBox inventory (SoT)",
        tags=["netbox", "orb", "network-lab"],
    )
    d["templating"] = {"list": host_vars(with_policy=False)}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "NetBox → Grafana path",
            (
                "Devices land in NetBox via **Orb → Diode**. "
                "Grafana Cloud queries NetBox **live** via Infinity datasource `netbox-api` "
                "(`/api/dcim/devices/`, `/api/dcim/interfaces/`). Inventory **audit history** stays in "
                "NetBox changelog/journal — Grafana shows latest SoT, not a CMDB timeseries. "
                "Optional later: a Prometheus recording rule from these Infinity snapshots.\n\n"
                "**Compare apples to apples:** NetBox **device** count ≈ ktranslate SNMP devices ≈ Orb "
                "`responsive_target_count` (logs). Orb `discovered_hosts` is crawl **entities** "
                "(device+interfaces), closer in spirit to NetBox **interface** count than to device count.\n\n"
                "NetBox UI: http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000/ "
                "(login `admin` / `NETBOX_ADMIN_PASSWORD` in `local/.env`)."
            ),
            y,
            h=7,
        )
    )
    y += 7
    panels.extend(
        [
            infinity_stat_panel(
                2,
                "NetBox devices",
                "/api/dcim/devices/?limit=1",
                y,
                0,
                6,
            ),
            infinity_stat_panel(
                3,
                "NetBox interfaces",
                "/api/dcim/interfaces/?limit=1",
                y,
                6,
                6,
                "Where Orb interface entities land after Diode.",
            ),
            {
                **stat_panel(
                    4,
                    "Orb crawl entities (NOT hosts)",
                    f'max(discovered_hosts{{deployment_host=~"$host", service_name=~".*snmp-discovery.*"}}) OR vector(0)',
                    y,
                    12,
                    6,
                ),
                "description": "Misnamed discovered_hosts ≈ entities/device crawl.",
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
            {
                **stat_panel(
                    5,
                    "ktranslate SNMP devices",
                    'count(count by (device_name) (kentik_snmp_CPU)) OR vector(0)',
                    y,
                    18,
                    6,
                ),
                "options": {"reduceOptions": {"calcs": ["lastNotNull"]}},
            },
        ]
    )
    y += 5
    panels.append(
        text_panel(
            50,
            "Inventory history",
            (
                "Grafana shows **current** NetBox SoT via Infinity. Who-changed-what lives in "
                "**NetBox changelog / journal**. Do not revive `netbox-inventory-otlp`. "
                "If an operator later wants Grafana-side history of latest counts, add a recording "
                "rule — that is optional, not part of this lab."
            ),
            y,
            h=4,
        )
    )
    y += 4
    panels.append(infinity_devices_table(6, "NetBox devices (live REST)", y, h=10))
    y += 10
    panels.append(
        text_panel(
            7,
            "Gap checklist",
            (
                "1. NetBox **device** list ≈ ktranslate SNMP devices ≈ Orb responsive SNMP targets.\n"
                "2. NetBox **interfaces** ≫ devices — that is expected Orb entity fan-out after Diode.\n"
                "3. Do **not** treat Prom `discovered_hosts` as host inventory — it is crawl entities.\n"
                "4. `kentik_snmp_*` stays on ktranslate — Orb does not replace continuous SNMP health."
            ),
            y,
            h=4,
        )
    )
    d["panels"] = panels
    return d


def build_pktvisor() -> dict[str, Any]:
    d = dash_meta(
        "orb-pktvisor-edge",
        "23. Orb pktvisor edge analytics",
        tags=["orb", "pktvisor", "network-lab"],
    )
    d["templating"] = {"list": host_vars(with_policy=False)}
    y = 0
    panels: list[dict] = []
    # Live pktvisor flow handler OTLP: flow_in_*, flow_out_*, flow_top_*, flow_cardinality_*
    panels.append(
        text_panel(
            1,
            "pktvisor flow analytics (no PCAP)",
            (
                "Orb **pktvisor** NetFlow `:19995` + sFlow `:16343` → OTLP → Grafana. "
                "softflowd dual-exports to ktranslate `:9995` and pktvisor; spine sFlow collector 2 → `:16343`.\n\n"
                "Handler: `flow` only (`dns`/`dhcp`/`net` need PCAP). Metrics: `flow_in_*`, `flow_out_*`, `flow_top_*`."
            ),
            y,
            h=5,
        )
    )
    y += 5
    panels.extend(
        [
            {**stat_panel(2, "Flow records", 'sum(flow_records_flows) OR vector(0)', y, 0, 6), "options": {"reduceOptions": {"calcs": ["lastNotNull"]}}},
            {**stat_panel(3, "In packets", 'sum(flow_in_packets) OR vector(0)', y, 6, 6), "options": {"reduceOptions": {"calcs": ["lastNotNull"]}}},
            {**stat_panel(4, "Out packets", 'sum(flow_out_packets) OR vector(0)', y, 12, 6), "options": {"reduceOptions": {"calcs": ["lastNotNull"]}}},
            {**stat_panel(5, "Conversations (card.)", 'sum(flow_cardinality_conversations) OR vector(0)', y, 18, 6), "options": {"reduceOptions": {"calcs": ["lastNotNull"]}}},
        ]
    )
    y += 5
    panels.append(
        ts_panel(
            6,
            "Bytes in / out",
            [
                {**prom_target("sum(flow_in_bytes)", "in_bytes"), "refId": "A"},
                {**prom_target("sum(flow_out_bytes)", "out_bytes"), "refId": "B"},
            ],
            y,
            unit="decbytes",
            h=8,
        )
    )
    y += 8
    panels.append(
        ts_panel(
            7,
            "Packets by L4 (in)",
            [
                {**prom_target("sum(flow_in_udp_packets)", "udp"), "refId": "A"},
                {**prom_target("sum(flow_in_tcp_packets)", "tcp"), "refId": "B"},
                {**prom_target("sum(flow_in_other_l4_packets)", "other"), "refId": "C"},
            ],
            y,
            unit="pps",
            h=8,
            w=12,
        )
    )
    panels.append(
        ts_panel(
            8,
            "Cardinality (IPs / ports)",
            [
                {**prom_target("sum(flow_cardinality_src_ips_in)", "src_ips_in"), "refId": "A"},
                {**prom_target("sum(flow_cardinality_dst_ips_out)", "dst_ips_out"), "refId": "B"},
                {**prom_target("sum(flow_cardinality_src_ports_in)", "src_ports"), "refId": "C"},
                {**prom_target("sum(flow_cardinality_dst_ports_out)", "dst_ports"), "refId": "D"},
            ],
            y,
            unit="none",
            h=8,
            w=12,
            x=12,
        )
    )
    y += 8
    panels.append(
        {
            **table_panel(
                9,
                "Top conversations (bytes)",
                "topk(15, flow_top_conversations_bytes)",
                y,
                h=9,
            ),
            "transformations": [
                {"id": "labelsToFields", "options": {}},
                {"id": "merge", "options": {}},
                {"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True}}},
            ],
        }
    )
    y += 9
    panels.append(
        {
            **table_panel(
                10,
                "Top destination ports (in, bytes)",
                "topk(15, flow_top_in_dst_ports_bytes)",
                y,
                h=9,
            ),
            "transformations": [
                {"id": "labelsToFields", "options": {}},
                {"id": "merge", "options": {}},
                {"id": "organize", "options": {"excludeByName": {"Time": True, "__name__": True}}},
            ],
        }
    )
    d["panels"] = panels
    return d


CATALOG = [
    ("20-orb-netbox-overview.json", build_overview),
    ("21-orb-snmp-discovery.json", build_discovery),
    ("22-netbox-inventory-sot.json", build_netbox),
    ("23-orb-pktvisor-edge.json", build_pktvisor),
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import", dest="do_import", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    built: list[tuple[str, dict]] = []
    for fname, builder in CATALOG:
        dash = builder()
        path = OUT / fname
        path.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")
        built.append((fname, dash))

    if not args.do_import:
        print(f"\nDry-run. Import: python3 {Path(__file__).name} --import")
        return 0

    env = load_env()
    base = env.get("GRAFANA_URL", "").rstrip("/")
    token = env.get("GRAFANA_TOKEN", "")
    if not base or not token:
        print("ERROR: GRAFANA_URL + GRAFANA_TOKEN required in local/.env")
        return 1

    ensure_folder(base, token)
    ok = 0
    for fname, dash in built:
        code, out = import_dashboard(base, token, dash)
        url = ""
        if isinstance(out, dict):
            url = (out.get("url") or "") if code in (200, 201) else str(out)[:200]
        print(f"import {fname} HTTP {code} {url}")
        if code in (200, 201):
            ok += 1
    print(f"imported {ok}/{len(built)}")
    return 0 if ok == len(built) else 1


if __name__ == "__main__":
    raise SystemExit(main())
