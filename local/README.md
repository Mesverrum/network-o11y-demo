# Local lab — WSL2 + ContainerLab + Docker Compose

Speakable Clos on a 16 GB laptop: **1 spine, 2 leaves, 2 clients**.

Collector stack follows the **[KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) golden path**:
credential groups under `groups/`, discovery/polling split, Alloy OTLP forwarder
with official netflow remapping, and `deployment.host` tagging. Clos extras
(gNMI incl. LLDP, topology exporter) sit alongside that pattern.

The AWS/EKS path under `../k8s/` and `../terraform/` is unchanged.

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

NetBox is optional (set `DISCOVERY_SOURCE=netbox` on a group + `NETBOX_*` in `.env`).

**Note:** Stock SR Linux SNMP does not export the IEEE LLDP rem-table (LLDP protocol is still enabled). Edges come from **gnmic** (`lldp_neighbors` subscribe), not SNMP topology-exporter.

## Prerequisites (WSL2 Ubuntu)

1. [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/) with the **WSL2 backend**, or Docker Engine inside WSL
2. [ContainerLab](https://containerlab.dev/install/) (`containerlab` or `clab`)
3. `yq` (Mike Farah) and `envsubst`: `sudo apt install yq gettext-base`
4. ~10–12 GB RAM available to Docker (three SR Linux `ixrd2l` nodes + collectors)
5. Grafana Cloud stack — OTLP credentials from **Connections → OpenTelemetry**

## First-time setup

```bash
cd local
cp .env.example .env
# Edit .env: set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY
# Optional: LAB_TESTER_ID=network-lab  (topology/entity label; else KTRANS_HOST or hostname)

cp groups/srl.env.sample groups/srl.env
make generate
sudo chown -R 1000:1000 config state   # discovery writes as uid 1000
```

## Bring-up

```bash
make check
make up          # clab → compose → snmp TARGETS → discover srl → softflowd → syslog
make status
make traffic     # ongoing UDP+ICMP workloads (steady/burst/reverse) client1↔client2
```

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
| `make snmp-targets` | Refresh `groups/srl.env` TARGETS after clab IP changes |
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

- Cap Docker Desktop memory around **10–12 GB** so Windows stays usable
- `make up` writes `compose-limits.generated.yaml` from host RAM (set `MEM_LIMITS=off` to skip)
- If nodes OOM, destroy the lab (`make down`) and close other heavy apps before `make up` again
- First pull of `ghcr.io/nokia/srlinux:24.10.1` is large (~1.3 GiB)

## Network name

Compose joins ContainerLab’s management bridge named `clab` (ContainerLab 0.72+). Override with `CLAB_NETWORK` in `.env` if `docker network ls` shows something else.

## Agent / LLM notes

Persistent guidance for coding agents lives in the repo root [`AGENTS.md`](../AGENTS.md) and [`.cursor/rules/`](../.cursor/rules/). Update those when local lab behavior changes.
