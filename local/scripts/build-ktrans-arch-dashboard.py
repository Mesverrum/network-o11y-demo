#!/usr/bin/env python3
"""Update KtransToGrafana architecture dashboard (v2 manifest via gcx).

Reflects consolidated `main` golden path: credential groups, discovery/polling
split, flow/syslog catalog enrichment, and docs/grafana.md verification queries.

Usage:
  python3 local/scripts/build-ktrans-arch-dashboard.py
  python3 local/scripts/build-ktrans-arch-dashboard.py --context marcnetterfield1
  python3 local/scripts/build-ktrans-arch-dashboard.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

UID = "ktranslate-architecture"
VIZ_VER = "13.1.0-27822252871"

PANELS: dict[str, tuple[str, str]] = {
    "panel-1": (
        "Purpose & audience",
        """## Ktranslate → Grafana Cloud: reference architecture

This guide documents the **recommended customer deployment** for delivering SNMP, flow, and syslog network telemetry into **Grafana Cloud** using [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana).

**Audience:** Network platform engineers, SREs, and observability teams rolling out collectors at a **new site or datacenter** — or scaling an existing footprint with additional credential groups.

**What you get when it works:**
- SNMP metrics as `kentik_snmp_*` (health, interfaces, sensors, BGP tables, etc.)
- Rolled-up flow metrics as `network_io_by_flow_*` (OTEL semantic convention names after Alloy preprocessing)
- Syslog and traps as OTLP logs (when `ktranslate_syslog` is enabled)
- Optional ICMP reachability as `kentik_ping_*`
- Per-group `service.name` labels (`ktranslate-snmp-<group>`, `ktranslate-discover-<group>`) plus **`deployment_host`** when `KTRANS_HOST` is set — so multiple collector hosts never mix in Grafana

