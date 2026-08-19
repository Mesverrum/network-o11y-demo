#!/usr/bin/env python3
"""Fix Device Details: expand all rows, safe RoomAlert PromQL, rehome Overview leftovers."""
from __future__ import annotations

import copy
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ktranslate_upstream import load_local_env, path_for_uid  # noqa: E402

UID = "ktranslate-device-details"
OVERVIEW, INTERFACES, HARDWARE, CONNECTIONS, FLOW, EVENTS, TELEMETRY = range(7)
HYPHEN_METRIC = "kentik_snmp_digital-sen1-1"
SAFE_SELECTOR = '{__name__="kentik_snmp_digital-sen1-1",device_name=~"$instance"}'
SAFE_PANEL = (
    '{__name__="kentik_snmp_digital-sen1-1",snmp_group=~"$snmp_group",device_name=~"$instance"}'
)


def load_env() -> dict[str, str]:
    load_local_env()
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(base: str, token: str, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
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
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:3000]}


def row_gate(row: dict) -> str | None:
    cr = row.get("spec", {}).get("conditionalRendering") or row.get("conditionalRendering")
    if not cr:
        return None
    stack = [cr]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("variable") and str(cur["variable"]).startswith("has_"):
                return str(cur["variable"])
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def find_and_remove(tabs: list[dict], gate: str) -> tuple[int, dict] | None:
    for ti, tab in enumerate(tabs):
        rows = tab["spec"]["layout"]["spec"]["rows"]
        for ri, row in enumerate(rows):
            if row_gate(row) == gate:
                return ti, rows.pop(ri)
    return None


def expand_all_rows(dash: dict) -> int:
    n = 0
    for tab in dash["spec"]["layout"]["spec"]["tabs"]:
        for row in tab["spec"]["layout"]["spec"]["rows"]:
            spec = row.setdefault("spec", {})
            if spec.get("collapse") is not False:
                spec["collapse"] = False
                n += 1
            else:
                # still count already-false? only changed
                pass
    # recount actually changed: compare - just set all False and count Trues flipped
    return n


def expand_all_rows_count(dash: dict) -> tuple[int, int]:
    flipped = 0
    total = 0
    for tab in dash["spec"]["layout"]["spec"]["tabs"]:
        for row in tab["spec"]["layout"]["spec"]["rows"]:
            total += 1
            spec = row.setdefault("spec", {})
            if spec.get("collapse") is True:
                flipped += 1
            spec["collapse"] = False
    return flipped, total


def fix_hyphen_promql(obj: Any, fixes: list[str]) -> Any:
    """Rewrite bare hyphenated metric usage to __name__= form."""
    if isinstance(obj, dict):
        return {k: fix_hyphen_promql(v, fixes) for k, v in obj.items()}
    if isinstance(obj, list):
        return [fix_hyphen_promql(v, fixes) for v in obj]
    if isinstance(obj, str) and HYPHEN_METRIC in obj:
        orig = obj
        # Already safe panel form
        if '__name__="kentik_snmp_digital-sen1-1"' in obj:
            return obj
        # label_values(kentik_snmp_digital-sen1-1{...},device_name)
        if obj.startswith("label_values(") and HYPHEN_METRIC in obj:
            obj = f'label_values({SAFE_SELECTOR},device_name)'
            fixes.append(f"gate/query: {orig[:80]} -> {obj}")
            return obj
        # bare metric as metric field
        if obj.strip() == HYPHEN_METRIC:
            fixes.append(f"metric field: bare -> keep name but mark for gate metric rewrite")
            return obj  # metric field in QueryVariable may need different handling
        # selector form: kentik_snmp_digital-sen1-1{...}
        m = re.match(
            r"^kentik_snmp_digital-sen1-1(\{.*\})$",
            obj.strip(),
        )
        if m:
            labels = m.group(1)[1:-1]  # inside braces
            obj = '{__name__="kentik_snmp_digital-sen1-1",' + labels + "}"
            fixes.append(f"selector: {orig[:100]} -> {obj[:100]}")
            return obj
        # expr with bare name at start
        if obj.strip().startswith(HYPHEN_METRIC + "{"):
            rest = obj.strip()[len(HYPHEN_METRIC) :]
            obj = '{__name__="kentik_snmp_digital-sen1-1"' + rest.replace("{", ",", 1)
            # rest is {labels} -> ,labels}
            fixes.append(f"expr: {orig[:100]} -> {obj[:100]}")
            return obj
    return obj


