#!/usr/bin/env python3
"""Rebuild A1 Alloy Health around signals the network fork actually exports.

Always GET live first, then PUT v2. Never POST /api/dashboards/db.

What this stack has (colocated dual-write):
  up{job="alloy-snmp"}                    hot/cold scrape targets
  snmp_scrape_*                           walk/duration/packets/PDUs (gauges)
  snmp_CPU / snmp_Uptime                  device telemetry presence
  discovery_snmp_*{job="alloy"}           in-process discovery.snmp (snmp-sd)
  alloy_build_info{job="alloy"}           colocated collector build
  alloy_network_io_by_flow_bytes          integration=alloy-netflow (Sum → rate())
  Loki {service_name="alloy-snmptrap"}    traps
  Loki {service_name="alloy-syslog"}      syslog
  Loki docker/k8s Alloy lines             |= "SNMP discovery"

What it does *not* have:
  ktranslate CHF / jchf queues
  otelcol_receiver_* on this tenant
  job=integrations/alloy from this collector
    (that series is a different e2e Alloy on this stack — do not mix)

Usage:
  python local/scripts/rebuild-alloy-health.py --dry-run
  python local/scripts/rebuild-alloy-health.py
"""
from __future__ import annotations

import argparse
import copy
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-network-fork-dev"
NS = "stacks-1544961"
UID = "alloy-health"
VIZ = "13.2.0-31683987170"
PROM = {"name": "$datasource"}
LOKI = {"name": "grafanacloud-logs"}
SEL = 'job="alloy-snmp",snmp_group=~"$snmp_group",device_name=~"$device_name"'
DISC = 'job="alloy"'
DISC_LOG = '{service_name="alloy"} |~ "(?i)SNMP (discovery|catalog|probe|fingerprint)"'
CTX = ssl.create_default_context()


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    env["GRAFANA_URL"] = env.get("GRAFANA_URL_2") or env.get("GRAFANA_URL") or ""
    env["GRAFANA_TOKEN"] = env.get("GRAFANA_TOKEN_2") or env.get("GRAFANA_TOKEN") or ""
    return env


def api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        env["GRAFANA_URL"].rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=CTX, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:4000]}
        return e.code, payload


def query_var(name: str, label: str, metric: str, query: str, filters: list[dict] | None = None) -> dict:
    spec: dict[str, Any] = {
        "qryType": 1,
        "query": query,
        "label": label,
        "metric": metric,
        "refId": "PrometheusVariableQueryEditor-VariableQuery",
    }
    if filters:
        spec["labelFilters"] = filters
    return {
        "kind": "QueryVariable",
        "spec": {
            "name": name,
            "label": label.replace("_", " ").title() if name != "snmp_group" else "SNMP group",
            "hide": "dontHide",
            "refresh": "onTimeRangeChanged",
            "skipUrlSync": False,
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": {"name": "$datasource"},
                "spec": spec,
            },
            "regex": "",
            "regexApplyTo": "value",
            "sort": "alphabeticalAsc",
            "definition": query,
            "options": [],
            "multi": True,
            "includeAll": True,
            "allValue": ".*",
            "allowCustomValue": True,
            "current": {"text": "All", "value": ["$__all"]},
        },
    }


def variables() -> list[dict]:
    return [
        {
            "kind": "DatasourceVariable",
            "spec": {
                "name": "datasource",
                "pluginId": "prometheus",
                "refresh": "onDashboardLoad",
                "regex": "",
                "current": {"text": "grafanacloud-networko11ydev-prom", "value": "grafanacloud-prom"},
                "options": [],
                "multi": False,
                "includeAll": False,
                "label": "Prometheus data source",
                "hide": "dontHide",
                "skipUrlSync": False,
                "allowCustomValue": True,
            },
        },
        query_var(
            "snmp_group",
            "snmp_group",
            "up",
            'label_values(up{job="alloy-snmp"},snmp_group)',
        ),
        query_var(
            "device_name",
            "device_name",
            "up",
            'label_values(up{job="alloy-snmp",snmp_group=~"$snmp_group"},device_name)',
            filters=[{"label": "snmp_group", "op": "=~", "value": "$snmp_group"}, {"label": "job", "op": "=", "value": "alloy-snmp"}],
        ),
    ]


def _prom_q(expr: str, *, instant: bool, legend: str = "") -> dict:
    inner: dict[str, Any] = {
        "expr": expr,
        "instant": instant,
        "queryType": "instant" if instant else "range",
        "range": not instant,
    }
    if legend:
        inner["legendFormat"] = legend
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": "prometheus",
                "version": "v0",
                "datasource": PROM,
                "spec": inner,
            },
            "refId": "A",
            "hidden": False,
        },
    }


