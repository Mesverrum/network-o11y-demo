#!/usr/bin/env python3
"""Build lab-network-join-demo dashboard JSON for Network Lab folder.

Highlights the app↔network join: Tempo spans (clos-join-demo) and softflowd
flows share the same 5-tuple keys (peer addr/port), selectable via variables.
"""
from __future__ import annotations

import json
from pathlib import Path

from identity_scenario_panels import append_identity_panels, scenario_variable
from lab_env import tester_id

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "network-join-demo.json"

DS = {"type": "prometheus", "uid": "${datasource}"}
TEMPO = {"type": "tempo", "uid": "${tempo}"}
CLOS = 'device_name=~"$device"'
TESTER = 'tester_id="$tester_id"'
FLOW_MATCH = (
    'network_peer_address="$peer_addr",network_peer_port="$peer_port"'
)
# TraceQL: port is typed int on spans; addr is string.
TRACE_MATCH = (
    '{ resource.service.name = "$service" '
    '&& span.network.peer.address = "$peer_addr" '
    "&& span.network.peer.port = $peer_port }"
)


def markdown(title: str, content: str, panel_id: int, y: int, h: int = 6) -> dict:
    return {
        "id": panel_id,
        "type": "text",
        "title": title,
        "gridPos": {"h": h, "w": 24, "x": 0, "y": y},
        "options": {"mode": "markdown", "content": content},
    }


def row(title: str, panel_id: int, y: int) -> dict:
    return {
        "id": panel_id,
        "type": "row",
        "title": title,
        "gridPos": {"h": 1, "w": 24, "x": 0, "y": y},
        "collapsed": False,
        "panels": [],
    }


