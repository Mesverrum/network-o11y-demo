#!/usr/bin/env python3
"""Update KtransToGrafana architecture dashboard on marcnetterfield1.

Reflects the consolidated golden-path deployment model (credential groups,
discovery/polling split) — not the older monolith snmp.yaml / branch layout.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

UID = "ktrans-arch-replication"
VIZ_VER = "13.1.0-27822252871"

PANELS: dict[str, tuple[str, str]] = {
    "panel-1": (
        "Purpose & audience",
        """## Ktranslate → Grafana Cloud: reference architecture

This guide documents the **recommended customer deployment** for delivering SNMP, flow, and syslog network telemetry into **Grafana Cloud** using [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana).

**Audience:** Network platform engineers, SREs, and observability teams rolling out collectors at a **new site or datacenter** — or scaling an existing footprint with additional credential groups.

**What you get when it works:**
- SNMP metrics as `kentik_snmp_*` (health, interfaces, sensors, BGP tables, etc.)
- Rolled-up flow metrics as `network_io_by_flow_*` (OTEL semantic convention names)
- Syslog and traps as OTLP logs (when `ktranslate_syslog` is enabled)
- Optional ICMP reachability as `kentik_ping_*`
- Every signal tagged with **`deployment_host`** so multiple collector hosts never mix in Grafana

