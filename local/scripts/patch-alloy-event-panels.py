#!/usr/bin/env python3
"""Retarget A3/A4 Events Loki panels from ktranslate to Alloy streams.

Always GET live first, then PUT. Never POST /api/dashboards/db.

Alloy contract (cutover LAB_ALLOY_SYSLOG=1 / LAB_ALLOY_SNMPTRAP=1):
  {service_name="alloy-syslog"}   device syslog (plain text; severity/facility labels)
  {service_name="alloy-snmptrap"} SNMP traps (JSON body; trap_oid/device_name labels)

Do not use ktranslate eventType=KSnmpTrap or instrumentation_name=ktranslate-syslog.
Do not | json on syslog — lines are not JSON.

A2 (alloy-flow-summary) has no event panels.

Usage:
  python local/scripts/patch-alloy-event-panels.py --dry-run
  python local/scripts/patch-alloy-event-panels.py
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NS = os.environ.get("GRAFANA_NAMESPACE", "stacks-1061129")
A3_UID = "ma8p7dn"  # A3. Alloy Device Summary
A4_UID = "alloy-device-details"
LOKI_DS = "grafanacloud-logs"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("GRAFANA_")})
    return env


def api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    token = env["GRAFANA_TOKEN"]
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
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
        except json.JSONDecodeError:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def get_live(env: dict[str, str], uid: str) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    code, doc = api(env, "GET", path)
    if code != 200 or not isinstance(doc, dict):
        raise RuntimeError(f"GET {uid} failed HTTP {code}: {doc}")
    return doc


def put_live(env: dict[str, str], uid: str, doc: dict, message: str, out_dir: Path) -> dict:
    body = copy.deepcopy(doc)
    live = get_live(env, uid)
    rv = (live.get("metadata") or {}).get("resourceVersion")
    if rv:
        body.setdefault("metadata", {})["resourceVersion"] = rv
    labels = (live.get("metadata") or {}).get("labels") or {}
    if "grafana.app/deprecatedInternalID" in labels:
        body.setdefault("metadata", {}).setdefault("labels", {})[
            "grafana.app/deprecatedInternalID"
        ] = labels["grafana.app/deprecatedInternalID"]
    body.setdefault("metadata", {}).setdefault("annotations", {})["grafana.app/message"] = message
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    code, out = api(env, "PUT", path, body)
    if code not in (200, 201):
        raise RuntimeError(f"PUT {uid} failed HTTP {code}: {out}")
    kind = ((out or {}).get("spec") or {}).get("layout", {}).get("kind")
    gen = ((out or {}).get("metadata") or {}).get("generation")
    print(f"updated {uid} layout={kind} generation={gen}")
    if kind != "TabsLayout":
        raise RuntimeError(f"{uid}: TabsLayout lost — restore from version history")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{uid}-live.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def query_inner(panel: dict, ref: str = "A") -> dict:
    queries = ((panel.get("spec") or {}).get("data") or {}).get("spec", {}).get("queries") or []
    for q in queries:
        qspec = q.get("spec") or {}
        if qspec.get("refId") != ref:
            continue
        inner = ((qspec.get("query") or {}).get("spec") or {})
        if not isinstance(inner, dict):
            raise KeyError(f"query {ref} has no spec")
        return inner
    raise KeyError(f"query {ref} not found")


def set_loki(
    panel: dict,
    expr: str,
    *,
    ref: str = "A",
    legend: str | None = None,
    description: str | None = None,
    title: str | None = None,
) -> None:
    inner = query_inner(panel, ref)
    qwrap = None
    queries = ((panel.get("spec") or {}).get("data") or {}).get("spec", {}).get("queries") or []
    for q in queries:
        if (q.get("spec") or {}).get("refId") == ref:
            qwrap = q["spec"]["query"]
            break
    if not isinstance(qwrap, dict):
        raise KeyError(f"query wrap {ref}")
    qwrap["group"] = "loki"
    qwrap.setdefault("datasource", {})["name"] = LOKI_DS
    inner["expr"] = expr
    if legend is not None:
        inner["legendFormat"] = legend
    if description is not None:
        panel["spec"]["description"] = description
    if title is not None:
        panel["spec"]["title"] = title


def rename_partition_field(panel: dict, old: str, new: str) -> None:
    transforms = (
        ((panel.get("spec") or {}).get("data") or {}).get("spec", {}).get("transformations") or []
    )
    for t in transforms:
        opts = ((t.get("spec") or {}).get("options") or {})
        fields = opts.get("fields")
        if isinstance(fields, list):
            opts["fields"] = [new if f == old else f for f in fields]
    defaults = (
        ((panel.get("spec") or {}).get("vizConfig") or {})
        .get("spec", {})
        .get("fieldConfig", {})
        .get("defaults")
    )
    if isinstance(defaults, dict):
        dn = defaults.get("displayName")
        if isinstance(dn, str) and old in dn:
            defaults["displayName"] = dn.replace(old, new)


def sel(service: str, device_var: str) -> str:
    return (
        f'{{service_name="{service}",snmp_group=~"$snmp_group",'
        f'device_name=~"{device_var}"}}'
    )


def patch_a4(doc: dict) -> list[str]:
    els = (doc.get("spec") or {}).get("elements") or {}
    syslog = sel("alloy-syslog", "$instance")
    trap = sel("alloy-snmptrap", "$instance")
    notes: list[str] = []

    mapping = {
        "panel-335": (
            f"sum(count_over_time({syslog} [$__range]))",
            "Device syslog count over the dashboard range ({service_name=alloy-syslog}).",
        ),
        "panel-336": (
            syslog,
            "Recent device syslog from Alloy loki.source.syslog. Plain text; filter by device_name label.",
        ),
        "panel-337": (
            f"sum(count_over_time({trap} [$__range]))",
            "SNMP trap count over the dashboard range ({service_name=alloy-snmptrap}).",
        ),
        "panel-339": (
            trap,
            "Recent SNMP traps from Alloy otelcol.receiver.snmptrap. JSON body; device_name and trap_oid are attributes.",
        ),
        "panel-340": (
            f"sum(count_over_time({syslog} [$__interval]))",
            "Device syslog volume over time ({service_name=alloy-syslog}).",
        ),
        "panel-341": (
            f"sum(count_over_time({trap} [$__interval]))",
            "SNMP trap volume over time ({service_name=alloy-snmptrap}). Grouped by trap_oid on Trap Types.",
        ),
    }
    for key, (expr, desc) in mapping.items():
        panel = els.get(key)
        if not panel:
            raise KeyError(key)
        set_loki(panel, expr, description=desc)
        notes.append(key)

    types = els.get("panel-338")
    if not types:
        raise KeyError("panel-338")
    set_loki(
        types,
        f'sum by (trap_oid) (count_over_time({trap} [$__range]))',
        legend="{{trap_oid}}",
        description=(
            "SNMP traps for this device grouped by trap_oid label. "
            "IF-MIB: 1.3.6.1.6.3.1.1.5.3=linkDown, .5.4=linkUp. "
            "MIB names are not resolving on this lab image yet."
        ),
    )
    rename_partition_field(types, "TrapName", "trap_oid")
    notes.append("panel-338")
    return notes


def patch_a3(doc: dict) -> list[str]:
    els = (doc.get("spec") or {}).get("elements") or {}
    syslog = sel("alloy-syslog", "$device_name")
    trap = sel("alloy-snmptrap", "$device_name")
    notes: list[str] = []

    mapping = {
        "panel-201": (
            syslog,
            "Recent device syslog from Alloy loki.source.syslog (plain text, device_name label).",
        ),
        "panel-177": (
            trap,
            "Recent SNMP traps from Alloy otelcol.receiver.snmptrap (JSON body; trap_oid + device_name attributes).",
        ),
        "panel-197": (
            f"sum by (device_name) (count_over_time({syslog} [$__interval]))",
            "Device syslog volume by device ({service_name=alloy-syslog}).",
        ),
        "panel-198": (
            f"sum by (device_name) (count_over_time({trap} [$__interval]))",
            "SNMP trap volume by device ({service_name=alloy-snmptrap}).",
        ),
        "panel-200": (
            f"sum by (severity) (count_over_time({syslog} [$__interval]))",
            "Device syslog volume by RFC5424 severity label ({service_name=alloy-syslog}).",
        ),
        "panel-188": (
            f"sum by (trap_oid) (count_over_time({trap} [$__interval]))",
            "SNMP trap volume over time grouped by trap_oid ({service_name=alloy-snmptrap}).",
        ),
    }
    for key, (expr, desc) in mapping.items():
        panel = els.get(key)
        if not panel:
            raise KeyError(key)
        kwargs: dict[str, Any] = {"description": desc}
        if key == "panel-188":
            kwargs["legend"] = "{{trap_oid}}"
        set_loki(panel, expr, **kwargs)
        notes.append(key)

    types = els.get("panel-178")
    if not types:
        raise KeyError("panel-178")
    set_loki(
        types,
        f"sum by (trap_oid) (count_over_time({trap} [$__range]))",
        legend="{{trap_oid}}",
        description=(
            "SNMP trap counts over the range grouped by trap_oid. "
            "IF-MIB linkDown=.5.3, linkUp=.5.4. MIB names are not resolving yet."
        ),
    )
    rename_partition_field(types, "TrapName", "trap_oid")
    notes.append("panel-178")

    top = els.get("panel-199")
    if not top:
        raise KeyError("panel-199")
    set_loki(
        top,
        f"sum by (device_name) (count_over_time({syslog} [$__range]))",
        ref="A",
        description=(
            "Syslog (A) + SNMP trap (B) counts per device over the range. "
            "Alloy streams alloy-syslog / alloy-snmptrap."
        ),
    )
    set_loki(
        top,
        f"sum by (device_name) (count_over_time({trap} [$__range]))",
        ref="B",
    )
    notes.append("panel-199")

    vol = els.get("panel-191")
    logs = els.get("panel-192")
    if vol:
        set_loki(
            vol,
            (
                "sum by (detected_level) (count_over_time("
                '{service_name="alloy"} [$__interval]))'
            ),
            description="Alloy collector log volume by detected_level ({service_name=alloy}). Not device syslog.",
        )
        notes.append("panel-191")
    if logs:
        set_loki(
            logs,
            '{service_name="alloy"} |~ `$device_name`',
            title="Alloy Collector Logs",
            description=(
                "Alloy process logs mentioning this device filter. Device syslog/traps are the rows above."
            ),
        )
        notes.append("panel-192")

    collectors = els.get("panel-159")
    if collectors:
        set_loki(
            collectors,
            (
                "count(count by (service_name) (count_over_time("
                '{service_name=~"alloy-syslog|alloy-snmptrap"}[15m])))'
            ),
            description=(
                "Distinct Alloy event streams with data in the last 15m "
                "(alloy-syslog, alloy-snmptrap). Not ktranslate CHF."
            ),
        )
        inner = query_inner(collectors, "A")
        inner["instant"] = True
        inner["range"] = False
        inner["queryType"] = "instant"
        notes.append("panel-159")
    return notes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        print("GRAFANA_URL and GRAFANA_TOKEN required", file=sys.stderr)
        return 1

    jobs = [
        (A3_UID, "alloy-device-summary", patch_a3),
        (A4_UID, "alloy-device-details", patch_a4),
    ]
    for uid, folder, fn in jobs:
        doc = get_live(env, uid)
        kind = ((doc.get("spec") or {}).get("layout") or {}).get("kind")
        gen = (doc.get("metadata") or {}).get("generation")
        title = (doc.get("spec") or {}).get("title")
        print(f"live {uid} title={title!r} layout={kind} generation={gen}")
        if kind != "TabsLayout":
            print(f"refusing {uid}: not TabsLayout", file=sys.stderr)
            return 1
        notes = fn(doc)
        print(f"  patched {len(notes)} panels: {', '.join(notes)}")
        out_dir = ROOT / ".dash-payloads" / folder
        if args.dry_run:
            out_dir.mkdir(parents=True, exist_ok=True)
            (out_dir / f"{uid}-events-dry-run.json").write_text(
                json.dumps(doc, indent=2), encoding="utf-8"
            )
            print("  dry-run: not PUT")
            continue
        put_live(
            env,
            uid,
            doc,
            "Events tab: Loki alloy-syslog / alloy-snmptrap (not ktranslate)",
            out_dir,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
