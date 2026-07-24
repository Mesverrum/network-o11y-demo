#!/usr/bin/env python3
"""Anonymize telco-fiber-isp-architecture dashboard for public sharing."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DASH_PATH = ROOT / ".dash-payloads" / "telco-fiber-isp-architecture.json"
UID = "telco-fiber-isp-architecture"
NAMESPACE = "stacks-1061129"
FOLDER = "telco-carrier-fiber"

# Canonical inline infinity payload (shared across stat panels + ops KPI table).
INFINITY_PAYLOAD = {
    "domain": "Access Network Architecture",
    "description": "Business case and investor metrics for unified access-network telemetry platform",
    "updated": "2026-07-24T00:00:00Z",
    "investor_metrics": [
        {
            "id": "observability_run_rate_savings",
            "name": "O11y Run-Rate Savings",
            "value": 4.2,
            "unit": "M USD",
            "grafana_unit": "currencyUSD",
            "decimals": 1,
            "yoy_delta": "Log analytics + NMS sunset",
            "source": "CIO business case",
            "why_care": "Tool consolidation is a board-level opex line item with explicit payback targets.",
            "ops_driver": "Five ingest lanes converging on observability platform",
        },
        {
            "id": "broadband_net_adds_q",
            "name": "Broadband Net Adds (Q)",
            "value": 89.4,
            "unit": "K",
            "grafana_unit": "short",
            "decimals": 1,
            "yoy_delta": "+18%",
            "source": "Earnings release — broadband access",
            "why_care": "Architecture must not block activation velocity or market rollouts.",
            "ops_driver": "PON availability, subs_impacted correlation",
        },
        {
            "id": "wholesale_sla_penalty_avoided",
            "name": "SLA Penalties Avoided",
            "value": 1.8,
            "unit": "M USD",
            "grafana_unit": "currencyUSD",
            "decimals": 1,
            "source": "Finance ops model",
            "why_care": "Wholesale SLA credits hit EBITDA even when not headline in earnings.",
            "ops_driver": "TWAMP lane + SLO automation",
        },
        {
            "id": "truck_roll_opex",
            "name": "Truck Roll Cost / Event",
            "value": 285,
            "unit": "USD",
            "grafana_unit": "currencyUSD",
            "decimals": 0,
            "source": "Field ops finance",
            "why_care": "Remote-fixable CPE faults are pure opex leakage when correlation is slow.",
            "ops_driver": "Field-service dispatch + plant timeline before roll",
        },
        {
            "id": "mean_time_to_correlate",
            "name": "Mean Time to Correlate",
            "value": 8.4,
            "unit": "min",
            "grafana_unit": "m",
            "decimals": 1,
            "yoy_delta": "vs 45 min siloed NOC",
            "source": "NOC pilot",
            "why_care": "Every minute of uncorrelated outage drives churn and SLA penalty exposure.",
            "ops_driver": "Kafka + flow + trap unified timeline",
        },
    ],
    "investor_lens": [
        {
            "public_metric": "Broadband net adds / penetration",
            "reported_value": "89.4K / 42.6%",
            "ops_kpi": "Activation blocked by plant faults",
            "ops_on_board": "telco-fiber-access-operations",
            "narrative": "Architecture must surface subs_impacted before earnings miss",
        },
        {
            "public_metric": "Broadband churn",
            "reported_value": "1.48%",
            "ops_kpi": "Outage correlation latency",
            "ops_on_board": "unified timeline (5 lanes)",
            "narrative": "Ticket spikes precede disconnects — ingest speed and join quality matter",
        },
        {
            "public_metric": "Opex / subscriber",
            "reported_value": "$12.40",
            "ops_kpi": "Truck roll avoidance",
            "ops_on_board": "field-service + plant correlation chain",
            "narrative": "Field dispatch is largest controllable opex after labor",
        },
        {
            "public_metric": "Capex on network software",
            "reported_value": "$18M FY",
            "ops_kpi": "Tool sunset ROI",
            "ops_on_board": "Displace table on this board",
            "narrative": "Board asks payback period on observability consolidation",
        },
        {
            "public_metric": "Wholesale SLA credits",
            "reported_value": "$1.2M LTM",
            "ops_kpi": "SLO error budget",
            "ops_on_board": "SLO automation lane",
            "narrative": "Penalty avoidance not always in earnings script but hits EBITDA",
        },
    ],
    "pipeline_note": "Hypothetical access-network reference architecture. Investor metrics frame the business case for unified observability.",
}

INFINITY_JSON = json.dumps(INFINITY_PAYLOAD, separators=(",", ":"))

TEXT_REPLACEMENTS = [
    # Titles / headings
    ("Fiber ISP Future-State Telemetry Architecture", "Access Network Future-State Telemetry Architecture"),
    ("Fiber ISP operator patterns", "Access network operator patterns"),
    ("Typical fiber ISP operator patterns", "Typical access network operator patterns"),
    ("Typical fiber ISP pattern", "Typical access network pattern"),
    ("Fiber Net Adds (Q)", "Broadband Net Adds (Q)"),
    ("Fiber ISP Architecture", "Access Network Architecture"),
    ("Fiber Access Ops", "Access Network Ops"),
    ("Hypothetical fiber ISP reference architecture", "Hypothetical access-network reference architecture"),
    ("Five-lane fiber ISP telemetry model", "Five-lane access-network telemetry model"),
    ("fiber ISP", "access network"),
    ("fiber operators", "access network operators"),
    ("fiber broadband", "broadband access"),
    ("Fiber net adds / penetration", "Broadband net adds / penetration"),
    ("fiber equivalent", "access-network equivalent"),
    # Grafana does not replace Altiplano IndexSearch -> generic
    (
        "Grafana does not replace Altiplano IndexSearch for historical FM.",
        "Observability layer does not replace EMS historical FM search.",
    ),
    # Toolchain: remove When column header and cells - rebuild table via regex below
]

# Ordered longest-first string replacements for HTML/dot/content fields.
VENDOR_ALIASES = [
    ("Nokia Altiplano", "Nokia Altiplano / Calix CMS"),
    ("Adtran Mosaic CP", "Adtran Mosaic / Calix Aria"),
    ("Altiplano REST/NBI, Mosaic NETCONF, NSP GraphQL", "EMS REST/NBI, NETCONF, GraphQL (Nokia NSP / Cisco Crosswork)"),
    ("Altiplano, Mosaic, NSP event buses", "EMS/NMS event buses (Altiplano, Mosaic, NSP, Crosswork)"),
    ("Altiplano Kafka + location master", "EMS Kafka + location master"),
    ("Splunk", "Splunk / Elastic"),
    ("SolarWinds", "SolarWinds / LibreNMS"),
    ("OpsGenie", "OpsGenie / PagerDuty"),
    ("Dynatrace", "Dynatrace / New Relic"),
    ("Nagios", "Nagios / Icinga"),
    ("ktranslate", "SNMP collector (ktranslate / snmp_exporter)"),
    ("gNMIc", "gNMI collector (gNMIc / OpenConfig)"),
    ("OFSC", "field-service platform (Oracle OFS / Salesforce FSL)"),
    ("Grafana IRM", "on-call platform (Grafana IRM / PagerDuty)"),
    ("Grafana SLO", "SLO automation"),
    ("Grafana Cloud", "observability backend"),
    ("Grafana as the correlation layer", "observability platform as the correlation layer"),
    ("Grafana operational KPIs", "Operational KPIs"),
    ("Grafana target", "Observability target"),
    ("Grafana backend", "Metrics/logs backend"),
    ("Grafana vs Splunk/SolarWinds", "observability vs legacy log/NMS tools"),
    ("Loki via ktranslate syslog", "log store via syslog collector"),
    ("Loki/Mimir", "logs/metrics backend"),
    ("Tempo + OTEL", "tracing backend + OTEL"),
    ("Kafka DS or Alloy consumer", "Kafka consumer (native DS / OpenTelemetry collector)"),
    ("Alloy scrape / Infinity", "OpenTelemetry collector scrape / API poller"),
    ("Alloy Kafka component", "OpenTelemetry Kafka receiver"),
    ("Alloy telemetry", "OpenTelemetry telemetry pipeline"),
    ("Nokia SR OS", "Nokia SR OS / Juniper Junos"),
    ("Nokia NSP", "Nokia NSP / Cisco Crosswork"),
]

DOT_DIAGRAM = r"""digraph access_network_future_state {
  rankdir=LR;
  splines=ortho;
  compound=true;
  fontname="Helvetica";
  node [fontname="Helvetica" fontsize=10 shape=box style="rounded,filled"];
  edge [fontname="Helvetica" fontsize=9];

  subgraph cluster_sources {
    label="Sources";
    style=dashed;
    color="#666666";

    subgraph cluster_access {
      label="Access / OLT";
      color="#4a90d9";
      style=filled;
      fillcolor="#e8f4fc";

      altiplano [label="EMS/controller A\n(Nokia Altiplano / Calix CMS)" fillcolor="#cce5ff"];
      mosaic [label="EMS/controller B\n(Adtran Mosaic / Calix Aria)" fillcolor="#cce5ff"];
      smx [label="Legacy NMS\n(SNMP only)" fillcolor="#f5d0a9"];
      aoe [label="Legacy EMS\n(SNMP/traps)" fillcolor="#f5d0a9"];
    }

    subgraph cluster_ipmpls {
      label="IP/MPLS";
      color="#6b8e23";
      style=filled;
      fillcolor="#f0f7e6";

      nsp [label="Service orchestrator\n(Nokia NSP / Cisco Crosswork)" fillcolor="#d4e8c0"];
      sr [label="PE/router\n(SR OS / Junos)" fillcolor="#d4e8c0"];
    }
  }

  subgraph cluster_lanes {
    label="Ingest lanes";
    color="#e67e22";
    style=filled;
    fillcolor="#fef5e7";

    lane1 [label="Lane 1\nKafka event streams" fillcolor="#fdebd0"];
    lane2 [label="Lane 2\nCommand-plane APIs" fillcolor="#fdebd0"];
    lane3 [label="Lane 3\nStreaming telemetry" fillcolor="#fdebd0"];
    lane4 [label="Lane 4\nSNMP poll + traps + syslog" fillcolor="#fdebd0"];
    lane5 [label="Lane 5\nFlow export (NetFlow/IPFIX)" fillcolor="#fdebd0"];
  }

  subgraph cluster_middleware {
    label="Collectors & middleware";
    color="#8e44ad";
    style=filled;
    fillcolor="#f5eef8";

    gnmic [label="gNMIc\ngNMI dial-out / subscribe" fillcolor="#e8daef"];
    ktranslate [label="ktranslate\nSNMP + traps + flows" fillcolor="#e8daef"];
    alloy [label="Alloy\nOTLP pipelines\n(Kafka receiver)" fillcolor="#d7bde2"];
    infinity [label="Infinity datasource\nREST / GraphQL / NETCONF poll" fillcolor="#d7bde2"];
  }

  subgraph cluster_gcloud {
    label="Grafana Cloud";
    color="#f46800";
    style=filled;
    fillcolor="#fff4e6";

    gc [label="Dashboards + correlation\n+ alerting + SLOs" fillcolor="#f46800" fontcolor="#ffffff" shape=component];
    logs [label="Loki" fillcolor="#ffe0b2"];
    metrics [label="Mimir" fillcolor="#ffe0b2"];
    traces [label="Tempo" fillcolor="#ffe0b2"];
  }

  // Sources → lanes
  altiplano -> lane1 [label="FM/config events"];
  mosaic -> lane1;
  nsp -> lane1;
  altiplano -> lane2 [label="REST/NBI"];
  mosaic -> lane2 [label="NETCONF"];
  nsp -> lane2 [label="GraphQL"];
  sr -> lane3 [label="gNMI dial-out"];
  smx -> lane4;
  aoe -> lane4;
  sr -> lane4 [label="SNMP/traps"];
  sr -> lane5 [label="NetFlow/IPFIX"];

  // Lanes → collectors & middleware
  lane1 -> alloy [label="lane 1"];
  lane2 -> infinity [label="lane 2"];
  lane3 -> gnmic [label="lane 3"];
  lane4 -> ktranslate [label="lane 4"];
  lane5 -> ktranslate [label="lane 5"];

  gnmic -> alloy [label="OTLP"];
  ktranslate -> alloy [label="OTLP"];

  // Middleware → Grafana Cloud
  alloy -> gc [label="lanes 1,3,4,5"];
  infinity -> gc [label="lane 2"];

  gc -> logs;
  gc -> metrics;
  gc -> traces;
}"""

TOOLCHAIN_HTML = """<div style='display:flex;gap:12px;flex-wrap:wrap'><div style='flex:1;min-width:280px'><h4>Displace → observability platform</h4><table border='1' cellpadding='3' style='border-collapse:collapse;width:100%;font-size:11px'><tr><th>Displace</th><th>Today</th><th>Target</th></tr><tr><td><b>Splunk / Elastic</b></td><td>Logs, API trace headers, device syslog</td><td>Log store via syslog collector</td></tr><tr><td><b>SolarWinds / LibreNMS</b></td><td>SNMP, IPAM, SAM, CGNAT</td><td>SNMP collector → metrics backend</td></tr><tr><td><b>Unified Assurance</b></td><td>NOC traps, access FM</td><td>Kafka lane + alerting</td></tr><tr><td><b>Dynatrace / New Relic</b></td><td>K8s/API tracing</td><td>Tracing backend + OTEL</td></tr><tr><td><b>OpsGenie / PagerDuty</b></td><td>Alert routing</td><td>On-call / IRM platform</td></tr><tr><td><b>Nagios / Icinga</b></td><td>Legacy checks</td><td>Culled / absorbed</td></tr></table></div><div style='flex:1;min-width:280px'><h4>Systems of record (keep)</h4><table border='1' cellpadding='3' style='border-collapse:collapse;width:100%;font-size:11px'><tr><th>System</th><th>Role</th><th>Observability touch</th></tr><tr><td><b>EMS/NMS</b></td><td>Access provisioning, FM, config</td><td>Kafka + API lanes (not replaced)</td></tr><tr><td><b>IP/MPLS orchestrator</b></td><td>Service lifecycle, inventory</td><td>API lane + inventory sync</td></tr><tr><td><b>BSS/OSS</b></td><td>Subscriber, work orders</td><td>Correlation joins (location, ticket)</td></tr><tr><td><b>Field service</b></td><td>Dispatch, truck rolls</td><td>Timeline overlay on plant events</td></tr><tr><td><b>Inventory / GIS</b></td><td>Plant, market boundaries</td><td>Geo + market drill-down</td></tr></table></div></div>"""

INTRO_HTML = """<h2>Access Network Future-State Telemetry Architecture</h2><p>Hypothetical architecture: five ingestion lanes (Kafka event streams, vendor command-plane APIs, device streaming telemetry, SNMP poll+traps, flow export) converging on an observability platform as the correlation layer. EMS/NMS systems remain systems of record; the observability layer does not replace EMS historical FM search.</p><p><b>Pain points this view addresses:</b></p><ul style='margin-top:0'><li>SNMP trap workflows hide alarm lifecycle and structured context</li><li>EMS Kafka buses do not expose every PM counter — northbound APIs still matter</li><li>Streaming telemetry (gNMI dial-out) needed where 15–30 min SNMP poll is too slow</li><li>Flow export blind spots hide congestion until TWAMP SLA or tickets spike</li><li>Full Kafka → log-store duplication would inflate cost without operational gain</li></ul>"""

OPERATOR_PATTERNS_HTML = """<h4>Typical access network operator patterns</h4><table border='1' cellpadding='4' style='border-collapse:collapse;width:100%;font-size:12px'><tr><th>Topic</th><th>Typical access network pattern</th></tr><tr><td><b>Tool sunset</b></td><td>Splunk / Elastic → log store via syslog collector; SolarWinds / LibreNMS → SNMP collector first; legacy NOC assurance → Kafka lane; APM → tracing backend on contract horizon; OpsGenie / PagerDuty → on-call platform</td></tr><tr><td><b>Lane 1 Kafka</b></td><td>EMS/NMS publish FM + config changes to Kafka; native Kafka DS may not alert → <b>OTel Kafka receiver</b> for alerting path</td></tr><tr><td><b>Lane 2 APIs</b></td><td>Vendor northbound APIs (REST, NETCONF, NBI) for inventory, config drift, and PM counters not yet on the Kafka bus</td></tr><tr><td><b>Lane 3 Streaming</b></td><td>gNMI/gRPC dial-out and subscribe — TWAMP/SLA, optical PM, CGNAT; OLTs sensitive to SNMP polling</td></tr><tr><td><b>Lane 4 SNMP collector</b></td><td>SNMP poll, trap listener, and syslog from legacy NEs and EMS-adjacent systems</td></tr><tr><td><b>Lane 5 Flows</b></td><td>NetFlow/IPFIX/sFlow from PE and aggregation routers — congestion, DDoS, CGNAT visibility</td></tr></table>"""

ALIGNMENT_HTML = """<h4>Lane mapping to telco-carrier demos</h4><table border='1' cellpadding='4' style='border-collapse:collapse;width:100%;font-size:12px'><tr><th>Lane</th><th>Sources</th><th>Collector</th><th>Backend</th><th>Demo reference</th></tr><tr><td><b>1 Kafka streams</b></td><td>EMS/NMS event buses (Altiplano, Mosaic, NSP, Crosswork)</td><td>Kafka consumer (native DS / OTel)</td><td>Explore + selective logs/metrics</td><td><code>telco-fiber-access-operations</code> FM</td></tr><tr><td><b>2 Command-plane APIs</b></td><td>EMS REST/NBI, NETCONF, GraphQL</td><td>OTel scrape / API poller</td><td>Metrics (inventory, PM gaps)</td><td>EMS PM not yet in Kafka</td></tr><tr><td><b>3 Streaming telemetry</b></td><td>Router OS (SR OS / Junos), OLT paths (gNMI dial-out)</td><td>gNMI collector (gNMIc / OpenConfig)</td><td>Metrics (sub-minute counters)</td><td>TWAMP, CGNAT, optical PM</td></tr><tr><td><b>4 SNMP, traps, syslog</b></td><td>Legacy NMS, EMS, router OS, legacy NEs</td><td>SNMP collector trap + poll + syslog</td><td>Metrics + logs</td><td>Trap lifecycle panels</td></tr><tr><td><b>5 Flow export</b></td><td>PE routers, BNG, CGNAT nodes</td><td>Flow collector (ktranslate / GoFlow)</td><td>Flow analytics + Sankey</td><td>Congestion + DDoS patterns</td></tr></table>"""

CUSTOMER_IMPACT_HTML = """<p><b>Gap today:</b> Demo stack covers ingest architecture but not subscriber-facing outcomes. HFC dashboard (<code>telco-cable-hfc-operations</code>) has modem flap → truck roll correlation; see <code>telco-fiber-access-operations</code> for the access-network equivalent.</p><table border='1' cellpadding='3' style='border-collapse:collapse;width:100%;font-size:11px;margin-top:8px'><tr><th>Customer-facing signal</th><th>Typical operator need</th><th>Demo metric</th><th>Data source</th></tr><tr><td><b>Subscribers per OLT/PON loss</b></td><td>Hundreds of subs per OLT; market → subscriber drill-down</td><td><code>onts_offline</code>, <code>subs_impacted</code> per PON</td><td>EMS Kafka + location master</td></tr><tr><td><b>PE router / BGP disconnect</b></td><td>Packet drops, interface overload, CGNAT monitoring; core SLA focus</td><td><code>bgp_session_down</code>, <code>interface_discards</code></td><td>gNMI streaming + SNMP poll/traps</td></tr><tr><td><b>Market-level outage</b></td><td>Exec view: subs impacted, ETA, truck rolls queued</td><td><code>subs_impacted</code>, <code>markets_affected</code></td><td>EMS FM + BSS location join</td></tr></table>"""

FOOTER_HTML = """<p><i>Hypothetical access-network reference architecture. Investor metrics frame the business case for unified observability — companion ops board: telco-fiber-access-operations. Requires Graphviz panel (<code>grafana-graphviz-panel</code>). Companion: <code>telco-fiber-access-operations</code>.</i></p>"""

INVESTOR_LENS_HTML = """<h4>Investor &amp; earnings lens</h4><p>Metrics below mirror what public wireless, cable, and access network operators report in <b>quarterly earnings</b>, <b>10-Q/K supplements</b>, and <b>investor decks</b> (net adds, ARPU/ARPA, churn, service revenue growth). Operational KPIs on this board are the <i>leading indicators</i> analysts use to model those figures.</p><p style='font-size:12px;margin-top:4px'><i>Demo pattern:</i> cell availability dip → VoLTE MOS fall → postpaid churn risk → wireless service revenue guidance pressure.</p>"""

STAT_DESCRIPTIONS = {
    "observability_run_rate_savings": "Tool consolidation is a board-level opex line item with explicit payback targets. YoY / QoQ: log analytics + NMS sunset. Public source: CIO business case. Ops drivers on this board: Five ingest lanes converging on observability platform.",
    "broadband_net_adds_q": "Architecture must not block activation velocity or market rollouts. YoY / QoQ: +18%. Public source: Earnings release — broadband access. Ops drivers on this board: PON availability, subs_impacted correlation.",
    "wholesale_sla_penalty_avoided": "Wholesale SLA credits hit EBITDA even when not headline in earnings. Public source: Finance ops model. Ops drivers on this board: TWAMP lane + SLO automation.",
    "truck_roll_opex": "Remote-fixable CPE faults are pure opex leakage when correlation is slow. Public source: Field ops finance. Ops drivers on this board: field-service dispatch + plant timeline before roll.",
    "mean_time_to_correlate": "Every minute of uncorrelated outage drives churn and SLA penalty exposure. YoY / QoQ: vs 45 min siloed NOC. Public source: NOC pilot. Ops drivers on this board: Kafka + flow + trap unified timeline.",
}

ROOT_SELECTORS = {
    "observability_run_rate_savings": '.investor_metrics[] | select(.id=="observability_run_rate_savings") | .value',
    "broadband_net_adds_q": '.investor_metrics[] | select(.id=="broadband_net_adds_q") | .value',
    "wholesale_sla_penalty_avoided": '.investor_metrics[] | select(.id=="wholesale_sla_penalty_avoided") | .value',
    "truck_roll_opex": '.investor_metrics[] | select(.id=="truck_roll_opex") | .value',
    "mean_time_to_correlate": '.investor_metrics[] | select(.id=="mean_time_to_correlate") | .value',
}


def apply_vendor_aliases(text: str) -> str:
    for old, new in VENDOR_ALIASES:
        text = text.replace(old, new)
    return text


def replace_text_fields(obj) -> None:
    if isinstance(obj, str):
        return
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "content" and isinstance(v, str):
                # handled per-panel below
                pass
            elif k == "dotDiagram" and isinstance(v, str):
                obj[k] = DOT_DIAGRAM
            elif k == "data" and isinstance(v, str) and "investor_metrics" in v:
                obj[k] = INFINITY_JSON
            elif isinstance(v, str):
                if "/d/telco-" in v or re.search(r"telco-[a-z]+-", v):
                    obj[k] = v
                else:
                    s = v
                    for old, new in TEXT_REPLACEMENTS:
                        s = s.replace(old, new)
                    s = apply_vendor_aliases(s)
                    s = re.sub(r"\bfiber\b", "access network", s, flags=re.I)
                    s = re.sub(r"\bFiber\b", "Access network", s)
                    obj[k] = s
            else:
                replace_text_fields(v)
    elif isinstance(obj, list):
        for item in obj:
            replace_text_fields(item)


def patch_dashboard(data: dict) -> dict:
    spec = data["spec"]
    spec["title"] = "Access Network Future-State Telemetry Architecture"
    spec["description"] = "Five-lane access-network telemetry model (Kafka, APIs, streaming, SNMP, flows) with Graphviz architecture diagram."
    spec["tags"] = [t for t in spec.get("tags", []) if t not in {"fiber", "isp"}] + ["access-network", "carrier"]

    elements = spec["elements"]
    elements["panel-1"]["spec"]["vizConfig"]["spec"]["options"]["content"] = INTRO_HTML
    elements["panel-10"]["spec"]["vizConfig"]["spec"]["options"]["dotDiagram"] = DOT_DIAGRAM
    elements["panel-11"]["spec"]["vizConfig"]["spec"]["options"]["content"] = ALIGNMENT_HTML
    elements["panel-12"]["spec"]["title"] = "Access network operator patterns"
    elements["panel-12"]["spec"]["vizConfig"]["spec"]["options"]["content"] = OPERATOR_PATTERNS_HTML
    elements["panel-13"]["spec"]["vizConfig"]["spec"]["options"]["content"] = TOOLCHAIN_HTML
    elements["panel-14"]["spec"]["vizConfig"]["spec"]["options"]["content"] = CUSTOMER_IMPACT_HTML
    elements["panel-15"]["spec"]["vizConfig"]["spec"]["options"]["content"] = FOOTER_HTML
    elements["panel-2"]["spec"]["vizConfig"]["spec"]["options"]["content"] = INVESTOR_LENS_HTML

    stat_panels = {
        "panel-3": "observability_run_rate_savings",
        "panel-4": "broadband_net_adds_q",
        "panel-5": "wholesale_sla_penalty_avoided",
        "panel-6": "truck_roll_opex",
        "panel-7": "mean_time_to_correlate",
    }
    metric_names = {m["id"]: m["name"] for m in INFINITY_PAYLOAD["investor_metrics"]}
    for panel_key, metric_id in stat_panels.items():
        panel = elements[panel_key]["spec"]
        panel["title"] = metric_names[metric_id]
        panel["description"] = STAT_DESCRIPTIONS[metric_id]
        q = panel["data"]["spec"]["queries"][0]["spec"]["query"]["spec"]
        q["data"] = INFINITY_JSON
        q["root_selector"] = ROOT_SELECTORS[metric_id]

    # Ops KPI table — period column removed from investor_lens payload.
    panel8 = elements["panel-8"]["spec"]
    q8 = panel8["data"]["spec"]["queries"][0]["spec"]["query"]["spec"]
    q8["data"] = INFINITY_JSON

    # Dashboard links — preserve internal UIDs; only retitle labels.
    for link in spec.get("links", []):
        if link.get("title") == "Fiber ISP Architecture":
            link["title"] = "Access Network Architecture"
        if link.get("title") == "Fiber Access Ops":
            link["title"] = "Access Network Ops"

    replace_text_fields(spec)

    # Repair any accidental fiber→access-network substitution inside dashboard UIDs/URLs.
    def fix_uids(obj) -> None:
        if isinstance(obj, str):
            return
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                if isinstance(v, str) and ("/d/telco-" in v or k in {"url", "name"}):
                    obj[k] = (
                        v.replace("telco-access network-", "telco-fiber-")
                        .replace("access network-access", "fiber-access")
                    )
                else:
                    fix_uids(v)
        elif isinstance(obj, list):
            for item in obj:
                fix_uids(item)

    fix_uids(spec)
    return data


def upsert(data: dict) -> None:
    staging = ROOT / ".dash-payloads" / "telco-fiber-isp-architecture.upload.json"

    def prepare() -> None:
        meta = data.setdefault("metadata", {})
        meta["name"] = UID
        meta["namespace"] = NAMESPACE
        ann = meta.setdefault("annotations", {})
        ann["grafana.app/folder"] = FOLDER
        ann["grafana.app/message"] = "Anonymize access-network architecture dashboard for public sharing"
        staging.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")

    def refresh_rv() -> None:
        proc = subprocess.run(
            ["gcx", "--context", "marcnetterfield1", "dashboards", "get", UID, "-o", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=True,
        )
        lines = [ln for ln in proc.stdout.splitlines() if not ln.startswith('{"class":"hint"')]
        cur = json.loads("\n".join(lines))
        rv = (cur.get("metadata") or {}).get("resourceVersion")
        if rv:
            data["metadata"]["resourceVersion"] = rv
        labels = (cur.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in labels:
            data["metadata"].setdefault("labels", {})["grafana.app/deprecatedInternalID"] = labels[
                "grafana.app/deprecatedInternalID"
            ]

    prepare()
    try:
        refresh_rv()
        prepare()
        subprocess.run(
            ["gcx", "--context", "marcnetterfield1", "dashboards", "update", UID, "-f", str(staging)],
            check=True,
        )
        print("updated", UID)
    except subprocess.CalledProcessError as e:
        if "404" in (e.stderr or "") or "NotFound" in (e.stderr or ""):
            data["metadata"].pop("resourceVersion", None)
            prepare()
            subprocess.run(
                ["gcx", "--context", "marcnetterfield1", "dashboards", "create", "-f", str(staging)],
                check=True,
            )
            print("created", UID)
            return
        refresh_rv()
        prepare()
        subprocess.run(
            ["gcx", "--context", "marcnetterfield1", "dashboards", "update", UID, "-f", str(staging)],
            check=True,
        )
        print("updated (retry)", UID)


def main() -> None:
    data = json.loads(DASH_PATH.read_text(encoding="utf-8"))
    patched = patch_dashboard(data)
    DASH_PATH.write_text(json.dumps(patched, indent=2), encoding="utf-8")
    upsert(patched)
    print("https://marcnetterfield1.grafana.net/d/telco-fiber-isp-architecture")


if __name__ == "__main__":
    main()
