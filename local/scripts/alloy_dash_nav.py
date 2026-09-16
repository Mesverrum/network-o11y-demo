"""Shared A0–A4 dashboard links and user-facing copy helpers.

Nav is one tag dropdown (``network-o11y``), not hard-coded /d/alloy-* links.
"""

from __future__ import annotations

import json
import re
from typing import Any

ALLOY_NAV_TAG = "network-o11y"


def ensure_alloy_nav_tag(spec: dict[str, Any]) -> None:
    tags = [t for t in (spec.get("tags") or []) if t != "ktranslate"]
    if ALLOY_NAV_TAG not in tags:
        tags.append(ALLOY_NAV_TAG)
    spec["tags"] = tags


def apply_alloy_nav_links(spec: dict[str, Any], current_uid: str = "") -> None:
    """Replace spec.links with a dashboards dropdown for tag network-o11y."""
    ensure_alloy_nav_tag(spec)
    spec["links"] = [
        {
            "title": "Network O11y",
            "url": "",
            "type": "dashboards",
            "icon": "dashboard",
            "tooltip": "",
            "tags": [ALLOY_NAV_TAG],
            "asDropdown": True,
            "targetBlank": False,
            "includeVars": True,
            "keepTime": True,
        }
    ]


# Longer phrases first. These are user-facing description/markdown only.
_PROSE_REPLACEMENTS: list[tuple[str, str]] = [
    (
        "Clone of 04. Network Device Details. Panels are being retargeted one at a "
        "time from ktranslate (kentik_snmp_*, CHF, ktranslate Loki) to Alloy "
        "collectors (snmp_* job=alloy-snmp, alloy-netflow, alloy-snmptrap, alloy-syslog).",
        "Device-level Alloy SNMP, flow, traps, and syslog "
        "(`snmp_*` job=alloy-snmp, alloy-netflow, alloy-snmptrap, alloy-syslog).",
    ),
    (
        "Clone of 02. Network Flow Summary for Alloy-native flow "
        "(otelcol.receiver.netflow → signaltometrics). "
        "Metric: alloy_network_io_by_flow_bytes{integration=\"alloy-netflow\"}. "
        "Counters: rate() / increase(), not ktranslate max_over_time or * 8 / 60. "
        "No MaxMind geo or ktranslate L7 app-id on this path yet. "
        "src_host/dst_host come from Alloy reverse-DNS (udp_host_cache_size) "
        "with catalog names as fallback.",
        "Alloy-native flow (otelcol.receiver.netflow → signaltometrics). "
        "Metric: alloy_network_io_by_flow_bytes{integration=\"alloy-netflow\"}. "
        "Counters: rate() / increase(). No MaxMind geo or L7 app-id on this path yet. "
        "src_host/dst_host come from Alloy reverse-DNS (udp_host_cache_size) "
        "with catalog names as fallback.",
    ),
    (
        "this stack uses ktranslate/gnmic + Alloy, not the legacy kentik_snmp_PollingHealth metric",
        "this stack uses Alloy SNMP scrape",
    ),
    (
        "ktranslate-only filter; hidden on the Alloy board (no provider label).",
        "Hidden — this board has no provider label.",
    ),
    (
        "Peer port and L7 application (ktranslate protocol name).",
        "Peer port and L7 application name (when present).",
    ),
    ("which interfaces ktranslate collects", "which interfaces Alloy scrapes"),
    ("visible to ktranslate", "visible to Alloy SNMP scrape"),
    (" (not a ktranslate delta gauge)", ""),
    (" (not ktranslate delta gauges)", ""),
    ("; not ktranslate delta gauges", ""),
    (" (ktranslate-only metric)", ""),
    ("Use rate() — not ktranslate * 8 / 60.", "Use rate()."),
    (" — not ktranslate * 8 / 60.", "."),
    ("not ktranslate max_over_time or * 8 / 60. ", ""),
    ("No MaxMind geo or ktranslate L7 app-id", "No MaxMind geo or L7 app-id"),
    ("Not ktranslate CHF/jchf. ", ""),
    (". Not ktranslate CHF.", "."),
    (" Not ktranslate CHF.", ""),
    ("Not ktranslate CHF.", ""),
    ("Not CHF kkc_snmp_traps.", ""),
    ("they are not ktranslate jchf.", "they are Alloy scrape and component metrics."),
    (", not `kentik_snmp_*`.", "."),
    (" not `kentik_snmp_*`.", "."),
]


