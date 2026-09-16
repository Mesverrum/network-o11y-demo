#!/usr/bin/env python3
"""Clone the networko11ydev ktranslate folder UX onto Alloy data in fb9d2s.

Source of UX:
  02/03/04 — already-retargeted Alloy boards on marcnetterfield1 (A2/A3/A4)
  00 — live ktranslate architecture on networko11ydev, queries rewritten

Target: folder uid=fb9d2s (alloy network fork) on stacks-1544961.

Always GET live first. Create/update via dashboard.grafana.app/v2 — never
POST /api/dashboards/db (that flattens TabsLayout).
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from alloy_dash_nav import (
    apply_alloy_nav_links,
    rewrite_alloy_flow_exporters,
    scrub_spec_prose,
)

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-network-fork-dev"
SRC_NS = "stacks-1061129"
DST_NS = "stacks-1544961"
FOLDER = "fb9d2s"

# marc → dest UID/title
MARC_COPIES = [
    {
        "src_uid": "alloy-flow-summary",
        "dst_uid": "alloy-flow-summary",
        "title": "A2. Alloy Flow Summary",
        "layout": "RowsLayout",
    },
    {
        "src_uid": "ma8p7dn",
        "dst_uid": "alloy-device-summary",
        "title": "A3. Alloy Device Summary",
        "layout": "TabsLayout",
    },
    {
        "src_uid": "alloy-device-details",
        "dst_uid": "alloy-device-details",
        "title": "A4. Alloy Device Details",
        "layout": "TabsLayout",
    },
]

DEV_CLONES = [
    {
        "src_uid": "ktranslate-architecture",
        "dst_uid": "alloy-architecture",
        "title": "A0. Alloy Architecture",
        "layout": "GridLayout",
        "kind": "architecture",
    },
    # A1 is rebuilt from Alloy signals — do not CHF-rewrite ktranslate-health.
    # python3 local/scripts/rebuild-alloy-health.py
]

DS_REPLACEMENTS = {
    "grafanacloud-marcnetterfield1-prom": "grafanacloud-networko11ydev-prom",
    "grafanacloud-marcnetterfield1-logs": "grafanacloud-networko11ydev-logs",
    "grafanacloud-marcnetterfield1-traces": "grafanacloud-networko11ydev-traces",
}

CTX = ssl.create_default_context()

# ktranslate CHF / SNMP → Alloy collector health
HEALTH_METRIC_MAP = [
    ("kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_time", "snmp_scrape_walk_duration_seconds"),
    ("kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total", "snmp_scrape_duration_seconds"),
    ("kentik_ktranslate_chf_kkc_snmp_missing_metadata", "snmp_scrape_pdus_returned"),
    ("kentik_ktranslate_chf_kkc_snmp_missing", "snmp_scrape_packets_retried"),
    ("kentik_ktranslate_chf_kkc_snmp_errors", "snmp_scrape_packets_retried"),
    ("kentik_ktranslate_chf_kkc_snmp_fail", "up"),
    ("kentik_ktranslate_chf_kkc_snmp_devices", "up"),
    ("kentik_ktranslate_chf_kkc_device_metrics", "snmp_CPU"),
    ("kentik_ktranslate_chf_kkc_iface_metrics", "snmp_ifOperStatus"),
    ("kentik_ktranslate_chf_kkc_snmp_traps", "snmp_scrape_pdus_returned"),
    ("kentik_ktranslate_chf_kkc_syslog_messages", "alloy_component_controller_running_components"),
    ("kentik_ktranslate_chf_kkc_syslog_errors", "alloy_component_evaluation_seconds_count"),
    ("kentik_ktranslate_chf_kkc_syslog_queue", "alloy_component_evaluation_seconds_count"),
    ("kentik_ktranslate_chf_kkc_netflow_flows", "alloy_network_io_by_flow_bytes"),
    ("kentik_ktranslate_chf_kkc_inputq_len", "alloy_component_dependencies_wait_seconds_count"),
    ("kentik_ktranslate_chf_kkc_outputq_len", "alloy_component_evaluation_seconds_count"),
    ("kentik_ktranslate_chf_kkc_jchfq", "alloy_component_controller_running_components"),
    ("kentik_ktranslate_chf_kkc_metrics_sent", "alloy_resources_process_cpu_seconds_total"),
    ("kentik_ktranslate_chf_kkc_logs_sent", "alloy_resources_process_cpu_seconds_total"),
    ("kentik_snmp_PollingHealth", "up"),
    ("kentik_snmp_PollingStatus", "up"),
    ("kentik_snmp_DeviceMetrics", "snmp_CPU"),
]

ARCH_MARKDOWN = {
    "Purpose": """## Alloy network → Grafana Cloud