> Community reference implementation (not maintained by Kentik or Grafana). Treat it as the deployment blueprint; use [GitHub issues](https://github.com/Mesverrum/KtransToGrafana/issues) for config questions.

**Upstream docs:** [architecture](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/architecture.md) · [configuration](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/configuration.md) · [operations](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/operations.md)""",
    ),
    "panel-2": (
        "Architecture (reference)",
        """## End-to-end data path

![Ktranslate architecture diagram](https://raw.githubusercontent.com/Mesverrum/KtransToGrafana/main/ktrans_architecture.png)

![Ktranslate to Alloy OTLP path](https://raw.githubusercontent.com/Mesverrum/KtransToGrafana/main/ktrans_to_alloy.png)

```
Network devices / exporters          Collector host (Docker Compose)                 Grafana Cloud
─────────────────────────────        ─────────────────────────────────               ───────────────
SNMP (161/udp)  ───────────────►  ktranslate_snmp_<group>  ──┐
                                   ▲                          │
discover_<group> ──writes─────────┘ state/devices-<group>.yaml
NetFlow/sFlow   ───────────────►  ktranslate_flow  ─────────┼──►  Grafana Alloy  ──OTLP/HTTP──►  Mimir + Loki
Syslog (opt.)   ───────────────►  ktranslate_syslog ────────┘      (config.alloy)              Explore + dashboards
```

**Key ideas:**
1. **Discovery and polling are split** — short-lived `discover_<group>` jobs find devices and atomically update `state/devices-<group>.yaml`; long-running `ktranslate_snmp_<group>` pollers mount polling config **read-only** and reload via `SIGUSR2` when the device list changes.
2. **Git stays source of truth** for credentials, scan ranges, and polling rules; the **network is source of truth** for which devices exist right now.
3. ktranslate emits **OTLP**; a minimal **Alloy** agent forwards to your Grafana Cloud OTLP gateway — no self-hosted Prometheus/Loki required on the collector host.""",
    ),
    "panel-3": (
        "Docker Compose services",
        """## Containers (generated + base stack)

Base file: [`compose-base.yaml`](https://github.com/Mesverrum/KtransToGrafana/blob/main/compose-base.yaml)  
Per-group services: **`compose-groups.generated.yaml`** (from `make generate`)

| Service | Role | Notes |
|---|---|---|
| **`ktranslate_snmp_<group>`** | Long-running SNMP poller for one credential group | Reads `config/poller-<group>.yaml` + `@include state/devices-<group>.yaml`; emits `kentik_snmp_*` |
| **`discover_<group>`** | One-shot discovery (Compose profile) | Runs via `make discover GROUP=<group>`; writes `state/devices-<group>.yaml`; signals poller reload |
| **`ktranslate_flow`** | NetFlow / sFlow / IPFIX aggregation | UDP **9995**; rollup caps cardinality (`--rollup_top_k`, `--rollup_interval`) |
| **`ktranslate_syslog`** | Syslog + SNMP trap ingestion (optional) | UDP/TCP **1514** / trap port per group |
| **`alloy`** | OTLP router → Grafana Cloud | `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY` from `.env`; adds `deployment_host` |

**What is *not* in the golden path:** a single mutable root `snmp.yaml` with `--snmp_discovery_on_start`. Discovery is explicit and repeatable.

**Alloy preprocessing (flow only):** renames rollup metrics to `network.io.by_flow` semantic names and sets `service.name=integrations/ktranslate-netflow` so official NetFlow dashboards apply. SNMP keeps per-group `OTEL_SERVICE_NAME` values (e.g. `ktranslate-snmp-cisco`) so SNMP is **not** rewritten.""",
    ),
    "panel-4": (
        "Deployment model (credential groups)",
        """## One model — no branch selection

Older KtransToGrafana layouts used separate Git branches (`main`, `multicontainer_example`, `multicontainer_netbox`). **All of that is consolidated on `main`.**

A deployment is **N credential groups**, one declarative file each under `groups/<name>.env`:

```
cp groups/cisco.env.sample  groups/cisco.env    # CIDR discovery example
cp groups/palo.env.sample   groups/palo.env     # NetBox discovery example
# edit credentials, ports, discovery source
make generate
make up
make discover GROUP=cisco
make discover GROUP=palo
```

| Concept | How it works |
|---|---|
| **Credential group** | One SNMP credential set + unique host ports (`METALISTEN_PORT`, `TRAP_PORT`) |
| **`DISCOVERY_SOURCE=cidr`** | Scan `TARGETS` (CIDRs or `/32` IPs) |
| **`DISCOVERY_SOURCE=netbox`** | Pull devices matching tag/site/role filters from NetBox |
| **Mixed inventory** | Different groups can use different sources side by side |
| **Single device** | Degenerate case: one group, one `/32` target |
| **Unknown credential map** | `SNMP_VERSION=mixed` + multiple communities/v3 sets — discovery records the working cred per device in `state/devices-<group>.yaml` |

**Generated artifacts** (do not hand-edit — change `groups/*.env` or `templates/` instead):
- `config/discovery-<group>.yaml`
- `config/poller-<group>.yaml`
- `compose-groups.generated.yaml`""",
    ),
    "panel-5": (
        "Metrics you should see",
        """## Metric families (Prometheus / Mimir)

| Signal | Example metrics | Primary labels |
|---|---|---|
| SNMP | `kentik_snmp_CPU`, `kentik_snmp_if_OperStatus`, `kentik_snmp_entSensorValue` | `device_name`, `provider`, `if_interface_name` |
| Flow (rolled up) | `network_io_by_flow_bytes` | `device_name`, `network_local_address`, `network_peer_address`, `network_protocol_name` |
| Ping (opt.) | `kentik_ping_PacketLossPct`, `kentik_ping_AvgRttMs` | `device_name` |
| Multi-site filter | any of the above | `deployment_host` (collector host identity) |

**Cardinality rule of thumb:** ~1,000 active series per network device (simple gear less, core/LB more). Flow is capped by rollup top-K — see the [KtransToGrafana README](https://github.com/Mesverrum/KtransToGrafana#readme) for active-series math.

**Dashboard hygiene:** use template variables (`$device_name`, `$instance`) — never hardcode device hostnames in panel queries.""",
    ),
    "panel-6": (
        "Dashboards in this folder",
        """## Grafana dashboards (starter set)

| Dashboard | UID | Use |
|---|---|---|
| [00. Network Device Summary](/d/mavgvqv/00-network-device-summary) | `mavgvqv` | Fleet health — all SNMP devices |
| [01. Network Device Details](/d/magz6qw1/01-network-device-details) | `magz6qw1` | Per-device drilldown (Overview, Interfaces, Sensors, Connections) |
| [02. Network Flow Summary](/d/be8hpir89dds0a/02-network-flow-summary) | `be8hpir89dds0a` | Top talkers, protocols, geo — rolled-up flow |
| [03. Ktranslate Architecture](/d/ktrans-arch-replication/ktranslate-architecture-and-datacenter-replication) | `ktrans-arch-replication` | This guide |

**Importing to another Grafana stack:** export JSON from each dashboard (**Settings → JSON Model**) or use starter JSON in the [KtransToGrafana `dashboards/` folder](https://github.com/Mesverrum/KtransToGrafana/tree/main/dashboards). On import, map the Prometheus datasource and re-link drilldown URLs if UIDs change.""",
    ),
    "panel-7": (
        "Site rollout checklist",
        """## Stand up another collector site

### 1. Collector host
- [ ] Linux host with Docker + Compose (`docker run hello-world`)
- [ ] Reachability: SNMP **161/udp**, flow exporters (typically **9995/udp**), outbound **HTTPS** to Grafana Cloud OTLP
- [ ] Sufficient RAM — SNMP pollers are the heavy containers (auto-sized via `make limits`)

### 2. Clone & configure [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana)
- [ ] `git clone https://github.com/Mesverrum/KtransToGrafana.git && cd KtransToGrafana`
- [ ] `cp .env.sample .env` — set `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY` (Grafana Cloud → **Connections → OpenTelemetry**)
- [ ] Copy group samples: `cp groups/cisco.env.sample groups/<site>.env` (one file per credential group)
- [ ] Edit each `groups/<name>.env`: `GROUP`, SNMP creds, unique ports, `DISCOVERY_SOURCE`, targets or NetBox filters
- [ ] Optional: `KTRANS_HOST=<site-id>` in `.env` (else hostname auto-fills `deployment_host`)
- [ ] `make generate` then `sudo chown -R 1000:1000 config state`

### 3. Start & discover
- [ ] `make preflight` → `make up`
- [ ] `make discover GROUP=<name>` for **each** group (pollers start with empty `{}` stubs until discovery runs)
- [ ] Schedule discovery: cron `scripts/run-discovery.sh <group>` every 6h (stagger groups a few minutes apart)

### 4. Validate Grafana Cloud
- [ ] `count by (device_name) (kentik_snmp_DeviceMetrics)` — one series per polled device
- [ ] `count by (device_name, deployment_host) (kentik_snmp_DeviceMetrics)` — confirm site tag
- [ ] `sum by (device_name) (rate(network_io_by_flow_bytes[5m]))` — if flow exporters aim at UDP 9995

### 5. Production hardening
- [ ] Restrict `.env` permissions; separate `.env` per environment (`docker compose --env-file .env.prod …`)
- [ ] Pin images: `KTRANSLATE_IMAGE`, `ALLOY_IMAGE` in `.env`
- [ ] Document CIDRs, credentials, and NetBox filters per group
- [ ] Tune flow `--rollup_top_k` if cardinality or cost is high""",
    ),
    "panel-8": (
        "Verification queries",
        """## PromQL quick checks (Explore → Prometheus)

**SNMP devices polling:**
```promql
count by (device_name) (kentik_snmp_DeviceMetrics)
```

**Scope to one collector host:**
```promql
count by (device_name) (
  kentik_snmp_DeviceMetrics{deployment_host="$deployment_host"}
)
```

**SNMP active series by device (rough footprint):**
```promql
count by (device_name) ({__name__=~"kentik_snmp_.+"})
```

**Flow bytes rate by exporter:**
```promql
sum by (device_name) (rate(network_io_by_flow_bytes[5m]))
```

**Ping loss (if enabled):**
```promql
avg by (device_name) (kentik_ping_PacketLossPct)
```

If Explore returns data but dashboards are empty, check the **device template variable** and datasource selector at the top of each dashboard.""",
    ),
    "panel-9": (
        "Troubleshooting & references",
        """## When something breaks

| Symptom | First place to look |
|---|---|
| No SNMP devices after `make up` | Discovery not run yet — `make discover GROUP=<name>`; then inspect `state/devices-<group>.yaml` |
| Discovery empty | `docker compose logs discover_<group>`; test `snmpwalk` from host; ACLs / wrong creds |
| Devices in state but no metrics | Profile gap — check poller logs for `sysObjectID`; search [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles) or open an upstream PR ([profile tutorial](https://github.com/kentik/ktranslate/wiki/Tutorial:-Writing-a-custom-yaml-file-for-SNMP)) |
| Poller not picking up new devices | Re-run discovery (sends `SIGUSR2` reload); confirm `state/` owned by uid **1000** |
| No flow | Exporter IP/port, firewall UDP **9995**, `ktranslate_flow` logs |
| Metrics in Cloud but wrong names | Alloy transform — SNMP should **not** get `integrations/ktranslate-netflow` service name |
| Sites mixed in Grafana | Filter on `deployment_host`; set explicit `KTRANS_HOST` per collector |

**References**
- [KtransToGrafana README](https://github.com/Mesverrum/KtransToGrafana#readme)
- [Kentik ktranslate](https://github.com/kentik/ktranslate)
- [Kentik SNMP profiles](https://github.com/kentik/snmp-profiles)
- [Grafana Cloud OTLP](https://grafana.com/docs/grafana-cloud/send-data/otlp/)
- [Advanced Ktranslate Configuration](https://github.com/kentik/ktranslate/wiki/Advanced-Ktranslate-Configuration)

**Contact:** [KtransToGrafana Issues](https://github.com/Mesverrum/KtransToGrafana/issues) on GitHub.""",
    ),
}


def text_panel(pid: int, title: str, content: str) -> dict:
    return {
        "kind": "Panel",
        "spec": {
            "id": pid,
            "title": title,
            "description": "",
            "links": [],
            "data": {
                "kind": "QueryGroup",
                "spec": {"queries": [], "queryOptions": {}, "transformations": []},
            },
            "vizConfig": {
                "group": "text",
                "kind": "VizConfig",
                "version": VIZ_VER,
                "spec": {
                    "fieldConfig": {"defaults": {}, "overrides": []},
                    "options": {
                        "mode": "markdown",
                        "content": content,
                        "code": {
                            "language": "plaintext",
                            "showLineNumbers": False,
                            "showMiniMap": False,
                        },
                    },
                },
            },
        },
    }


def gcx_get() -> dict:
    raw = subprocess.check_output(
        ["gcx", "--context", "marcnetterfield1", "dashboards", "get", UID, "-o", "json"],
        stderr=subprocess.DEVNULL,
    ).decode("utf-8", errors="replace")
    return json.loads(raw[raw.find("{") :])


def gcx_update(dash: dict) -> None:
    out = Path("/tmp/ktrans-arch-patched.json")
    out.write_text(json.dumps(dash, indent=2), encoding="utf-8")
    subprocess.run(
        ["gcx", "--context", "marcnetterfield1", "dashboards", "update", UID, "-f", str(out)],
        check=True,
    )


def main() -> None:
    dash = gcx_get()
    elements = dash["spec"]["elements"]
    for key, (title, content) in PANELS.items():
        pid = int(key.split("-")[1])
        old = elements.get(key, {})
        if old.get("spec", {}).get("id"):
            pid = old["spec"]["id"]
        elements[key] = text_panel(pid, title, content)

    dash["spec"]["elements"] = elements
    dash["spec"]["title"] = "03. Ktranslate Architecture & Datacenter Replication"
    dash["spec"]["description"] = (
        "Reference architecture for KtransToGrafana golden-path deployment "
        "(credential groups, discovery/polling split) → Grafana Cloud OTLP."
    )
    ann = dash.setdefault("metadata", {}).setdefault("annotations", {})
    ann["grafana.app/message"] = "Updated to KtransToGrafana golden-path deployment model"
    gcx_update(dash)
    print(f"Updated https://marcnetterfield1.grafana.net/d/{UID}/ktranslate-architecture-and-datacenter-replication")


if __name__ == "__main__":
    main()
