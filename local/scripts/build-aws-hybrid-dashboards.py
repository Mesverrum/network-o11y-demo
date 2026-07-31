#!/usr/bin/env python3
"""Build hybrid connectivity + AWS capacity headroom dashboards.

Usage:
  python3 local/scripts/build-aws-hybrid-dashboards.py --import
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "aws-hybrid"
FOLDER_UID = "cloud-network"

# Import shared metric constants/helpers from CSP builder
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
gauge_panel = csp.gauge_panel
api_request = csp.api_request
ensure_folder = csp.ensure_folder
import_dashboard = csp.import_dashboard

NAT = csp.NAT_OUT
NAT_OUT = csp.NAT_OUT
NAT_ERR = csp.NAT_ERR_PORT
NAT_PKT = csp.NAT_PKT_DROP
NAT_ACTIVE = csp.NAT_ACTIVE_CONN
NAT_GW = csp.NAT_GW_LABEL
nat_filter = csp.nat_filter
nat_total_bps = csp.nat_total_bps_expr
nat_egress_bps = csp.nat_egress_bps_expr
ALB_BYTES = csp.ALB_BYTES
ALB_REQUESTS = csp.ALB_REQUESTS
ALB_5XX = csp.ALB_5XX
ALB_LB = csp.ALB_LB_LABEL
NLB_BYTES = csp.NLB_BYTES
NLB_LCUS = csp.NLB_LCUS

# Documented AWS soft limits (per resource / AZ) — for headroom % panels
NAT_BW_LIMIT_BPS = 100e9  # 100 Gbps
NAT_CONN_LIMIT = 2_000_000  # concurrent connections (order of magnitude)
NLB_LCU_SOFT_LIMIT = 1000.0  # account soft planning number


def base_vars() -> list[dict]:
    return csp.base_vars()


def build_05_connectivity() -> dict[str, Any]:
    d = dash_meta("hybrid-connectivity-health", "05. Hybrid Connectivity Health")
    d["templating"] = {
        "list": base_vars()
        + [
            {
                "name": "agent_id",
                "type": "query",
                "datasource": ds(),
                "definition": "label_values(hybrid_probe_success, agent_id)",
                "query": {"query": "label_values(hybrid_probe_success, agent_id)", "refId": "A"},
                "includeAll": True,
                "allValue": ".*",
                "multi": True,
                "label": "Probe agent",
            }
        ]
    }
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            (
                "**You ↔ AWS path health.** Top rows use `hybrid_probe_*` from the mesh agents "
                "(laptop + AWS traffic hosts). Lower rows use CloudWatch NAT/ALB signals.\n\n"
                "Run probes: `make -C local hybrid-probe-laptop` and `make -C local hybrid-probe-aws`."
            ),
            y,
            3,
        )
    )
    y += 3
    panels.append(row("Synthetic mesh", y, 2))
    y += 1
    panels.extend(
        [
            stat_panel(
                3,
                "Probe success rate",
                'avg(hybrid_probe_success{agent_id=~"$agent_id"}) OR vector(0)',
                y,
                0,
                6,
                "percentunit",
            ),
            stat_panel(
                4,
                "Worst latency (p95 est.)",
                'quantile(0.95, hybrid_probe_latency_ms{agent_id=~"$agent_id"}) OR vector(0)',
                y,
                6,
                6,
                "ms",
            ),
            stat_panel(
                5,
                "Active probe agents",
                "count(count by (agent_id) (hybrid_probe_up)) OR vector(0)",
                y,
                12,
                6,
            ),
            stat_panel(
                6,
                "NAT port alloc errors (1h)",
                f"sum(increase({NAT_ERR}{nat_filter()}[1h])) OR vector(0)",
                y,
                18,
                6,
            ),
        ]
    )
    y += 5
    panels.append(
        ts_panel(
            7,
            "Probe latency by target",
            [
                prom_target(
                    'hybrid_probe_latency_ms{agent_id=~"$agent_id"}',
                    "{{agent_id}} → {{target}}",
                )
            ],
            y,
            unit="ms",
        )
    )
    y += 9
    panels.append(
        table_panel(
            8,
            "Mesh matrix (success now)",
            'hybrid_probe_success{agent_id=~"$agent_id"}',
            y,
            7,
        )
    )
    y += 7
    panels.append(row("AWS path indicators", y, 10))
    y += 1
    panels.append(
        ts_panel(
            11,
            "NAT internet egress (all gateways)",
            [
                prom_target(
                    f"sum by ({NAT_GW}) (rate({NAT_OUT}{nat_filter()}[$__rate_interval])) * 8",
                    "{{" + NAT_GW + "}}",
                )
            ],
            y,
            8,
        )
    )
    panels.append(
        ts_panel(
            12,
            "ALB request rate",
            [
                prom_target(
                    f"sum by ({ALB_LB}) (rate({ALB_REQUESTS}{{region=~\"$region\"}}[$__rate_interval]))",
                    "{{" + ALB_LB + "}}",
                )
            ],
            y,
            8,
            12,
            unit="reqps",
        )
    )
    y += 8
    panels.append(
        ts_panel(
            13,
            "Probe success over time",
            [
                prom_target(
                    'hybrid_probe_success{agent_id=~"$agent_id"}',
                    "{{agent_id}} → {{target}}",
                )
            ],
            y,
            unit="none",
        )
    )
    d["panels"] = panels
    return d


def build_06_capacity() -> dict[str, Any]:
    d = dash_meta("aws-capacity-headroom", "06. AWS Capacity & Headroom")
    d["templating"] = {"list": base_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            (
                "Throughput vs **documented AWS soft limits** (planning numbers, not hard throttle).\n\n"
                f"| Service | Limit used in panels |\n|---|---|\n"
                f"| NAT Gateway | {int(NAT_BW_LIMIT_BPS/1e9)} Gbps bandwidth; "
                f"{NAT_CONN_LIMIT/1e6:.0f}M conn scale |\n"
                f"| NLB | {int(NLB_LCU_SOFT_LIMIT)} LCUs (planning) |\n"
                f"| ALB | relative processed bytes / request rate (no single cap) |"
            ),
            y,
            4,
        )
    )
    y += 4
    panels.append(row("NAT Gateway", y, 2))
    y += 1
    panels.extend(
        [
            gauge_panel(
                3,
                "NAT bandwidth vs 100 Gbps",
                f"({nat_total_bps()}) / {NAT_BW_LIMIT_BPS}",
                y,
                0,
                8,
                1.0,
            ),
            gauge_panel(
                4,
                "NAT active connections vs 2M scale",
                f"(max({NAT_ACTIVE}{nat_filter()})) / {NAT_CONN_LIMIT}",
                y,
                8,
                8,
                1.0,
            ),
            stat_panel(
                5,
                "Port allocation errors",
                f"sum(increase({NAT_ERR}{nat_filter()}[1h])) OR vector(0)",
                y,
                16,
                8,
            ),
        ]
    )
    y += 6
    panels.append(
        ts_panel(
            6,
            "NAT total bandwidth (bps)",
            [prom_target(nat_total_bps(), "total")],
            y,
        )
    )
    y += 9
    panels.append(row("Network Load Balancer", y, 10))
    y += 1
    panels.extend(
        [
            gauge_panel(
                11,
                "NLB LCUs vs planning limit",
                f"(sum(rate({NLB_LCUS}{{region=~\"$region\"}}[$__rate_interval])) or vector(0)) / {NLB_LCU_SOFT_LIMIT}",
                y,
                0,
                12,
                1.0,
            ),
            ts_panel(
                12,
                "NLB processed bytes",
                [
                    prom_target(
                        f"sum by ({ALB_LB}) (rate({NLB_BYTES}{{region=~\"$region\"}}[$__rate_interval])) * 8",
                        "{{" + ALB_LB + "}}",
                    )
                ],
                y,
                8,
                12,
            ),
        ]
    )
    y += 8
    panels.append(row("Application Load Balancer", y, 20))
    y += 1
    panels.extend(
        [
            ts_panel(
                21,
                "ALB processed bytes (bps)",
                [
                    prom_target(
                        f"sum by ({ALB_LB}) (rate({ALB_BYTES}{{region=~\"$region\"}}[$__rate_interval])) * 8",
                        "{{" + ALB_LB + "}}",
                    )
                ],
                y,
                8,
                12,
            ),
            ts_panel(
                22,
                "ALB ELB 5xx rate",
                [
                    prom_target(
                        f"sum by ({ALB_LB}) (rate({ALB_5XX}{{region=~\"$region\"}}[$__rate_interval]))",
                        "{{" + ALB_LB + "}}",
                    )
                ],
                y,
                8,
                12,
                unit="ops",
            ),
        ]
    )
    y += 8
    panels.append(row("EC2 network (ASG aggregate)", y, 30))
    y += 1
    panels.append(
        ts_panel(
            31,
            "EC2 network packets/s by ASG",
            [
                prom_target(
                    f"sum by ({csp.EC2_GROUP_LABEL}) (rate({csp.EC2_NET_IN}{{region=~\"$region\"}}[$__rate_interval])"
                    f" + rate({csp.EC2_NET_OUT}{{region=~\"$region\"}}[$__rate_interval]))",
                    "{{" + csp.EC2_GROUP_LABEL + "}}",
                )
            ],
            y,
            unit="pps",
        )
    )
    d["panels"] = panels
    return d


CATALOG = [
    ("05-hybrid-connectivity-health.json", build_05_connectivity),
    ("06-aws-capacity-headroom.json", build_06_capacity),
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
        print(f"\nImport: python3 {Path(__file__).name} --import")
        return 0

    env = load_env()
    base = env.get("GRAFANA_URL", "").rstrip("/")
    token = env.get("GRAFANA_TOKEN", "")
    if not base or not token.startswith("glsa_"):
        print("ERROR: GRAFANA_URL + GRAFANA_TOKEN in local/.env")
        return 1

    ensure_folder(base, token)
    ok = 0
    for fname, dash in built:
        code, out = import_dashboard(base, token, dash)
        if 200 <= code < 300:
            url = out.get("url", "") if isinstance(out, dict) else ""
            print(f"imported {dash['title']} HTTP {code} {url}")
            ok += 1
        else:
            print(f"FAILED {fname} HTTP {code}: {out}")
    return 0 if ok == len(built) else 1


if __name__ == "__main__":
    raise SystemExit(main())
