#!/usr/bin/env python3
"""Retarget live NetBox OTLP panels to Infinity REST; drop netbox-inventory sidecar queries.

Pulls v2 manifests for dashboards 20/22/24/25, replaces Prometheus
netbox_* queries with Infinity `netbox-api`, rewrites deep links to `$instance`,
keeps TabsLayout. Inventory history stays in NetBox (changelog/journal).
"""
from __future__ import annotations

import copy
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NS = "stacks-1061129"
INFINITY_UID = "netbox-api"
NB_URL = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)
UIDS = [
    "ktranslate-device-details-netbox",
    "netbox-inventory-sot",
    "orb-netbox-overview",
    "orb-ktranslate-entity-readiness",
]
NEEDLES = (
    "netbox_device_info",
    "netbox_interface_info",
    "netbox_device_count",
    "netbox_interface_count",
    "netbox_ip_address_count",
    "netbox-inventory-otlp",
    'service_name="netbox-inventory"',
    "service_name=\\\"netbox-inventory\\\"",
)


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(env: dict[str, str], method: str, path: str, body: Any | None = None):
    base = env["GRAFANA_URL"].rstrip("/")
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
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
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:4000]}
        return e.code, payload


def infinity_spec(*, url: str, columns: list[dict], root: str, object_root: bool) -> dict:
    spec: dict[str, Any] = {
        "type": "json",
        "source": "url",
        "format": "table",
        "parser": "backend",
        "url": url,
        "url_options": {"method": "GET", "data": ""},
        "root_selector": root,
        "columns": columns,
        "filters": [],
    }
    if object_root:
        spec["json_options"] = {"root_is_not_array": True, "columnar": False}
    return spec


def infinity_query(spec: dict, *, ref: str = "A", hidden: bool = False) -> dict:
    return {
        "kind": "PanelQuery",
        "spec": {
            "query": {
                "kind": "DataQuery",
                "group": "yesoreyeram-infinity-datasource",
                "version": "v0",
                "datasource": {"name": INFINITY_UID},
                "spec": spec,
            },
            "refId": ref,
            "hidden": hidden,
        },
    }


def count_spec(path: str) -> dict:
    return infinity_spec(
        url=f"{NB_URL}{path}",
        columns=[{"selector": "count", "text": "count", "type": "number"}],
        root="",
        object_root=True,
    )


COUNT_PATHS = {
    "dev_count": "/api/dcim/devices/?limit=1",
    "iface_count": "/api/dcim/interfaces/?limit=1",
    "ip_count": "/api/ipam/ip-addresses/?limit=1",
    "dev_present": "/api/dcim/devices/?name=${instance}&limit=1",
    "iface_count_selected": "/api/dcim/interfaces/?device=${instance}&limit=1",
}

DEVICE_LIST_COLUMNS = [
    {"selector": "name", "text": "Device", "type": "string"},
    {"selector": "id", "text": "NetBox ID", "type": "number"},
    {"selector": "status.value", "text": "Status", "type": "string"},
    {"selector": "site.name", "text": "Site", "type": "string"},
    {"selector": "role.name", "text": "Role", "type": "string"},
    {"selector": "device_type.manufacturer.name", "text": "Manufacturer", "type": "string"},
    {"selector": "device_type.display", "text": "Type", "type": "string"},
    {"selector": "platform.name", "text": "Platform", "type": "string"},
    {"selector": "serial", "text": "Serial", "type": "string"},
    {"selector": "primary_ip.address", "text": "Primary IP", "type": "string"},
]


def classify_expr(expr: str) -> str | None:
    if not expr:
        return None
    if "netbox_interface_count" in expr and "netbox_device_count" in expr:
        return "fanout"
    if "netbox_ip_address_count" in expr:
        return "ip_count"
    if "netbox_interface_count" in expr:
        return "iface_count"
    if "netbox_device_count" in expr:
        return "dev_count"
    if "netbox_interface_info" in expr:
        return "iface_table"
    if "netbox_device_info" in expr:
        if "$instance" in expr:
            return "dev_present"
        return "dev_table"
    return None


def query_expr(q: dict) -> str:
    dspec = ((q.get("spec") or {}).get("query") or {}).get("spec") or {}
    expr = dspec.get("expr") or dspec.get("expression") or ""
    return expr if isinstance(expr, str) else json.dumps(expr)


def query_blob(q: dict) -> str:
    return json.dumps(q)