def _loki_q(expr: str, *, instant: bool) -> dict:
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": "loki",
                "version": "v0",
                "datasource": LOKI,
                "spec": {
                    "expr": expr,
                    "instant": instant,
                    "queryType": "instant" if instant else "range",
                    "range": not instant,
                },
            },
            "refId": "A",
            "hidden": False,
        },
    }


def panel(
    pid: int,
    title: str,
    viz: str,
    queries: list[dict],
    *,
    desc: str = "",
    unit: str | None = None,
    instant_stat: bool = False,
    thresholds: list[tuple[float | None, str]] | None = None,
    transforms: list[dict] | None = None,
) -> dict:
    if viz == "stat":
        options = {
            "colorMode": "background",
            "graphMode": "none",
            "justifyMode": "auto",
            "orientation": "auto",
            "percentChangeColorMode": "standard",
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "showPercentChange": False,
            "textMode": "auto",
            "wideLayout": True,
        }
        steps = [{"value": t[0], "color": t[1]} for t in (thresholds or [(0, "blue")])]
        if steps and steps[0]["value"] is None:
            steps[0]["value"] = 0
        field = {
            "defaults": {
                "unit": unit or "short",
                "thresholds": {"mode": "absolute", "steps": steps},
                "color": {"mode": "thresholds"},
            },
            "overrides": [],
        }
    elif viz == "timeseries":
        options = {
            "legend": {
                "calcs": ["mean", "max"],
                "displayMode": "list",
                "placement": "bottom",
                "showLegend": True,
            },
            "tooltip": {"mode": "multi", "sort": "desc"},
        }
        field = {
            "defaults": {
                "unit": unit or "short",
                "color": {"mode": "palette-classic"},
                "custom": {
                    "drawStyle": "line",
                    "fillOpacity": 10,
                    "lineWidth": 2,
                    "showPoints": "never",
                    "spanNulls": 120000,
                    "stacking": {"group": "A", "mode": "none"},
                },
            },
            "overrides": [],
        }
    elif viz == "table":
        options = {"cellHeight": "sm", "footer": {"show": False}, "showHeader": True}
        field = {"defaults": {"custom": {"align": "auto", "filterable": True}}, "overrides": []}
    elif viz == "logs":
        options = {
            "dedupStrategy": "none",
            "enableLogDetails": True,
            "showLabels": False,
            "showTime": True,
            "sortOrder": "Descending",
            "wrapLogMessage": False,
        }
        field = {"defaults": {}, "overrides": []}
    else:
        raise ValueError(viz)

    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": desc,
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": queries,
                    "transformations": transforms or [],
                    "queryOptions": {},
                },
            },
            "vizConfig": {
                "kind": "VizConfig",
                "group": viz,
                "version": VIZ,
                "spec": {"options": options, "fieldConfig": field},
            },
        },
    }


