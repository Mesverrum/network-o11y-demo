# Local lab — Docker + ContainerLab + Compose (laptop)

Speakable Clos on a 16 GB laptop: **1 spine, 2 leaves, 2 clients**. Runs on
**macOS** (Docker Desktop) or **Linux** (WSL2 / native).

Collector stack follows the **[KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) golden path**:
credential groups under `groups/`, discovery/polling split, Alloy OTLP forwarder
with official netflow remapping, and `deployment.host` tagging. Clos extras
(gNMI incl. LLDP, topology exporter) sit alongside that pattern.

The AWS/EKS path under `../k8s/` and `../terraform/` is unchanged.

**New to networking or ktranslate?** See **[docs/network-observability-primer.md](../docs/network-observability-primer.md)** — terminology, telemetry types, pain points, and how this stack maps to Grafana Cloud.

## Talk-track topology

```
        spine1 (AS 201)
         /         \
     leaf1         leaf2
    (AS 101)      (AS 102)
       |             |
    client1       client2
   172.17.0.1    172.17.0.2
```

| Stream | Path |
|--------|------|
| SNMP | SR Linux → `ktranslate_snmp_srl` → Alloy → Grafana Cloud (`kentik_snmp_*`) |
| NetFlow | softflowd on clients → `ktranslate_flow` → Alloy → GC (`network_io_by_flow`) |
| Syslog | SR Linux → `ktranslate_syslog` → Alloy → GC |
| gNMI | SR Linux → `gnmic` (OTLP) → Alloy → GC (`gnmi_*`, `job="gnmic"`) |
| Topology devices | SR Linux SNMP → `topology_exporter` (OTLP) → Alloy → GC (`network_topology_device_info`) |
| Topology edges | SR Linux LLDP via **gnmic** YANG → Alloy remap → GC (`network_topology_edge_info`) |

NetBox Cloud is **optional** for inventory-driven discovery (`groups/srl.env.netbox.sample`). Default bring-up uses **CIDR** targets from ContainerLab mgmt IPs (`groups/srl.env.sample`). See [`local/netbox/README.md`](local/netbox/README.md).

**Note:** Stock SR Linux SNMP does not export the IEEE LLDP rem-table (LLDP protocol is still enabled). Edges come from **gnmic** (`lldp_neighbors` subscribe), not SNMP topology-exporter.

## Prerequisites

