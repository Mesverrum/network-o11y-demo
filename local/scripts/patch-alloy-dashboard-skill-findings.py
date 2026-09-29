#!/usr/bin/env python3
"""Apply Alloy dashboard skill findings to live A3/A4 v2 manifests.

Always GET live first and PUT the same manifest with its resourceVersion.
Never uses the legacy dashboard API, so TabsLayout is preserved.
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Iterator

from alloy_dash_nav import scrub_spec_prose


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-dashboard-skill-findings"
TESTER_ID = "network-lab"
STACKS = {
    "marc": {
        "url": "GRAFANA_URL",
        "token": "GRAFANA_TOKEN",
        "namespace": "stacks-1061129",
        "a3": "ma8p7dn",
        "a4": "alloy-device-details",
    },
    "dev": {
        "url": "GRAFANA_URL_2",
        "token": "GRAFANA_TOKEN_2",
        "namespace": "stacks-1544961",
        "a3": "alloy-device-summary",
        "a4": "alloy-device-details",
    },
}
A3_INSTANT_PANELS = {
    "panel-156",
    "panel-169",
    "panel-174",
    "panel-175",
    "panel-176",
    "panel-181",
    "panel-182",
    "panel-208",
    "panel-209",
    "panel-210",
}
A4_INSTANT_PANELS = {"panel-205"}
FLOW_METRIC_RE = re.compile(
    r'(?<![A-Za-z0-9_:])alloy_network_io_by_flow_bytes\{(?:[^"}]|"[^"]*")*\}'
)


def rewrite_flow_expr(expr: str) -> str:
    """Retarget ktranslate flow names and rollups to Alloy counters."""
    if "network_io_by_flow_bytes" not in expr:
        return expr
    out = re.sub(
        r"(?<!alloy_)network_io_by_flow_bytes",
        "alloy_network_io_by_flow_bytes",
        expr,
    )
    out = re.sub(
        r"alloy_network_io_by_flow_bytes\{(?![^}]*integration=)",
        'alloy_network_io_by_flow_bytes{integration="alloy-netflow",',
        out,
    )
    out = re.sub(r"\bnetwork_protocol_name\b", "network_transport", out)
    out = re.sub(
        r"max_over_time\((alloy_network_io_by_flow_bytes\{.*?\})\[\$__range\]\)",
        r"increase(\1[$__range])",
        out,
        flags=re.S,
    )
    out = re.sub(
        r"max_over_time\((alloy_network_io_by_flow_bytes\{.*?\})\[\$__interval\]\)",
        r"rate(\1[$__interval])",
        out,
        flags=re.S,
    )
    return out


def rewrite_links(spec: dict[str, Any]) -> None:
    text = json.dumps(spec)
    text = text.replace(
        "/d/ktranslate-flow-summary", "/d/alloy-flow-summary"
    )
    spec.clear()
    spec.update(json.loads(text))


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for raw in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        env[key.strip()] = value.strip().strip('"').strip("'")
    env.update(os.environ)
    env["GRAFANA_URL"] = env.get("GRAFANA_URL") or env.get(
        "NETTERFIELD_GRAFANA_URL", ""
    )
    env["GRAFANA_TOKEN"] = env.get("GRAFANA_TOKEN") or env.get(
        "NETTERFIELD_GRAFANA_TOKEN", ""
    )
    return env


def api(
    base: str,
    token: str,
    method: str,
    path: str,
    body: Any | None = None,
) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            raw = response.read().decode("utf-8")
            return response.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:2000]}
        return exc.code, payload


def dashboard_path(namespace: str, uid: str) -> str:
    return f"/apis/dashboard.grafana.app/v2/namespaces/{namespace}/dashboards/{uid}"


def get_live(base: str, token: str, namespace: str, uid: str) -> dict[str, Any]:
    code, document = api(base, token, "GET", dashboard_path(namespace, uid))
    if code != 200 or not isinstance(document, dict):
        raise RuntimeError(f"GET {uid} failed HTTP {code}: {document}")
    layout = ((document.get("spec") or {}).get("layout") or {}).get("kind")
    if layout != "TabsLayout":
        raise RuntimeError(f"{uid}: expected TabsLayout, got {layout}")
    return document


def put_live(
    base: str,
    token: str,
    namespace: str,
    uid: str,
    document: dict[str, Any],
) -> dict[str, Any]:
    body = copy.deepcopy(document)
    body.setdefault("metadata", {}).setdefault("annotations", {})[
        "grafana.app/message"
    ] = "Apply Alloy dashboard skill findings"
    code, result = api(
        base, token, "PUT", dashboard_path(namespace, uid), body
    )
    if code not in (200, 201) or not isinstance(result, dict):
        raise RuntimeError(f"PUT {uid} failed HTTP {code}: {result}")
    layout = ((result.get("spec") or {}).get("layout") or {}).get("kind")
    if layout != "TabsLayout":
        raise RuntimeError(f"{uid}: TabsLayout lost after update")
    return result


def elements(document: dict[str, Any]) -> dict[str, dict[str, Any]]:
    value = ((document.get("spec") or {}).get("elements") or {})
    if not isinstance(value, dict):
        raise KeyError("spec.elements")
    return value


def panel_spec(document: dict[str, Any], name: str) -> dict[str, Any]:
    element = elements(document).get(name)
    if not isinstance(element, dict) or not isinstance(element.get("spec"), dict):
        raise KeyError(name)
    return element["spec"]


def iter_queries(
    document: dict[str, Any],
) -> Iterator[tuple[str, str, dict[str, Any], dict[str, Any]]]:
    for name, element in elements(document).items():
        spec = element.get("spec") or {}
        title = str(spec.get("title") or name)
        query_group = ((spec.get("data") or {}).get("spec") or {})
        for query in query_group.get("queries") or []:
            query_spec = query.get("spec") or {}
            inner = ((query_spec.get("query") or {}).get("spec") or {})
            yield name, title, query_spec, inner


def set_panel_instant(document: dict[str, Any], name: str) -> int:
    changed = 0
    for panel_name, _, query_spec, inner in iter_queries(document):
        if panel_name != name or not isinstance(inner.get("expr"), str):
            continue
        if "$__range" in inner["expr"] or " offset " in inner["expr"]:
            raise RuntimeError(f"{name}: refusing instant conversion for range expression")
        before = (inner.get("instant"), inner.get("range"), inner.get("queryType"))
        inner["instant"] = True
        inner["range"] = False
        inner["queryType"] = "instant"
        query_spec["instant"] = True
        if before != (True, False, "instant"):
            changed += 1
    return changed


def remove_kentik_ping_queries(document: dict[str, Any]) -> int:
    spec = panel_spec(document, "panel-68")
    query_group = ((spec.get("data") or {}).get("spec") or {})
    queries = query_group.get("queries") or []
    kept = []
    removed = 0
    for query in queries:
        inner = ((((query.get("spec") or {}).get("query") or {}).get("spec")) or {})
        if "kentik_ping_" in str(inner.get("expr") or ""):
            removed += 1
        else:
            kept.append(query)
    query_group["queries"] = kept
    return removed


def replace_exact_value(value: Any, old: str, new: str) -> int:
    changed = 0
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(child, str) and child == old:
                value[key] = new
                changed += 1
            else:
                changed += replace_exact_value(child, old, new)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, str) and child == old:
                value[index] = new
                changed += 1
            else:
                changed += replace_exact_value(child, old, new)
    return changed


def rename_has_ping(document: dict[str, Any]) -> int:
    changed = 0
    for variable in (document.get("spec") or {}).get("variables") or []:
        spec = variable.get("spec") or {}
        if spec.get("name") == "has_ping":
            spec["name"] = "has_snmp_scrape_health"
            spec["description"] = (
                "Gates the Alloy SNMP scrape-health row; this is not ICMP ping."
            )
            changed += 1
    changed += replace_exact_value(
        (document.get("spec") or {}).get("layout"),
        "has_ping",
        "has_snmp_scrape_health",
    )
    return changed


def clean_topology_transform(document: dict[str, Any], name: str) -> int:
    spec = panel_spec(document, name)
    transformations = (((spec.get("data") or {}).get("spec") or {}).get(
        "transformations"
    ) or [])
    changed = 0
    stale = (
        "tBgpPeerNg",
        "snmp_tBgpPeerNg",
        "tags_kentik_model",
        "tags_container_service",
    )
    for transformation in transformations:
        options = (transformation.get("spec") or {}).get("options") or {}
        for field in ("excludeByName", "renameByName", "indexByName"):
            mapping = options.get(field)
            if not isinstance(mapping, dict):
                continue
            for key in list(mapping):
                if any(token in key for token in stale):
                    mapping.pop(key, None)
                    changed += 1
    return changed


def ensure_alloy_flow_selector(selector: str) -> str:
    if "integration=" in selector:
        return selector
    return selector.replace(
        "alloy_network_io_by_flow_bytes{",
        'alloy_network_io_by_flow_bytes{integration="alloy-netflow",',
        1,
    )


def rewrite_a4_flow(document: dict[str, Any]) -> int:
    changed = 0
    for _, _, _, inner in iter_queries(document):
        expr = inner.get("expr")
        if not isinstance(expr, str) or "network_io_by_flow_bytes" not in expr:
            continue
        rewritten = rewrite_flow_expr(expr)
        is_instant = bool(inner.get("instant"))

        def replace_selector(match: re.Match[str]) -> str:
            selector = ensure_alloy_flow_selector(match.group(0))
            start = match.start()
            prefix = rewritten[max(0, start - 16) : start]
            if re.search(r"(?:rate|increase)\($", prefix):
                return selector
            window = "$__range" if is_instant else "$__rate_interval"
            function = "increase" if is_instant else "rate"
            return f"{function}({selector}[{window}])"

        rewritten = FLOW_METRIC_RE.sub(replace_selector, rewritten)
        rewritten = re.sub(
            r"last_over_time\((increase\(alloy_network_io_by_flow_bytes"
            r'\{(?:[^"}]|"[^"]*")*\}\[\$__range\]\))\[\$__range\]\)',
            r"\1",
            rewritten,
        )
        if rewritten != expr:
            inner["expr"] = rewritten
            changed += 1

    for variable in (document.get("spec") or {}).get("variables") or []:
        query_spec = (((variable.get("spec") or {}).get("query") or {}).get("spec") or {})
        metric = query_spec.get("metric")
        if metric == "network_io_by_flow_bytes":
            query_spec["metric"] = "alloy_network_io_by_flow_bytes"
            changed += 1
        query = query_spec.get("query")
        if isinstance(query, str) and "network_io_by_flow_bytes" in query:
            rewritten = rewrite_flow_expr(query)
            if rewritten != query:
                query_spec["query"] = rewritten
                changed += 1

    before = json.dumps(document.get("spec") or {}, sort_keys=True)
    rewrite_links(document["spec"])
    after = json.dumps(document.get("spec") or {}, sort_keys=True)
    if after != before:
        changed += 1
    return changed


def add_topology_stale_stat(document: dict[str, Any]) -> int:
    panel_name = "panel-354"
    all_elements = elements(document)
    if panel_name in all_elements:
        stale_panel = all_elements[panel_name]
    else:
        stale_panel = copy.deepcopy(all_elements["panel-328"])
        all_elements[panel_name] = stale_panel

    spec = stale_panel["spec"]
    spec["id"] = 354
    spec["title"] = "Topology Graph Stale"
    spec["description"] = (
        "Global topology-exporter state. 0 is current; 1 means the exporter is "
        "holding its last-known snapshot while fresh ingest is unavailable. "
        "A missing metric is treated as unknown/stale."
    )
    query_group = ((spec.get("data") or {}).get("spec") or {})
    queries = query_group.get("queries") or []
    if not queries:
        raise KeyError("panel-354 query")
    query_spec = queries[0].get("spec") or {}
    inner = ((query_spec.get("query") or {}).get("spec") or {})
    inner["expr"] = (
        f'max(network_topology_graph_stale{{tester_id="{TESTER_ID}"}}) '
        "OR vector(1)"
    )
    inner["legendFormat"] = "Graph stale"
    inner["instant"] = True
    inner["range"] = False
    inner["queryType"] = "instant"
    query_spec["instant"] = True

    defaults = (
        ((spec.get("vizConfig") or {}).get("spec") or {})
        .get("fieldConfig", {})
        .get("defaults")
    )
    if not isinstance(defaults, dict):
        raise KeyError("panel-354 fieldConfig.defaults")
    defaults["unit"] = "short"
    defaults["min"] = 0
    defaults["max"] = 1
    defaults["color"] = {"mode": "thresholds"}
    defaults["thresholds"] = {
        "mode": "absolute",
        "steps": [
            {"value": 0, "color": "green"},
            {"value": 1, "color": "red"},
        ],
    }

    layout = ((document.get("spec") or {}).get("layout") or {})
    rows_found = 0

    def walk(node: Any) -> None:
        nonlocal rows_found
        if isinstance(node, dict):
            node_spec = node.get("spec") or {}
            if (
                node.get("kind") == "RowsLayoutRow"
                and node_spec.get("title") == "Observed Topology"
            ):
                node_spec.pop("conditionalRendering", None)
                grid = node_spec.get("layout") or {}
                items = ((grid.get("spec") or {}).get("items") or [])
                for item in items:
                    item_spec = item.get("spec") or {}
                    reference = item_spec.get("element") or {}
                    if reference.get("name") == "panel-329":
                        item_spec["x"] = 6
                        item_spec["width"] = 12
                if not any(
                    ((item.get("spec") or {}).get("element") or {}).get("name")
                    == panel_name
                    for item in items
                ):
                    items.append(
                        {
                            "kind": "GridLayoutItem",
                            "spec": {
                                "x": 18,
                                "y": 0,
                                "width": 6,
                                "height": 5,
                                "element": {
                                    "kind": "ElementReference",
                                    "name": panel_name,
                                },
                            },
                        }
                    )
                rows_found += 1
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(layout)
    if rows_found != 1:
        raise RuntimeError(f"expected one Observed Topology row, found {rows_found}")
    return 1


def patch_a3(document: dict[str, Any]) -> dict[str, int]:
    spec = document.get("spec") or {}
    spec["description"] = (
        "Alloy fleet view: SNMP (`snmp_*`, job=`alloy-snmp`), recording-rule "
        "composites, Alloy-native flow and events, and topology-exporter "
        "BGP/LLDP edges. Interface counters use Prometheus rates. Device "
        "drill-down links open A4 Alloy Device Details."
    )
    panel_spec(document, "panel-189")["description"] = (
        "Firing network alert instances from the Alloy network rule group."
    )
    counts = {
        "instant_queries": sum(
            set_panel_instant(document, name) for name in A3_INSTANT_PANELS
        ),
        "topology_transform_fields": clean_topology_transform(
            document, "panel-167"
        ),
        "prose": scrub_spec_prose(spec),
    }
    return counts


def patch_a4(document: dict[str, Any]) -> dict[str, int]:
    counts = {
        "removed_kentik_ping_queries": remove_kentik_ping_queries(document),
        "renamed_scrape_gate": rename_has_ping(document),
        "instant_queries": sum(
            set_panel_instant(document, name) for name in A4_INSTANT_PANELS
        ),
        "topology_transform_fields": clean_topology_transform(
            document, "panel-330"
        ),
        "topology_stale_stat": add_topology_stale_stat(document),
        "flow_rewrites": rewrite_a4_flow(document),
        "prose": scrub_spec_prose(document.get("spec") or {}),
    }
    return counts


def query_rows(document: dict[str, Any], needle: str) -> list[str]:
    rows = []
    for name, title, query_spec, inner in iter_queries(document):
        expr = inner.get("expr")
        if isinstance(expr, str) and needle in expr:
            rows.append(
                f"{name} {title!r} ref={query_spec.get('refId')} "
                f"instant={inner.get('instant')}: {expr}"
            )
    return rows


def validate_document(role: str, document: dict[str, Any]) -> None:
    layout = ((document.get("spec") or {}).get("layout") or {}).get("kind")
    if layout != "TabsLayout":
        raise RuntimeError(f"{role}: layout changed to {layout}")
    text = json.dumps(document.get("spec") or {})
    forbidden = ["kentik_ping_", "/d/ktranslate-flow-summary"]
    for token in forbidden:
        if token in text:
            raise RuntimeError(f"{role}: forbidden token remains: {token}")
    if role == "a4":
        for row in query_rows(document, "network_io_by_flow_bytes"):
            if "alloy_network_io_by_flow_bytes" not in row:
                raise RuntimeError(f"a4: ktranslate flow metric remains: {row}")
            if "label_values(" not in row and not any(
                function in row for function in ("rate(", "increase(")
            ):
                raise RuntimeError(f"a4: unconverted flow counter: {row}")


def validate_promql(
    base: str, token: str, document: dict[str, Any], names: set[str]
) -> None:
    for name, title, _, inner in iter_queries(document):
        if name not in names:
            continue
        expr = inner.get("expr")
        if not isinstance(expr, str):
            continue
        concrete = (
            expr.replace("$device_name", ".*")
            .replace("$instance", ".*")
            .replace("$snmp_group", ".*")
            .replace("$__range", "1h")
            .replace("$__rate_interval", "5m")
            .replace("$__interval", "5m")
        )
        concrete = re.sub(r"\$\{[^}]+\}", ".*", concrete)
        concrete = re.sub(r"\$[A-Za-z_][A-Za-z0-9_]*", ".*", concrete)
        params = urllib.parse.urlencode({"query": concrete})
        path = "/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?" + params
        code, payload = api(base, token, "GET", path)
        status = payload.get("status") if isinstance(payload, dict) else None
        if code != 200 or status != "success":
            raise RuntimeError(
                f"{name} {title}: PromQL failed HTTP {code}: {payload}"
            )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--stack", choices=["all", *STACKS], default="all")
    args = parser.parse_args()
    env = load_env()
    targets = STACKS if args.stack == "all" else {args.stack: STACKS[args.stack]}
    OUT.mkdir(parents=True, exist_ok=True)

    for stack, config in targets.items():
        base = env.get(config["url"], "")
        token = env.get(config["token"], "")
        if not base or not token:
            raise SystemExit(
                f"{stack}: need {config['url']} and {config['token']} in local/.env"
            )
        for role in ("a3", "a4"):
            uid = config[role]
            document = get_live(base, token, config["namespace"], uid)
            metadata = document.get("metadata") or {}
            print(
                f"{stack} {role} {uid}: generation={metadata.get('generation')} "
                f"resourceVersion={metadata.get('resourceVersion')} layout=TabsLayout"
            )
            (OUT / f"{stack}-{role}-{uid}-before.json").write_text(
                json.dumps(document, indent=2), encoding="utf-8"
            )
            counts = patch_a3(document) if role == "a3" else patch_a4(document)
            validate_document(role, document)
            validate_names = A3_INSTANT_PANELS | {"panel-167"}
            if role == "a4":
                validate_names = A4_INSTANT_PANELS | {
                    "panel-68",
                    "panel-282",
                    "panel-283",
                    "panel-284",
                    "panel-285",
                    "panel-286",
                    "panel-287",
                    "panel-288",
                    "panel-301",
                    "panel-302",
                    "panel-303",
                    "panel-304",
                    "panel-305",
                    "panel-306",
                    "panel-307",
                    "panel-308",
                    "panel-309",
                    "panel-310",
                    "panel-311",
                    "panel-312",
                    "panel-330",
                    "panel-354",
                }
            validate_promql(base, token, document, validate_names)
            (OUT / f"{stack}-{role}-{uid}-patched.json").write_text(
                json.dumps(document, indent=2), encoding="utf-8"
            )
            print(f"  changes={counts}")
            if role == "a4":
                for row in query_rows(document, "network_io_by_flow_bytes"):
                    print(f"  flow {row}")
            if args.dry_run:
                continue
            result = put_live(
                base, token, config["namespace"], uid, document
            )
            (OUT / f"{stack}-{role}-{uid}-live.json").write_text(
                json.dumps(result, indent=2), encoding="utf-8"
            )
            print(
                f"  updated generation={(result.get('metadata') or {}).get('generation')}"
            )


if __name__ == "__main__":
    main()
