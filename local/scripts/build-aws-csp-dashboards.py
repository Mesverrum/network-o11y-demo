#!/usr/bin/env python3
"""Build and import AWS CSP hybrid network dashboards (classic JSON API).

Dashboards from docs/aws-csp-observability-dashboards-draft.md

Usage:
  python3 local/scripts/build-aws-csp-dashboards.py              # write JSON only
  python3 local/scripts/build-aws-csp-dashboards.py --import     # write + POST to GC
"""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "aws-csp"
FOLDER_UID = "cloud-network"
FOLDER_TITLE = "Cloud Network"

# Grafana Cloud CloudWatch → Prometheus naming (underscore-separated metric names;
# resource dimensions use dimension_* labels, e.g. dimension_NatGatewayId).
NAT_OUT = "aws_natgateway_bytes_out_to_destination_sum"
NAT_IN_SRC = "aws_natgateway_bytes_in_from_source_sum"
NAT_IN_DST = "aws_natgateway_bytes_in_from_destination_sum"
NAT_OUT_SRC = "aws_natgateway_bytes_out_to_source_sum"
NAT_ERR_PORT = "aws_natgateway_error_port_allocation_sum"
NAT_PKT_DROP = "aws_natgateway_packets_drop_count_sum"
NAT_ACTIVE_CONN = "aws_natgateway_active_connection_count_maximum"
NAT_CONN_ATTEMPT = "aws_natgateway_connection_attempt_count_sum"
NAT_GW_LABEL = "dimension_NatGatewayId"

ALB_BYTES = "aws_applicationelb_processed_bytes_sum"
ALB_REQUESTS = "aws_applicationelb_request_count_sum"
ALB_5XX = "aws_applicationelb_httpcode_elb_5_xx_count_sum"
ALB_ACTIVE_CONN = "aws_applicationelb_active_connection_count_average"
ALB_LB_LABEL = "dimension_LoadBalancer"

FH_HTTP = "aws_firehose_delivery_to_http_endpoint_bytes_sum"
FH_S3 = "aws_firehose_delivery_to_s3_bytes_sum"

EC2_NET_IN = "aws_ec2_network_packets_in_sum"
EC2_NET_OUT = "aws_ec2_network_packets_out_sum"
EC2_GROUP_LABEL = "dimension_AutoScalingGroupName"

# Not yet in this account — panels show placeholders until provisioned.
VPN_TUNNEL = "aws_vpn_tunnel_state_average"
TGW_IN = "aws_transitgateway_bytes_in_sum"
TGW_OUT = "aws_transitgateway_bytes_out_sum"
TGW_ATTACH_LABEL = "dimension_TransitGatewayAttachmentId"
NLB_BYTES = "aws_networkelb_processed_bytes_sum"
NLB_LCUS = "aws_networkelb_consumed_lcus_sum"
NLB_LB_LABEL = "dimension_LoadBalancer"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def ds() -> dict[str, str]:
    return {"type": "prometheus", "uid": "${datasource}"}


def base_vars(extra: list[dict] | None = None) -> list[dict]:
    vars_: list[dict] = [
        {
            "name": "datasource",
            "type": "datasource",
            "query": "prometheus",
            "current": {"text": "grafanacloud-prom", "value": "grafanacloud-prom"},
            "label": "Datasource",
        },
        {
            "name": "region",
            "type": "query",
            "datasource": ds(),
            "definition": f'label_values({NAT_OUT}, region)',
            "query": {"query": f'label_values({NAT_OUT}, region)', "refId": "A"},
            "label": "Region",
            "includeAll": True,
            "allValue": ".*",
            "multi": True,
            "refresh": 2,
        },
        {
            "name": "nat_gateway_id",
            "type": "query",
            "datasource": ds(),
            "definition": f'label_values({NAT_OUT}{{region=~"$region"}}, {NAT_GW_LABEL})',
            "query": {
                "query": f'label_values({NAT_OUT}{{region=~"$region"}}, {NAT_GW_LABEL})',
                "refId": "A",
            },
            "label": "NAT Gateway",
            "includeAll": True,
            "allValue": ".*",
            "multi": True,
            "refresh": 2,
        },
    ]
    if extra:
        vars_.extend(extra)
    return vars_


