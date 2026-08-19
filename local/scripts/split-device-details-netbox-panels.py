#!/usr/bin/env python3
"""Split dashboard 25: SNMP panels stay SNMP; NetBox SoT is Infinity REST (no join).

Pulls the live v2 manifest, then:
- Overview System Info: SNMP-only (drop query N + SoT SQL + __none__ stubs)
- Interfaces Interface Summary: SNMP-only (drop query G + __none__ stubs)
- Adds sibling Infinity panels (NetBox CMDB identity, NetBox interfaces)

Empty NetBox → empty Infinity table (200 + results[]). No SQL LEFT JOIN.
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NS = "stacks-1061129"
UID = "ktranslate-device-details-netbox"
INFINITY_UID = "netbox-api"
NB_URL = (
    "http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000"
)

SNMP_SYSINFO_SQL = """SELECT DISTINCT Field, Details FROM (
  SELECT 'Device Name' AS Field, COALESCE(MAX(SysName), 'N/A') AS Details FROM A
  UNION ALL SELECT 'Model', COALESCE(MAX(tags_kentik_model), 'N/A') FROM A
  UNION ALL SELECT 'IP Address', COALESCE(MAX(src_addr), 'N/A') FROM A
  UNION ALL SELECT 'SNMP Group', COALESCE(MAX(tags_snmp_group), 'N/A') FROM A
  UNION ALL SELECT 'Poll Interval', COALESCE(MAX(SysPollInterval), 'N/A') FROM A
  UNION ALL SELECT 'Uptime', CONCAT(FLOOR(MAX(__value__) / 8640000), 'd ', FLOOR(MAX(__value__) / 100 % 86400 / 3600), 'h ', FLOOR(MAX(__value__) / 100 % 3600 / 60), 'm') FROM A
  UNION ALL SELECT 'Description', COALESCE(MAX(SysDescr), 'N/A') FROM A
) t
LIMIT 30"""

IFACE_SQL = (
    'SELECT A.if_interface_name AS Interface, '
    'MAX(A.if_Alias) AS Alias, '
    'MIN(A.if_OperStatus) AS "Oper Status", '
    'MAX(A.if_Speed) * 1 AS Speed, '
    'MAX(B.__value__) AS "In BPS (avg)", '
    'MAX(C.__value__) AS "Out BPS (avg)", '
    'MAX(E.__value__) AS "In Util % (latest)", '
    'MAX(F.__value__) AS "Out Util % (latest)" '
    "FROM A "
    "LEFT JOIN B ON A.if_interface_name = B.if_interface_name "
    "LEFT JOIN C ON A.if_interface_name = C.if_interface_name "
    "LEFT JOIN E ON A.if_interface_name = E.if_interface_name "
    "LEFT JOIN F ON A.if_interface_name = F.if_interface_name "
    "GROUP BY A.if_interface_name "
    "ORDER BY 1 LIMIT 1000"
)

DEVICE_JSONATA = (
    "$map(["
    '["Device", results[0].name],'
    '["NetBox ID", $string(results[0].id)],'
    '["Status", results[0].status.value],'
    '["Site", results[0].site.name],'
    '["Role", results[0].role.name],'
    '["Manufacturer", results[0].device_type.manufacturer.name],'
    '["Device type", results[0].device_type.display],'
    '["Platform", results[0].platform.name],'
    '["Serial", results[0].serial],'
    '["Primary IP", results[0].primary_ip.address],'
    '["Rack", results[0].rack.name]'
    '], function($p) {{"Field": $p[0], "Details": $p[1]}})'
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


def strip_none_stub(expr: str) -> str:
    if "__none__" not in expr:
        return expr.rstrip()
    pos = expr.find(" or (\n")
    if pos == -1:
        pos = expr.find(" or (")
    if pos == -1:
        return expr.rstrip()
    return expr[:pos].rstrip()


def infinity_query(spec: dict) -> dict:
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
            "refId": "A",
            "hidden": False,
        },
    }


def table_viz(*, footer: bool = False) -> dict:
    opts: dict[str, Any] = {"cellHeight": "sm", "showHeader": True}
    if footer:
        opts["footer"] = {"show": True, "reducer": ["count"], "countRows": True}
    return {
        "kind": "VizConfig",
        "group": "table",
        "version": "",
        "spec": {
            "options": opts,
            "fieldConfig": {
                "defaults": {
                    "custom": {
                        "align": "auto",
                        "cellOptions": {"type": "auto"},
                        "inspect": False,
                        "wrapText": True,
                    }
                },
                "overrides": [
                    {
                        "matcher": {"id": "byName", "options": "Field"},
                        "properties": [{"id": "custom.width", "value": 140}],
                    },
                    {
                        "matcher": {"id": "byName", "options": "NetBox ID"},
                        "properties": [
                            {
                                "id": "links",
                                "value": [
                                    {
                                        "title": "Open in NetBox",
                                        "url": "${netbox_url}/dcim/devices/${__value.raw}/",
                                        "targetBlank": True,
                                    }
                                ],
                            }
                        ],
                    },
                ],
            },
        },
    }


def nb_link(title: str, url: str) -> dict:
    return {
        "title": title,
        "url": url,
        "type": "link",
        "icon": "external link",
        "tooltip": "",
        "tags": [],
        "asDropdown": False,
        "targetBlank": True,
        "includeVars": True,
        "keepTime": False,
    }


def cmdb_panel(pid: int) -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": "NetBox CMDB identity",
            "description": (
                "Live NetBox REST via Infinity (SoT). Independent of SNMP — "
                "empty inventory shows an empty table, not nulls in System Info."
            ),
            "links": [
                nb_link(
                    "Open device in NetBox",
                    "${netbox_url}/dcim/devices/?q=${instance}",
                )
            ],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [
                        infinity_query(
                            {
                                "type": "json",
                                "source": "url",
                                "format": "table",
                                "parser": "backend",
                                "url": f"{NB_URL}/api/dcim/devices/?name=${{instance}}&limit=1",
                                "url_options": {"method": "GET", "data": ""},
                                "root_selector": DEVICE_JSONATA,
                                "columns": [
                                    {"selector": "Field", "text": "Field", "type": "string"},
                                    {"selector": "Details", "text": "Details", "type": "string"},
                                ],
                                "filters": [],
                            }
                        )
                    ],
                    "transformations": [],
                    "queryOptions": {},
                },
            },
            "vizConfig": table_viz(),
        },
    }


def ifaces_panel(pid: int) -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": "NetBox interfaces (SoT)",
            "description": (
                "Intended interface inventory from NetBox REST (Infinity). "
                "Not joined to SNMP — compare by name next to Interface Summary."
            ),
            "links": [
                nb_link(
                    "All interfaces in NetBox",
                    "${netbox_url}/dcim/interfaces/?device=${instance}",
                )
            ],
            "data": {
                "kind": "QueryGroup",
                "spec": {
                    "queries": [
                        infinity_query(
                            {
                                "type": "json",
                                "source": "url",
                                "format": "table",
                                "parser": "backend",
                                "url": (
                                    f"{NB_URL}/api/dcim/interfaces/"
                                    "?device=${instance}&limit=200"
                                ),
                                "url_options": {"method": "GET", "data": ""},
                                "root_selector": "results",
                                "columns": [
                                    {"selector": "name", "text": "Name", "type": "string"},
                                    {"selector": "type.label", "text": "Type", "type": "string"},
                                    {"selector": "enabled", "text": "Enabled", "type": "boolean"},
                                    {"selector": "mgmt_only", "text": "Mgmt only", "type": "boolean"},
                                    {
                                        "selector": "description",
                                        "text": "Description",
                                        "type": "string",
                                    },
                                    {
                                        "selector": "count_ipaddresses",
                                        "text": "IPs",
                                        "type": "number",
                                    },
                                    {"selector": "cable.id", "text": "Cable ID", "type": "number"},
                                ],
                                "filters": [],
                            }
                        )
                    ],
                    "transformations": [],
                    "queryOptions": {},
                },
            },
            "vizConfig": table_viz(footer=True),
        },
    }


def grid_item(name: str, *, x: int, y: int, w: int, h: int) -> dict:
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


def queries_of(el: dict) -> list:
    return (((el.get("spec") or {}).get("data") or {}).get("spec") or {}).get(
        "queries"
    ) or []


def set_sql(el: dict, ref: str, expr: str) -> None:
    for q in queries_of(el):
        qs = q.get("spec") or {}
        if qs.get("refId") != ref:
            continue
        spec = (qs.get("query") or {}).setdefault("spec", {})
        spec["type"] = "sql"
        spec["expression"] = expr
        return
    raise KeyError(f"SQL ref {ref} missing")


def set_prom_expr(el: dict, ref: str, expr: str) -> None:
    for q in queries_of(el):
        qs = q.get("spec") or {}
        if qs.get("refId") != ref:
            continue
        qs["query"]["spec"]["expr"] = expr
        return
    raise KeyError(f"prom ref {ref} missing")


def drop_refs(el: dict, refs: set[str]) -> None:
    qg = el["spec"]["data"]["spec"]
    qg["queries"] = [
        q for q in qg["queries"] if (q.get("spec") or {}).get("refId") not in refs
    ]


def simplify_snmp_table(el: dict, *, sql_ref: str, sql: str, drop: set[str]) -> None:
    qg = el["spec"]["data"]["spec"]
    for q in qg["queries"]:
        qs = q.get("spec") or {}
        dq = qs.get("query") or {}
        if dq.get("group") != "prometheus":
            continue
        dspec = dq.get("spec") or {}
        expr = dspec.get("expr") or ""
        if "__none__" in expr:
            dspec["expr"] = strip_none_stub(expr)
    drop_refs(el, drop)
    set_sql(el, sql_ref, sql)


def max_panel_id(elements: dict) -> int:
    n = 0
    for el in elements.values():
        pid = (el.get("spec") or {}).get("id")
        if isinstance(pid, int) and pid > n:
            n = pid
    return n


def probe_infinity(env: dict[str, str]) -> None:
    now = int(time.time() * 1000)
    q = {
        "refId": "A",
        "datasource": {"type": "yesoreyeram-infinity-datasource", "uid": INFINITY_UID},
        "type": "json",
        "source": "url",
        "format": "table",
        "parser": "backend",
        "url": f"{NB_URL}/api/dcim/devices/?name=spine1&limit=1",
        "url_options": {"method": "GET", "data": ""},
        "root_selector": DEVICE_JSONATA,
        "columns": [
            {"selector": "Field", "text": "Field", "type": "string"},
            {"selector": "Details", "text": "Details", "type": "string"},
        ],
        "filters": [],
    }
    code, out = api(env, "POST", "/api/ds/query", {"queries": [q], "from": str(now - 60000), "to": str(now)})
    if code != 200:
        raise SystemExit(f"Infinity probe HTTP {code}: {out}")
    res = ((out or {}).get("results") or {}).get("A") or {}
    if res.get("error"):
        raise SystemExit(f"Infinity probe error: {res.get('error')}")
    frames = res.get("frames") or []
    n = 0
    if frames:
        values = (frames[0].get("data") or {}).get("values") or []
        n = len(values[0]) if values else 0
    print(f"infinity probe spine1 rows={n} status={res.get('status')}")
    if n < 5:
        raise SystemExit("Infinity CMDB flatten returned too few rows")


def main() -> int:
    os.environ.setdefault("PYTHONUTF8", "1")
    env = load_env()
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"

    code, ds = api(env, "GET", f"/api/datasources/uid/{INFINITY_UID}")
    if code != 200:
        raise SystemExit(f"Infinity DS {INFINITY_UID} missing ({code})")
    print("datasource", ds.get("name"), ds.get("type"))
    probe_infinity(env)

    code, dash = api(env, "GET", path)
    if code != 200 or not dash:
        print("GET failed", code, dash)
        return 1
    gen0 = (dash.get("metadata") or {}).get("generation")
    print("pulled generation", gen0)

    els = dash["spec"]["elements"]
    p60 = els["panel-60"]
    simplify_snmp_table(p60, sql_ref="B", sql=SNMP_SYSINFO_SQL, drop={"N"})
    p60["spec"]["title"] = "System Info"
    p60["spec"]["description"] = (
        "SNMP identity for $instance (sysName, model, mgmt IP, uptime). "
        "NetBox CMDB is the sibling Infinity panel — not joined here."
    )
    print("panel-60 SNMP-only")

    p315 = els["panel-315"]
    simplify_snmp_table(p315, sql_ref="D", sql=IFACE_SQL, drop={"G"})
    p315["spec"]["title"] = "Interface Summary"
    p315["spec"]["description"] = (
        "Live SNMP oper/speed/traffic for $instance. "
        "NetBox interface inventory is the sibling Infinity panel — not joined here."
    )
    # Drop leftover SoT column width overrides
    fc = p315["spec"]["vizConfig"]["spec"].setdefault("fieldConfig", {})
    overrides = fc.get("overrides") or []
    sot_names = {"Type (SoT)", "Enabled (SoT)", "NB Description", "IPs (SoT)", "Cable ID"}
    fc["overrides"] = [
        o
        for o in overrides
        if (o.get("matcher") or {}).get("options") not in sot_names
    ]
    print("panel-315 SNMP-only")

    # Overview Interface Summary clone — drop unused NetBox join if present
    p58 = els.get("panel-58")
    if p58:
        refs = {(q.get("spec") or {}).get("refId") for q in queries_of(p58)}
        if "G" in refs or "N" in refs:
            simplify_snmp_table(
                p58,
                sql_ref="D" if "D" in refs else "B",
                sql=IFACE_SQL if "D" in refs else SNMP_SYSINFO_SQL,
                drop={"G", "N"} & refs,
            )
            print("panel-58 stripped NetBox join")

    next_id = max_panel_id(els) + 1
    cmdb_id = next_id
    next_id += 1
    ifaces_id = next_id
    n_cmdb = f"panel-{cmdb_id}"
    n_ifaces = f"panel-{ifaces_id}"
    els[n_cmdb] = cmdb_panel(cmdb_id)
    els[n_ifaces] = ifaces_panel(ifaces_id)
    print("added", n_cmdb, n_ifaces)

    tabs = dash["spec"]["layout"]["spec"]["tabs"]
    overview = next(t for t in tabs if t["spec"]["title"] == "Overview")
    for row in overview["spec"]["layout"]["spec"]["rows"]:
        if (row.get("spec") or {}).get("title") != "SNMP Device Details":
            continue
        items = row["spec"]["layout"]["spec"]["items"]
        new_items = []
        for it in items:
            name = it["spec"]["element"]["name"]
            if name == "panel-60":
                new_items.append(grid_item("panel-60", x=0, y=0, w=10, h=10))
                new_items.append(grid_item(n_cmdb, x=10, y=0, w=10, h=10))
            elif name in ("panel-99", "panel-100"):
                new_items.append(it)
            else:
                new_items.append(it)
        row["spec"]["layout"]["spec"]["items"] = new_items
        row["spec"]["title"] = "Identity — SNMP live + NetBox SoT"
        print("relayout Overview identity row")
        break

    iface_tab = next(t for t in tabs if t["spec"]["title"] == "Interfaces")
    for row in iface_tab["spec"]["layout"]["spec"]["rows"]:
        if (row.get("spec") or {}).get("title") != "Interface Summary":
            continue
        items = row["spec"]["layout"]["spec"]["items"]
        new_items = []
        for it in items:
            name = it["spec"]["element"]["name"]
            if name == "panel-315":
                new_items.append(grid_item("panel-315", x=0, y=10, w=12, h=14))
                new_items.append(grid_item(n_ifaces, x=12, y=10, w=12, h=14))
            else:
                new_items.append(it)
        row["spec"]["layout"]["spec"]["items"] = new_items
        print("relayout Interfaces summary row")
        break

    ann = dash.setdefault("metadata", {}).setdefault("annotations", {})
    ann["grafana.app/message"] = (
        "Split NetBox SoT to Infinity panels; SNMP System Info / Interface Summary no longer join"
    )

    code, out = api(env, "PUT", path, dash)
    if code not in (200, 201):
        print("PUT failed", code)
        print(json.dumps(out, indent=2)[:3000] if isinstance(out, dict) else out)
        return 1
    kind = (out or {}).get("spec", {}).get("layout", {}).get("kind")
    gen = (out or {}).get("metadata", {}).get("generation")
    print(f"updated {UID} generation={gen} layout={kind}")
    if kind != "TabsLayout":
        print("ERROR: TabsLayout lost")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
