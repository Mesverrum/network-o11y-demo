# AGENTS.md — guidance for LLM coding agents

**New operator on any Grafana Cloud stack?** Start with [**Agent playbook**](#agent-playbook--run-the-local-lab-on-the-operators-stack) below.

Keep this file accurate as the lab evolves. When you change architecture, collectors, metric names, or bring-up steps, **update this file and `.cursor/rules/` in the same change**.

## What this repo is

Companion demo for the blog series **Network Observability Without the Lock-in**. Two deployment paths:

| Path | Location | Audience |
|------|----------|----------|
| **Local lab (preferred for laptops)** | [`local/`](local/) | Docker Desktop + ContainerLab + Compose (macOS or WSL2/Linux); 16 GB–friendly |
| **AWS / EKS** | [`terraform/`](terraform/), [`k8s/`](k8s/) | Full Clos on Clabbernetes; NetBox + Ansible stages |

Do **not** lift-and-shift the EKS/Clabbernetes stack onto a laptop. Local work belongs under `local/`. Leave AWS manifests alone unless the user explicitly asks for EKS changes.

## Agent playbook — run the local lab on the operator's stack

**Audience:** LLM coding agents helping a new teammate bring up `local/` on **their own** Grafana Cloud stack (macOS, WSL2, or native Linux). Follow this section before improvising.

### Read order

1. This section (playbook)
2. [`local/README.md`](local/README.md) — operator commands and platform notes
3. [`docs/network-observability-primer.md`](docs/network-observability-primer.md) — optional; networking/ktranslate context for the user

### Hard rules for agents

| Do | Do not |
|----|--------|
| Work under `local/` only | Port EKS/Clabbernetes networking into `local/` |
| Ask the user for **their** Grafana Cloud OTLP creds if `.env` is missing or placeholder | Assume `networko11ydev`, `marcnetterfield1`, or any stack baked into the repo |
| Run `make check` before `make up` | Commit `local/.env`, `local/groups/*.env`, `local/config/`, or `local/state/` |
| Use `make stabilize` when SRL nodes stop | Run `clab deploy --reconfigure` unless the user explicitly asks |
| Use `python3 local/scripts/retarget-otlp-gc.py --write` (env vars) on any OS | Rely on `retarget-otlp-networko11ydev.py` / `marcnetterfield1` on Mac (Windows CredMgr only) |

### Detect platform

```bash
uname -s          # Darwin = macOS, Linux = WSL or native
docker info       # must succeed before bring-up
```

| Platform | How agents run commands | Extra setup |
|----------|-------------------------|-------------|
| **macOS** | Native terminal in repo `local/` | `brew install containerlab yq gettext`; Docker Desktop **10–12 GB** RAM; disable Resource Saver during lab |
| **WSL2** | Bash in WSL (`cd .../local`) | `sudo apt install yq gettext-base`; `sudo chown -R 1000:1000 config state` after `make generate` |
| **Windows host only** | `wsl -e bash -lc 'cd /mnt/c/.../network-o11y-demo/local && <cmd>'` | Same as WSL2; repo on `/mnt/c` is OK — `clab.sh` mirrors fabric to ext4 automatically |
| **Native Linux** | Bash in `local/` | `chown` only if preflight warns about uid ≠ 1000 on `config/` / `state/` |

**Apple Silicon:** images are `linux/amd64`; first `make up` may take **~15 min** under emulation. This is expected.

### Credentials — ask the user if any are missing

The operator must supply values from **their** Grafana Cloud stack:

- **Grafana Cloud → Connections → OpenTelemetry** → OTLP endpoint URL, instance ID, access policy token
- Map to `local/.env`:
  - `GC_OTLP_URL` — e.g. `https://otlp-gateway-prod-<region>.grafana.net/otlp`
  - `GC_OTLP_ACCOUNT` — stack instance / OTLP account id (numeric)
  - `GC_OTLP_KEY` — `glc_…` token (metrics:write, logs:write, traces:write)

Optional:

- `LAB_TESTER_ID` — label for topology/entity metrics (default `network-lab`; set to operator name on shared stacks)
- `KTRANS_HOST` — overrides hostname tag on all telemetry (else auto from machine hostname)

**Merge helper (any OS):**

```bash
export GRAFANA_URL=https://<stack>.grafana.net
export GC_OTLP_URL=... GC_OTLP_ACCOUNT=... GC_OTLP_KEY=...
python3 local/scripts/retarget-otlp-gc.py --write
```

Restart Alloy after OTLP changes: `docker compose -f local/compose-base.yaml … up -d --force-recreate alloy` or `make -C local up`.

### First-time bring-up (exact sequence)

```bash
cd local
cp .env.example .env
cp groups/srl.env.sample groups/srl.env
# Edit .env: GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY (and optional LAB_TESTER_ID)

make generate
# Linux/WSL only, if preflight warns:
# sudo chown -R 1000:1000 config state

make check          # must pass (docker, containerlab, yq, envsubst, non-placeholder .env)
make up             # staggered ~10 min (default LAB_STAGGER_SECS=25)
make status
make traffic        # client1↔client2 UDP/ICMP workloads
```

From repo root: `make local-up` ≡ `make -C local up`.

**What `make up` does:** deploy ContainerLab fabric (spine1 → leaf1 → leaf2 → client1 → client2 with settle pauses) → start collectors one-by-one (`alloy`, `ktranslate_snmp_srl`, `ktranslate_flow`, `ktranslate_sflow`, `ktranslate_syslog`, `gnmic`, `topology_exporter`) → refresh SNMP targets → `make discover GROUP=srl` → softflowd, syslog, sFlow, traps.

**Parallel / faster (less safe on 16 GB):** `make up-parallel` or `LAB_STAGGER=0 make up`.

### Success criteria (verify in the operator's Grafana Cloud)

Use Grafana Explore → Prometheus (or Grafana Cloud MCP if authenticated to **their** stack).

```promql
count by (device_name, service_name) (kentik_snmp_DeviceMetrics)
```

Expect **three** devices: `spine1`, `leaf1`, `leaf2`.

```promql
sum by (device_name) (rate(network_io_by_flow[5m]))
```

```promql
count by (device_id) (network_topology_device_info{tester_id="<LAB_TESTER_ID or network-lab>"})
```

**Local sanity checks:**

```bash
make -C local status
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'spine|leaf|client|ktranslate|alloy|gnmic|topology'
```

Expect **12** running containers (5 fabric + 7 collectors) when healthy.

### Troubleshooting (agent decision tree)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make check` fails on placeholders | `.env` not customized | User must paste OTLP creds |
| `make check` fails containerlab | Not installed | macOS: `brew install containerlab`; Linux: [containerlab.dev/install](https://containerlab.dev/install/) |
| `compute-limits.sh` / memory error | Unusual host RAM detection | Set `MEM_LIMITS=off` in `.env`, re-run `make up` |
| SRL container **exit 143** | SIGTERM (sleep, `make down`, `clab --reconfigure`, Docker Desktop stop) — **not OOM** | `make -C local stabilize`; never `clab deploy --reconfigure` |
| BGP/EVPN/SNMP missing after deploy on `/mnt/c` | drvfs postdeploy failure | `make -C local fabric-apply` or `make stabilize` (ext4 mirror via `clab.sh`) |
| `leaf1` stuck / yang reload | Fabric boot race | Wait; or `docker restart leaf1` then `make stabilize` |
| No flows in Grafana | softflowd not pointed at collector | `make -C local softflowd` (especially after compose recreate) |
| No metrics at all | OTLP misconfig or Alloy down | Check `docker logs alloy --tail 50`; verify `GC_OTLP_*`; recreate alloy |
| Discovery permission error | `config/` / `state/` ownership | `sudo chown -R 1000:1000 config state` (Linux/WSL) |
| GHCR pull denied (topology_exporter) | Image auth | `make -C local topology-exporter-image` |

**Recovery command of first resort:** `make -C local stabilize` (starts stopped SRL nodes, applies fabric, discover, sidecar configs — no full clab redeploy).

### Optional next steps (only if user asks)

| Goal | Command |
|------|---------|
| App↔network join demo traces | `make -C local join-app` |
| Latency fault talk-track | `make -C local join-fault` / `join-fault-stop` |
| Synthetic traps + link flaps | `make -C local events-loop` |
| Import join dashboard | `python3 local/scripts/build-network-join-demo.py` then import script with user's `GRAFANA_URL` + token |
| NetBox-driven discovery | `cp groups/srl.env.netbox.sample groups/srl.env`, set `NETBOX_*` in `.env`, `make netbox-sync && make up` |

### Grafana Cloud MCP

If MCP is available, authenticate to the **operator's** stack (same as `GRAFANA_URL` / `GC_OTLP_*`). Use it to run verification PromQL and generate Explore deeplinks — do not assume a specific stack name in docs or queries.

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

### Bring-up (macOS or WSL/Linux)

```bash
cd local
cp .env.example .env          # set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY
cp groups/srl.env.sample groups/srl.env
make generate
# Linux/WSL only: sudo chown -R 1000:1000 config state
make up
make traffic
```

**macOS:** `brew install containerlab yq gettext`; Docker Desktop **10–12 GB** RAM.
Set OTLP creds in `.env` or `python3 scripts/retarget-otlp-gc.py --write`. Apple Silicon
uses amd64 emulation — slower but supported. See `local/README.md` → macOS quick reference.

**WSL (Windows):** path via `/mnt/c/Users/<you>/projects/network-o11y-demo/local` is fine;
`clab.sh` mirrors fabric to ext4 when on drvfs.

`make up` **staggers** fabric sr_cli readiness and collectors with `LAB_STAGGER_SECS`
(default 25) pauses. Use `make up-parallel` or `LAB_STAGGER=0` to disable.
`make stabilize` honors `LAB_STAGGER` for collector bring-up.

Optional NetBox Cloud discovery: `cp groups/srl.env.netbox.sample groups/srl.env`, set `NETBOX_*` in `.env`, then `make generate && make netbox-sync && make up`.

From repo root: `make local-up` / `make local-down` / `make local-help`.

Agents on Windows may run the same via `wsl -e bash -lc 'cd ... && make up'`.

### Operational gotchas

1. **ContainerLab mgmt network is `clab`** (v0.72+ shared bridge), not `srl-local`. Set `CLAB_NETWORK=clab` in `.env`.
2. **Shell scripts must be LF** (CRLF breaks `set -o pipefail`). `.gitattributes` forces LF under `local/`.
3. **Alloy comments are `//`**, not `#`.
4. **`state/devices-*.yaml` is mutable** (discovery writes device lists); never commit `config/` / `state/` / `groups/*.env`. UID 1000 must own `config/` and `state/`.
5. **Syslog / SNMP traps:** pipe into `sr_cli` via `docker exec -i` (non-interactive); see `local/scripts/syslog-config.sh` and `snmp-trap-config.sh`. Both must use **mgmt** (`system logging network-instance mgmt`, trap-group `network-instance mgmt`) or packets never leave the box. Traps → poller `:1620`. One-shot: `make -C local emit-events`. Periodic: `make -C local events-loop` (synthetic traps ~3m, real flaps ~5m; `events-stop` / `events-status`).
6. **`/mnt/c` + ContainerLab postdeploy:** drvfs breaks SR Linux `config.tmp` commits when clab labdir/startup-config bind-mounts live on `/mnt/c`. `make up` / `make fabric-up` / `make stabilize` auto-mirror `topology.clab.yml` + `configs/fabric/` to ext4 (`CLAB_EXT4_ROOT`, default `~/.cache/network-o11y-demo/clab`) via `scripts/clab.sh`. `make fabric-apply` re-applies configs (defaults to `FULL_FABRIC=1` on ext4 workdir). Compose/o11y can stay on `/mnt/c`. **Do not** run `clab deploy --reconfigure` unless the user explicitly asks — it SIGTERM-stops all lab containers (exit 143), which looks like a crash but is not OOM.
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
| `lab-ktranslate-flow` | Network Flow Summary (ktranslate) — `network_io_by_flow_bytes` from softflowd + spine sFlow |
| `lab-network-join-demo` | Network join demo (SIG model) — flows + LLDP subway + SNMP errors/CPU |

JSON payloads: `local/.dash-payloads/topology/`, `local/.dash-payloads/network-join-demo.json`, `local/.dash-payloads/ktranslate-import/lab-ktranslate-flow.json`. Skip `topology-schedule` (long-running mutator harness only).

**Flow dashboard:** UID `lab-ktranslate-flow`, folder `network-lab`. Adapted from the ktranslate **02. Network Flow Summary** pattern (Commvault/marcnetterfield1). Rebuild/import: `python3 local/scripts/build-ktranslate-flow-dashboard.py` then `python3 local/scripts/import-ktranslate-flow-dashboard.py` (prefers `gcx --context networko11ydev`). Source export: `gcx --context commvault dashboards get be8hpir89dds0a`.

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