def dash_meta(uid: str, title: str, tags: list[str] | None = None) -> dict[str, Any]:
    return {
        "uid": uid,
        "title": title,
        "tags": tags or ["aws", "cloud-network", "hybrid-o11y"],
        "timezone": "browser",
        "schemaVersion": 42,
        "version": 0,
        "refresh": "1m",
        "time": {"from": "now-24h", "to": "now"},
        "graphTooltip": 1,
        "editable": True,
    }


def row(title: str, y: int, panel_id: int) -> dict[str, Any]:
    return {
        "id": panel_id,
        "type": "row",
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
        "panels": [],
    }


def text_panel(pid: int, title: str, content: str, y: int, h: int = 4) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "text",
        "title": title,
        "gridPos": {"h": h, "w": 24, "x": 0, "y": y},
        "options": {"mode": "markdown", "content": content},
    }


def prom_target(expr: str, legend: str = "", instant: bool = False) -> dict[str, Any]:
    t: dict[str, Any] = {"refId": "A", "expr": expr, "datasource": ds()}
    if legend:
        t["legendFormat"] = legend
    if instant:
        t["instant"] = True
        t["range"] = False
    return t


def stat_panel(pid: int, title: str, expr: str, y: int, x: int, w: int, unit: str = "") -> dict[str, Any]:
    p: dict[str, Any] = {
        "id": pid,
        "type": "stat",
        "title": title,
        "gridPos": {"h": 5, "w": w, "x": x, "y": y},
        "datasource": ds(),
        "targets": [prom_target(expr, instant=True)],
    }
    if unit:
        p["fieldConfig"] = {"defaults": {"unit": unit}}
    return p


def ts_panel(
    pid: int,
    title: str,
    targets: list[dict[str, Any]],
    y: int,
    h: int = 9,
    w: int = 24,
    x: int = 0,
    unit: str = "bps",
) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "timeseries",
        "title": title,
        "gridPos": {"h": h, "w": w, "x": x, "y": y},
        "datasource": ds(),
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"drawStyle": "line", "fillOpacity": 10}}},
        "targets": targets,
    }


def table_panel(pid: int, title: str, expr: str, y: int, h: int = 8) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "table",
        "title": title,
        "gridPos": {"h": h, "w": 24, "x": 0, "y": y},
        "datasource": ds(),
        "targets": [prom_target(expr, instant=True)],
        "transformations": [
            {"id": "organize", "options": {"excludeByName": {"Time": True}, "renameByName": {}}},
        ],
    }


def gauge_panel(pid: int, title: str, expr: str, y: int, x: int, w: int, max_val: float) -> dict[str, Any]:
    return {
        "id": pid,
        "type": "gauge",
        "title": title,
        "gridPos": {"h": 6, "w": w, "x": x, "y": y},
        "datasource": ds(),
        "fieldConfig": {
            "defaults": {
                "unit": "percentunit",
                "min": 0,
                "max": max_val,
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "yellow", "value": 0.5},
                        {"color": "red", "value": 0.8},
                    ],
                },
            }
        },
        "targets": [prom_target(expr)],
    }


def deferred_panel(
    pid: int, title: str, resource: str, y: int, h: int = 4, w: int = 24, x: int = 0
) -> dict[str, Any]:
    return text_panel(
        pid,
        title,
        (
            f"**{resource} not deployed yet** in this AWS account. "
            "Panels will populate after you provision the resource and stream its "
            "CloudWatch namespace via Grafana Cloud AWS Observability."
        ),
        y,
        h,
    )


def nat_filter() -> str:
    return f'{{region=~"$region", {NAT_GW_LABEL}=~"$nat_gateway_id"}}'


def nat_total_bps_expr() -> str:
    f = nat_filter()
    return (
        f"sum(rate({NAT_IN_DST}{f}[$__rate_interval])"
        f" + rate({NAT_IN_SRC}{f}[$__rate_interval])"
        f" + rate({NAT_OUT}{f}[$__rate_interval])"
        f" + rate({NAT_OUT_SRC}{f}[$__rate_interval])) * 8"
    )


def nat_egress_bps_expr() -> str:
    return f"sum(rate({NAT_OUT}{nat_filter()}[$__rate_interval])) * 8"


