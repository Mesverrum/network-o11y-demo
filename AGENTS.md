# AGENTS.md — guidance for LLM coding agents

Keep this file accurate as the lab evolves. When you change architecture, collectors, metric names, or bring-up steps, **update this file and `.cursor/rules/` in the same change**.

## What this repo is

Companion demo for the blog series **Network Observability Without the Lock-in**. Two deployment paths:

| Path | Location | Audience |
|------|----------|----------|
| **Local lab (preferred for laptops)** | [`local/`](local/) | WSL2 + ContainerLab + Docker Compose; 16 GB–friendly |
| **AWS / EKS** | [`terraform/`](terraform/), [`k8s/`](k8s/) | Full Clos on Clabbernetes; NetBox + Ansible stages |

Do **not** lift-and-shift the EKS/Clabbernetes stack onto a laptop. Local work belongs under `local/`. Leave AWS manifests alone unless the user explicitly asks for EKS changes.

## Local lab (current phase)

- **Topology:** 1 spine (`spine1`) + 2 leaves (`leaf1`, `leaf2`) + 2 clients (`client1`, `client2`); all SR Linux `ixrd2l`
- **Talk track:** eBGP underlay + EVPN MAC-VRF; clients `172.17.0.1` / `172.17.0.2`
- **Collectors:** `ktranslate_snmp_srl` (golden-path poller), `ktranslate_flow`, `ktranslate_syslog`, **`gnmic`** (incl. LLDP neighbors), **`topology_exporter`**
- **NetBox Cloud (optional):** `scripts/netbox-populate.py` + `update-netbox-mgmt-ips.py` when `DISCOVERY_SOURCE=netbox` in `groups/srl.env` (`groups/srl.env.netbox.sample`). Default bring-up uses **CIDR** discovery (`groups/srl.env.sample`). See `local/netbox/README.md`.
- **ktranslate model:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) golden path — `groups/*.env` → `make generate` → discovery/polling split (`discover_srl` profile + read-only poller). No root `snmp.yaml` + `snmp_discovery_on_start`
- **SRL SNMP profile:** `local/snmp-profiles/nokia/nokia-srlinux.yml` bind-mounted into poller/discover at `/etc/ktranslate/profiles/kentik_snmp/nokia/`; `mibs_enabled` includes `IF-MIB` + `TIMETRA-{SYSTEM,CHASSIS,BGP}-MIB`. Discovery should set `mib_profile: nokia-srlinux.yml` (sysObjectID `1.3.6.1.4.1.6527.1.20.*`)
- **Alloy role:** OTLP receive + Docker log scrape (lab containers except ktranslate) → preprocess → OTLP HTTP to Grafana Cloud. ktranslate already tees its own logs (and device syslog/traps) over OTLP via `--tee_logs=true`.
- **Topology:** `topology_exporter` discovers devices via SNMP (`network_topology_device_info`). LLDP edges via **gnmic** `/system/lldp/.../neighbor` → Alloy remaps `…lldp_interface_neighbor_system_name` → `network_topology_edge_info` (stock SRL SNMP has no LLDP rem-table; LLDP protocol itself is enabled)
- **Topology exporter image:** GHCR may require auth; build local pin with `make -C local topology-exporter-image` (`srl-local/network-topology-exporter:v1.0.0` from GitHub release binary)
- **Deferred:** Ansible, full 2-spine/3-leaf Clos, local LGTM stack

### Bring-up (WSL)

```bash
cd /mnt/c/Users/<you>/projects/network-o11y-demo/local   # Windows path via /mnt/c/...
cp .env.example .env          # set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY
cp groups/srl.env.sample groups/srl.env
make generate
sudo chown -R 1000:1000 config state
make up
make traffic
```

Optional NetBox Cloud discovery: `cp groups/srl.env.netbox.sample groups/srl.env`, set `NETBOX_*` in `.env`, then `make generate && make netbox-sync && make up`.

From repo root: `make local-up` / `make local-down` / `make local-help`.

Agents on Windows may run the same via `wsl -e bash -lc 'cd ... && make up'`.

### Operational gotchas

1. **ContainerLab mgmt network is `clab`** (v0.72+ shared bridge), not `srl-local`. Set `CLAB_NETWORK=clab` in `.env`.
2. **Shell scripts must be LF** (CRLF breaks `set -o pipefail`). `.gitattributes` forces LF under `local/`.
3. **Alloy comments are `//`**, not `#`.
4. **`state/devices-*.yaml` is mutable** (discovery writes device lists); never commit `config/` / `state/` / `groups/*.env`. UID 1000 must own `config/` and `state/`.
5. **Syslog / SNMP traps:** pipe into `sr_cli` via `docker exec -i` (non-interactive); see `local/scripts/syslog-config.sh` and `snmp-trap-config.sh`. Both must use **mgmt** (`system logging network-instance mgmt`, trap-group `network-instance mgmt`) or packets never leave the box. Traps → poller `:1620`. One-shot: `make -C local emit-events`. Periodic: `make -C local events-loop` (synthetic traps ~3m, real flaps ~5m; `events-stop` / `events-status`).
6. **`/mnt/c` + ContainerLab postdeploy:** clab cannot commit `config.tmp` when the lab dir is on Windows drvfs (`/mnt/c/...`). Postdeploy fails; fabric startup-config is **not** applied automatically. `make up` and `make fabric-apply` run `scripts/apply-fabric-config.sh` (SNMP-only by default on `/mnt/c`; set `FULL_FABRIC=1` to attempt full `configs/fabric/*.cfg`, which often fails with `net_inst_mgr`). **Prefer** a native WSL clone (`~/projects/network-o11y-demo`) for full BGP/EVPN via postdeploy. **Do not** run `clab deploy --reconfigure` unless the user explicitly asks — it SIGTERM-stops all lab containers (exit 143), which looks like a crash but is not OOM.
7. **Recovery without redeploy:** `make -C local stabilize` — `docker start` stopped SRL nodes, apply fabric, NetBox sync, discover, softflowd/syslog/traps. Not a memory issue: SRL exits with code 143 (SIGTERM), `OOMKilled=false`.