> Community reference implementation (not maintained by Kentik or Grafana). Treat it as the deployment blueprint; use [GitHub issues](https://github.com/Mesverrum/KtransToGrafana/issues) for config questions.

**Upstream docs:** [README](https://github.com/Mesverrum/KtransToGrafana#readme) · [architecture](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/architecture.md) · [configuration](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/configuration.md) · [operations](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/operations.md) · [grafana](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/grafana.md)""",
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
         ▲                              ▲
         └──── config/catalog.yaml ─────┘   (device_name enrichment for flow + syslog)
```

**Key ideas:**
1. **Discovery and polling are split** — short-lived `discover_<group>` jobs find devices and atomically update `state/devices-<group>.yaml`; long-running `ktranslate_snmp_<group>` pollers mount polling config **read-only** and reload via `SIGUSR2` when the device list changes.
2. **Flow and syslog share a generated catalog** (`config/catalog.yaml`) that `@`-includes every group's device file so exporter IPs map to the same `device_name` / tags as SNMP.
3. **Git stays source of truth** for credentials, scan ranges, and polling rules; the **network is source of truth** for which devices exist right now.
4. ktranslate emits **OTLP**; a minimal **Alloy** agent forwards to your Grafana Cloud OTLP gateway — no self-hosted Prometheus/Loki required on the collector host.""",
    ),
    "panel-3": (
        "Docker Compose services",
        """## Containers (generated + base stack)

Base: [`compose-base.yaml`](https://github.com/Mesverrum/KtransToGrafana/blob/main/compose-base.yaml) (copy from `compose-base.yaml.sample`)  
Per-group: **`compose-groups.generated.yaml`** · catalog mounts: **`compose-catalog.generated.yaml`** (from `make generate`)

| Service | Role | Notes |
|---|---|---|
| **`ktranslate_snmp_<group>`** | Long-running SNMP poller for one credential group | Reads `config/poller-<group>.yaml` + `@include state/devices-<group>.yaml`; `OTEL_SERVICE_NAME=ktranslate-snmp-<group>` |
| **`discover_<group>`** | One-shot discovery (Compose profile) | `make discover GROUP=<group>`; writes `state/devices-<group>.yaml`; signals poller reload |
| **`ktranslate_flow`** | NetFlow / sFlow / IPFIX aggregation | UDP **9995**; mounts catalog as `/snmp.yaml` (`--flow_only=true`); rollup `--rollup_top_k=100`, `--rollup_interval=60` |
| **`ktranslate_syslog`** | Syslog + SNMP trap ingestion (optional) | UDP/TCP **1514**; same catalog for device enrichment |
| **`alloy`** | OTLP router → Grafana Cloud | `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY` from `.env`; flow preprocessing → `network.io.by_flow` |

**What is *not* in the golden path:** a single mutable root `snmp.yaml` with `--snmp_discovery_on_start`. Discovery is explicit: `make discover GROUP=<name>` (or `make discover-all`).

**Optional sflow demo:** `make detect-net && make up-demo` adds instant flow before routers export — see [operations.md § sflow demo](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/operations.md).

**Alloy preprocessing (flow only):** renames rollup metrics to `network.io.by_flow` and sets datapoint label `integration=ktranslate-netflow` on rollups only (CHF/logs keep `OTEL_SERVICE_NAME`). SNMP/discovery keep per-group `OTEL_SERVICE_NAME` values.""",
    ),
    "panel-4": (
        "Deployment model (credential groups)",
        """## One model on `main` — no branch selection

Older layouts used separate Git branches (`main`, `multicontainer_example`, `multicontainer_netbox`). **All consolidated on `main`**; old branch tips preserved as `archive/*` tags.

A deployment is **N credential groups**, one declarative file each under `groups/<name>.env`:

```
cp groups/onboarding.env.sample groups/onboarding.env   # range + candidate creds
cp groups/cisco.env.sample     groups/cisco.env         # CIDR example
cp groups/palo.env.sample      groups/palo.env          # NetBox example
# edit credentials, ports, discovery source
make generate
make up
make discover GROUP=onboarding
```

| Concept | How it works |
|---|---|
| **Credential group** | One SNMP credential set + unique host ports (`METALISTEN_PORT`, `TRAP_PORT`) |
| **`DISCOVERY_SOURCE=cidr`** | Scan `TARGETS` (CIDRs or `/32` IPs) |
| **`DISCOVERY_SOURCE=netbox`** | Pull devices matching tag/site/role filters from NetBox (`NETBOX_HOST` / `NETBOX_TOKEN` in `.env`) |
| **Unknown credential map** | `SNMP_VERSION=mixed` + comma-separated communities and/or numbered `SNMP_V3_*_2`…`_9` sets — discovery records the working cred per device in `state/devices-<group>.yaml` |
| **Single device** | Degenerate case: `groups/single.env.sample` with one `/32` target |

**Generated artifacts** (do not hand-edit — change `groups/*.env` or `templates/` instead):
- `config/discovery-<group>.yaml`, `config/poller-<group>.yaml`
- `config/catalog.yaml` — enrichment for flow + syslog (`@` includes all `state/devices-*.yaml`)
- `compose-groups.generated.yaml`, `compose-catalog.generated.yaml`""",
    ),
    "panel-5": (
        "Metrics you should see",
        """## Metric families (Prometheus / Mimir)

| Signal | Example metrics | Primary labels |
|---|---|---|
| SNMP | `kentik_snmp_CPU`, `kentik_snmp_if_OperStatus`, `kentik_snmp_DeviceMetrics` | `device_name`, `service_name` (`ktranslate-snmp-<group>`), `if_interface_name` |
| Flow (rolled up) | `network_io_by_flow_bytes` | `device_name`, `network_local_address`, `network_peer_address`, `network_protocol_name` |
| Ping (opt.) | `kentik_ping_PacketLossPct`, `kentik_ping_AvgRttMs` | `device_name` |
| Multi-site filter | any of the above | `deployment_host` (collector host identity via `KTRANS_HOST`) |

**Cardinality rule of thumb:** gear varies widely (UPS ~50 series, core/LB 10k+). Flow ceiling: `rollup_top_k × (active_series_window / rollup_interval)` — with defaults `100 × (1200/60) = 2,000` series worst case. See [grafana.md § Flow data](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/grafana.md).

**Dashboard hygiene:** use template variables (`$device_name`, `$instance`, `$deployment_host`) — never hardcode device hostnames in panel queries.""",
    ),
    "panel-6": (
        "Dashboards in this folder",
        """## Grafana dashboards (starter set)

| Dashboard | UID | Use |
|---|---|---|
| [00. Ktranslate Architecture](/d/ktranslate-architecture/00-ktranslate-architecture) | `ktranslate-architecture` | This guide |
| [01. Ktranslate Health](/d/ktranslate-health/01-ktranslate-health) | `ktranslate-health` | Collector CHF / jchf health |
| [02. Network Flow Summary](/d/ktranslate-flow-summary/02-network-flow-summary) | `ktranslate-flow-summary` | Top talkers, protocols — rolled-up flow |
| [03. Network Device Summary](/d/ktranslate-device-summary/03-network-device-summary) | `ktranslate-device-summary` | Fleet health — all SNMP devices |
| [04. Network Device Details](/d/ktranslate-device-details/04-network-device-details) | `ktranslate-device-details` | Per-device drilldown (Overview, Interfaces, BGP, …) |

**Also in the [KtransToGrafana `dashboards/` folder](https://github.com/Mesverrum/KtransToGrafana/tree/main/dashboards):**
- `Ktranslate Flow Summary.json` — OTEL semconv flow names (post-Alloy transform)
- `ktranslate network fleet overview.json`, `ktranslate snmp device view.json`
- **`alerts/`** — example alert rules and notification templates
- **`skills/`** — onboarding guides for new hardware

**Importing to another Grafana stack:** export JSON (**Settings → JSON Model**) or import from the repo `dashboards/` folder. Map the Prometheus datasource; re-link drilldown URLs if UIDs change.""",
    ),
    "panel-7": (
        "Site rollout checklist",
        """## Stand up another collector site

### 1. Collector host
- [ ] Linux host with Docker + Compose (`docker run hello-world`); `yq` + `envsubst`
- [ ] Reachability: SNMP **161/udp**, flow exporters (typically **9995/udp**), outbound **HTTPS** to Grafana Cloud OTLP
- [ ] Sufficient RAM — SNMP pollers are the heavy containers (`make limits` auto-sizes)

### 2. Clone & configure [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana)
- [ ] `git clone … && cd KtransToGrafana`
- [ ] `cp .env.sample .env` — `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY` (Grafana Cloud → **Connections → OpenTelemetry**)
- [ ] `cp config.alloy.sample config.alloy` · `cp compose-base.yaml.sample compose-base.yaml`
- [ ] `cp groups/onboarding.env.sample groups/<site>.env` (or `cisco.env.sample` / `palo.env.sample`)
- [ ] Edit each `groups/<name>.env`: `GROUP`, SNMP creds, unique ports, `DISCOVERY_SOURCE`, `TARGETS` or NetBox filters
- [ ] Optional: `KTRANS_HOST=<site-id>` in `.env` (else hostname auto-fills `deployment_host`)
- [ ] `make generate` then `sudo chown -R 1000:1000 config state`

### 3. Start & discover
- [ ] `make preflight` → `make up`
- [ ] `make discover GROUP=<name>` for **each** group (pollers start with `{}` stubs until discovery runs)
- [ ] Optional instant flow: `make detect-net && make up-demo`
- [ ] Schedule: cron `scripts/run-discovery.sh <group>` every 6h (stagger groups)

### 4. Validate Grafana Cloud
- [ ] `count by (device_name, service_name) (kentik_snmp_DeviceMetrics)` — one row per polled device per group
- [ ] `count by (device_name, deployment_host) (kentik_snmp_DeviceMetrics)` — confirm site tag
- [ ] `sum by (device_name) (rate(network_io_by_flow_bytes[5m]))` — if flow exporters aim at UDP 9995
- [ ] Review `state/devices-<group>.yaml` — credential that worked per device

### 5. Production hardening
- [ ] Restrict `.env` permissions; separate `.env` per environment (`docker compose --env-file .env.prod …`)
- [ ] Pin images: `KTRANSLATE_IMAGE`, `ALLOY_IMAGE` in `.env`
- [ ] Document CIDRs, credentials, and NetBox filters per group
- [ ] Tune flow `--rollup_top_k` if cardinality or cost is high""",
    ),
    "panel-8": (
        "Verification queries",
        """## PromQL quick checks (Explore → Prometheus)

From [docs/grafana.md](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/grafana.md):

**SNMP devices polling (by credential group):**
```promql
count by (device_name, service_name) (kentik_snmp_DeviceMetrics)
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
| No SNMP devices after `make up` | Discovery not run — `make discover GROUP=<name>`; inspect `state/devices-<group>.yaml` |
| Discovery empty | `docker compose logs discover_<group>`; test `snmpwalk` from host; ACLs / wrong creds — see [`troubleshooting/`](https://github.com/Mesverrum/KtransToGrafana/tree/main/troubleshooting) |
| Devices in state but no metrics | Profile gap — check poller logs for `sysObjectID`; search [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles) |
| Poller not picking up new devices | Re-run discovery (`SIGUSR2` reload); confirm `state/` owned by uid **1000** |
| Flow missing `device_name` | Catalog stale — `make discover-all` reloads flow/syslog + all pollers |
| No flow | Exporter IP/port, firewall UDP **9995**, `ktranslate_flow` logs; try `make up-demo` |
| Metrics in Cloud but wrong names | Alloy transform — flow rollups use `integration=ktranslate-netflow`; SNMP/CHF keep `ktranslate-*` service names |
| Sites mixed in Grafana | Filter on `deployment_host`; set explicit `KTRANS_HOST` per collector |

**References**
- [KtransToGrafana README](https://github.com/Mesverrum/KtransToGrafana#readme) · [operations.md](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/operations.md) · [grafana.md](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/grafana.md)
- [Kentik ktranslate](https://github.com/kentik/ktranslate) · [Kentik SNMP profiles](https://github.com/kentik/snmp-profiles)
- [Grafana Cloud OTLP](https://grafana.com/docs/grafana-cloud/send-data/otlp/) · [ktranslate-netflow integration](https://grafana.com/docs/grafana-cloud/monitor-infrastructure/integrations/integration-reference/integration-ktranslate-netflow/)

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


def parse_gcx_json(raw: str) -> dict:
    """Parse dashboard JSON from gcx output (may include hint lines)."""
    marker = '{\n  "apiVersion"'
    start = raw.find(marker)
    if start < 0:
        start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"gcx returned no JSON: {raw[:500]}")
    obj, _ = json.JSONDecoder().raw_decode(raw, start)
    return obj


def gcx_get(context: str) -> dict:
    raw = subprocess.check_output(
        ["gcx", "--context", context, "--agent", "dashboards", "get", UID, "-o", "json"],
        stderr=subprocess.STDOUT,
    ).decode("utf-8", errors="replace")
    return parse_gcx_json(raw)


def gcx_update(context: str, dash: dict, dry_run: bool) -> Path:
    out = Path(tempfile.gettempdir()) / "ktrans-arch-patched.json"
    out.write_text(json.dumps(dash, indent=2), encoding="utf-8")
    if dry_run:
        print(f"dry-run: wrote {out}")
        return out
    subprocess.run(
        ["gcx", "--context", context, "--agent", "dashboards", "update", UID, "-f", str(out)],
        check=True,
    )
    return out


def patch_dashboard(dash: dict) -> dict:
    elements = dash["spec"]["elements"]
    for key, (title, content) in PANELS.items():
        pid = int(key.split("-")[1])
        old = elements.get(key, {})
        if old.get("spec", {}).get("id"):
            pid = old["spec"]["id"]
        elements[key] = text_panel(pid, title, content)

    dash["spec"]["elements"] = elements
    dash["spec"]["title"] = "00. Ktranslate Architecture"
    dash["spec"]["description"] = (
        "Reference architecture for KtransToGrafana golden-path deployment "
        "(credential groups, discovery/polling split, catalog enrichment) → Grafana Cloud OTLP."
    )
    ann = dash.setdefault("metadata", {}).setdefault("annotations", {})
    ann["grafana.app/message"] = (
        "Synced to KtransToGrafana main: credential groups, catalog.yaml, onboarding flow"
    )
    return dash


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--context", default="marcnetterfield1", help="gcx context (default: marcnetterfield1)")
    ap.add_argument("--dry-run", action="store_true", help="Write JSON only; do not push")
    args = ap.parse_args()

    dash = gcx_get(args.context)
    layout_kind = dash.get("spec", {}).get("layout", {}).get("kind", "?")
    print(f"Fetched {UID} layout={layout_kind} generation={dash.get('metadata', {}).get('generation', '?')}")

    dash = patch_dashboard(dash)
    gcx_update(args.context, dash, args.dry_run)

    if not args.dry_run:
        print(
            f"Updated https://marcnetterfield1.grafana.net/d/{UID}/"
            "00-ktranslate-architecture"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