def build_00_hybrid_boundary() -> dict[str, Any]:
    d = dash_meta("hybrid-network-boundary", "00. Hybrid Network Boundary")
    d["templating"] = {
        "list": base_vars(
            [
                {
                    "name": "tester_id",
                    "type": "query",
                    "datasource": ds(),
                    "definition": "label_values(network_topology_device_info, tester_id)",
                    "query": {
                        "query": "label_values(network_topology_device_info, tester_id)",
                        "refId": "A",
                    },
                    "label": "On-prem tester_id",
                    "current": {"text": "network-lab", "value": "network-lab"},
                    "includeAll": True,
                    "allValue": ".*",
                }
            ]
        )
    }
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            (
                "**On-prem ↔ AWS boundary view.** Panels populate when **ktranslate/topology** metrics "
                "and **Grafana Cloud AWS Observability** (CloudWatch metric streams) are both enabled.\n\n"
                "Enable AWS: Grafana Cloud → Observability → Cloud provider → AWS → CloudWatch metric streams."
            ),
            y,
            3,
        )
    )
    y += 3
    panels.append(row("On-prem fabric", y, 2))
    y += 1
    panels.extend(
        [
            stat_panel(
                3,
                "Topology devices",
                'count(network_topology_device_info{tester_id=~"$tester_id"}) OR vector(0)',
                y,
                0,
                6,
            ),
            stat_panel(
                4,
                "Topology edges",
                'count(network_topology_edge_info{tester_id=~"$tester_id"}) OR vector(0)',
                y,
                6,
                6,
            ),
            stat_panel(
                5,
                "Avg ping loss %",
                'avg(kentik_ping_PacketLossPct) OR vector(0)',
                y,
                12,
                6,
                "percent",
            ),
            stat_panel(
                6,
                "Polled devices",
                "count(count by (device_name) (kentik_snmp_CPU)) OR vector(0)",
                y,
                18,
                6,
            ),
        ]
    )
    y += 5
    panels.append(
        {
            "id": 7,
            "type": "nodeGraph",
            "title": "On-prem topology (topology_exporter)",
            "gridPos": {"h": 12, "w": 24, "x": 0, "y": y},
            "datasource": ds(),
            "targets": [
                {
                    **prom_target(
                        'label_replace(label_replace(network_topology_device_info{tester_id=~"$tester_id"}, '
                        '"id", "$1", "device", "(.*)"), "title", "$1", "device", "(.*)")',
                        instant=True,
                    ),
                    "refId": "Nodes",
                    "format": "table",
                },
                {
                    **prom_target(
                        'label_replace(label_replace(label_replace(network_topology_edge_info{tester_id=~"$tester_id"}, '
                        '"id", "$1", "src_port", "(.*)"), "source", "$1", "src_device", "(.*)"), '
                        '"target", "$1", "dst_device", "(.*)")',
                        instant=True,
                    ),
                    "refId": "Edges",
                    "format": "table",
                },
            ],
        }
    )
    y += 12
    panels.append(row("Hybrid path health", y, 8))
    y += 1
    panels.append(
        ts_panel(
            9,
            "NAT internet egress (cloud)",
            [prom_target(f"sum by ({NAT_GW_LABEL}) (rate({NAT_OUT}{nat_filter()}[$__rate_interval])) * 8", "{{" + NAT_GW_LABEL + "}}")],
            y,
            8,
            12,
        )
    )
    panels.append(
        ts_panel(
            10,
            "On-prem flow volume (ktranslate)",
            [
                prom_target(
                    "sum(max_over_time(network_io_by_flow_bytes[$__interval])) OR vector(0)",
                    "flow bytes",
                )
            ],
            y,
            8,
            12,
            12,
            "bytes",
        )
    )
    y += 8
    panels.append(deferred_panel(11, "VPN / Direct Connect (deferred)", "Site-to-Site VPN or Direct Connect", y, 4))
    y += 4
    panels.append(
        text_panel(
            13,
            "Migration checklist",
            (
                "- [ ] Baseline NAT `BytesOutToDestination` for 7 days before cutover\n"
                "- [ ] Enable VPC Flow Logs on hybrid attachments (cross-AZ attribution)\n"
                "- [ ] Tag ENIs / workloads with `service` / `app` for cost allocation\n"
                "- [ ] Compare on-prem flow totals vs NAT egress weekly\n"
                "- [ ] Alert on `ErrorPortAllocation` and VPN tunnel down"
            ),
            y,
            5,
        )
    )
    d["panels"] = panels
    return d