| | **macOS** | **WSL2 / Linux** |
|---|-----------|------------------|
| Docker | [Docker Desktop](https://docs.docker.com/desktop/setup/install/mac-install/) — allocate **10–12 GB** RAM in Settings → Resources | [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) (WSL2 backend) or Docker Engine in WSL |
| ContainerLab | `brew install containerlab` ([install docs](https://containerlab.dev/install/)) | [ContainerLab](https://containerlab.dev/install/) (`containerlab` or `clab`) |
| CLI tools | `brew install yq gettext` (`envsubst` from gettext) | `sudo apt install yq gettext-base` |
| Grafana Cloud | OTLP credentials from **Connections → OpenTelemetry** (`GC_OTLP_URL`, account, key) | same |

**Apple Silicon (M1/M2/M3):** SR Linux and several images are `linux/amd64`. Docker runs them under emulation — expect slower first boot and longer `make up` (~15 min). A 16 GB Mac with 10+ GB for Docker is recommended.

**Windows + WSL only:** if the repo lives on `/mnt/c/...`, see [WSL `/mnt/c` and fabric config](#wsl-mntc-and-fabric-config) below. macOS and native Linux clones use the repo directory directly (no ext4 mirror needed).

## First-time setup (all platforms)

```bash
cd local
cp .env.example .env
# Edit .env: set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY
# Optional: LAB_TESTER_ID=network-lab  (topology/entity label; else KTRANS_HOST or hostname)

cp groups/srl.env.sample groups/srl.env
make generate
```

**Linux / WSL only** (discovery writes as uid 1000):

```bash
sudo chown -R 1000:1000 config state
```

On macOS, `chown` is usually not required unless discovery fails with permission errors on `config/` or `state/`.

## Bring-up

```bash
make check
make up          # staggered: spine→leaves→clients→collectors (25s pauses)
make status
make traffic     # ongoing UDP+ICMP workloads (steady/burst/reverse) client1↔client2
```

`make up` (default) staggers fabric nodes and telemetry collectors with
`LAB_STAGGER_SECS` pauses and logs host RAM between steps — tuned from
the Jul 2026 stability ladder. Use `make up-parallel` or `LAB_STAGGER=0` for
the old all-at-once path. Expect **~10 minutes** for a cold `make up`.

`make up` prints `deployment.host`, starts the stack, rewrites `groups/srl.env`
TARGETS from ContainerLab mgmt `/32`s, then runs `make discover GROUP=srl`.

Tear down:

```bash
make down
```

## Verify in Grafana Cloud

Explore → Prometheus:

```promql
count by (device_name, service_name) (kentik_snmp_DeviceMetrics)
```

```promql
topk(20, network_io_by_flow_bytes)
```

**Network join demo dashboard** (SIG UX: conversations + Clos LLDP subway + packet-relevant SNMP): UID `lab-network-join-demo` in folder `network-lab`. Payload: `.dash-payloads/network-join-demo.json`. Import: `python3 scripts/build-network-join-demo.py` then `python3 scripts/import-network-join-demo-gcx.py` (set `GCX_BIN` + `GCX_CONTEXT`, or `GRAFANA_URL` + `GRAFANA_TOKEN` in `.env` and use `scripts/import-network-join-demo.sh`). OTLP: set `GC_OTLP_*` in `.env` (helper: `python3 scripts/retarget-otlp-gc.py --write`). If flows vanish after recreate: `make softflowd`. **Identity tab** (`demo_model` variable): parallel `entity_demo_*` datasets for hostname / poison / mac_alias / address / iface / edge_attrs / vrf.

**Flow dashboard** (ktranslate NetFlow/sFlow): UID `lab-ktranslate-flow` in folder `network-lab`. Panels use `network_io_by_flow_bytes` with exporter/src/dst/protocol variables (same layout as marcnetterfield1 **02. Network Flow Summary**). Rebuild/import: `python3 scripts/build-ktranslate-flow-dashboard.py` then `python3 scripts/import-ktranslate-flow-dashboard.py` (`gcx --context networko11ydev` preferred).

**Clos join app (app↔network):** `make join-app` deploys a tiny OTel Go HTTP client on `client1` and server on `client2` (`172.17.0.1`→`172.17.0.2:8080` over EVPN). Traces land in Tempo as `service.name=clos-join-demo` with `network.peer.*` / `server.address` join keys; softflowd should show `network_peer_port="8080"`. Source: `join-app/`. Stop: `make join-app-stop`. Talk track: dashboard **Investigation** row → `make join-fault` (netem 200 ms/1 % on client `eth1`) → watch app p95 climb → `make join-fault-stop`.

```promql
count by (device_id) (network_topology_device_info{tester_id="network-lab"})
```

```promql
count by (src_device, dst_device) (network_topology_edge_info{tester_id="network-lab"})
```

Syslog/logs appear under the OTLP → Loki path for `service.name=ktranslate-syslog` (plus `-<host>` when `KTRANS_HOST` is set).

First-time topology exporter image (if GHCR pull is unauthorized):

```bash
make topology-exporter-image
```

## Useful targets

| Target | Purpose |
|--------|---------|
| `make generate` | Render `config/*` + `compose-groups.generated.yaml` from `groups/*.env` |
| `make discover GROUP=srl` | One-shot SNMP discovery → `state/devices-srl.yaml` + poller reload |
| `make host` | Print resolved `deployment.host` |
| `make logs` | Tail Alloy + ktranslate |
| `make snmp-targets` | Refresh `groups/srl.env` TARGETS (cidr discovery only) |
| `make netbox-populate` | Seed NetBox Cloud with local lab topology |
| `make netbox-sync-mgmt` | Refresh NetBox spine/leaf mgmt IPs from clab (NetBox mode only) |
| `make netbox-sync` | Populate + mgmt sync — optional; see `local/netbox/README.md` |
| `make fabric-up` | Deploy SRL fabric only (ext4 workdir on `/mnt/c`; no collectors) |
| `make fabric-apply` | (Re)apply `configs/fabric/*.cfg` after edits or failed postdeploy |
| `make sync-clab-workdir` | Mirror topology + fabric configs to ext4 when repo is on `/mnt/c` |
| `make stabilize` | Recover without `clab --reconfigure`: start SRL, fabric, discover |
| `make topology-targets` | Refresh topology-exporter SNMP hosts after clab IP changes |
| `make topology-exporter-image` | Build local exporter image from GitHub release binary |
| `make softflowd` / `make syslog` | Re-apply client/device helpers |
| `make join-app` / `join-app-stop` | OTel HTTP client↔server on EVPN clients (trace↔flow join) |
| `make join-fault` / `join-fault-stop` | tc netem delay/loss on client eth1 (join demo talk track) |
| `make snmp-traps-config` | Point SRL SNMP traps at `ktranslate_snmp_srl:1620` |
| `make emit-events` | One-shot: configure syslog+traps, flap links for real device events |
| `make events-loop` / `events-stop` / `events-status` | Background: synthetic traps every 3m + real flaps every 5m |
| `make traffic` / `traffic-stop` / `traffic-status` | ongoing UDP iperf (steady+burst+reverse) + ICMP |
| `make traps` / `traps-burst` / `traps-loop` | Synthetic SNMPv2c traps → poller `:1620` (`public`; foreground loop default 3m) |

## Golden path notes (vs older monolith)

- **No more** root `snmp.yaml` + `--snmp_discovery_on_start`. Discovery is a one-shot
  `discover_srl` profile; the long-running poller mounts `config/poller-srl.yaml`
  read-only and `@`-includes `state/devices-srl.yaml`.
- Flow rollups + Alloy preprocess match the official Grafana Cloud
  **ktranslate-netflow** integration (`network_io_by_flow` + OTEL semconv labels).
- Add another credential group by copying `groups/srl.env.sample` →
  `groups/<name>.env`, assigning unique ports, then `make generate && make up && make discover GROUP=<name>`.

Upstream docs: [KtransToGrafana README](https://github.com/Mesverrum/KtransToGrafana) ·
[configuration](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/configuration.md) ·
[architecture](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/architecture.md) ·
[operations](https://github.com/Mesverrum/KtransToGrafana/blob/main/docs/operations.md).

## Memory tips

- Give Docker **10–12 GB** RAM (Docker Desktop → Settings → Resources on Mac/Windows)
- `make up` writes `compose-limits.generated.yaml` from host/Docker RAM (`scripts/compute-limits.sh` supports Linux, macOS, and Docker Desktop)
- Set `MEM_LIMITS=off` in `.env` if limit generation fails on an unusual host
- If nodes OOM, run `make down`, free RAM, then `make up` again
- First pull of `ghcr.io/nokia/srlinux:24.10.1` is large (~1.3 GiB)

## macOS quick reference

```bash
# One-time
brew install containerlab yq gettext
# Docker Desktop: 10–12 GB RAM, disable aggressive "Resource Saver" while lab runs

cd local && cp .env.example .env && cp groups/srl.env.sample groups/srl.env
# Set GC_OTLP_* in .env (paste from Grafana Cloud → OpenTelemetry)
make check && make generate && make up
make status && make traffic
```

**Credentials:** set `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, and `GC_OTLP_KEY` directly in
`.env` (Grafana Cloud → **Connections → OpenTelemetry**). Or export them and run
`python3 scripts/retarget-otlp-gc.py --write`. Stack-specific helpers
(`retarget-otlp-networko11ydev.py`, etc.) use Windows Credential Manager only.

**Recovery:** `make stabilize` (no `clab deploy --reconfigure` — that SIGTERM-stops
all nodes). `make fabric-watch` keeps SRL containers up if Docker restarts.

## WSL `/mnt/c` and fabric config

When the repo lives under `/mnt/c/Users/...`, ContainerLab **postdeploy cannot commit**
SR Linux startup config (`config.tmp` permission error on drvfs).

**Automatic fix:** `make up`, `make fabric-up`, and `make stabilize` detect drvfs and
mirror `topology.clab.yml` + `configs/fabric/` to native ext4 (default
`~/.cache/network-o11y-demo/clab`) before `clab deploy`. Postdeploy can then commit
full BGP/EVPN startup config. Override with `CLAB_EXT4_ROOT` in `.env`.

```bash
make sync-clab-workdir   # preview ext4 mirror path
make fabric-up           # fabric only (no collectors / NetBox)
make fabric-apply        # re-apply after editing configs/fabric/*.cfg
make stabilize           # full recovery without clab --reconfigure
```

If you still see missing BGP/EVPN after deploy, run `FULL_FABRIC=1 make fabric-apply`.
**Avoid** `clab deploy --reconfigure` unless you intend to reset the whole lab — it
SIGTERM-stops all nodes (exit code 143), which is not OOM. For editors/IDEs tied to
Windows paths, you can keep the repo on `/mnt/c`; only clab’s deploy workdir moves to ext4.
Alternatively, clone the whole repo to `~/projects/network-o11y-demo` on ext4.

**Keeping fabric alive:** SRL nodes sometimes receive SIGTERM (exit 143) from Docker/WSL
(e.g. Docker Desktop resource saver, disk pressure on `C:`). Use the background watchdog:

```bash
make fabric-watch          # poll every 60s, auto fabric-stabilize
make fabric-watch-status
make fabric-stabilize      # one-shot recovery without collectors
```

`make fabric-up` starts `fabric-watch` automatically. In Docker Desktop, disable
**Resource Saver** and avoid stopping the engine while the lab should run.

## Network name

Compose joins ContainerLab’s management bridge named `clab` (ContainerLab 0.72+). Override with `CLAB_NETWORK` in `.env` if `docker network ls` shows something else.

## Agent / LLM notes

Persistent guidance for coding agents lives in the repo root [`AGENTS.md`](../AGENTS.md) and [`.cursor/rules/`](../.cursor/rules/). Update those when local lab behavior changes.