def fix_roomalert_variable(dash: dict, fixes: list[str]) -> None:
    for var in dash["spec"].get("variables") or []:
        spec = var.get("spec") or {}
        if spec.get("name") != "has_roomalert":
            continue
        q = spec.get("query")
        if not isinstance(q, dict):
            continue
        inner = q.get("spec") or {}
        if not isinstance(inner, dict):
            continue
        before = json.dumps(inner)
        # Hyphenated metric names are illegal PromQL identifiers. Use __name__ matcher.
        inner["metric"] = ""
        inner["query"] = (
            'label_values({__name__="kentik_snmp_digital-sen1-1",device_name=~"$instance"},device_name)'
        )
        # Keep labelFilters for UI editors; query string is authoritative at runtime.
        after = json.dumps(inner)
        if before != after:
            fixes.append("has_roomalert: metric cleared + __name__ label_values query")
            print("has_roomalert before:", before[:350])
            print("has_roomalert after:", after[:350])


def rehome(dash: dict, moves: dict[str, int]) -> list[str]:
    tabs = dash["spec"]["layout"]["spec"]["tabs"]
    names = [t["spec"]["title"] for t in tabs]
    report = []
    for gate, dest in moves.items():
        found = find_and_remove(tabs, gate)
        if not found:
            report.append(f"MISSING {gate}")
            continue
        src, row = found
        if src == dest:
            tabs[src]["spec"]["layout"]["spec"]["rows"].append(row)
            report.append(f"already {gate} on {names[dest]}")
            continue
        # Ensure expanded when rehomed
        (row.get("spec") or {}).update({"collapse": False})
        tabs[dest]["spec"]["layout"]["spec"]["rows"].append(row)
        title = (row.get("spec") or {}).get("title")
        report.append(f"moved {gate}: {names[src]} -> {names[dest]} ({title})")
    return report


def push(patched: dict) -> None:
    env = load_env()
    url, token = env["GRAFANA_URL"], env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, existing = api(url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}")
    if status != 200:
        raise SystemExit(f"GET failed {status}")
    body = copy.deepcopy(patched)
    body["metadata"]["namespace"] = ns
    body["metadata"]["name"] = UID
    body["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
    for k in ("generation", "creationTimestamp", "uid", "managedFields"):
        body["metadata"].pop(k, None)
    body.pop("status", None)
    ann = body["metadata"].setdefault("annotations", {})
    ann["grafana.app/folder"] = existing.get("metadata", {}).get("annotations", {}).get(
        "grafana.app/folder", "network-lab"
    )
    status, data = api(url, token, "PUT", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}", body)
    print(f"PUT -> {status} gen={(data or {}).get('metadata', {}).get('generation')}")
    if status not in (200, 201):
        raise SystemExit(data)
    status2, after = api(url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}")
    kind = after["spec"]["layout"]["kind"]
    print("verify layout", kind)
    if kind != "TabsLayout":
        raise SystemExit("layout degraded")
    still = sum(
        1
        for tab in after["spec"]["layout"]["spec"]["tabs"]
        for row in tab["spec"]["layout"]["spec"]["rows"]
        if (row.get("spec") or {}).get("collapse") is True
    )
    print(f"rows still collapse=True: {still}")
    for var in after["spec"].get("variables") or []:
        if (var.get("spec") or {}).get("name") == "has_roomalert":
            inner = var["spec"]["query"]["spec"]
            print("has_roomalert.metric=", repr(inner.get("metric")))
            print("has_roomalert.query=", inner.get("query"))
            if "digital-sen1-1{" in (inner.get("query") or "") and "__name__" not in (inner.get("query") or ""):
                raise SystemExit("roomalert gate still unsafe")
            if inner.get("metric") == HYPHEN_METRIC:
                raise SystemExit("roomalert metric field still hyphenated")


def main() -> int:
    env = load_env()
    url, token = env["GRAFANA_URL"], env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, live = api(url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}")
    if status != 200:
        raise SystemExit(f"GET {status}")
    print("pulled gen", live["metadata"].get("generation"))

    dash = copy.deepcopy(live)
    # Which rows were collapsed?
    for tab in dash["spec"]["layout"]["spec"]["tabs"]:
        for row in tab["spec"]["layout"]["spec"]["rows"]:
            if (row.get("spec") or {}).get("collapse") is True:
                print("  was collapsed:", tab["spec"]["title"], "/", row["spec"].get("title"))

    flipped, total = expand_all_rows_count(dash)
    print(f"expanded rows: flipped {flipped}/{total} to collapse=False")

    fixes: list[str] = []
    dash["spec"] = fix_hyphen_promql(dash["spec"], fixes)
    fix_roomalert_variable(dash, fixes)
    for f in fixes:
        print("fix:", f)

    moves = {
        "has_exagrid": HARDWARE,
        "has_tcp": CONNECTIONS,
        "has_udp": CONNECTIONS,
    }
    for line in rehome(dash, moves):
        print(line)

    path = path_for_uid(UID)
    path.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
    print("wrote", path)

    push(dash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
