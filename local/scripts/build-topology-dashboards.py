#!/usr/bin/env python3
"""Build lab-adapted topology dashboards (local Network Lab folder)."""
from __future__ import annotations

import json
from pathlib import Path

from lab_env import tester_id

OUT = Path(__file__).resolve().parents[1] / ".dash-payloads" / "topology"
OUT.mkdir(parents=True, exist_ok=True)

TID = tester_id()

# Minimal dashboards for the local lab (uids unique per stack).
TOPOLOGY_GRAPH = {
    "uid": "lab-topology-graph",
    "title": "Network Topology (topology-exporter)",
    "tags": ["topology", "network-lab", "topology-exporter"],
    "timezone": "browser",
    "schemaVersion": 42,
    "refresh": "1m",
    "time": {"from": "now-15m", "to": "now"},
    "templating": {
        "list": [
            {
                "name": "datasource",
                "type": "datasource",
                "query": "prometheus",
                "current": {"text": "default", "value": "grafanacloud-prom"},
                "label": "Datasource",
            },
            {
                "name": "tester_id",
                "type": "query",
                "datasource": {"type": "prometheus", "uid": "${datasource}"},
                "definition": "label_values(network_topology_device_info, tester_id)",
                "query": {
                    "query": "label_values(network_topology_device_info, tester_id)",
                    "refId": "StandardVariableQuery",
                },
                "current": {"text": TID, "value": TID},
                "label": "Tester ID",
                "refresh": 1,
                "sort": 1,
            },
        ]
    },
    "panels": [
        {
            "id": 1,
            "type": "nodeGraph",
            "title": "Network Topology Graph",
            "gridPos": {"h": 16, "w": 24, "x": 0, "y": 0},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "Nodes",
                    "expr": 'label_replace(label_replace(label_replace(label_replace(network_topology_device_info{tester_id="$tester_id"}, "id", "$1", "device", "(.*)"), "mainStat", "$1", "device", "(.*)"), "title", "$1", "vendor", "(.*)"), "subTitle", "$1", "site", "(.*)")',
                    "format": "table",
                    "instant": True,
                },
                {
                    "refId": "Edges",
                    "expr": 'label_replace(label_replace(label_replace(label_replace(label_replace(network_topology_edge_info{tester_id="$tester_id"}, "id", "$1", "src_port", "(.*)"), "source", "$1", "src_device", "(.*)"), "target", "$1", "dst_device", "(.*)"), "mainStat", "$1", "discovery_proto", "(.*)"), "secondaryStat", "$1", "link_kind", "(.*)")',
                    "format": "table",
                    "instant": True,
                },
            ],
            "options": {
                "layoutAlgorithm": "layered",
                "nodes": {"nodeRadius": 40},
                "zoomMode": "cooperative",
            },
        },
        {
            "id": 2,
            "type": "table",
            "title": "Edge Detail Table",
            "gridPos": {"h": 8, "w": 24, "x": 0, "y": 16},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'network_topology_edge_info{tester_id="$tester_id"}',
                    "format": "table",
                    "instant": True,
                }
            ],
        },
    ],
}

HARNESS_HEALTH = {
    "uid": "lab-topology-health",
    "title": "Topology Exporter Health",
    "tags": ["topology", "network-lab", "topology-exporter"],
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
                "current": {"text": "default", "value": "grafanacloud-prom"},
                "label": "Datasource",
            },
            {
                "name": "tester_id",
                "type": "query",
                "datasource": {"type": "prometheus", "uid": "${datasource}"},
                "definition": "label_values(network_topology_device_info, tester_id)",
                "query": {
                    "query": "label_values(network_topology_device_info, tester_id)",
                    "refId": "StandardVariableQuery",
                },
                "current": {"text": TID, "value": TID},
                "label": "Tester ID",
                "refresh": 1,
                "sort": 1,
            },
        ]
    },
    "panels": [
        {
            "id": 1,
            "type": "stat",
            "title": "Devices",
            "gridPos": {"h": 6, "w": 6, "x": 0, "y": 0},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'count(network_topology_device_info{tester_id="$tester_id"})',
                    "instant": True,
                }
            ],
        },
        {
            "id": 2,
            "type": "stat",
            "title": "Edges",
            "gridPos": {"h": 6, "w": 6, "x": 6, "y": 0},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'count(network_topology_edge_info{tester_id="$tester_id"})',
                    "instant": True,
                }
            ],
        },
        {
            "id": 3,
            "type": "stat",
            "title": "Discovery Successes",
            "gridPos": {"h": 6, "w": 6, "x": 12, "y": 0},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'network_topology_discovery_devices_total{tester_id="$tester_id",status="success"}',
                }
            ],
        },
        {
            "id": 4,
            "type": "stat",
            "title": "OTLP Push OK",
            "gridPos": {"h": 6, "w": 6, "x": 18, "y": 0},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'sum(network_topology_otlp_push_total{status="ok"})',
                }
            ],
        },
        {
            "id": 5,
            "type": "timeseries",
            "title": "Discovery Cycle Duration",
            "gridPos": {"h": 10, "w": 12, "x": 0, "y": 6},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "fieldConfig": {"defaults": {"unit": "s"}},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'histogram_quantile(0.95, sum(rate(network_topology_discovery_cycle_duration_seconds_bucket{tester_id="$tester_id"}[$__rate_interval])) by (le))',
                    "legendFormat": "p95",
                },
                {
                    "refId": "B",
                    "expr": 'histogram_quantile(0.50, sum(rate(network_topology_discovery_cycle_duration_seconds_bucket{tester_id="$tester_id"}[$__rate_interval])) by (le))',
                    "legendFormat": "p50",
                },
            ],
        },
        {
            "id": 6,
            "type": "timeseries",
            "title": "Discovery Outcomes",
            "gridPos": {"h": 10, "w": 12, "x": 12, "y": 6},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": 'sum(network_topology_discovery_devices_total{tester_id="$tester_id"}) by (status, reason)',
                    "legendFormat": "{{status}} ({{reason}})",
                }
            ],
        },
        {
            "id": 7,
            "type": "timeseries",
            "title": "Walker Outcomes (LLDP / BGP)",
            "gridPos": {"h": 10, "w": 24, "x": 0, "y": 16},
            "datasource": {"type": "prometheus", "uid": "${datasource}"},
            "targets": [
                {
                    "refId": "A",
                    "expr": "sum(network_topology_walker_outcome_total) by (walker, outcome)",
                    "legendFormat": "{{walker}}: {{outcome}}",
                },
                {
                    "refId": "B",
                    "expr": "sum(network_topology_bgp_walker_outcome_total) by (walker, outcome)",
                    "legendFormat": "bgp {{walker}}: {{outcome}}",
                },
            ],
        },
    ],
}


def main() -> None:
    for name, dash in (
        ("lab-topology-graph.json", TOPOLOGY_GRAPH),
        ("lab-topology-health.json", HARNESS_HEALTH),
    ):
        path = OUT / name
        path.write_text(json.dumps(dash, indent=2) + "\n")
        print(f"wrote {path}")


if __name__ == "__main__":
    main()
