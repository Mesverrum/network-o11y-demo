#!/usr/bin/env python3
"""Write the dashboards the hub app ships in src/dashboards/.

Every query reads what the hub pipeline itself ships, filtered by collector="$collector",
so the boards answer "did the Fleet config for this group work" rather than lab-wide state.
Run: python3 scripts/build-dashboards.py
"""
from __future__ import annotations

import json
import pathlib

OUT = pathlib.Path(__file__).resolve().parents[1] / "src" / "dashboards"
DS = {"type": "prometheus", "uid": "${ds}"}
C = 'collector="$collector"'
G = 'group="$group"'
CTRL = 'controller_id="${pipeline}.default"'
TAGS = ["network-instrumentation-hub"]


def target(expr: str, legend: str = "__auto", instant: bool = False, ref: str = "A", fmt: str = "time_series") -> dict:
    return {
        "datasource": DS,
        "refId": ref,
        "expr": expr,
        "legendFormat": legend,
        "instant": instant,
        "range": not instant,
        "format": fmt,
    }


def stat(title: str, expr: str, x: int, y: int, w: int = 4, h: int = 4, unit: str = "none",
         steps: list | None = None, mappings: list | None = None, desc: str = "", legend: str = "__auto",
         text_mode: str = "auto") -> dict:
    return {
        "type": "stat",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(expr, legend, instant=True)],
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "background",
            "graphMode": "none",
            "textMode": text_mode,
            "justifyMode": "auto",
        },
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "mappings": mappings or [],
                "thresholds": {"mode": "absolute", "steps": steps or [{"color": "green", "value": None}]},
                "noValue": "Waiting",
            },
            "overrides": [],
        },
    }