def table_transforms(rename: dict[str, str], order: list[str], *, keep: list[str] | None = None) -> list[dict]:
    exclude = {
        "Time": True,
        "job": True,
        "collector": True,
        "deployment_host": True,
        "service_name": True,
        "service_instance_id": True,
        "sysObjectID": True,
    }
    for name in keep or []:
        exclude.pop(name, None)
    return [
        {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
        {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
        {
            "kind": "Transformation",
            "group": "organize",
            "spec": {
                "options": {
                    "excludeByName": exclude,
                    "indexByName": {name: i for i, name in enumerate(order)},
                    "renameByName": rename,
                }
            },
        },
    ]


def grid_item(name: str, x: int, y: int, w: int, h: int) -> dict:
    return {
        "kind": "GridLayoutItem",
        "spec": {
            "x": x,
            "y": y,
            "width": w,
            "height": h,
            "element": {"kind": "ElementReference", "name": name},
        },
    }


def row(title: str, items: list[dict], *, hide_header: bool = False) -> dict:
    return {
        "kind": "RowsLayoutRow",
        "spec": {
            "title": title,
            "collapse": False,
            "hideHeader": hide_header,
            "fillScreen": False,
            "layout": {"kind": "GridLayout", "spec": {"items": items}},
        },
    }


def tab(title: str, rows: list[dict]) -> dict:
    return {
        "kind": "TabsLayoutTab",
        "spec": {
            "title": title,
            "layout": {"kind": "RowsLayout", "spec": {"rows": rows}},
        },
    }


def build_elements() -> dict[str, dict]:
    els: dict[str, dict] = {}

    def add(key: str, p: dict) -> None:
        els[key] = p

    # --- Overview stats ---
    add(
        "ov-up",
        panel(
            1,
            "Devices up (hot)",
            "stat",
            [_prom_q(f'count(count by (device_name) (up{{{SEL},snmp_tier="hot"}} == 1)) OR vector(0)', instant=True)],
            desc="Distinct devices with a successful Alloy hot-tier SNMP scrape (60s).",
            thresholds=[(0, "red"), (1, "green")],
        ),
    )
    add(
        "ov-down",
        panel(
            2,
            "Devices down (hot)",
            "stat",
            [_prom_q(f'count(up{{{SEL},snmp_tier="hot"}} == 0) OR vector(0)', instant=True)],
            desc="Hot-tier scrape targets that are down. 0 is healthy.",
            thresholds=[(0, "green"), (1, "yellow"), (2, "red")],
        ),
    )
    add(
        "ov-cpu",
        panel(
            3,
            "Devices with snmp_CPU",
            "stat",
            [_prom_q(f'count(count by (device_name) (snmp_CPU{{{SEL}}})) OR vector(0)', instant=True)],
            desc="Devices exporting snmp_CPU (identity/CPU walk succeeded).",
            thresholds=[(0, "red"), (1, "green")],
        ),
    )
    add(
        "ov-flow",
        panel(
            4,
            "Flow conversations",
            "stat",
            [_prom_q('count(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}) OR vector(0)', instant=True)],
            desc="Series count for Alloy-native flow (otelcol.receiver.netflow → signaltometrics).",
            thresholds=[(0, "red"), (1, "green")],
        ),
    )
    add(
        "ov-traps",
        panel(
            5,
            "Trap lines (15m)",
            "stat",
            [_loki_q('sum(count_over_time({service_name="alloy-snmptrap"}[15m])) or vector(0)', instant=True)],
            desc="Loki {service_name=alloy-snmptrap}.",
            thresholds=[(0, "blue")],
        ),
    )
    add(
        "ov-syslog",
        panel(
            6,
            "Syslog lines (15m)",
            "stat",
            [_loki_q('sum(count_over_time({service_name="alloy-syslog"}[15m])) or vector(0)', instant=True)],
            desc="Loki {service_name=alloy-syslog}. Plain text; severity is a label.",
            thresholds=[(0, "blue")],
        ),
    )
    add(
        "ov-catalog",
        panel(
            9,
            "Discovery catalog",
            "stat",
            [_prom_q(f'sum(discovery_snmp_devices{{{DISC}}}) OR vector(0)', instant=True)],
            desc="Devices in the last successful discovery.snmp catalog (job=alloy). Not the walk.",
            thresholds=[(0, "red"), (1, "green")],
        ),
    )
    add(
        "ov-walk",
        panel(
            7,
            "Hot walk duration",
            "timeseries",
            [
                _prom_q(
                    f'max by (device_name) (snmp_scrape_walk_duration_seconds{{{SEL},snmp_tier="hot"}})',
                    instant=False,
                    legend="{{device_name}}",
                )
            ],
            desc="snmp_exporter walk duration per device (hot tier). Gauge — not rate().",
            unit="s",
        ),
    )
    add(
        "ov-up-ts",
        panel(
            8,
            "Hot scrape up",
            "timeseries",
            [
                _prom_q(
                    f'max by (device_name) (up{{{SEL},snmp_tier="hot"}})',
                    instant=False,
                    legend="{{device_name}}",
                )
            ],
            desc="1 = Alloy reached the device on the hot scrape. job=alloy-snmp.",
        ),
    )

    # --- SNMP scrape ---
    add(
        "sc-table",
        panel(
            10,
            "Scrape targets",
            "table",
            [
                _prom_q(
                    f'max by (device_name, snmp_group, snmp_tier, instance) (up{{{SEL}}})',
                    instant=True,
                )
            ],
            desc="One row per device × tier (hot 60s / cold 5m). Value 1 = up.",
            transforms=table_transforms(
                {"device_name": "Device", "snmp_group": "Group", "snmp_tier": "Tier", "instance": "Exporter", "Value": "Up"},
                ["device_name", "snmp_group", "snmp_tier", "instance", "Value"],
            ),
        ),
    )
    add(
        "sc-walk-mod",
        panel(
            11,
            "Walk duration by module",
            "timeseries",
            [
                _prom_q(
                    f'max by (device_name, module, snmp_tier) (snmp_scrape_walk_duration_seconds{{{SEL}}})',
                    instant=False,
                    legend="{{device_name}} {{module}} {{snmp_tier}}",
                )
            ],
            desc="Per-module walk time (if_mib, if_mib_meta, ip_addr, nokia_srlinux_ext, …). Gauge.",
            unit="s",
        ),
    )
    add(
        "sc-retry",
        panel(
            12,
            "Packets retried (last scrape)",
            "timeseries",
            [
                _prom_q(
                    f'sum by (device_name, module) (snmp_scrape_packets_retried{{{SEL}}})',
                    instant=False,
                    legend="{{device_name}} {{module}}",
                )
            ],
            desc="snmp_exporter last-scrape retry count (gauge, not a counter). Spikes mean timeouts.",
        ),
    )
    add(
        "sc-pdu",
        panel(
            13,
            "PDUs returned (last scrape)",
            "timeseries",
            [
                _prom_q(
                    f'sum by (device_name, module) (snmp_scrape_pdus_returned{{{SEL}}})',
                    instant=False,
                    legend="{{device_name}} {{module}}",
                )
            ],
            desc="SNMP PDUs returned on the last walk. Gauge.",
        ),
    )
    add(
        "sc-uptime",
        panel(
            14,
            "Device sysUpTime",
            "timeseries",
            [
                _prom_q(
                    f'max by (device_name) (snmp_Uptime{{{SEL}}}) / 100',
                    instant=False,
                    legend="{{device_name}}",
                )
            ],
            desc="SNMPv2 sysUpTime (TimeTicks) as seconds. Reboots reset this.",
            unit="s",
        ),
    )

    # --- Flow ---
    add(
        "fl-count",
        panel(
            20,
            "Flow series",
            "stat",
            [_prom_q('count(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}) OR vector(0)', instant=True)],
            desc="Conversations currently in Mimir from Alloy netflow/sFlow.",
            thresholds=[(0, "red"), (1, "green")],
        ),
    )
    add(
        "fl-bps",
        panel(
            21,
            "Flow throughput",
            "timeseries",
            [
                _prom_q(
                    'sum(rate(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}[$__rate_interval])) * 8',
                    instant=False,
                    legend="bps",
                )
            ],
            desc="Alloy flow is a cumulative Sum. Use rate().",
            unit="bps",
        ),
    )
    add(
        "fl-dev",
        panel(
            22,
            "Flow bytes by device",
            "timeseries",
            [
                _prom_q(
                    'sum by (device_name) (rate(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}[$__rate_interval]))',
                    instant=False,
                    legend="{{device_name}}",
                )
            ],
            desc="Bytes/s by catalog device_name (sampler join). Empty device_name = unmatched exporter.",
            unit="Bps",
        ),
    )

    # --- Events ---
    add(
        "ev-trap-vol",
        panel(
            30,
            "Trap volume",
            "timeseries",
            [
                _loki_q(
                    'sum by (trap_oid) (count_over_time({service_name="alloy-snmptrap"}[$__interval]))',
                    instant=False,
                )
            ],
            desc="Loki {service_name=alloy-snmptrap}. Group by trap_oid — not eventType=KSnmpTrap.",
        ),
    )
    add(
        "ev-syslog-vol",
        panel(
            31,
            "Syslog volume",
            "timeseries",
            [
                _loki_q(
                    'sum by (severity) (count_over_time({service_name="alloy-syslog"}[$__interval]))',
                    instant=False,
                )
            ],
            desc="Loki {service_name=alloy-syslog}. severity is a label; do not | json.",
        ),
    )
    add(
        "ev-traps",
        panel(
            32,
            "Recent traps",
            "logs",
            [_loki_q('{service_name="alloy-snmptrap"}', instant=False)],
            desc="JSON trap body. Labels include device_name, trap_oid, snmp_group when join hits.",
        ),
    )
    add(
        "ev-syslog",
        panel(
            33,
            "Recent syslog",
            "logs",
            [_loki_q('{service_name="alloy-syslog"}', instant=False)],
            desc="Plain-text syslog (protocol=none). severity/facility are labels.",
        ),
    )
    # --- Discovery (snmp-sd / discovery.snmp) ---
    add(
        "ds-devices",
        panel(
            40,
            "Catalog by group",
            "stat",
            [_prom_q(f'sum by (group) (discovery_snmp_devices_by_group{{{DISC}}}) OR vector(0)', instant=True)],
            desc="Last successful catalog. group is the discovery job (hq / branch1 / branch2).",
            thresholds=[(0, "red"), (1, "green")],
        ),
    )
    add(
        "ds-stale",
        panel(
            41,
            "Stale (misses > 0)",
            "stat",
            [_prom_q(f'sum(discovery_snmp_catalog_stale{{{DISC}}}) OR vector(0)', instant=True)],
            desc="Catalog entries that missed this scan and are approaching drop.",
            thresholds=[(0, "green"), (1, "yellow"), (3, "red")],
        ),
    )
    add(
        "ds-unknown",
        panel(
            42,
            "Unknown fingerprints",
            "stat",
            [_prom_q(f'sum(increase(discovery_snmp_fingerprint_total{{{DISC},result="unknown"}}[1h])) OR vector(0)', instant=True)],
            desc="sysObjectID used the default device_base/if_mib chain in the last hour.",
            thresholds=[(0, "green"), (1, "yellow")],
        ),
    )
    add(
        "ds-scan",
        panel(
            43,
            "Scan duration",
            "timeseries",
            [
                _prom_q(
                    f'histogram_quantile(0.95, sum by (le) (rate(discovery_snmp_scan_duration_seconds_bucket{{{DISC}}}[$__rate_interval])))',
                    instant=False,
                    legend="p95",
                )
            ],
            desc="discovery.snmp scan duration. Compare to refresh_interval (lab 5m).",
            unit="s",
        ),
    )
    add(
        "ds-errors",
        panel(
            44,
            "Probe errors by reason",
            "timeseries",
            [
                _prom_q(
                    f'sum by (reason, group) (increase(discovery_snmp_probe_errors_total{{{DISC}}}[$__rate_interval]))',
                    instant=False,
                    legend="{{group}} {{reason}}",
                )
            ],
            desc="Identity Get failures. timeout/refused on a CIDR sweep is normal; no_auth/no_sys is not.",
        ),
    )
    add(
        "ds-fp",
        panel(
            45,
            "Fingerprint outcome",
            "timeseries",
            [
                _prom_q(
                    f'sum by (result, group) (increase(discovery_snmp_fingerprint_total{{{DISC}}}[$__rate_interval]))',
                    instant=False,
                    legend="{{group}} {{result}}",
                )
            ],
            desc="known = matcher hit. unknown = default chain (device_base / if_mib).",
        ),
    )
    add(
        "ds-table",
        panel(
            46,
            "Catalog identity",
            "table",
            [
                _prom_q(
                    f'max by (device_name, address, group, auth, sysObjectID) (discovery_snmp_device_info{{{DISC}}})',
                    instant=True,
                )
            ],
            desc="Last-good catalog. Join this to up{job=alloy-snmp} when a walk is empty.",
            transforms=table_transforms(
                {
                    "device_name": "Device",
                    "address": "Address",
                    "group": "Group",
                    "auth": "Auth",
                    "sysObjectID": "sysObjectID",
                    "Value": "In catalog",
                },
                ["device_name", "address", "group", "auth", "sysObjectID", "Value"],
                keep=["sysObjectID"],
            ),
        ),
    )
    add(
        "ds-logs",
        panel(
            47,
            "Discovery logs",
            "logs",
            [_loki_q(DISC_LOG, instant=False)],
            desc="Alloy stdout: scan complete, catalog add/drop, unknown fingerprint, no_auth/no_sys. Timeouts stay Debug.",
        ),
    )
    return els


def build_layout() -> dict:
    return {
        "kind": "TabsLayout",
        "spec": {
            "tabs": [
                tab(
                    "Overview",
                    [
                        row(
                            "Fleet",
                            [
                                grid_item("ov-up", 0, 0, 3, 5),
                                grid_item("ov-down", 3, 0, 3, 5),
                                grid_item("ov-cpu", 6, 0, 3, 5),
                                grid_item("ov-catalog", 9, 0, 3, 5),
                                grid_item("ov-flow", 12, 0, 4, 5),
                                grid_item("ov-traps", 16, 0, 4, 5),
                                grid_item("ov-syslog", 20, 0, 4, 5),
                            ],
                        ),
                        row(
                            "Hot scrape",
                            [
                                grid_item("ov-up-ts", 0, 0, 12, 10),
                                grid_item("ov-walk", 12, 0, 12, 10),
                            ],
                        ),
                    ],
                ),
                tab(
                    "Discovery",
                    [
                        row(
                            "Catalog",
                            [
                                grid_item("ds-devices", 0, 0, 8, 5),
                                grid_item("ds-stale", 8, 0, 8, 5),
                                grid_item("ds-unknown", 16, 0, 8, 5),
                            ],
                        ),
                        row(
                            "Scan + probes",
                            [
                                grid_item("ds-scan", 0, 0, 12, 9),
                                grid_item("ds-errors", 12, 0, 12, 9),
                            ],
                        ),
                        row("Fingerprint", [grid_item("ds-fp", 0, 0, 24, 8)]),
                        row("Identity", [grid_item("ds-table", 0, 0, 24, 8)]),
                        row("Logs", [grid_item("ds-logs", 0, 0, 24, 12)]),
                    ],
                ),
                tab(
                    "SNMP scrape",
                    [
                        row("Targets", [grid_item("sc-table", 0, 0, 24, 8)]),
                        row(
                            "Walk cost",
                            [
                                grid_item("sc-walk-mod", 0, 0, 24, 10),
                            ],
                        ),
                        row(
                            "Last scrape",
                            [
                                grid_item("sc-retry", 0, 0, 12, 9),
                                grid_item("sc-pdu", 12, 0, 12, 9),
                            ],
                        ),
                        row("Device uptime", [grid_item("sc-uptime", 0, 0, 24, 8)]),
                    ],
                ),
                tab(
                    "Flow",
                    [
                        row("Volume", [grid_item("fl-count", 0, 0, 6, 5), grid_item("fl-bps", 6, 0, 18, 8)]),
                        row("By device", [grid_item("fl-dev", 0, 0, 24, 10)]),
                    ],
                ),
                tab(
                    "Events",
                    [
                        row(
                            "Volume",
                            [
                                grid_item("ev-trap-vol", 0, 0, 12, 9),
                                grid_item("ev-syslog-vol", 12, 0, 12, 9),
                            ],
                        ),
                        row(
                            "Recent",
                            [
                                grid_item("ev-traps", 0, 0, 12, 12),
                                grid_item("ev-syslog", 12, 0, 12, 12),
                            ],
                        ),
                    ],
                ),
            ]
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        print("Need GRAFANA_URL_2 / GRAFANA_TOKEN_2", file=sys.stderr)
        return 1

    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"
    code, live = api(env, "GET", path)
    if code != 200 or not isinstance(live, dict):
        print(f"GET {UID} failed {code}: {live}", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "alloy-health-pre-rebuild.json").write_text(json.dumps(live), encoding="utf-8")
    print(f"live gen={live['metadata'].get('generation')} elements={len(live['spec'].get('elements') or {})}")

    doc = copy.deepcopy(live)
    spec = doc["spec"]
    spec["title"] = "A1. Alloy Health"
    spec["description"] = (
        "Collector health for the Alloy network fork on this stack: "
        "discovery.snmp (job=alloy discovery_snmp_*), SNMP scrape "
        "(up + snmp_scrape_*), Alloy-native flow, and Loki "
        "alloy-snmptrap / alloy-syslog. "
        "Do not use job=integrations/alloy here — that series is a different Alloy."
    )
    spec["tags"] = ["alloy", "network-lab", "network-o11y", "health"]
    spec["variables"] = variables()
    spec["elements"] = build_elements()
    spec["layout"] = build_layout()
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from alloy_dash_nav import apply_alloy_nav_links

    apply_alloy_nav_links(spec, "alloy-health")
    doc.setdefault("metadata", {}).setdefault("annotations", {})["grafana.app/message"] = (
        "A1 Discovery tab: discovery_snmp_* job=alloy + snmp-sd logs"
    )

    (OUT / "alloy-health-rebuild.json").write_text(json.dumps(doc), encoding="utf-8")
    print(f"elements={len(spec['elements'])} tabs={len(spec['layout']['spec']['tabs'])}")
    if args.dry_run:
        print("dry-run: wrote alloy-health-rebuild.json")
        return 0

    code, out = api(env, "PUT", path, doc)
    if code not in (200, 201) or not isinstance(out, dict):
        print(f"PUT failed {code}: {out}", file=sys.stderr)
        return 1
    kind = out["spec"]["layout"]["kind"]
    gen = out["metadata"].get("generation")
    print(f"updated {UID} layout={kind} generation={gen}")
    if kind != "TabsLayout":
        print("TabsLayout lost — restore from version history", file=sys.stderr)
        return 1
    (OUT / "alloy-health-live.json").write_text(json.dumps(out), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