def main() -> None:
    tid = tester_id()
    narrative = """### Investigation story (read this row top→bottom)

| Step | What to look at | Signal |
|------|-----------------|--------|
| 1 | **App** latency | Tempo p95 for `$service` → `$peer_addr:$peer_port` |
| 2 | **Conversation** still there? | softflowd bytes for the same peer |
| 3 | **Where it can travel** | Candidate subway: service → clients → leaf/spine Clos |
| 4 | **Infra under that path** | CPU + interface errors on spine1/leaf1/leaf2 |

**Talk track:** `make join-app` (steady ~15–30 ms) → `make join-fault` (netem delay/loss on client eth1) → watch **App p95** climb while **flows** keep matching → `make join-fault-stop`.

Join key: `span.network.peer.*` = `network_peer_*`. Path is LLDP **candidates**, not a proven per-flow route.
"""

    join_legend = """```
  Tempo span attrs                    Prometheus flow labels
  ─────────────────                   ──────────────────────
  network.peer.address   ───────►     network_peer_address     ($peer_addr)
  network.peer.port      ───────►     network_peer_port        ($peer_port)
  server.address         ───────►     (same as peer for client spans)
  clos.local.address     ───────►     network_local_address    (client1 = 172.17.0.1)
```

Change **Peer addr / Peer port** in the dashboard header to pivot both panels together.
"""

    path_dev = 'device_name=~"spine1|leaf1|leaf2"'
    path_if = 'if_interface_name=~"ethernet-1/(1|2|49)"'
    # Investigation subway: service + EVPN clients + Clos only
    invest_nodes = (
        "("
        + f'label_replace(label_replace(label_replace('
        + f'max by (id, title, kind) (clos_join_entity_info{{{TESTER}}}), '
        + '"mainStat", "$1", "kind", "(.*)"), '
        + '"arc__service", "1", "kind", "service"), '
        + '"arc__host", "1", "kind", "host")'
        + ") or ("
        + f'label_replace(label_replace(label_replace('
        + f'network_topology_device_info{{{TESTER},device=~"spine1|leaf1|leaf2"}}, '
        + '"id", "$1", "device", "(.*)"), '
        + '"title", "$1", "device", "(.*)"), '
        + '"arc__device", "1", "device", "(.*)")'
        + ")"
    )
    invest_edges = (
        "("
        + 'label_replace(label_replace(label_replace(label_replace('
        + f'max by (id, src, dst, kind) (clos_join_edge_info{{{TESTER}}}), '
        + '"source", "$1", "src", "(.*)"), '
        + '"target", "$1", "dst", "(.*)"), '
        + '"mainStat", "$1", "kind", "(.*)"), '
        + '"secondaryStat", "$1", "kind", "(.*)")'
        + ") or ("
        + f'label_replace(label_replace(label_replace(label_replace('
        + f'network_topology_edge_info{{{TESTER},src_device=~"spine1|leaf1|leaf2",dst_device=~"spine1|leaf1|leaf2"}}, '
        + '"id", "$1", "src_port", "(.*)"), '
        + '"source", "$1", "src_device", "(.*)"), '
        + '"target", "$1", "dst_device", "(.*)"), '
        + '"mainStat", "lldp", "discovery_proto", "(.*)")'
        + ")"
    )

    dash = {
        "uid": "lab-network-join-demo",
        "title": "Network join demo (SIG model)",
        "description": (
            "Investigation talk track + Identity tabs (hostname/mac/address/iface prove·disprove). "
            "Fault: make -C local join-fault."
        ),
        "tags": ["network-lab", "sig", "join-demo", "topology", "netflow", "traces"],
        "timezone": "browser",
        "schemaVersion": 39,
        "version": 1,
        "refresh": "10s",
        "time": {"from": "now-15m", "to": "now"},
        "templating": {
            "list": [
                {
                    "name": "datasource",
                    "type": "datasource",
                    "query": "prometheus",
                    "current": {
                        "text": "grafanacloud-prom",
                        "value": "grafanacloud-prom",
                    },
                    "label": "Metrics",
                },
                {
                    "name": "tempo",
                    "type": "datasource",
                    "query": "tempo",
                    "current": {
                        "text": "grafanacloud-traces",
                        "value": "grafanacloud-traces",
                    },
                    "label": "Traces",
                },
                {
                    "name": "service",
                    "type": "custom",
                    "query": "clos-join-demo",
                    "current": {"text": "clos-join-demo", "value": "clos-join-demo"},
                    "options": [
                        {"text": "clos-join-demo", "value": "clos-join-demo", "selected": True}
                    ],
                    "label": "App service",
                },
                {
                    "name": "peer_addr",
                    "type": "textbox",
                    "query": "172.17.0.2",
                    "current": {"text": "172.17.0.2", "value": "172.17.0.2"},
                    "label": "Peer addr",
                },
                {
                    "name": "peer_port",
                    "type": "textbox",
                    "query": "8080",
                    "current": {"text": "8080", "value": "8080"},
                    "label": "Peer port",
                },
                {
                    "name": "tester_id",
                    "type": "query",
                    "datasource": DS,
                    "definition": "label_values(network_topology_device_info, tester_id)",
                    "query": {
                        "query": "label_values(network_topology_device_info, tester_id)",
                        "refId": "StandardVariableQuery",
                    },
                    "current": {
                        "text": tid,
                        "value": tid,
                    },
                    "label": "Tester ID",
                    "refresh": 1,
                    "sort": 1,
                    "includeAll": False,
                },
                {
                    "name": "device",
                    "type": "query",
                    "datasource": DS,
                    "definition": 'label_values(kentik_snmp_Uptime{device_name=~"spine1|leaf1|leaf2"}, device_name)',
                    "query": {
                        "query": 'label_values(kentik_snmp_Uptime{device_name=~"spine1|leaf1|leaf2"}, device_name)',
                        "refId": "StandardVariableQuery",
                    },
                    "current": {"text": "All", "value": "$__all"},
                    "includeAll": True,
                    "multi": True,
                    "allValue": "spine1|leaf1|leaf2",
                    "label": "Clos device",
                    "refresh": 1,
                    "sort": 1,
                },
                scenario_variable(),
            ]
        },
        "annotations": {"list": []},
        "panels": [],
    }

    panels: list[dict] = []
    y = 0

    # ── Investigation (the story) ──────────────────────────────────
    panels.append(row("Investigation — app → conversation → path → infra", 200, y))
    y += 1
    panels.append(markdown("How to read this", narrative, 201, y, h=6))
    y += 6

    panels.append(
        {
            "id": 202,
            "type": "timeseries",
            "title": "1 · App p95 latency ($service → $peer_addr:$peer_port)",
            "description": "TraceQL metrics. After `make join-fault`, this should jump; `join-fault-stop` clears it.",
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": f"{TRACE_MATCH} | quantile_over_time(duration, 0.95)",
                    "filters": [],
                },
                {
                    "refId": "B",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": f"{TRACE_MATCH} | quantile_over_time(duration, 0.50)",
                    "filters": [],
                },
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "s",
                    "custom": {"drawStyle": "line", "fillOpacity": 15, "spanNulls": True},
                },
                "overrides": [
                    {
                        "matcher": {"id": "byFrameRefID", "options": "A"},
                        "properties": [{"id": "displayName", "value": "p95"}],
                    },
                    {
                        "matcher": {"id": "byFrameRefID", "options": "B"},
                        "properties": [{"id": "displayName", "value": "p50"}],
                    },
                ],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    panels.append(
        {
            "id": 203,
            "type": "timeseries",
            "title": "2 · Conversation still matched? (flow bytes)",
            "description": "Same $peer_addr:$peer_port. Fault should not remove the join — only slow the app.",
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"network_io_by_flow_bytes{{{FLOW_MATCH}}}",
                    "legendFormat": "{{network_local_address}}:{{network_local_port}} → {{network_peer_address}}:{{network_peer_port}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "decbytes",
                    "custom": {"drawStyle": "line", "fillOpacity": 15, "spanNulls": True},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    y += 8

    panels.append(
        {
            "id": 204,
            "type": "nodeGraph",
            "title": "3 · Candidate path (service → clients → Clos)",
            "description": "LLDP + runs_on/attached overlay. Candidates only — not proven per-flow.",
            "gridPos": {"h": 12, "w": 12, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "Nodes",
                    "expr": invest_nodes,
                    "format": "table",
                    "instant": True,
                },
                {
                    "refId": "Edges",
                    "expr": invest_edges,
                    "format": "table",
                    "instant": True,
                },
            ],
            "options": {
                "layoutAlgorithm": "layered",
                "nodes": {"nodeRadius": 36},
                "zoomMode": "cooperative",
            },
        }
    )
    panels.append(
        {
            "id": 205,
            "type": "timeseries",
            "title": "4 · Path infra — CPU % (spine/leaves)",
            "description": "Underlay devices on the candidate Clos path.",
            "gridPos": {"h": 6, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"kentik_snmp_CPU{{{path_dev}}}",
                    "legendFormat": "{{device_name}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "percent",
                    "min": 0,
                    "max": 100,
                    "custom": {"drawStyle": "line", "fillOpacity": 10},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    panels.append(
        {
            "id": 206,
            "type": "timeseries",
            "title": "4 · Path infra — ifInErrors (client + fabric ports)",
            "description": "ethernet-1/1,/2,/49 on Clos. Quiet unless you flap or discard; latency fault may not move this.",
            "gridPos": {"h": 6, "w": 12, "x": 12, "y": y + 6},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": (
                        f"sum by (device_name, if_interface_name) ("
                        f"rate(kentik_snmp_ifInErrors{{{path_dev},{path_if}}}[$__rate_interval]))"
                    ),
                    "legendFormat": "{{device_name}} {{if_interface_name}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "eps",
                    "custom": {"drawStyle": "line", "fillOpacity": 5},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    y += 12

    panels.append(
        {
            "id": 207,
            "type": "stat",
            "title": "App p95 (now)",
            "gridPos": {"h": 4, "w": 4, "x": 0, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": f"{TRACE_MATCH} | quantile_over_time(duration, 0.95)",
                    "filters": [],
                }
            ],
            "fieldConfig": {"defaults": {"unit": "s"}, "overrides": []},
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "area",
            },
        }
    )
    panels.append(
        {
            "id": 208,
            "type": "stat",
            "title": "Span rate",
            "gridPos": {"h": 4, "w": 4, "x": 4, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": f"{TRACE_MATCH} | rate()",
                    "filters": [],
                }
            ],
            "fieldConfig": {"defaults": {"unit": "ops"}, "overrides": []},
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 209,
            "type": "stat",
            "title": "Matched flow series",
            "gridPos": {"h": 4, "w": 4, "x": 8, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"count(network_io_by_flow_bytes{{{FLOW_MATCH}}})",
                    "instant": True,
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 210,
            "type": "text",
            "title": "Fault inject",
            "gridPos": {"h": 4, "w": 12, "x": 12, "y": y},
            "options": {
                "mode": "markdown",
                "content": (
                    "**On:** `make -C local join-fault` → netem **200 ms / 1 %** on client1 `eth1`\n\n"
                    "**Off:** `make -C local join-fault-stop`\n\n"
                    "**Both ends:** `JOIN_FAULT_CLIENTS=client1,client2 make -C local join-fault`\n\n"
                    "**Custom:** `./scripts/join-fault.sh start 400ms 2%`\n\n"
                    "Keep `make join-app` running. Refresh ~10 s."
                ),
            },
        }
    )
    y += 4

    # ── Identity prove/disprove tabs ───────────────────────────────
    y = append_identity_panels(panels, y, row, markdown)

    # ── Detail: join keys + tables ─────────────────────────────────
    panels.append(row("Detail — join keys & raw span/flow tables", 100, y))
    y += 1
    panels.append(markdown("Join keys (span attr → flow label)", join_legend, 101, y, h=5))
    y += 5

    panels.append(
        {
            "id": 102,
            "type": "table",
            "title": "App spans (Tempo) — $service peer $peer_addr:$peer_port",
            "description": (
                "TraceQL filters clos-join-demo by the same peer addr/port the "
                "flow panel uses. Click a Trace ID to open the waterfall."
            ),
            "gridPos": {"h": 11, "w": 12, "x": 0, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": TRACE_MATCH,
                    "limit": 30,
                    "tableType": "traces",
                    "filters": [],
                }
            ],
            "options": {"showHeader": True, "footer": {"show": False}},
            "fieldConfig": {
                "defaults": {"custom": {"align": "auto", "filterable": True}},
                "overrides": [],
            },
        }
    )
    panels.append(
        {
            "id": 103,
            "type": "table",
            "title": "Matching flows (Prometheus) — peer $peer_addr:$peer_port",
            "description": (
                "softflowd → ktranslate → Alloy. Same $peer_addr / $peer_port as "
                "the Tempo panel — this is the conversation side of the join."
            ),
            "gridPos": {"h": 11, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"network_io_by_flow_bytes{{{FLOW_MATCH}}}",
                    "format": "table",
                    "instant": True,
                }
            ],
            "transformations": [
                {"id": "labelsToFields", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "job": True,
                            "service_name": True,
                            "dst_host": True,
                            "src_host": True,
                        },
                        "renameByName": {
                            "network_local_address": "local.addr",
                            "network_local_port": "local.port",
                            "network_peer_address": "peer.addr",
                            "network_peer_port": "peer.port",
                            "network_transport": "transport",
                            "device_name": "exporter",
                            "Value": "bytes",
                        },
                    },
                },
            ],
            "options": {"showHeader": True, "footer": {"show": False}},
            "fieldConfig": {
                "defaults": {"custom": {"align": "auto", "filterable": True}},
                "overrides": [],
            },
        }
    )
    y += 11

    panels.append(
        {
            "id": 104,
            "type": "timeseries",
            "title": "Span rate (TraceQL metrics) — same peer filter",
            "description": "App request rate for the joined conversation.",
            "gridPos": {"h": 8, "w": 12, "x": 0, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": f"{TRACE_MATCH} | rate()",
                    "filters": [],
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "ops",
                    "custom": {"drawStyle": "line", "fillOpacity": 15, "spanNulls": True},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    panels.append(
        {
            "id": 105,
            "type": "timeseries",
            "title": "Flow bytes — same peer filter",
            "description": "Network conversation volume for the joined 5-tuple.",
            "gridPos": {"h": 8, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"network_io_by_flow_bytes{{{FLOW_MATCH}}}",
                    "legendFormat": "{{network_local_address}}:{{network_local_port}} → {{network_peer_address}}:{{network_peer_port}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "decbytes",
                    "custom": {"drawStyle": "line", "fillOpacity": 15, "spanNulls": True},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    y += 8

    panels.append(
        {
            "id": 106,
            "type": "stat",
            "title": "Joined span hits",
            "description": "Traces matching service + peer in the time range.",
            "gridPos": {"h": 4, "w": 6, "x": 0, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": TRACE_MATCH,
                    "limit": 100,
                    "tableType": "traces",
                    "filters": [],
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["count"]},
                "colorMode": "value",
                "graphMode": "none",
                "textMode": "value_and_name",
            },
        }
    )
    panels.append(
        {
            "id": 107,
            "type": "stat",
            "title": "Joined flow series",
            "gridPos": {"h": 4, "w": 6, "x": 6, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"count(network_io_by_flow_bytes{{{FLOW_MATCH}}})",
                    "instant": True,
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 108,
            "type": "stat",
            "title": "p95 span duration",
            "gridPos": {"h": 4, "w": 6, "x": 12, "y": y},
            "datasource": TEMPO,
            "targets": [
                {
                    "refId": "A",
                    "datasource": TEMPO,
                    "queryType": "traceql",
                    "query": f"{TRACE_MATCH} | quantile_over_time(duration, 0.95)",
                    "filters": [],
                }
            ],
            "fieldConfig": {
                "defaults": {"unit": "s"},
                "overrides": [],
            },
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 109,
            "type": "stat",
            "title": "Ops",
            "gridPos": {"h": 4, "w": 6, "x": 18, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": "vector(1)",
                    "instant": True,
                }
            ],
            # Use a text panel instead — stat with vector(1) is silly.
            # Replaced below.
        }
    )
    # Replace silly ops stat with markdown ops hint
    panels[-1] = {
        "id": 109,
        "type": "text",
        "title": "Ops",
        "gridPos": {"h": 4, "w": 6, "x": 18, "y": y},
        "options": {
            "mode": "markdown",
            "content": (
                "`make join-app` · `make softflowd`\n\n"
                "Empty spans → check Alloy OTLP.\n"
                "Empty flows → softflowd / peer vars."
            ),
        },
    }
    y += 4

    # ── 1. All conversations (context) ─────────────────────────────
    panels.append(row("1 — All conversations (flow context)", 10, y))
    y += 1
    panels.append(
        {
            "id": 11,
            "type": "table",
            "title": "Top conversations (network_io_by_flow_bytes)",
            "description": "Full softflowd rollup — find the join-app row among UDP iperf noise.",
            "gridPos": {"h": 10, "w": 14, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": "topk(20, network_io_by_flow_bytes)",
                    "format": "table",
                    "instant": True,
                }
            ],
            "transformations": [
                {"id": "labelsToFields", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "job": True,
                            "service_name": True,
                            "dst_host": True,
                            "src_host": True,
                        },
                        "renameByName": {
                            "network_local_address": "local.addr",
                            "network_local_port": "local.port",
                            "network_peer_address": "peer.addr",
                            "network_peer_port": "peer.port",
                            "network_transport": "transport",
                            "network_protocol_name": "proto.name",
                            "device_name": "exporter",
                            "Value": "bytes",
                        },
                    },
                },
            ],
            "fieldConfig": {
                "defaults": {"custom": {"align": "auto", "filterable": True}},
                "overrides": [],
            },
            "options": {"showHeader": True, "footer": {"show": False}},
        }
    )
    panels.append(
        {
            "id": 12,
            "type": "timeseries",
            "title": "Top flow bytes",
            "gridPos": {"h": 10, "w": 10, "x": 14, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": "topk(8, network_io_by_flow_bytes)",
                    "legendFormat": "{{network_local_address}}:{{network_local_port}} → {{network_peer_address}}:{{network_peer_port}} ({{network_transport}})",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "decbytes",
                    "custom": {"drawStyle": "line", "fillOpacity": 10, "spanNulls": True},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
                "tooltip": {"mode": "multi"},
            },
        }
    )
    y += 10

    panels.append(row("2 — Candidate subway (LLDP + service/host entities)", 20, y))
    y += 1
    # Device/host/service nodes + LLDP edges + runs_on/attached overlay from join-app.
    nodes_expr = (
        "("
        + f'label_replace(label_replace(label_replace(label_replace('
        + f'network_topology_device_info{{{TESTER}}}, '
        + f'"id", "$1", "device", "(.*)"), '
        + f'"title", "$1", "device", "(.*)"), '
        + f'"mainStat", "device", "device", "(.*)"), '
        + f'"arc__device", "1", "device", "(.*)")'
        + ") or ("
        + 'label_replace(label_replace('
        + f'max by (id, title, kind) (clos_join_entity_info{{kind="host",{TESTER}}}), '
        + '"mainStat", "host", "kind", ".*"), '
        + '"arc__host", "1", "kind", ".*")'
        + ") or ("
        + 'label_replace(label_replace('
        + f'max by (id, title, kind) (clos_join_entity_info{{kind="service",{TESTER}}}), '
        + '"mainStat", "service", "kind", ".*"), '
        + '"arc__service", "1", "kind", ".*")'
        + ")"
    )
    edges_expr = (
        "("
        + f'label_replace(label_replace(label_replace(label_replace(label_replace('
        + f'network_topology_edge_info{{{TESTER}}}, '
        + f'"id", "$1", "src_port", "(.*)"), '
        + f'"source", "$1", "src_device", "(.*)"), '
        + f'"target", "$1", "dst_device", "(.*)"), '
        + f'"mainStat", "$1", "discovery_proto", "(.*)"), '
        + f'"secondaryStat", "lldp", "link_kind", "(.*)")'
        + ") or ("
        + 'label_replace(label_replace(label_replace(label_replace('
        + f'max by (id, src, dst, kind) (clos_join_edge_info{{{TESTER}}}), '
        + '"source", "$1", "src", "(.*)"), '
        + '"target", "$1", "dst", "(.*)"), '
        + '"mainStat", "$1", "kind", "(.*)"), '
        + '"secondaryStat", "$1", "kind", "(.*)")'
        + ")"
    )
    panels.append(
        {
            "id": 21,
            "type": "nodeGraph",
            "title": "Clos subway + service entities",
            "description": (
                "LLDP fabric (connected_to) plus join-app overlay: "
                "clos-join-demo —runs_on→ client1/2 —attached→ leaf1/2. "
                "Not a proven per-flow path."
            ),
            "gridPos": {"h": 16, "w": 16, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "Nodes",
                    "expr": nodes_expr,
                    "format": "table",
                    "instant": True,
                },
                {
                    "refId": "Edges",
                    "expr": edges_expr,
                    "format": "table",
                    "instant": True,
                },
            ],
            "options": {
                "layoutAlgorithm": "layered",
                "nodes": {"nodeRadius": 40},
                "zoomMode": "cooperative",
            },
        }
    )
    panels.append(
        {
            "id": 22,
            "type": "table",
            "title": "Entity + LLDP edges",
            "gridPos": {"h": 16, "w": 8, "x": 16, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"network_topology_edge_info{{{TESTER}}}",
                    "format": "table",
                    "instant": True,
                },
                {
                    "refId": "B",
                    "expr": f"clos_join_edge_info{{{TESTER}}}",
                    "format": "table",
                    "instant": True,
                },
            ],
            "transformations": [
                {"id": "merge", "options": {}},
                {"id": "labelsToFields", "options": {}},
                {
                    "id": "organize",
                    "options": {
                        "excludeByName": {
                            "Time": True,
                            "__name__": True,
                            "tester_id": True,
                            "Value": True,
                            "service_name": True,
                            "deployment_environment": True,
                        },
                        "renameByName": {
                            "src_device": "src",
                            "dst_device": "dst",
                            "src_port": "src_port",
                            "dst_port": "dst_port",
                            "discovery_proto": "proto",
                            "link_kind": "kind",
                            "kind": "kind",
                        },
                    },
                },
            ],
            "options": {"showHeader": True},
        }
    )
    y += 16

    # ── 3. SNMP health ─────────────────────────────────────────────
    panels.append(row("3 — Packet-relevant health (highlight; ignore PSU/fan)", 30, y))
    y += 1
    panels.append(
        {
            "id": 31,
            "type": "timeseries",
            "title": "Interface in/out errors (Clos)",
            "description": "Highlight CRC/error counters — not facility metrics.",
            "gridPos": {"h": 9, "w": 12, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"sum by (device_name, if_interface_name) (rate(kentik_snmp_ifInErrors{{{CLOS}}}[$__rate_interval]))",
                    "legendFormat": "{{device_name}} {{if_interface_name}} in",
                },
                {
                    "refId": "B",
                    "expr": f"sum by (device_name, if_interface_name) (rate(kentik_snmp_ifOutErrors{{{CLOS}}}[$__rate_interval]))",
                    "legendFormat": "{{device_name}} {{if_interface_name}} out",
                },
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "eps",
                    "custom": {"drawStyle": "line", "fillOpacity": 5},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    panels.append(
        {
            "id": 32,
            "type": "timeseries",
            "title": "Device CPU % (Clos)",
            "gridPos": {"h": 9, "w": 12, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"kentik_snmp_CPU{{{CLOS}}}",
                    "legendFormat": "{{device_name}}",
                }
            ],
            "fieldConfig": {
                "defaults": {
                    "unit": "percent",
                    "min": 0,
                    "max": 100,
                    "custom": {"drawStyle": "line", "fillOpacity": 10},
                },
                "overrides": [],
            },
            "options": {
                "legend": {"displayMode": "list", "placement": "bottom", "showLegend": True},
            },
        }
    )
    y += 9

    panels.append(
        {
            "id": 33,
            "type": "stat",
            "title": "SNMP devices up",
            "gridPos": {"h": 4, "w": 6, "x": 0, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"count(kentik_snmp_Uptime{{{CLOS}}})",
                    "instant": True,
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 34,
            "type": "stat",
            "title": "Topology devices",
            "gridPos": {"h": 4, "w": 6, "x": 6, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"count(network_topology_device_info{{{TESTER}}})",
                    "instant": True,
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 35,
            "type": "stat",
            "title": "Service/host entities",
            "gridPos": {"h": 4, "w": 6, "x": 12, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"count(clos_join_entity_info{{{TESTER}}})",
                    "instant": True,
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )
    panels.append(
        {
            "id": 36,
            "type": "stat",
            "title": "Sum ifInErrors (raw)",
            "gridPos": {"h": 4, "w": 6, "x": 18, "y": y},
            "datasource": DS,
            "targets": [
                {
                    "refId": "A",
                    "expr": f"sum(kentik_snmp_ifInErrors{{{CLOS}}})",
                    "instant": True,
                }
            ],
            "options": {
                "reduceOptions": {"calcs": ["lastNotNull"]},
                "colorMode": "value",
                "graphMode": "none",
            },
        }
    )

    dash["panels"] = panels
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