def ts(title: str, targets: list, x: int, y: int, w: int = 12, h: int = 8, unit: str = "none",
       desc: str = "", stack: bool = False) -> dict:
    return {
        "type": "timeseries",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": targets,
        "options": {"legend": {"displayMode": "table", "placement": "right", "calcs": ["lastNotNull"]},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
        "fieldConfig": {
            "defaults": {
                "unit": unit,
                "custom": {"drawStyle": "line", "lineWidth": 1, "fillOpacity": 10,
                           "stacking": {"mode": "normal" if stack else "none", "group": "A"}},
            },
            "overrides": [],
        },
    }


def table(title: str, expr: str, x: int, y: int, keep: list[str], rename: dict | None = None,
          w: int = 24, h: int = 8, desc: str = "", value_name: str | None = None) -> dict:
    index = {name: i for i, name in enumerate(keep)}
    excluded = {}
    if value_name is None:
        excluded["Value"] = True
    return {
        "type": "table",
        "title": title,
        "description": desc,
        "datasource": DS,
        "gridPos": {"x": x, "y": y, "w": w, "h": h},
        "targets": [target(expr, instant=True, fmt="table")],
        "transformations": [
            {"id": "labelsToFields", "options": {}},
            {"id": "merge", "options": {}},
            {"id": "filterFieldsByName", "options": {"include": {"names": keep + (["Value"] if value_name else [])}}},
            {"id": "organize", "options": {
                "excludeByName": excluded,
                "indexByName": index,
                "renameByName": {**(rename or {}), **({"Value": value_name} if value_name else {})},
            }},
        ],
        "options": {"showHeader": True, "cellHeight": "sm"},
        "fieldConfig": {"defaults": {}, "overrides": []},
    }


def row(title: str, y: int) -> dict:
    return {"type": "row", "title": title, "collapsed": False, "gridPos": {"x": 0, "y": y, "w": 24, "h": 1}, "panels": []}


def text(content: str, x: int, y: int, w: int = 24, h: int = 3) -> dict:
    return {"type": "text", "title": "", "gridPos": {"x": x, "y": y, "w": w, "h": h},
            "options": {"mode": "markdown", "content": content}}


def variables(with_group: bool = True, with_pipeline: bool = True) -> dict:
    lst = [
        {
            "name": "ds",
            "label": "Stack",
            "type": "datasource",
            "query": "prometheus",
            "current": {"text": "marcnetterfield1-prom", "value": "mf1-prom"},
            "hide": 0,
        },
        {
            "name": "collector",
            "label": "Collector",
            "type": "query",
            "datasource": DS,
            "query": {"query": "label_values(discovery_snmp_group_info, collector)", "refId": "collector"},
            "definition": "label_values(discovery_snmp_group_info, collector)",
            "current": {"text": "hub-canary", "value": "hub-canary"},
            "refresh": 2,
            "sort": 1,
        },
    ]
    if with_group:
        lst.append({
            "name": "group",
            "label": "Group",
            "type": "query",
            "datasource": DS,
            "query": {"query": 'label_values(discovery_snmp_group_info{collector="$collector"}, group)', "refId": "group"},
            "definition": 'label_values(discovery_snmp_group_info{collector="$collector"}, group)',
            "current": {"text": "hub-demo", "value": "hub-demo"},
            "refresh": 2,
            "sort": 1,
        })
    if with_pipeline:
        lst.append({
            "name": "pipeline",
            "label": "Fleet pipeline",
            "type": "textbox",
            "query": "hub_hub_demo",
            "current": {"text": "hub_hub_demo", "value": "hub_hub_demo"},
        })
    return {"list": lst}


def links() -> list:
    return [
        {"title": "Hub dashboards", "type": "dashboards", "tags": TAGS, "asDropdown": False,
         "includeVars": True, "keepTime": True},
        {"title": "Receiving", "type": "link", "url": "/a/mesverrum-networkinstrumentationhub-app/receiving",
         "icon": "arrow-right"},
    ]


def dashboard(uid: str, title: str, description: str, panels: list, **var_kw) -> dict:
    for i, p in enumerate(panels, start=1):
        p["id"] = i
    return {
        "uid": uid,
        "title": title,
        "description": description,
        "tags": TAGS,
        "editable": True,
        "schemaVersion": 39,
        "version": 1,
        "refresh": "30s",
        "time": {"from": "now-3h", "to": "now"},
        "timepicker": {},
        "templating": variables(**var_kw),
        "links": links(),
        "annotations": {"list": []},
        "panels": panels,
    }


RED_GREEN = [{"color": "red", "value": None}, {"color": "green", "value": 1}]
ZERO_GOOD = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
YES_NO = [{"type": "value", "options": {"1": {"text": "Yes", "color": "green"}, "0": {"text": "No", "color": "red"}}}]


def rollout() -> dict:
    p = [
        text("**Did Fleet deliver the hub pipeline, and is it running?** Remote config and component health "
             "come from the pipeline's own self-metrics (`collector=\"$collector\"`). "
             "Empty panels mean the collector has not loaded a pipeline that ships them yet.", 0, 0),
        stat("Config loaded", f"max(remotecfg_last_load_successful{{{C}}})", 0, 3, steps=RED_GREEN, mappings=YES_NO,
             desc="remotecfg_last_load_successful from the collector. 1 means the last Fleet poll applied cleanly."),
        stat("Fleet polls (5m)", f"sum(increase(remotecfg_load_attempts_total{{{C}}}[5m])) or vector(0)", 4, 3,
             steps=RED_GREEN, desc="The collector asks Fleet for config every 30s, so expect about 10. "
                                   "Zero means it lost contact with Fleet."),
        stat("Failed loads (1h)", f"sum(increase(remotecfg_load_failures_total{{{C}}}[1h])) or vector(0)", 8, 3,
             steps=ZERO_GOOD),
        stat("Pipeline healthy components",
             f'sum(alloy_component_controller_running_components{{{C},{CTRL},health_type="healthy"}})', 12, 3,
             steps=RED_GREEN, desc="Healthy components inside the Fleet module for $pipeline."),
        stat("Pipeline unhealthy components",
             f'sum(alloy_component_controller_running_components{{{C},{CTRL},health_type!="healthy"}}) or vector(0)',
             16, 3, steps=ZERO_GOOD),
        stat("Running revision", f"count by (hub_revision) (discovery_snmp_group_info{{{C},group=~\"$group\"}})", 20, 3,
             legend="{{hub_revision}}", text_mode="name", steps=[{"color": "blue", "value": None}],
             desc="Content hash the hub stamped into the pipeline. The Receiving page compares it with what Apply sent; "
                  "a collector that rejects a new pipeline keeps echoing the old hash."),
        row("Over time", 7),
        ts("Remote config load", [
            target(f"max(remotecfg_last_load_successful{{{C}}})", "last load ok"),
            target(f"sum(increase(remotecfg_load_failures_total{{{C}}}[5m]))", "failures / 5m", ref="B"),
            target(f"time() - max(remotecfg_last_load_success_timestamp_seconds{{{C}}})", "since config changed (s)",
                   ref="C"),
        ], 0, 8, desc="The last-load timestamp moves only when Fleet hands over a changed config, not on every poll."),
        ts("Components by Fleet module and health", [
            target(f"sum by (controller_id, health_type) (alloy_component_controller_running_components{{{C}}})",
                   "{{controller_id}} {{health_type}}"),
        ], 12, 8, desc="Every module Fleet delivered to this collector, not just the hub one."),
        ts("Hub revision over time", [
            target(f"count by (hub_revision) (discovery_snmp_group_info{{{C},group=~\"$group\"}})", "{{hub_revision}}"),
        ], 0, 16, w=8, h=6, desc="A new line means the collector started running a new hub pipeline."),
        stat("Alloy version", f"max by (version) (alloy_build_info{{{C}}})", 8, 16, legend="{{version}}",
             text_mode="name", w=4, h=6, steps=[{"color": "blue", "value": None}],
             desc="Build the collector is running. Older builds may lack components the pipeline uses."),
        table("Modules on this collector",
              f"sum by (controller_id, health_type) (alloy_component_controller_running_components{{{C}}})",
              12, 16, ["controller_id", "health_type"], {"controller_id": "Fleet module", "health_type": "Health"},
              w=12, h=6, value_name="Components"),
    ]
    return dashboard("hub-fleet-rollout", "Hub 1 · Fleet rollout",
                     "Did Fleet deliver the Instrumentation Hub pipeline to the collector, and is it healthy?", p,
                     with_pipeline=True)


def discovery() -> dict:
    p = [
        text("**Did discovery find what the group asked for?** `discovery_snmp_group_info` echoes the group and "
             "note back from the collector; `discovery_snmp_device_info` is one row per device that answered.", 0, 0),
        stat("Group reported", f"count(count by (group) (discovery_snmp_group_info{{{C},{G}}})) or vector(0)", 0, 3,
             steps=RED_GREEN,
             mappings=[{"type": "value", "options": {"0": {"text": "No", "color": "red"}}},
                       {"type": "range", "options": {"from": 1, "to": 1e9, "result": {"text": "Yes", "color": "green"}}}]),
        stat("Devices found", f"count(count by (device_name, address) (discovery_snmp_device_info{{{C},{G}}})) or vector(0)",
             4, 3, steps=RED_GREEN, desc="Counted once per device, even while an old pipeline revision is going stale."),
        stat("Scrape targets (all tiers)", f"sum(discovery_snmp_targets_by_tier{{{C}}}) or vector(0)", 8, 3,
             steps=RED_GREEN, desc="Targets discovery handed to the hot, cold, and topology scrapes."),
        stat("Scans (24h)", f"sum(increase(discovery_snmp_scans_total{{{C}}}[24h])) or vector(0)", 12, 3),
        stat("Scan failures (24h)", f"sum(increase(discovery_snmp_scan_failures_total{{{C}}}[24h])) or vector(0)", 16, 3,
             steps=ZERO_GOOD),
        stat("Login failures (1h)", f"sum(increase(discovery_snmp_auth_failures_total{{{C}}}[1h])) or vector(0)", 20, 3,
             steps=[{"color": "green", "value": None}, {"color": "orange", "value": 1}],
             desc="Addresses that answered but refused every login in the group. Some are expected on a shared subnet."),
        table("Group as the collector sees it", f"discovery_snmp_group_info{{{C},{G}}}", 0, 7,
              ["group", "description", "collector", "component_path", "hub_revision"],
              {"group": "Group", "description": "Note", "collector": "Collector", "component_path": "Fleet module",
               "hub_revision": "Revision"},
              h=4),
        table("Devices found",
              f"max by (device_name, address, auth, sysObjectID) (discovery_snmp_device_info{{{C},{G}}})", 0, 11,
              ["device_name", "address", "auth", "sysObjectID"],
              {"device_name": "Device", "address": "Address", "auth": "Login", "sysObjectID": "sysObjectID"}, h=9),
        ts("Targets by tier", [target(f"sum by (tier) (discovery_snmp_targets_by_tier{{{C}}})", "{{tier}}")], 0, 20),
        ts("Probe outcomes", [
            target(f"sum(rate(discovery_snmp_probes_total{{{C}}}[5m]))", "probes/s"),
            target(f"sum(rate(discovery_snmp_auth_failures_total{{{C}}}[5m]))", "login failures/s", ref="B"),
            target(f"sum(rate(discovery_snmp_scan_failures_total{{{C}}}[5m]))", "scan failures/s", ref="C"),
        ], 12, 20, unit="ops"),
    ]
    return dashboard("hub-discovery", "Hub 2 · Discovery",
                     "What the hub discovery group found on its collector.", p, with_pipeline=False)


def arriving() -> dict:
    snmp = f'job="alloy-snmp",{C}'
    p = [
        text("**Is device data arriving from this collector?** Hot tier every 60s (CPU, octets, oper status), "
             "cold tier every 5m (names, errors, discards), neighbor topology every 15m. "
             "The lab's main Alloy polls the same devices with a different `collector` label, so these panels only "
             "count the hub's own scrapes.", 0, 0),
        stat("Hot devices answering", f'sum(up{{{snmp},snmp_tier="hot"}}) or vector(0)', 0, 3, steps=RED_GREEN),
        stat("Hot devices polled", f'count(up{{{snmp},snmp_tier="hot"}}) or vector(0)', 4, 3, steps=RED_GREEN),
        stat("Cold devices answering", f'sum(up{{{snmp},snmp_tier="cold"}}) or vector(0)', 8, 3, steps=RED_GREEN,
             desc="Compare with Hot devices polled. The cold walk is larger and runs every 5 minutes."),
        stat("Last cold sample", f"time() - max(timestamp(snmp_ifInErrors{{{snmp}}}))", 12, 3, unit="s",
             steps=[{"color": "green", "value": None}, {"color": "orange", "value": 600}, {"color": "red", "value": 900}]),
        stat("Interface series", f"count(snmp_ifHCInOctets{{{snmp}}}) or vector(0)", 16, 3, steps=RED_GREEN),
        stat("Neighbor links", f"count(network_topology_edge_info{{{C}}}) or vector(0)", 20, 3,
             steps=[{"color": "blue", "value": None}, {"color": "green", "value": 1}],
             desc="Blue until the first 15-minute neighbor walk lands, or if neighbor topology is off."),
        table("Poll status by device and tier", f"up{{{snmp}}}", 0, 7,
              ["device_name", "snmp_tier", "sysObjectID"],
              {"device_name": "Device", "snmp_tier": "Tier"}, w=12, h=8, value_name="Up"),
        ts("Poll success by tier", [
            target(f"sum by (snmp_tier) (up{{{snmp}}})", "{{snmp_tier}} up"),
            target(f"count by (snmp_tier) (up{{{snmp}}})", "{{snmp_tier}} polled", ref="B"),
        ], 12, 7, h=8),
        ts("CPU %", [target(f"snmp_CPU{{{snmp}}}", "{{device_name}}")], 0, 15, unit="percent"),
        ts("Inbound traffic by device", [
            target(f"sum by (device_name) (rate(snmp_ifHCInOctets{{{snmp}}}[5m])) * 8", "{{device_name}}"),
        ], 12, 15, unit="bps"),
        ts("Interface errors/s (cold tier)", [
            target(f"sum by (device_name) (rate(snmp_ifInErrors{{{snmp}}}[15m]))", "{{device_name}}"),
        ], 0, 23, unit="ops"),
        ts("Scrape duration", [
            target(f"max by (snmp_tier) (scrape_duration_seconds{{{snmp}}})", "{{snmp_tier}}"),
        ], 12, 23, unit="s"),
        table("Neighbor links", f"network_topology_edge_info{{{C}}}", 0, 31,
              ["src_device", "src_port", "dst_device", "dst_port", "discovery_proto", "evidence"],
              {"src_device": "From", "src_port": "Port", "dst_device": "To", "dst_port": "Peer port",
               "discovery_proto": "Via", "evidence": "Evidence"}, h=8),
    ]
    return dashboard("hub-data-arriving", "Hub 3 · Data arriving",
                     "Hot, cold, and topology data the hub pipeline polls on its collector.", p,
                     with_group=False, with_pipeline=False)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, board in (("fleet-rollout", rollout()), ("discovery", discovery()), ("data-arriving", arriving())):
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(board, indent=2) + "\n", encoding="utf-8", newline="\n")
        print("wrote", path.relative_to(OUT.parents[1]))


if __name__ == "__main__":
    main()
