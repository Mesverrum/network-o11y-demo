# Orb agent — NetBox Labs sidecar (prefer **AWS colocated**)

Default path runs on the **colocated EC2** host next to ContainerLab (`172.20.20.0/24`).

## Full toolchain (recommended)

```bash
make -C local netbox-colocated   # NetBox + Diode + live Orb
make -C local netbox-ui-tunnel   # browser → http://127.0.0.1:8000/
```

Data path:

```
Clos SNMP → Orb snmp_discovery → dry-run JSON (/opt/.../orb/out)
                ↘ OTLP → Alloy → Grafana Cloud
Populate overlay → NetBox UI (intended Clos SoT)
Grafana Cloud Infinity `netbox-api` → NetBox REST (live SoT on dashboards 20/22/24/25)
```

Live Diode (`ORB_DRY_RUN=0`) still works as a crawl demo, but it duplicates SRL boxes at site `network-lab` and fills unused IF-MIB ports. After populate, keep Orb on dry-run:

```bash
make -C local orb-dry-diode-colocated
python3 local/scripts/netbox-populate.py --profile colocated --tidy-only
```

## Orb-only

```bash
make -C local orb-colocated       # dry-run by default; live if DIODE_* in remote .env
make -C local orb-dry-diode-colocated  # persist ORB_DRY_RUN=1 on the host
make -C local orb-down-colocated
make -C local orb-up-local        # laptop only (avoid if RAM-constrained)
```

Dry-run JSON (when `ORB_DRY_RUN=1`): `/opt/network-o11y-demo/local/orb/out/`

## Env knobs

| Variable | Default | Meaning |
|----------|---------|---------|
| `ORB_DRY_RUN` | `1` (orb-only) / `0` after `netbox-colocated` | Write JSON vs Diode |
| `ORB_OTLP` | `0` / `1` after netbox-colocated | Export Orb metrics to Alloy |
| `ORB_SNMP_TARGETS` | `172.20.20.0/24` | SNMP discovery scope |
| `DIODE_CLIENT_ID` / `SECRET` | set by bring-up | diode-ingest OAuth client |
| `ORB_DIODE_TARGET` | `grpc://127.0.0.1:8080/diode` | Diode gRPC |
| `ORB_PKTVISOR` | `0` | Enable pktvisor taps (NetFlow **19995** / sFlow **16343** — avoids ktranslate `9995`/`6343`) |

## pktvisor (no PCAP)

```bash
# Redeploy Orb with pktvisor + dual softflowd/sFlow feeds
ORB_PKTVISOR=1 ORB_DRY_RUN=0 ORB_OTLP=1 make -C local orb-colocated
```

Handlers enabled on flow taps: **flow** only (`dns`/`dhcp`/`net` require PCAP and are rejected on NetFlow/sFlow inputs). PCAP is intentionally off.

`make softflowd` / sFlow scripts honor `ORB_PKTVISOR=1` and dual-export to the host clab gateway (`172.20.20.1` by default): NetFlow **9995** (ktranslate) + **19995** (pktvisor), sFlow **6343** + **16343**. Softflowd uses **one process per destination** (Alpine softflowd multi-`-n` starved `:9995` when `:19995` was added). SRL sFlow supports two collectors natively.

## Grafana Cloud dashboards

Folder **Network Lab**. Rebuild/import:

```bash
python3 local/scripts/build-orb-netbox-dashboards.py --import
# or: make -C local orb-netbox-dashes
```

| UID | Title | Data |
|-----|-------|------|
| `orb-netbox-overview` | 20. Orb + NetBox overview | Compare NetBox / Orb discovery / ktranslate SNMP counts |
| `orb-snmp-discovery` | 21. Orb SNMP discovery | `discovered_hosts`, `discovery_*`, Diode API latency |
| `netbox-inventory-sot` | 22. NetBox inventory (SoT) | Infinity `netbox-api` (`/api/dcim/devices/`, `/api/dcim/interfaces/`). Latest SoT only — audit history is NetBox changelog/journal. |
| `orb-pktvisor-edge` | 23. Orb pktvisor edge analytics | `dns_*` / `net_*` / `packets_*` (empty until `ORB_PKTVISOR=1` + flow export) |
| `orb-ktranslate-entity-readiness` | 24. Network SoT vs telemetry (leadership) | Compare NetBox/Orb/pktvisor vs ktranslate for KG entity readiness |
| `ktranslate-device-details-netbox` | 25. Device Details + NetBox SoT | Clone of Device Details in folder **NetBox × Device Details** — CMDB enrichment + NetBox deep links |

Rebuild Device Details enrich clone: `make -C local device-details-netbox` (or `python3 local/scripts/build-device-details-netbox-enrich.py`). Map: [`local/docs/device-details-netbox-enrichment.md`](../docs/device-details-netbox-enrichment.md).

Rebuild leadership board: `python3 local/scripts/build-orb-ktranslate-leadership-dash.py --import`

## Gap checklist

1. NetBox UI shows the populate Clos SoT (`python3 local/scripts/netbox-populate.py --profile colocated`). Orb discovery writes dry-run JSON unless you opt into live Diode (`ORB_DRY_RUN=0`). After live ingest, tidy: `--tidy-only` + `make -C local orb-dry-diode-colocated`.
2. Open dashboards 20/22/24/25 — NetBox panels are Infinity REST. Orb discovery metrics: `service_name=~snmp-discovery`, `deployment_host=aws-colocated-lab`.
3. Confirm **no** new `kentik_snmp_*` from Orb alone (ktranslate still owns health SNMP).
4. pktvisor panels light up only after `ORB_PKTVISOR=1` and a NetFlow exporter aimed at host `:19995` (do not steal softflowd from ktranslate `:9995`).