_SKIP_KEYS = {
    "expr",
    "query",
    "metric",
    "datasource",
    "uid",
    "refId",
    "type",
    "kind",
    "id",
    "pluginVersion",
}


def scrub_ktranslate_prose(text: str) -> str:
    """Rewrite leftover ktranslate comparison copy. Does not touch PromQL."""
    out = text
    for old, new in _PROSE_REPLACEMENTS:
        if old in out:
            out = out.replace(old, new)
    out = re.sub(r"  +", " ", out)
    out = re.sub(r" \n", "\n", out)
    return out


def rewrite_alloy_flow_exporters(spec: dict[str, Any]) -> int:
    """Drop the ktranslate if_Address SQL join on Flow Exporters.

    Alloy already stamps ``device_name`` from the SNMP/catalog join at collect
    time (``flow.sampler_address``). IP-MIB ``if_Address`` is empty on this path,
    so the old LEFT JOIN never matched. The table is the flow rollup only.
    """
    n = 0
    for el in (spec.get("elements") or {}).values():
        es = el.get("spec") or {}
        if (es.get("title") or "") != "Flow Exporters":
            continue
        data = ((es.get("data") or {}).get("spec") or {})
        queries = data.get("queries") or []
        keep: list[Any] = []
        for q in queries:
            qs = q.get("spec") or {}
            qspec = (qs.get("query") or {}).get("spec") or {}
            blob = json.dumps(qspec)
            if "kentik_snmp" in blob or qspec.get("type") == "sql":
                n += 1
                continue
            if qs.get("refId") == "A":
                qs["hidden"] = False
                qspec["instant"] = True
                qspec["range"] = False
                qspec["queryType"] = "instant"
                qspec.pop("format", None)
            keep.append(q)
        data["queries"] = keep
        data["transformations"] = [
            {"kind": "Transformation", "group": "labelsToFields", "spec": {"options": {}}},
            {"kind": "Transformation", "group": "merge", "spec": {"options": {}}},
            {
                "kind": "Transformation",
                "group": "organize",
                "spec": {
                    "options": {
                        "excludeByName": {"Time": True},
                        "indexByName": {"device_name": 0, "Value": 1},
                        "renameByName": {
                            "device_name": "Exporter",
                            "Value": "Total Bytes",
                        },
                    }
                },
            },
        ]
        viz = ((es.get("vizConfig") or {}).get("spec") or {})
        fc = viz.get("fieldConfig") or {}
        overrides = (fc.get("overrides") or [])
        fc["overrides"] = [
            o
            for o in overrides
            if ((o.get("matcher") or {}).get("options")) != "SNMP Device"
        ]
        es["description"] = (
            "NetFlow/sFlow samplers after the Alloy catalog join "
            "(`device_name` from `flow.sampler_address`). "
            "Softflowd clients show up here; they are not SNMP-polled switches."
        )
        n += 1
    return n


def scrub_spec_prose(obj: Any) -> int:
    """Walk a dashboard spec and scrub user-facing strings. Skip query fields."""
    n = 0
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in _SKIP_KEYS:
                continue
            if isinstance(v, str) and k in {
                "description",
                "content",
                "title",
                "tooltip",
                "label",
            }:
                nv = scrub_ktranslate_prose(v)
                if nv != v:
                    obj[k] = nv
                    n += 1
            else:
                n += scrub_spec_prose(v)
    elif isinstance(obj, list):
        for v in obj:
            n += scrub_spec_prose(v)
    return n