def build_01_egress_economics() -> dict[str, Any]:
    d = dash_meta("aws-egress-transit-economics", "01. Egress & Transit Economics")
    d["templating"] = {"list": base_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            (
                "**The dashboard that pays for itself.** Internet egress via NAT is the most common "
                "surprise line item. Compare with on-prem flow rollups on dashboard **00**.\n\n"
                "NAT limit reference: ~100 Gbps / 10M pps per gateway."
            ),
            y,
            3,
        )
    )
    y += 3
    panels.append(row("Executive KPIs", y, 2))
    y += 1
    panels.extend(
        [
            stat_panel(3, "Internet egress (NAT)", nat_egress_bps_expr(), y, 0, 6, "bps"),
            stat_panel(4, "Total NAT bandwidth", nat_total_bps_expr(), y, 6, 6, "bps"),
            stat_panel(
                5,
                "NAT gateways",
                f"count(count by ({NAT_GW_LABEL}) ({NAT_OUT}{nat_filter()})) OR vector(0)",
                y,
                12,
                4,
            ),
            stat_panel(
                6,
                "Port alloc errors (1h)",
                f"sum(increase({NAT_ERR_PORT}{nat_filter()}[1h])) OR vector(0)",
                y,
                16,
                4,
            ),
            stat_panel(
                7,
                "Packets dropped (1h)",
                f"sum(increase({NAT_PKT_DROP}{nat_filter()}[1h])) OR vector(0)",
                y,
                20,
                4,
            ),
        ]
    )
    y += 5
    panels.append(row("NAT drill-down", y, 10))
    y += 1
    panels.append(
        ts_panel(
            11,
            "Internet egress bps by NAT gateway",
            [
                prom_target(
                    f"sum by ({NAT_GW_LABEL}) (rate({NAT_OUT}{nat_filter()}[$__rate_interval])) * 8",
                    "{{" + NAT_GW_LABEL + "}}",
                )
            ],
            y,
        )
    )
    y += 9
    panels.append(
        ts_panel(
            12,
            "Total NAT bandwidth by gateway",
            [
                prom_target(
                    f"sum by ({NAT_GW_LABEL}) (rate({NAT_IN_DST}{nat_filter()}[$__rate_interval])"
                    f" + rate({NAT_IN_SRC}{nat_filter()}[$__rate_interval])"
                    f" + rate({NAT_OUT}{nat_filter()}[$__rate_interval])"
                    f" + rate({NAT_OUT_SRC}{nat_filter()}[$__rate_interval])) * 8",
                    "{{" + NAT_GW_LABEL + "}}",
                )
            ],
            y,
        )
    )
    y += 9
    panels.append(
        table_panel(
            13,
            "NAT byte counters (current hour rate)",
            f"sum by ({NAT_GW_LABEL}) (rate({NAT_OUT}{nat_filter()}[1h]))",
            y,
        )
    )
    y += 8
    panels.append(row("Other egress paths", y, 20))
    y += 1
    panels.extend(
        [
            ts_panel(
                21,
                "ALB processed bytes",
                [
                    prom_target(
                        f"sum by ({ALB_LB_LABEL}) (rate({ALB_BYTES}{{region=~\"$region\"}}[$__rate_interval])) * 8",
                        "{{" + ALB_LB_LABEL + "}}",
                    )
                ],
                y,
                8,
                12,
            ),
            ts_panel(
                22,
                "ALB request rate",
                [
                    prom_target(
                        f"sum by ({ALB_LB_LABEL}) (rate({ALB_REQUESTS}{{region=~\"$region\"}}[$__rate_interval]))",
                        "{{" + ALB_LB_LABEL + "}}",
                    )
                ],
                y,
                8,
                12,
                12,
                "reqps",
            ),
        ]
    )
    y += 8
    panels.extend(
        [
            ts_panel(
                23,
                "NLB processed bytes",
                [
                    prom_target(
                        f"sum by ({NLB_LB_LABEL}) (rate({NLB_BYTES}{{region=~\"$region\"}}[$__rate_interval])) * 8",
                        "{{" + NLB_LB_LABEL + "}}",
                    )
                ],
                y,
                4,
                12,
            ),
            ts_panel(
                24,
                "Firehose → HTTP (observability egress)",
                [prom_target(f"sum(rate({FH_HTTP}{{region=~\"$region\"}}[$__rate_interval])) * 8", "Firehose HTTP")],
                y,
                4,
                12,
                12,
            ),
        ]
    )
    y += 4
    panels.append(deferred_panel(25, "Transit Gateway bytes (deferred)", "Transit Gateway", y, 4))
    y += 4
    panels.append(row("On-prem correlation", y, 30))
    y += 1
    panels.append(
        ts_panel(
            31,
            "On-prem flow bytes vs NAT internet egress",
            [
                prom_target("sum(max_over_time(network_io_by_flow_bytes[$__interval])) OR vector(0)", "on-prem flows"),
                prom_target(nat_egress_bps_expr() + " / 8", "NAT egress bytes/s"),
            ],
            y,
            10,
            unit="bytes",
        )
    )
    d["panels"] = panels
    return d