def uses_otlp(q: dict) -> bool:
    blob = query_blob(q)
    return any(n in blob for n in NEEDLES) or classify_expr(query_expr(q)) is not None


def rewrite_links(s: str) -> str:
    s = s.replace(
        "${netbox_url}/dcim/devices/${netbox_id}/",
        "${netbox_url}/dcim/devices/?q=${instance}",
    )
    s = s.replace("device_id=${netbox_id}", "device=${instance}")
    s = s.replace(
        "`$netbox_id` is resolved from `netbox_device_info{device_name=~\"$instance\"}`.",
        "Deep links search NetBox by `$instance` (device name).",
    )
    s = s.replace(
        "`$netbox_id` is resolved from `netbox_device_info{{device_name=~\"$instance\"}}`.",
        "Deep links search NetBox by `$instance` (device name).",
    )
    s = s.replace("netbox-inventory-otlp", "Infinity datasource `netbox-api`")
    s = s.replace("`netbox_device_info`", "NetBox REST (Infinity)")
    s = s.replace("netbox_device_info", "NetBox REST (Infinity)")
    s = s.replace("`netbox_device_count`", "NetBox `/api/dcim/devices/` count")
    s = s.replace("`netbox_interface_count`", "NetBox `/api/dcim/interfaces/` count")
    s = s.replace("netbox_device_count", "NetBox device count (Infinity)")
    s = s.replace("netbox_interface_count", "NetBox interface count (Infinity)")
    s = s.replace('service_name="netbox-inventory"', "Infinity `netbox-api`")
    return s


def walk_rewrite_strings(obj: Any) -> Any:
    if isinstance(obj, str):
        return rewrite_links(obj)
    if isinstance(obj, list):
        return [walk_rewrite_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: walk_rewrite_strings(v) for k, v in obj.items()}
    return obj


def first_stat_viz(elements: dict) -> dict | None:
    for el in elements.values():
        viz = (el.get("spec") or {}).get("vizConfig") or {}
        if viz.get("group") == "stat":
            return copy.deepcopy(viz)
    return None


def set_infinity_count(el: dict, kind: str, *, ref: str = "A") -> None:
    path = COUNT_PATHS[kind]
    qg = el["spec"]["data"]["spec"]
    qg["queries"] = [infinity_query(count_spec(path), ref=ref)]
    qg["transformations"] = []
    desc = (el["spec"].get("description") or "")
    if "OTLP" in desc or "netbox_device" in desc or "inventory export" in desc:
        el["spec"]["description"] = (
            "Live NetBox REST via Infinity `netbox-api`. "
            "Empty inventory returns count=0 (not a panel error)."
        )


def set_infinity_table(el: dict) -> None:
    qg = el["spec"]["data"]["spec"]
    qg["queries"] = [
        infinity_query(
            infinity_spec(
                url=f"{NB_URL}/api/dcim/devices/?limit=200",
                columns=DEVICE_LIST_COLUMNS,
                root="results",
                object_root=False,
            )
        )
    ]
    qg["transformations"] = []
    el["spec"]["description"] = (
        "Live NetBox device list via Infinity. Click NetBox ID / Device name in NetBox UI."
    )
    # Ensure table viz
    if (el["spec"].get("vizConfig") or {}).get("group") != "table":
        el["spec"]["vizConfig"] = {
            "kind": "VizConfig",
            "group": "table",
            "version": "",
            "spec": {
                "options": {"showHeader": True, "cellHeight": "sm"},
                "fieldConfig": {"defaults": {"custom": {"inspect": False}}, "overrides": []},
            },
        }


def set_fanout(el: dict) -> None:
    qg = el["spec"]["data"]["spec"]
    qg["queries"] = [
        infinity_query(count_spec(COUNT_PATHS["iface_count"]), ref="A", hidden=True),
        infinity_query(count_spec(COUNT_PATHS["dev_count"]), ref="B", hidden=True),
        {
            "kind": "PanelQuery",
            "spec": {
                "refId": "C",
                "hidden": False,
                "query": {
                    "kind": "DataQuery",
                    "group": "__expr__",
                    "version": "v0",
                    "datasource": {"name": "__expr__"},
                    "spec": {
                        "type": "sql",
                        "expression": 'SELECT A.count - B.count AS "Fan-out"',
                    },
                },
            },
        },
    ]
    qg["transformations"] = []
    el["spec"]["description"] = (
        "NetBox interface count minus device count (Infinity). "
        "Talk-track: Orb discovered_hosts tracks entities, not hosts."
    )


