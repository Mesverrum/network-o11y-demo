#!/usr/bin/env python3
"""Patch live Alloy A3/A4 connection panels to topology-exporter metrics.

Always GET live first, then PUT through dashboard.grafana.app/v2 so TabsLayout
survives. The marcnetterfield1 A3/A4 boards are the source copied to the
networko11ydev Alloy Network Fork folder.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-topology-connections"
NS = os.environ.get("GRAFANA_NAMESPACE", "stacks-1061129")
TESTER_ID = "network-lab"
SUMMARY_UID = "ma8p7dn"
DETAILS_UID = "alloy-device-details"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("GRAFANA_")})
    env["GRAFANA_URL"] = env.get("GRAFANA_URL") or env.get("NETTERFIELD_GRAFANA_URL", "")
    env["GRAFANA_TOKEN"] = env.get("GRAFANA_TOKEN") or env.get(
        "NETTERFIELD_GRAFANA_TOKEN", ""
    )
    return env


def api(
    env: dict[str, str], method: str, path: str, body: Any | None = None
) -> tuple[int, Any]:
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:2000]}
        return exc.code, payload


def get_live(env: dict[str, str], uid: str) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    code, doc = api(env, "GET", path)
    if code != 200 or not isinstance(doc, dict):
        raise RuntimeError(f"GET {uid} failed HTTP {code}: {doc}")
    layout = ((doc.get("spec") or {}).get("layout") or {}).get("kind")
    if layout != "TabsLayout":
        raise RuntimeError(f"{uid}: expected TabsLayout, got {layout}")
    return doc


def put_live(env: dict[str, str], uid: str, doc: dict, message: str) -> dict:
    body = copy.deepcopy(doc)
    body.setdefault("metadata", {}).setdefault("annotations", {})[
        "grafana.app/message"
    ] = message
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    code, out = api(env, "PUT", path, body)
    if code not in (200, 201) or not isinstance(out, dict):
        raise RuntimeError(f"PUT {uid} failed HTTP {code}: {out}")
    layout = ((out.get("spec") or {}).get("layout") or {}).get("kind")
    if layout != "TabsLayout":
        raise RuntimeError(f"{uid}: TabsLayout lost after update")
    print(
        f"updated {uid} layout={layout} "
        f"generation={(out.get('metadata') or {}).get('generation')}"
    )
    return out


def panel(doc: dict, name: str) -> dict:
    value = ((doc.get("spec") or {}).get("elements") or {}).get(name)
    if not isinstance(value, dict):
        raise KeyError(f"missing {name}")
    return value


def panel_spec(doc: dict, name: str) -> dict:
    value = panel(doc, name).get("spec")
    if not isinstance(value, dict):
        raise KeyError(f"missing {name}.spec")
    return value


def set_query(
    doc: dict,
    name: str,
    expr: str,
    *,
    instant: bool,
    legend: str = "__auto",
    table: bool = False,
) -> None:
    ps = panel_spec(doc, name)
    queries = (((ps.get("data") or {}).get("spec") or {}).get("queries") or [])
    if not queries:
        raise KeyError(f"{name}: no queries")
    query = queries[0].get("spec") or {}
    inner = ((query.get("query") or {}).get("spec") or {})
    inner["expr"] = expr
    inner["legendFormat"] = legend
    inner["instant"] = instant
    inner["range"] = not instant
    inner["queryType"] = "instant" if instant else "range"
    if table:
        inner["format"] = "table"
    query["instant"] = instant


def selected_edges(device_var: str, proto: str | None = None) -> str:
    proto_filter = f',discovery_proto="{proto}"' if proto else ""
    common = f'tester_id="{TESTER_ID}"{proto_filter}'
    return (
        f'(network_topology_edge_info{{{common},src_device=~"${device_var}"}} '
        f'or network_topology_edge_info{{{common},dst_device=~"${device_var}"}})'
    )


def count_selected(device_var: str, proto: str) -> str:
    return f"count({selected_edges(device_var, proto)}) OR vector(0)"


def set_title_description(doc: dict, name: str, title: str, description: str) -> None:
    ps = panel_spec(doc, name)
    ps["title"] = title
    ps["description"] = description


def set_short_unit(doc: dict, name: str) -> None:
    defaults = (
        (((panel_spec(doc, name).get("vizConfig") or {}).get("spec") or {}).get(
            "fieldConfig"
        ) or {}).get("defaults")
    )
    if isinstance(defaults, dict):
        defaults["unit"] = "short"
        defaults["min"] = 0
        defaults.pop("max", None)


def set_observed_count_thresholds(doc: dict, name: str) -> None:
    defaults = (
        (((panel_spec(doc, name).get("vizConfig") or {}).get("spec") or {}).get(
            "fieldConfig"
        ) or {}).get("defaults")
    )
    if isinstance(defaults, dict):
        defaults["unit"] = "short"
        defaults["min"] = 0
        defaults["thresholds"] = {
            "mode": "absolute",
            "steps": [
                {"value": 0, "color": "red"},
                {"value": 1, "color": "green"},
            ],
        }
        defaults["color"] = {"mode": "thresholds"}


def hide_table_noise(doc: dict, name: str) -> None:
    viz = (panel_spec(doc, name).get("vizConfig") or {}).get("spec") or {}
    options = viz.get("options") or {}
    options.pop("sortBy", None)
    field_config = viz.get("fieldConfig") or {}
    field_config["overrides"] = [
        {
            "matcher": {
                "id": "byRegexp",
                "options": "^(Time|Value|__name__|job|instance|service_instance_id|tester_id)$",
            },
            "properties": [{"id": "custom.hidden", "value": True}],
        }
    ]


def rename_tab(doc: dict, old: str, new: str) -> None:
    tabs = ((((doc.get("spec") or {}).get("layout") or {}).get("spec") or {}).get("tabs") or [])
    new_exists = False
    for tab in tabs:
        ts = tab.get("spec") or {}
        if tab.get("kind") == "TabsLayoutTab" and ts.get("title") == old:
            ts["title"] = new
            return
        if tab.get("kind") == "TabsLayoutTab" and ts.get("title") == new:
            new_exists = True
    if new_exists:
        return
    raise KeyError(f"tab {old}")


def rename_row(doc: dict, tab_title: str, new_title: str) -> None:
    tabs = ((((doc.get("spec") or {}).get("layout") or {}).get("spec") or {}).get("tabs") or [])
    for tab in tabs:
        ts = tab.get("spec") or {}
        if ts.get("title") != tab_title:
            continue
        rows = ((((ts.get("layout") or {}).get("spec") or {}).get("rows")) or [])
        if not rows:
            raise KeyError(f"{tab_title}: no rows")
        rows[0].setdefault("spec", {})["title"] = new_title
        return
    raise KeyError(f"tab {tab_title}")


def patch_summary(doc: dict) -> None:
    rename_tab(doc, "Routing", "Connections")
    rename_row(doc, "Connections", "Observed Topology")

    set_query(doc, "panel-165", count_selected("device_name", "bgp"), instant=True)
    set_title_description(
        doc,
        "panel-165",
        "Observed BGP Sessions",
        "Established BGP sessions reconciled by topology-exporter. A session disappears while it is down.",
    )

    expr = (
        f'sort_desc(count by (src_device) (network_topology_edge_info{{tester_id="{TESTER_ID}",'
        'discovery_proto="bgp",src_device=~"$device_name"}))'
    )
    set_query(doc, "panel-164", expr, instant=True, legend="{{src_device}}")
    set_title_description(
        doc,
        "panel-164",
        "Observed BGP Sessions by Device",
        "Current established BGP sessions grouped by the reporting network device.",
    )
    set_short_unit(doc, "panel-164")

    set_query(doc, "panel-166", count_selected("device_name", "lldp"), instant=True)
    set_title_description(
        doc,
        "panel-166",
        "Observed LLDP Links",
        "Current physical adjacencies reconciled by topology-exporter.",
    )

    set_query(
        doc,
        "panel-167",
        selected_edges("device_name"),
        instant=True,
        table=True,
    )
    set_title_description(
        doc,
        "panel-167",
        "Observed Connections",
        "Current BGP and LLDP edges. Use discovery_proto, evidence, src/dst device, ports, and AS labels to distinguish connection types.",
    )
    hide_table_noise(doc, "panel-167")

    set_query(
        doc,
        "panel-168",
        f"count by (discovery_proto) ({selected_edges('device_name')})",
        instant=False,
        legend="{{discovery_proto}}",
    )
    set_title_description(
        doc,
        "panel-168",
        "Observed Topology Edges Over Time",
        "Topology-exporter edge count by protocol. Intentional lab fault injection can briefly remove an edge.",
    )


def patch_has_bgp(doc: dict) -> None:
    for variable in (doc.get("spec") or {}).get("variables") or []:
        vs = variable.get("spec") or {}
        if vs.get("name") != "has_bgp":
            continue
        query = vs.get("query") or {}
        qspec = query.get("spec") or {}
        qspec["metric"] = "network_topology_edge_info"
        qspec["label"] = "src_device"
        qspec["query"] = (
            f'label_values(network_topology_edge_info{{tester_id="{TESTER_ID}",'
            'discovery_proto="bgp",src_device=~"$instance"},src_device)'
        )
        qspec["labelFilters"] = [
            {"label": "tester_id", "op": "=", "value": TESTER_ID},
            {"label": "discovery_proto", "op": "=", "value": "bgp"},
            {"label": "src_device", "op": "=~", "value": "$instance"},
        ]
        return
    raise KeyError("has_bgp")


def patch_details(doc: dict) -> None:
    rename_row(doc, "Connections", "Observed Topology")
    patch_has_bgp(doc)

    set_query(doc, "panel-328", count_selected("instance", "bgp"), instant=True)
    set_title_description(
        doc,
        "panel-328",
        "Observed BGP Sessions",
        "Established BGP edges involving this device. Absence means the edge is unavailable or the topology graph is stale.",
    )
    set_observed_count_thresholds(doc, "panel-328")

    # Convert the old flap timeseries into a second compact connection count.
    panel_spec(doc, "panel-329")["vizConfig"] = copy.deepcopy(
        panel_spec(doc, "panel-328")["vizConfig"]
    )
    set_query(doc, "panel-329", count_selected("instance", "lldp"), instant=True)
    set_title_description(
        doc,
        "panel-329",
        "Observed LLDP Links",
        "Current physical adjacencies involving this device, reconciled from topology signals.",
    )
    set_observed_count_thresholds(doc, "panel-329")

    set_query(
        doc,
        "panel-330",
        selected_edges("instance"),
        instant=True,
        table=True,
    )
    set_title_description(
        doc,
        "panel-330",
        "Observed Connections",
        "Current BGP and LLDP edges involving this device. Raw topology-tier walks stay local and topology-exporter publishes this reconciled graph.",
    )
    hide_table_noise(doc, "panel-330")


def validate_promql(env: dict[str, str], doc: dict, names: list[str]) -> None:
    seen: set[str] = set()
    for name in names:
        ps = panel_spec(doc, name)
        queries = (((ps.get("data") or {}).get("spec") or {}).get("queries") or [])
        for query in queries:
            inner = ((((query.get("spec") or {}).get("query") or {}).get("spec")) or {})
            expr = inner.get("expr")
            if not isinstance(expr, str):
                continue
            expr = expr.replace("$device_name", ".*").replace("$instance", ".*")
            if expr in seen:
                continue
            seen.add(expr)
            params = urllib.parse.urlencode({"query": expr})
            path = (
                "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?"
                + params
            )
            code, payload = api(env, "GET", path)
            status = ((payload or {}).get("status") if isinstance(payload, dict) else None)
            if code != 200 or status != "success":
                raise RuntimeError(f"{name}: PromQL validation failed HTTP {code}: {payload}")
            rows = (((payload or {}).get("data") or {}).get("result") or [])
            print(f"  validated {name} PromQL rows={len(rows)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only", choices=[SUMMARY_UID, DETAILS_UID])
    args = parser.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("GRAFANA_URL and GRAFANA_TOKEN are required")

    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [
        (
            SUMMARY_UID,
            patch_summary,
            ["panel-165", "panel-164", "panel-166", "panel-167", "panel-168"],
        ),
        (
            DETAILS_UID,
            patch_details,
            ["panel-328", "panel-329", "panel-330"],
        ),
    ]
    for uid, patcher, panel_names in jobs:
        if args.only and uid != args.only:
            continue
        doc = get_live(env, uid)
        meta = doc.get("metadata") or {}
        print(
            f"live {uid} generation={meta.get('generation')} "
            f"resourceVersion={meta.get('resourceVersion')} layout=TabsLayout"
        )
        (OUT / f"{uid}-before.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8"
        )
        patcher(doc)
        validate_promql(env, doc, panel_names)
        (OUT / f"{uid}-patched.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8"
        )
        if args.dry_run:
            print(f"dry-run {uid}: wrote patched manifest")
            continue
        out = put_live(
            env,
            uid,
            doc,
            "Connections/Routing panels use topology-exporter BGP + LLDP edges",
        )
        (OUT / f"{uid}-live.json").write_text(
            json.dumps(out, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