def build_02_cross_zone() -> dict[str, Any]:
    d = dash_meta("aws-cross-zone-traffic", "02. Cross-AZ & Cross-Region Traffic")
    d["templating"] = {"list": base_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            (
                "CloudWatch **does not** expose per-service cross-AZ bytes. These panels are "
                "**proxies** (NAT hairpin, TGW, ELB). For precision, enable **VPC Flow Logs → Loki** "
                "(phase 2). Single-NAT topologies (like this repo's Terraform demo) amplify cross-AZ charges."
            ),
            y,
            4,
        )
    )
    y += 4
    panels.append(row("AZ & attachment proxies", y, 2))
    y += 1
    panels.extend(
        [
            stat_panel(
                3,
                "EC2 network series",
                f"count({EC2_NET_IN}{{region=~\"$region\"}}) OR vector(0)",
                y,
                0,
                6,
            ),
            stat_panel(
                4,
                "NAT gateways",
                f"count(count by ({NAT_GW_LABEL}) ({NAT_OUT}{nat_filter()})) OR vector(0)",
                y,
                6,
                6,
            ),
            stat_panel(5, "NAT total bps", nat_total_bps_expr(), y, 12, 6, "bps"),
            stat_panel(
                6,
                "ALB load balancers",
                f"count(count by ({ALB_LB_LABEL}) ({ALB_REQUESTS}{{region=~\"$region\"}})) OR vector(0)",
                y,
                18,
                6,
            ),
        ]
    )
    y += 5
    panels.append(deferred_panel(7, "Transit Gateway by attachment (deferred)", "Transit Gateway", y, 4))
    y += 4
    panels.append(
        ts_panel(
            8,
            "ALB processed bytes by load balancer",
            [
                prom_target(
                    f"sum by ({ALB_LB_LABEL}) (rate({ALB_BYTES}{{region=~\"$region\"}}[$__rate_interval])) * 8",
                    "{{" + ALB_LB_LABEL + "}}",
                )
            ],
            y,
        )
    )
    y += 9
    panels.append(
        ts_panel(
            9,
            "EC2 network packets by ASG (top 10)",
            [
                prom_target(
                    f"topk(10, sum by ({EC2_GROUP_LABEL}) (rate({EC2_NET_IN}{{region=~\"$region\"}}[$__rate_interval])"
                    f" + rate({EC2_NET_OUT}{{region=~\"$region\"}}[$__rate_interval])))",
                    "{{" + EC2_GROUP_LABEL + "}}",
                )
            ],
            y,
            unit="pps",
        )
    )
    y += 9
    panels.append(
        text_panel(
            10,
            "Refactor triggers",
            (
                "| Threshold | Action |\n"
                "|-----------|--------|\n"
                "| Cross-AZ > 30% of VPC bytes (flow logs) | Architecture review |\n"
                "| Service in AZ-a → DB in AZ-b | Move workload or add local replica |\n"
                "| Single NAT + multi-AZ EKS | Expect cross-AZ charges to NAT AZ |\n"
                "| ELB cross-zone enabled + high processed bytes | Review target AZ affinity |"
            ),
            y,
            5,
        )
    )
    d["panels"] = panels
    return d