def rewrite_panel(el: dict, *, stat_viz: dict | None) -> str | None:
    spec = el.get("spec") or {}
    title = spec.get("title") or ""
    viz = (spec.get("vizConfig") or {}).get("group") or ""
    data = spec.get("data") or {}
    qg = data.get("spec") if isinstance(data, dict) else None
    if not qg:
        return None
    queries = qg.get("queries") or []
    if not queries:
        return None

    otlp_idxs = [i for i, q in enumerate(queries) if uses_otlp(q)]
    if not otlp_idxs:
        return None

    kinds = [classify_expr(query_expr(queries[i])) for i in otlp_idxs]
    all_otlp = len(otlp_idxs) == len(queries)

    # Mixed timeseries: drop NetBox Prom queries, keep Orb/ktranslate.
    if viz == "timeseries" and not all_otlp:
        qg["queries"] = [q for q in queries if not uses_otlp(q)]
        spec["title"] = title.replace("Devices vs interfaces vs ", "")
        spec["description"] = (
            (spec.get("description") or "")
            + " NetBox counts are Infinity stats on this board (not timeseries)."
        ).strip()
        return f"stripped NetBox from timeseries {title!r}"

    kind = next((k for k in kinds if k), None)
    if kind == "fanout":
        set_fanout(el)
        return f"fanout→Infinity SQL {title!r}"
    if kind == "dev_table" or (kind is None and "netbox_device_info" in json.dumps(queries)):
        set_infinity_table(el)
        return f"table→Infinity {title!r}"
    if kind in COUNT_PATHS:
        set_infinity_count(el, kind)
        if viz == "timeseries" and stat_viz:
            spec["vizConfig"] = copy.deepcopy(stat_viz)
        return f"stat→Infinity {kind} {title!r}"

    # Fallback: device count
    set_infinity_count(el, "dev_count")
    return f"fallback count {title!r}"


def drop_netbox_id_var(dash: dict) -> None:
    vars_ = (dash.get("spec") or {}).get("variables") or []
    dash["spec"]["variables"] = [
        v for v in vars_ if (v.get("spec") or {}).get("name") != "netbox_id"
    ]


def remaining_needles(dash: dict) -> list[str]:
    blob = json.dumps(dash)
    return [n for n in NEEDLES if n in blob]


def main() -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    env = load_env()
    code, ds = api(env, "GET", f"/api/datasources/uid/{INFINITY_UID}")
    if code != 200:
        raise SystemExit(f"Infinity DS missing ({code})")
    print("datasource", ds.get("name"))

    for uid in UIDS:
        path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
        code, dash = api(env, "GET", path)
        if code != 200 or not dash:
            print("GET failed", uid, code)
            return 1
        gen0 = (dash.get("metadata") or {}).get("generation")
        kind0 = dash["spec"]["layout"]["kind"]
        print(f"\n== {uid} gen={gen0} layout={kind0} ==")

        els = dash["spec"]["elements"]
        stat_viz = first_stat_viz(els)
        for name, el in list(els.items()):
            msg = rewrite_panel(el, stat_viz=stat_viz)
            if msg:
                print(" ", name, msg.encode("ascii", "replace").decode("ascii"))

        dash = walk_rewrite_strings(dash)
        drop_netbox_id_var(dash)
        leftover = remaining_needles(dash)
        if leftover:
            print("  leftover needles", leftover)

        ann = dash.setdefault("metadata", {}).setdefault("annotations", {})
        ann["grafana.app/message"] = (
            "NetBox panels query Infinity REST (netbox-api); retired netbox-inventory OTLP sidecar"
        )
        code, out = api(env, "PUT", path, dash)
        if code not in (200, 201):
            print("PUT failed", uid, code)
            print(json.dumps(out, indent=2)[:2500] if isinstance(out, dict) else out)
            return 1
        kind = (out or {}).get("spec", {}).get("layout", {}).get("kind")
        gen = (out or {}).get("metadata", {}).get("generation")
        print(f"  updated gen={gen} layout={kind}")
        if kind != kind0:
            print("ERROR layout changed", kind0, kind)
            return 1
        leftover2 = remaining_needles(out or dash)
        if leftover2:
            print("  still leftover after PUT", leftover2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