### Metrics to expect in Grafana Cloud

| Stream | PromQL / check |
|--------|----------------|
| SNMP | `count by (device_name, service_name) (kentik_snmp_DeviceMetrics)` → spine1, leaf1, leaf2 |
| NetFlow | `sum by (device_name) (rate(network_io_by_flow[5m]))` |
| Syslog | OTLP logs via ktranslate `--tee_logs` (`service_name` ≈ `ktranslate`, `tags.container_service=syslog`) |
| Docker stdout | Alloy `loki.source.docker` → OTLP (`collector=docker`, `service_name` = container: `topology_exporter`, `spine1`, …). ktranslate containers skipped (already teed) |
| gNMI | `{job="gnmic"}` — OTEL metric names often use `:` separators, e.g. `gnmi_bgp_neighbors_…:bgp_neighbor_session_state` |
| Topology devices | `network_topology_device_info{tester_id="network-lab"}` (OTLP may rename `device_id` → `device`) |
| Topology edges | `network_topology_edge_info{tester_id="network-lab"}` (gnmic LLDP → Alloy remap) |

Dashboards under [`grafana/dashboards/`](grafana/dashboards/) were authored for the **AWS** lab (`integrations/snmp`, gNMI). Many panels will be empty against the local ktranslate path until queries are retargeted. Folder in GC (if imported): **Network Lab** (`network-lab`).

Topology dashboards (adapted for this lab):

| UID | Title |
|-----|-------|
| `lab-topology-graph` | Network Topology (topology-exporter) |
| `lab-topology-health` | Topology Exporter Health |
| `lab-network-join-demo` | Network join demo (SIG model) — flows + LLDP subway + SNMP errors/CPU |

JSON payloads: `local/.dash-payloads/topology/`, `local/.dash-payloads/network-join-demo.json`. Skip `topology-schedule` (long-running mutator harness only).

**Join demo:** UID `lab-network-join-demo`, folder `network-lab`. Section **0** pairs Tempo `clos-join-demo` spans with softflowd flows on shared `$peer_addr`/`$peer_port` (default `172.17.0.2:8080`). Rebuild/import: `python3 local/scripts/build-network-join-demo.py` then `python3 local/scripts/import-network-join-demo-gcx.py` (or `import-network-join-demo.sh` with `GRAFANA_URL` + `GRAFANA_TOKEN`). After compose recreate, `make -C local softflowd` (collector IP drift).

**Clos join app (phase 2 traces):** minimal OTel Go HTTP client/server on EVPN clients — `make -C local join-app` (`local/join-app/`, `scripts/join-app.sh`). client1 `172.17.0.1` → client2 `172.17.0.2:8080` over the Clos; traces → Alloy `:4317` as `service.name=clos-join-demo` with `network.peer.*` / `server.address` for 5-tuple join vs softflowd (`network_peer_port="8080"`). Also exports `clos_join_entity_info` / `clos_join_edge_info` for the dashboard subway overlay (`runs_on` / `attached`). Stop: `make -C local join-app-stop`. Talk-track fault: `make -C local join-fault` / `join-fault-stop` (`scripts/join-fault.sh` — tc netem on client `eth1`); Investigation row on `lab-network-join-demo`. **Identity tabs:** parallel `entity_demo_*` datasets (`demo_model=hostname|hostname_poison|mac_alias|address|iface|edge_attrs|vrf`) prove/disprove OTel entity open questions — Q3: attrs-on-edge vs MAC-VRF as `network.vrf`.

**OTLP / Grafana Cloud:** copy `local/.env.example` → `local/.env` and set `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY` from your stack's OpenTelemetry connection. Optional `LAB_TESTER_ID` (default `network-lab`) labels topology and entity metrics. Merge helper: `python3 local/scripts/retarget-otlp-gc.py --write`. Restart Alloy after changing OTLP env: `docker compose … up -d --force-recreate alloy` (or `make up`).

## AWS / EKS path (unchanged)

See root [`README.md`](README.md) and `make post-03` … `post-06`. Uses Clabbernetes, Alloy SNMP exporter historically, gnmic, NetBox, Ansible. Do not mix those collector assumptions into `local/` work.

## Secrets — never commit

- `local/.env`, `local/groups/*.env`, `local/state/`, `local/config/`
- `k8s/telemetry/grafana-cloud-secret.yaml`, `grafana-cloud-api.token`, `grafana-cloud.instance`
- Terraform `*.tfvars`, AWS keys

## Grafana Cloud MCP

If the Grafana Cloud MCP server is available and authenticated, prefer it for Explore queries, dashboard import/patch, and deeplinks. Point MCP at **your** Grafana Cloud stack (the same one as `GRAFANA_URL` / `GC_OTLP_*` in `local/.env`).

## Blog / docs map

Series outline: [`blog/blog-series-overview.md`](blog/blog-series-overview.md). Local lab does not yet map 1:1 to every post (posts 3–6 assume K8s/NetBox/Ansible).

## Agent maintenance rule

When a session changes bring-up, topology, collectors, network names, or metric contracts, update:

1. This file (`AGENTS.md`)
2. Relevant `.cursor/rules/*.mdc`
3. [`local/README.md`](local/README.md) if operator-facing steps changed