def build_03_limits() -> dict[str, Any]:
    d = dash_meta("aws-network-limits-saturation", "03. Network Limits & Saturation")
    d["templating"] = {"list": base_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            "Distinguish **CSP network ceilings** (NAT ports, LB LCUs, VPN) from application latency.",
            y,
            2,
        )
    )
    y += 2
    panels.append(row("NAT gateway limits", y, 2))
    y += 1
    panels.append(
        gauge_panel(
            3,
            "NAT bandwidth vs 100 Gbps",
            f"({nat_total_bps_expr()}) / 100e9",
            y,
            0,
            8,
            1.0,
        )
    )
    panels.extend(
        [
            stat_panel(
                4,
                "Port allocation errors",
                f"sum({NAT_ERR_PORT}{nat_filter()}) OR vector(0)",
                y,
                8,
                8,
            ),
            stat_panel(
                5,
                "Packets dropped",
                f"sum({NAT_PKT_DROP}{nat_filter()}) OR vector(0)",
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
            "NAT active connections",
            [
                prom_target(
                    f"max by ({NAT_GW_LABEL}) ({NAT_ACTIVE_CONN}{nat_filter()})",
                    "{{" + NAT_GW_LABEL + "}}",
                )
            ],
            y,
            unit="none",
        )
    )
    y += 9
    panels.append(row("Load balancers", y, 10))
    y += 1
    panels.extend(
        [
            ts_panel(
                11,
                "ALB ELB 5xx",
                [
                    prom_target(
                        f'sum by ({ALB_LB_LABEL}) (rate({ALB_5XX}{{region=~"$region"}}[$__rate_interval]))',
                        "{{" + ALB_LB_LABEL + "}}",
                    )
                ],
                y,
                8,
                12,
                unit="ops",
            ),
            ts_panel(
                12,
                "ALB active connections",
                [
                    prom_target(
                        f'avg by ({ALB_LB_LABEL}) ({ALB_ACTIVE_CONN}{{region=~"$region"}})',
                        "{{" + ALB_LB_LABEL + "}}",
                    )
                ],
                y,
                8,
                12,
                12,
                "none",
            ),
        ]
    )
    y += 8
    panels.append(
        ts_panel(
            13,
            "NLB consumed LCUs",
            [
                prom_target(
                    f"sum by ({NLB_LB_LABEL}) (rate({NLB_LCUS}{{region=~\"$region\"}}[$__rate_interval]))",
                    "{{" + NLB_LB_LABEL + "}}",
                )
            ],
            y,
            4,
            unit="none",
        )
    )
    y += 4
    panels.append(row("On-prem saturation (same path)", y, 20))
    y += 1
    panels.extend(
        [
            ts_panel(
                21,
                "Interface errors/s (on-prem)",
                [
                    prom_target(
                        "sum by (device_name) ((kentik_snmp_ifInErrors) / 60)",
                        "in {{device_name}}",
                    ),
                    prom_target(
                        "sum by (device_name) ((kentik_snmp_ifOutErrors) / 60)",
                        "out {{device_name}}",
                    ),
                ],
                y,
                8,
                12,
                unit="ops",
            ),
            ts_panel(
                22,
                "Device CPU %",
                [prom_target("max by (device_name) (kentik_snmp_CPU)", "{{device_name}}")],
                y,
                8,
                12,
                12,
                "percent",
            ),
        ]
    )
    d["panels"] = panels
    return d


def build_04_obs_tax() -> dict[str, Any]:
    d = dash_meta("aws-observability-tax", "04. Observability & Platform Tax")
    d["templating"] = {"list": base_vars()}
    y = 0
    panels: list[dict] = []
    panels.append(
        text_panel(
            1,
            "About",
            (
                "Telemetry has **cost and egress**: Firehose metric streams, NAT for agents, "
                "Grafana Cloud active series, and ktranslate CHF health."
            ),
            y,
            3,
        )
    )
    y += 3
    panels.append(row("AWS observability egress", y, 2))
    y += 1
    panels.extend(
        [
            ts_panel(
                3,
                "Firehose → Grafana HTTP endpoint",
                [prom_target(f"sum(rate({FH_HTTP}{{region=~\"$region\"}}[$__rate_interval])) * 8", "HTTP")],
                y,
                8,
                12,
            ),
            ts_panel(
                4,
                "Firehose → S3 backup (failed batches)",
                [prom_target(f"sum(rate({FH_S3}{{region=~\"$region\"}}[$__rate_interval])) * 8", "S3")],
                y,
                8,
                12,
                12,
            ),
        ]
    )
    y += 8
    panels.append(
        ts_panel(
            5,
            "NAT egress (agents + workloads)",
            [prom_target(nat_egress_bps_expr(), "NAT internet")],
            y,
        )
    )
    y += 9
    panels.append(row("Grafana / ktranslate cardinality", y, 10))
    y += 1
    panels.extend(
        [
            stat_panel(
                11,
                "AWS metric families",
                'count(count by (__name__) ({__name__=~"aws_.*"})) OR vector(0)',
                y,
                0,
                8,
            ),
            stat_panel(
                12,
                "Flow series (on-prem)",
                "count(network_io_by_flow_bytes) OR vector(0)",
                y,
                8,
                8,
            ),
            stat_panel(
                13,
                "SNMP devices",
                "count(count by (device_name) (kentik_snmp_CPU)) OR vector(0)",
                y,
                16,
                8,
            ),
        ]
    )
    y += 5
    panels.append(
        ts_panel(
            14,
            "ktranslate CHF scrape health",
            [
                prom_target(
                    'sum by (service_name) (kentik_ktranslate_chf_kkc_snmp_poll_ms_count)',
                    "{{service_name}}",
                )
            ],
            y,
            unit="none",
        )
    )
    d["panels"] = panels
    return d


CATALOG = [
    ("00-hybrid-network-boundary.json", build_00_hybrid_boundary),
    ("01-egress-transit-economics.json", build_01_egress_economics),
    ("02-cross-zone-traffic.json", build_02_cross_zone),
    ("03-network-limits-saturation.json", build_03_limits),
    ("04-observability-tax.json", build_04_obs_tax),
]


def api_request(base: str, token: str, method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        f"{base}{path}",
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = raw.decode(errors="replace")
        return e.code, payload


def ensure_folder(base: str, token: str) -> None:
    code, _ = api_request(base, token, "GET", f"/api/folders/{FOLDER_UID}")
    if code == 200:
        return
    code, out = api_request(
        base,
        token,
        "POST",
        "/api/folders",
        {"uid": FOLDER_UID, "title": FOLDER_TITLE},
    )
    if code not in (200, 409, 412):
        raise RuntimeError(f"create folder failed HTTP {code}: {out}")


def import_dashboard(base: str, token: str, dash: dict) -> tuple[int, object]:
    payload = {"dashboard": dash, "folderUid": FOLDER_UID, "overwrite": True}
    return api_request(base, token, "POST", "/api/dashboards/db", payload)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--import", dest="do_import", action="store_true", help="POST dashboards to Grafana")
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
        print(f"\nDry-run only. Import with: python3 {Path(__file__).name} --import")
        return 0

    env = load_env()
    base = env.get("GRAFANA_URL", "").rstrip("/")
    token = env.get("GRAFANA_TOKEN", "")
    if not base or not token.startswith("glsa_"):
        print("ERROR: set GRAFANA_URL and GRAFANA_TOKEN (glsa_) in local/.env")
        return 1

    ensure_folder(base, token)
    ok = 0
    for fname, dash in built:
        code, out = import_dashboard(base, token, dash)
        if 200 <= code < 300:
            url = out.get("url", "") if isinstance(out, dict) else ""
            print(f"imported {dash['title']} ({dash['uid']}) HTTP {code} {url}")
            ok += 1
        else:
            print(f"FAILED {fname} HTTP {code}: {out}")
    print(f"\n{ok}/{len(built)} dashboards in folder '{FOLDER_TITLE}' ({FOLDER_UID})")
    return 0 if ok == len(built) else 1


if __name__ == "__main__":
    raise SystemExit(main())