These dashboards read the **Alloy network addons** (SNMP + traps + syslog + flow).

**What you get when it works:**
- SNMP as curated `snmp_*` (`job="alloy-snmp"`, label `snmp_group`)
- Interface counters are Prometheus **counters** — `rate(snmp_ifHCInOctets[$__rate_interval]) * 8` or recording rule `if:snmp_ifHCInOctets:rate5m * 8`
- Flow as `alloy_network_io_by_flow_bytes{integration="alloy-netflow"}` — use **`rate()` / `increase()`**
- Traps as Loki `{service_name="alloy-snmptrap"}` (JSON; group by `trap_oid`)
- Syslog as Loki `{service_name="alloy-syslog"}` (plain text; `severity` is a label)

**Docs:** [alloy-network-fork.md](https://github.com/Mesverrum/network-o11y-demo/blob/main/docs/alloy-network-fork.md) · fork [Mesverrum/alloy `network-snmp`](https://github.com/Mesverrum/alloy/tree/network-snmp) · discovery [Mesverrum/snmp-sd](https://github.com/Mesverrum/snmp-sd)
""",
    "Architecture": """## End-to-end data path

```
Network devices                         Alloy (hostNetwork)
─────────────────────────────           ────────────────────────────────
SNMP :161          ───────────────►  prometheus.exporter.snmp
                                       discovery.snmp (snmp-sd fingerprinters)
                                       hot 60s / cold 5m / optional topology
Traps :1620                            otelcol.receiver.snmptrap
Syslog :1514                           otelcol.receiver.syslog (protocol=none)
NetFlow :2055  sFlow :6344             otelcol.receiver.netflow
                                       → signaltometrics → alloy.network.io.by_flow
                                    Alloy OTLP HTTP ──► Grafana Cloud (Mimir + Loki)
```

This lab's Alloy also listens on `:11620` / `:1515` when another collector already owns `:1620` / `:1514`.

**Identity:** `device_name` from the SNMP catalog / `device-join.yml`. Group label is **`snmp_group`** (hq / branch1 / branch2).
""",
    "Compose": """## Collectors (Alloy path)

| Signal | Alloy component | Listen | PromQL / LogQL |
|---|---|---|---|
| SNMP | `prometheus.exporter.snmp` + `discovery.snmp` | scrape :161 | `snmp_CPU{job="alloy-snmp"}` |
| Traps | `otelcol.receiver.snmptrap` | `:1620` | `{service_name="alloy-snmptrap"}` |
| Syslog | `otelcol.receiver.syslog` | `:1514` | `{service_name="alloy-syslog"}` |
| NetFlow | `otelcol.receiver.netflow` | `:2055` | `rate(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}[5m])` |
| sFlow | same receiver | `:6344` | same metric |
| OTLP fan-out | `otelcol.exporter.otlphttp` | — | Grafana Cloud |

Composites (memory %, iface bps, error %) are Grafana-managed recording rules (`device:snmp_MemoryUtilization:percent`, `if:snmp_ifHCInOctets:rate5m`).
""",
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
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


def get_dash(base: str, token: str, ns: str, uid: str) -> dict | None:
    code, data = api(base, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{uid}")
    if code == 404:
        return None
    if code != 200 or not isinstance(data, dict):
        raise RuntimeError(f"GET {uid} on {base} -> {code}: {data}")
    return data


def remap_ds(obj: Any) -> Any:
    text = json.dumps(obj)
    for old, new in DS_REPLACEMENTS.items():
        text = text.replace(old, new)
    return json.loads(text)


COUNTRY_LABELS = ("network_peer_country", "network_local_country")
COUNTRY_ROW_TITLES = {"geo maps", "country breakdown"}


def _grid_element_keys(layout: Any) -> list[str]:
    if not isinstance(layout, dict) or layout.get("kind") != "GridLayout":
        return []
    keys: list[str] = []
    for item in (layout.get("spec") or {}).get("items") or []:
        ref = (item.get("spec") or {}).get("element")
        if isinstance(ref, str):
            keys.append(ref)
    return keys


def _blob_has_country(obj: Any) -> bool:
    return any(label in json.dumps(obj) for label in COUNTRY_LABELS)


def strip_flow_country_geo(spec: dict) -> list[str]:
    """Alloy-native flow has no MaxMind country labels — drop those rows/panels."""
    layout = spec.get("layout") or {}
    if layout.get("kind") != "RowsLayout":
        return []
    elements = spec.get("elements") or {}
    keep: list[Any] = []
    dropped: list[str] = []
    for row in (layout.get("spec") or {}).get("rows") or []:
        rspec = row.get("spec") or {}
        title = (rspec.get("title") or "").strip().lower()
        keys = _grid_element_keys(rspec.get("layout") or {})
        drop_row = title in COUNTRY_ROW_TITLES or (
            bool(keys) and all(_blob_has_country(elements.get(k) or {}) for k in keys)
        )
        if drop_row:
            dropped.extend(keys)
            continue
        keep.append(row)
    (layout.setdefault("spec", {}))["rows"] = keep
    for key, el in list(elements.items()):
        title = ((el.get("spec") or {}).get("title") or "").lower()
        if key in dropped or _blob_has_country(el) or "country" in title:
            elements.pop(key, None)
            if key not in dropped:
                dropped.append(key)
    spec["elements"] = elements
    return dropped


WAN_JOIN_OLD = (
    '* on(device_name, ifIndex) group_left(if_Alias) '
    '(snmp_ifAdminStatus{snmp_group=~"$snmp_group",device_name=~"$device_name",'
    'if_Alias=~".*WAN.*"} * 0 + 1)'
)
WAN_JOIN_NEW = (
    '* on(device_name, ifIndex) group_left(if_Alias) '
    '(max by (device_name, ifIndex, if_Alias) ('
    'snmp_ifAdminStatus{snmp_group=~"$snmp_group",device_name=~"$device_name",'
    'if_Alias=~".*WAN.*"}))'
)


def rewrite_flow_expr(expr: str) -> str:
    if "network_io_by_flow_bytes" not in expr and "alloy_network_io_by_flow_bytes" not in expr:
        return expr
    # Do not prefix alloy_ onto a name that already has it
    # (marc A2 is already alloy_network_io_by_flow_bytes).
    out = expr.replace("alloy_alloy_network_io_by_flow_bytes", "alloy_network_io_by_flow_bytes")
    out = re.sub(r"(?<!alloy_)network_io_by_flow_bytes", "alloy_network_io_by_flow_bytes", out)
    out = re.sub(
        r"alloy_network_io_by_flow_bytes\{(?![^}]*integration=)",
        'alloy_network_io_by_flow_bytes{integration="alloy-netflow",',
        out,
    )
    out = out.replace(
        'alloy_network_io_by_flow_bytes{integration="alloy-netflow"}{integration="alloy-netflow"}',
        'alloy_network_io_by_flow_bytes{integration="alloy-netflow"}',
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
    out = re.sub(
        r"\balloy_network_io_by_flow_bytes\b\s*\*\s*8\s*/\s*60",
        "rate(alloy_network_io_by_flow_bytes[$__rate_interval]) * 8",
        out,
    )
    out = out.replace(WAN_JOIN_OLD, WAN_JOIN_NEW)
    return out


def rewrite_health_expr(expr: str) -> str:
    out = expr
    for old, new in HEALTH_METRIC_MAP:
        out = out.replace(old, new)
    out = out.replace("kentik_snmp_", "snmp_")
    out = out.replace("tags_snmp_group", "snmp_group")
    out = re.sub(r'service_name=~"ktranslate\.\*"', 'service_name=~"alloy.*"', out)
    out = re.sub(r'service_name=~"ktranslate\.\*\|integrations/ktranslate-netflow"', 'service_name=~"alloy.*"', out)
    out = out.replace('service_name=~"ktranslate-snmp.*"', 'job="alloy-snmp"')
    out = out.replace('service_name=~"ktranslate-flow.*|ktranslate-sflow.*"', 'integration="alloy-netflow"')
    out = out.replace('service_name=~"ktranslate-syslog.*"', 'service_name="alloy-syslog"')
    out = out.replace("ktranslate-syslog", "alloy-syslog")
    out = out.replace("KSnmpTrap", "trap_oid")
    out = out.replace('eventType="trap_oid"', "")
    # PollingHealth became up — keep job if the selector is bare
    if re.search(r"\bup\{", out) and "job=" not in out:
        out = out.replace("up{", 'up{job="alloy-snmp",', 1)
        if "up}" in out or out.strip() == "up":
            out = out.replace("up", 'up{job="alloy-snmp"}', 1)
    out = rewrite_flow_expr(out)
    return out


INDEX_TOPK = re.compile(
    r"topk by \(device_name, Index\) \(1, (snmp_tBgpPeerNg\w+\{[^}]*\})\)"
)


MEM_HANDROLL = re.compile(
    r"100 \* snmp_MemoryUsed\{([^}]*)\} / on\(device_name, snmp_group\) "
    r"\(snmp_MemoryUsed\{[^}]*\} \+ snmp_MemoryFree\{[^}]*\}\)"
)


def rewrite_a3_followups_expr(expr: str) -> str:
    """Hot-tier liveness + memory recording rule. Do not add iface name filters."""
    out = expr
    out = re.sub(
        r"last_over_time\((snmp_CPU\{[^}]*\})\[1h\]\)",
        r"\1",
        out,
    )
    out = re.sub(
        r"last_over_time\((snmp_ifOperStatus\{[^}]*\})\[1h\]\)",
        r"\1",
        out,
    )
    out = MEM_HANDROLL.sub(r"device:snmp_MemoryUtilization:percent{\1}", out)
    return out


A4_ALIAS_JOIN = re.compile(
    r"\* on\(device_name, ifIndex, snmp_group\) group_left\(if_Alias\) "
    r"\(last_over_time\(snmp_ifAdminStatus(\{[^}]*\})\[\$__range\]\) \* 0 \+ 1\)"
)
A4_RATE_SUM = re.compile(
    r"rate\(sum by\(device_name, if_interface_name\) "
    r"\((snmp_if(?:HCInOctets|HCOutOctets|InErrors|OutErrors))(\{[^}]*\})\)"
    r"\[\$__rate_interval:\]\)"
)
A4_RATE_SUM_MAP = {
    "snmp_ifHCInOctets": "if:snmp_ifHCInOctets:rate5m",
    "snmp_ifHCOutOctets": "if:snmp_ifHCOutOctets:rate5m",
    "snmp_ifInErrors": "if:snmp_ifInErrors:rate5m",
    "snmp_ifOutErrors": "if:snmp_ifOutErrors:rate5m",
}


def rewrite_a4_port_expr(expr: str) -> str:
    """Ports already landed on live A4: alias join, octet/error rules, hot up."""
    out = A4_ALIAS_JOIN.sub(
        r"* on(device_name, ifIndex, snmp_group) group_left(if_Alias) "
        r"(max by (device_name, ifIndex, if_Alias, snmp_group) (snmp_ifAdminStatus\1))",
        expr,
    )

    def _rate_sum(m: re.Match) -> str:
        return (
            f"sum by(device_name, if_interface_name) "
            f"({A4_RATE_SUM_MAP[m.group(1)]}{m.group(2)})"
        )

    out = A4_RATE_SUM.sub(_rate_sum, out)
    out = out.replace(
        'network_local_address=~"${flow_device_ips:pipe}"',
        'src_device=~"$instance"',
    )
    out = out.replace(
        'network_peer_address=~"${flow_device_ips:pipe}"',
        'dst_device=~"$instance"',
    )
    if re.search(r"\bup\{job=\"alloy-snmp\"", out) and "snmp_tier=" not in out:
        if "count by(snmp_tier)" not in out and "max by (snmp_tier)" not in out:
            out = out.replace(
                'up{job="alloy-snmp",',
                'up{job="alloy-snmp",snmp_tier="hot",',
            )
    return out


def rewrite_bgp_alloy(expr: str) -> str:
    """Topology-tier TIMOS BGP: ConnState==6, no ktranslate Index flatten."""
    if "tBgp" not in expr and "Index" not in expr:
        return expr
    out = INDEX_TOPK.sub(r"\1", expr)
    out = re.sub(
        r"snmp_tBgpPeerNgOperStatus(\{[^}]*\})\s*==\s*2",
        r"snmp_tBgpPeerNgConnState\1 == 6",
        out,
    )
    out = re.sub(
        r"snmp_tBgpPeerNgOperStatus(\{[^}]*\})\s*!=\s*2",
        r"snmp_tBgpPeerNgConnState\1 != 6",
        out,
    )
    out = out.replace("snmp_tBgpPeerNgOperStatus{", "snmp_tBgpPeerNgConnState{")
    out = out.replace("by (device_name, Index)", "by (device_name, tBgpPeerNgAddress)")
    out = out.replace("by(device_name, Index)", "by (device_name, tBgpPeerNgAddress)")
    return out


def rewrite_snmp_expr(expr: str) -> str:
    """Generic ktranslate SNMP/events → Alloy (join demo + leftover A4 flow)."""
    out = expr
    out = out.replace("kentik_snmp_", "snmp_")
    out = out.replace("tags_snmp_group", "snmp_group")
    out = re.sub(
        r"\(snmp_ifHCInOctets(\{[^}]*\})\)\s*\*\s*8\s*/\s*60",
        r"rate(snmp_ifHCInOctets\1[$__rate_interval]) * 8",
        out,
    )
    out = re.sub(
        r"\(snmp_ifHCOutOctets(\{[^}]*\})\)\s*\*\s*8\s*/\s*60",
        r"rate(snmp_ifHCOutOctets\1[$__rate_interval]) * 8",
        out,
    )
    out = re.sub(
        r"\(snmp_ifInErrors(\{[^}]*\})\)\s*/\s*60",
        r"rate(snmp_ifInErrors\1[$__rate_interval])",
        out,
    )
    out = out.replace("kentik_snmp_MemoryUtilization", "snmp_MemoryUsed")
    out = rewrite_flow_expr(out)
    out = re.sub(r'service_name=~"ktranslate\.\*"', 'service_name=~"alloy.*"', out)
    out = out.replace('eventType="KSnmpTrap"', "")
    out = out.replace("instrumentation_name=\"ktranslate-syslog\"", "")
    return out


def _scrub_a4_flow_endpoints(spec: dict) -> int:
    """From/To device rows via src_device/dst_device (see _fix-a4-flow-endpoints)."""
    try:
        from importlib.util import module_from_spec, spec_from_file_location

        path = Path(__file__).with_name("_fix-a4-flow-endpoints.py")
        ms = spec_from_file_location("fix_a4_flow_endpoints", path)
        if ms is None or ms.loader is None:
            return 0
        mod = module_from_spec(ms)
        ms.loader.exec_module(mod)
        return int(mod.apply(spec))
    except Exception as exc:
        print(f"  flow-endpoint scrub skipped: {exc}")
        return 0


def _scrub_a4_hardware_tables(spec: dict) -> int:
    """Drop Alloy scrape columns on Hardware Sensors tables (see _fix-a4-hw-tables)."""
    try:
        from importlib.util import module_from_spec, spec_from_file_location

        path = Path(__file__).with_name("_fix-a4-hw-tables.py")
        ms = spec_from_file_location("fix_a4_hw_tables", path)
        if ms is None or ms.loader is None:
            return 0
        mod = module_from_spec(ms)
        ms.loader.exec_module(mod)
        return int(mod.scrub_a4_hardware_tables(spec))
    except Exception as exc:
        print(f"  hw-table scrub skipped: {exc}")
        return 0


def walk_rewrite(obj: Any, fn) -> int:
    n = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in ("expr", "query", "definition") and isinstance(v, str):
                nv = fn(v)
                if nv != v:
                    obj[k] = nv
                    n += 1
            elif k == "legendFormat" and isinstance(v, str):
                nv = v.replace("{{network_protocol_name}}", "{{network_transport}}")
                nv = nv.replace("{{tags_snmp_group}}", "{{snmp_group}}")
                if nv != v:
                    obj[k] = nv
                    n += 1
            elif k == "content" and isinstance(v, str):
                nv = fn(v) if ("kentik" in v or "ktranslate" in v.lower() or "network_io_by_flow" in v) else v
                if nv != v:
                    obj[k] = nv
                    n += 1
            else:
                n += walk_rewrite(v, fn)
    elif isinstance(obj, list):
        for v in obj:
            n += walk_rewrite(v, fn)
    return n


def prepare_meta(doc: dict, *, dst_uid: str, title: str, message: str) -> dict:
    out = remap_ds(copy.deepcopy(doc))
    meta = out.setdefault("metadata", {})
    meta["name"] = dst_uid
    meta["namespace"] = DST_NS
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    labels = meta.setdefault("labels", {})
    labels.pop("grafana.app/deprecatedInternalID", None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = message
    spec = out.setdefault("spec", {})
    spec["title"] = title
    tags = [t for t in (spec.get("tags") or []) if t not in ("ktranslate", "in-progress")]
    for t in ("alloy", "network-lab", "network-o11y"):
        if t not in tags:
            tags.append(t)
    spec["tags"] = tags
    out.pop("status", None)
    meta.pop("managedFields", None)
    return out


def ensure_device_allvalue(spec: dict) -> None:
    for v in spec.get("variables") or []:
        s = v.get("spec") or {}
        if s.get("name") in ("device_name", "device", "instance") and s.get("includeAll"):
            if not s.get("allValue"):
                s["allValue"] = ".*"


def rewrite_arch_markdown(spec: dict) -> None:
    for key, el in (spec.get("elements") or {}).items():
        title = ((el.get("spec") or {}).get("title") or "")
        blob = json.dumps(el)
        for needle, md in ARCH_MARKDOWN.items():
            if needle.lower() in title.lower() or (
                needle == "Purpose" and "audience" in title.lower()
            ):
                # v2 text panel content
                def set_content(obj: Any) -> bool:
                    if isinstance(obj, dict):
                        if "content" in obj and isinstance(obj["content"], str):
                            obj["content"] = md
                            return True
                        return any(set_content(v) for v in obj.values())
                    if isinstance(obj, list):
                        return any(set_content(v) for v in obj)
                    return False

                if set_content(el):
                    break
        # proof-query leftovers
        if "kentik_snmp" in blob or "Ktranslate" in blob:
            walk_rewrite(el, lambda s: s.replace("kentik_snmp_CPU", "snmp_CPU").replace("kentik_snmp_", "snmp_"))
    for var in spec.get("variables") or []:
        q = (((var.get("spec") or {}).get("query") or {}).get("spec") or {})
        if q.get("metric") == "kentik_snmp_PollingHealth" or "kentik_snmp" in str(
            q.get("query") or ""
        ):
            q["metric"] = "snmp_CPU"
            q["query"] = "label_values(snmp_CPU,snmp_group)"


def rewrite_links(spec: dict) -> None:
    mapping = {
        "/d/ktranslate-architecture": "/d/alloy-architecture",
        "/d/ktranslate-health": "/d/alloy-health",
        "/d/ktranslate-flow-summary": "/d/alloy-flow-summary",
        "/d/ktranslate-device-summary": "/d/alloy-device-summary",
        "/d/ktranslate-device-details": "/d/alloy-device-details",
        "/d/ma8p7dn": "/d/alloy-device-summary",
    }
    text = json.dumps(spec)
    for old, new in mapping.items():
        text = text.replace(old, new)
    spec.clear()
    spec.update(json.loads(text))


def upsert(base: str, token: str, uid: str, dash: dict, expected_layout: str) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{DST_NS}/dashboards/{uid}"
    create = f"/apis/dashboard.grafana.app/v2/namespaces/{DST_NS}/dashboards"
    existing = get_dash(base, token, DST_NS, uid)
    body = copy.deepcopy(dash)
    if existing:
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            body.setdefault("metadata", {})["resourceVersion"] = rv
        elabels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in elabels:
            body.setdefault("metadata", {}).setdefault("labels", {})[
                "grafana.app/deprecatedInternalID"
            ] = elabels["grafana.app/deprecatedInternalID"]
        code, out = api(base, token, "PUT", path, body)
        action = "updated"
    else:
        code, out = api(base, token, "POST", create, body)
        action = "created"
        if code == 409:
            existing = get_dash(base, token, DST_NS, uid)
            if existing:
                body.setdefault("metadata", {})["resourceVersion"] = (
                    existing.get("metadata") or {}
                ).get("resourceVersion")
                code, out = api(base, token, "PUT", path, body)
                action = "updated-after-409"
    if code not in (200, 201) or not isinstance(out, dict):
        raise RuntimeError(f"{action} {uid} -> {code}: {out}")
    kind = ((out.get("spec") or {}).get("layout") or {}).get("kind")
    gen = (out.get("metadata") or {}).get("generation")
    print(f"  {action} {uid} layout={kind} generation={gen}")
    if kind != expected_layout:
        raise RuntimeError(f"{uid}: expected {expected_layout}, got {kind} — restore from versions")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", metavar="UID")
    args = ap.parse_args()

    env = load_env()
    src_url, src_tok = env["GRAFANA_URL"], env["GRAFANA_TOKEN"]
    dst_url, dst_tok = env["GRAFANA_URL_2"], env["GRAFANA_TOKEN_2"]

    code, folder = api(dst_url, dst_tok, "GET", f"/api/folders/{FOLDER}")
    if code != 200:
        raise SystemExit(f"folder {FOLDER} missing on networko11ydev: {code} {folder}")
    print(f"target folder {FOLDER} = {folder.get('title')!r}")

    OUT.mkdir(parents=True, exist_ok=True)
    wanted = args.only

    for item in MARC_COPIES:
        if wanted and wanted not in (item["src_uid"], item["dst_uid"]):
            continue
        print(f"\ncopy marc {item['src_uid']} → {item['dst_uid']}")
        src = get_dash(src_url, src_tok, SRC_NS, item["src_uid"])
        if not src:
            print("  SKIP: missing on marc")
            continue
        src_kind = ((src.get("spec") or {}).get("layout") or {}).get("kind")
        print(f"  source layout={src_kind} gen={(src.get('metadata') or {}).get('generation')}")
        (OUT / f"{item['src_uid']}-marc.json").write_text(json.dumps(src), encoding="utf-8")
        clone = prepare_meta(
            src,
            dst_uid=item["dst_uid"],
            title=item["title"],
            message=f"Copy of marc {item['src_uid']} into alloy network fork folder",
        )
        spec = clone["spec"]
        ensure_device_allvalue(spec)
        n = walk_rewrite(spec, rewrite_flow_expr)
        if item["dst_uid"] in {"alloy-device-summary", "alloy-device-details"}:
            n += walk_rewrite(spec, rewrite_bgp_alloy)
        if item["dst_uid"] == "alloy-device-summary":
            n += walk_rewrite(spec, rewrite_a3_followups_expr)
        if item["dst_uid"] == "alloy-device-details":
            n += walk_rewrite(spec, rewrite_a4_port_expr)
            n += _scrub_a4_hardware_tables(spec)
            n += _scrub_a4_flow_endpoints(spec)
        if item["dst_uid"] == "alloy-flow-summary":
            dropped = strip_flow_country_geo(spec)
            print(f"  dropped country/geo panels: {dropped}")
            n += rewrite_alloy_flow_exporters(spec)
        rewrite_links(spec)
        apply_alloy_nav_links(spec, item["dst_uid"])
        n += scrub_spec_prose(spec)
        print(f"  flow-rewrite fields={n}")
        (OUT / f"{item['dst_uid']}-pre.json").write_text(json.dumps(clone), encoding="utf-8")
        if args.dry_run:
            print("  dry-run")
            continue
        upsert(dst_url, dst_tok, item["dst_uid"], clone, item["layout"])

    for item in DEV_CLONES:
        if wanted and wanted not in (item["src_uid"], item["dst_uid"]):
            continue
        print(f"\nclone dev {item['src_uid']} → {item['dst_uid']}")
        src = get_dash(dst_url, dst_tok, DST_NS, item["src_uid"])
        if not src:
            print("  SKIP: missing on networko11ydev")
            continue
        src_kind = ((src.get("spec") or {}).get("layout") or {}).get("kind")
        print(f"  source layout={src_kind} gen={(src.get('metadata') or {}).get('generation')}")
        (OUT / f"{item['src_uid']}-dev.json").write_text(json.dumps(src), encoding="utf-8")
        clone = prepare_meta(
            src,
            dst_uid=item["dst_uid"],
            title=item["title"],
            message=f"Clone of {item['src_uid']} retargeted to Alloy collectors",
        )
        spec = clone["spec"]
        ensure_device_allvalue(spec)
        kind = item["kind"]
        if kind == "architecture":
            rewrite_arch_markdown(spec)
            spec["description"] = (
                "Alloy network-fork architecture (SNMP / traps / syslog / netflow)."
            )
        elif kind == "health":
            n = walk_rewrite(spec, rewrite_health_expr)
            print(f"  health-rewrite fields={n}")
            spec["description"] = (
                "Alloy collector health: up{job=alloy-snmp}, snmp_scrape_*, "
                "alloy_component_*, Loki alloy-syslog / alloy-snmptrap, "
                "alloy_network_io_by_flow_bytes."
            )
        rewrite_links(spec)
        apply_alloy_nav_links(spec, item["dst_uid"])
        scrub_spec_prose(spec)
        (OUT / f"{item['dst_uid']}-pre.json").write_text(json.dumps(clone), encoding="utf-8")
        if args.dry_run:
            print("  dry-run")
            continue
        upsert(dst_url, dst_tok, item["dst_uid"], clone, item["layout"])

    print("\nFolder: https://networko11ydev.grafana.net/dashboards/f/fb9d2s/alloy-network-fork")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
