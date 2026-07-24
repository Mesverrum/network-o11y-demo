# AGENTS.md — guidance for LLM coding agents

**New operator on any Grafana Cloud stack?** Start with [**Agent playbook**](#agent-playbook--run-the-local-lab-on-the-operators-stack) below.

Keep this file accurate as the lab evolves. When you change architecture, collectors, metric names, or bring-up steps, **update this file and `.cursor/rules/` in the same change**.

## What this repo is

Companion demo for the blog series **Network Observability Without the Lock-in**. One **ktranslate-centric telemetry model** runs on every platform — see [`docs/ktranslate-unified-model.md`](docs/ktranslate-unified-model.md).

| Where it runs | How you start it |
|---------------|------------------|
| **Laptop** (macOS / Windows / Linux) | [`local/`](local/) + [`oneclick/`](oneclick/) — ContainerLab + Compose |
| **AWS / EKS** | [`terraform/`](terraform/) + [`k8s/`](k8s/) — same ktranslate roles as Kubernetes Deployments |

Do **not** lift-and-shift the EKS/Clabbernetes **networking** stack onto a laptop. Local work belongs under `local/`. Alloy is the OTLP sink on all paths; **SNMP, flow, sFlow, and syslog are always ktranslate**, not Alloy-native collectors.

## Agent playbook — run the local lab on the operator's stack

**Audience:** LLM coding agents helping a new teammate bring up `local/` on **their own** Grafana Cloud stack (macOS, WSL2, or native Linux). Follow this section before improvising.

### Read order

1. This section (playbook)
2. [`docs/ktranslate-unified-model.md`](docs/ktranslate-unified-model.md) — one collector model (ktranslate + Alloy + gnmic)
3. [`local/README.md`](local/README.md) — operator commands and platform notes
4. [`docs/network-observability-primer.md`](docs/network-observability-primer.md) — optional; networking context

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
| **macOS** | **Inside an OrbStack Linux VM** — ContainerLab has no macOS binary, so run the whole lab in a VM (`orb -m ubuntu ...`). See [`docs/macos-orbstack-setup.md`](docs/macos-orbstack-setup.md). | `brew install --cask orbstack`; in the VM install `docker.io docker-compose-v2 make gettext-base`, ContainerLab via get.containerlab.dev, mikefarah `yq`; give the VM **10–12 GB** RAM; clone to the VM's native disk (not `/Users`); run discovery as **`sudo make discover GROUP=srl`** (VM user is uid 501, ktranslate expects uid 1000) |
| **WSL2 (Windows)** | Bash in WSL on a **native ext4 clone** (`~/projects/network-o11y-demo/local`) — **not** `/mnt/c/...` | `sudo apt install yq gettext-base`; `sudo chown -R 1000:1000 config state` after `make generate`. From Cursor on Windows, run commands via `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && …'` or use `.\oneclick\deploy.ps1` |
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

**What `make up` does:** deploy ContainerLab fabric (spine1 → leaf1 → leaf2 → client1 → client2 with settle pauses) → start collectors one-by-one (`alloy`, `ktranslate_snmp_srl`, `ktranslate_flow`, `ktranslate_sflow`, `ktranslate_syslog`, `gnmic`) → refresh SNMP targets → `make discover GROUP=srl` → softflowd, syslog, sFlow, traps → **mgmt API catalog** OTLP export (`make mgmt-api-mock`). Optional: `topology_exporter` via `LAB_TOPOLOGY_EXPORTER=1` + `make topology-up`.

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
count by (device_id) (network_topology_edge_info{tester_id="<LAB_TESTER_ID or network-lab>"})
```

(Device nodes via optional `network_topology_device_info` need `LAB_TOPOLOGY_EXPORTER=1` + `make topology-up`.)

**Local sanity checks:**

```bash
make -C local status
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'spine|leaf|client|ktranslate|alloy|gnmic'
```

Expect **11** running containers (5 fabric + 6 collectors) when healthy. With optional `topology_exporter`: **12**.

### Troubleshooting (agent decision tree)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make check` fails on placeholders | `.env` not customized | User must paste OTLP creds |
| `Permission denied` on `./scripts/*.sh` | Git does not mark shell scripts executable on fresh clone | Fixed in repo: Makefile/scripts invoke `bash scripts/...`. Pull latest `main`. |
| `make check` fails containerlab | Not installed | macOS: `brew install containerlab`; Linux: [containerlab.dev/install](https://containerlab.dev/install/) |
| `compute-limits.sh` / memory error | Unusual host RAM detection | Set `MEM_LIMITS=off` in `.env`, re-run `make up` |
| SRL container **exit 143** | SIGTERM (sleep, `make down`, `clab --reconfigure`, Docker Desktop stop) — **not OOM** | `make -C local stabilize`; never `clab deploy --reconfigure` |
| BGP/EVPN/SNMP missing after deploy | Fabric config not applied or postdeploy race | `make -C local fabric-apply` or `make stabilize`; confirm repo is on **WSL ext4**, not `/mnt/c` |
| `leaf1` stuck / yang reload | Fabric boot race | Wait; or `docker restart leaf1` then `make stabilize` |
| No flows in Grafana | softflowd not pointed at collector | `make -C local softflowd` (especially after compose recreate) |
| No metrics at all | OTLP misconfig or Alloy down | Check `docker logs alloy --tail 50`; verify `GC_OTLP_*`; recreate alloy |
| SRL containers up, **no SNMP in Grafana** | SNMP agent not listening (not OTLP) | See **SNMP diagnosis** below — usually `network-instance mgmt` missing or `ag1` has no `community-entry` |
| ktranslate SNMP `connection refused` on :161 | Same as above | `bash scripts/enable-snmp-srl.sh`; verify `oper-state up` on `system snmp network-instance mgmt` |
| `FULL_FABRIC=1` / broken `apply-fabric-node` | Can wedge `net_inst_mgr` or wipe mgmt NI | **Do not** set unless user asks; prefer `make fabric-apply` (SNMP-only path) or `make down && make up` |
| Discovery permission error | `config/` / `state/` ownership | `sudo chown -R 1000:1000 config state` (Linux/WSL) |
| GHCR pull denied (topology_exporter) | Image auth | `LAB_TOPOLOGY_EXPORTER=1` + `make -C local topology-exporter-image` + `make topology-up` |

**Recovery command of first resort:** `make -C local stabilize` (starts stopped SRL nodes, applies fabric, discover, sidecar configs — no full clab redeploy).

### SNMP diagnosis (SRL up but empty Grafana)

**Symptom:** devices look healthy in `docker ps`, but Explore has no `kentik_snmp_*` and ktranslate logs show `recvfrom: connection refused` on UDP 161.

**Check locally first** (do not assume OTLP/stack misconfig until SNMP works):

```bash
# From WSL — community public matches groups/srl.env
snmpget -v2c -c public -t 2 172.20.20.2:161 1.3.6.1.2.1.1.5.0   # spine1

docker exec spine1 sr_cli -ec 'info from state system snmp network-instance mgmt' | grep oper-state
# expect: oper-state up

docker logs srl-local-telemetry-ktranslate_snmp_srl-1 --tail 20
```

| `oper-state` / symptom | Cause | Fix |
|------------------------|-------|-----|
| `down`, empty `error-msg` | `ag1` missing `community-entry ce1 community public` | `bash scripts/enable-snmp-srl.sh` (deletes clab `SNMPv2-RO-Community`, sets `ag1`/public) |
| grpc/snmp: `Network instance 'mgmt' does not exist` | `network-instance mgmt` wiped (often after `FULL_FABRIC=1`) | `bash scripts/restore-mgmt-ni.sh` then `enable-snmp-srl.sh`; if still wedged: `make down && make up` |
| `yang reload` / commit failures | Fabric boot race or partial apply | Wait; `docker restart <node>`; then `make stabilize` |

**Fabric contract:** `configs/fabric/*.cfg` must include **`network-instance mgmt`** (type `ip-vrf`, `mgmt0.0`, linux protocol) and **`system snmp access-group ag1 community-entry ce1 community public`**. `make fabric-apply` (default) pipes only SNMP via `enable-snmp-srl.sh`; full flat config requires `FULL_FABRIC=1` and is risky on a running lab.

**Verify in the operator's stack** (after SNMP polls for ~1–2 min):

```promql
count by (device_name, service_name) (kentik_snmp_DeviceMetrics)
```

### Agents on Windows (Cursor host)

| Do | Do not |
|----|--------|
| Run lab commands via `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && …'` | Inline bash `for` loops / `$var` in the **outer** PowerShell string — `$n`, `$ip` get eaten |
| Use repo scripts: `bash scripts/enable-snmp-srl.sh` | Long one-liners with nested quoting through `wsl -e bash -lc "…"` |
| Sync edits to the WSL clone when changing files on `C:\…` | Assume `~/network-o11y-demo` picked up Windows-side edits automatically |
| Strip CRLF before running new shell scripts: `sed -i 's/\r$//' scripts/foo.sh` | Run freshly written `.sh` from Windows without LF check (`set: pipefail\r: invalid option`) |
| Confirm `GC_OTLP_URL` / account in `local/.env` match the stack the user asked about | Assume Grafana Cloud MCP is on the same stack as the lab (MCP may be a different org) |

**WSL clone sync** (after editing on Windows):

```bash
cp -r /mnt/c/Users/<you>/projects/network-o11y-demo/local/configs/fabric ~/network-o11y-demo/local/configs/
cp /mnt/c/Users/<you>/projects/network-o11y-demo/local/scripts/*.sh ~/network-o11y-demo/local/scripts/
```

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

### Grafana dashboard updates — preserve `TabsLayout` (v2 manifest path)

**Audience:** agents patching or importing ktranslate / Network O11y dashboards on Grafana Cloud.

Grafana **v2** dashboards (generation ≥ 2, `spec.layout.kind: TabsLayout`) store tabs in the **App Platform manifest**, not in classic `dashboard.panels` JSON. Updating them through the **legacy** API **flattens tabs into one long scroll** — we hit this on Commvault Device Details (restored from version history).

| Path | Safe for tabbed v2 dashboards? | When to use |
|------|-------------------------------|-------------|
| `gcx dashboards get` → edit manifest → `gcx dashboards update` | **Yes** | Any patch on `mavgvqv`, `magz6qw1`, or other `TabsLayout` boards |
| `POST /api/dashboards/db` with `{ "dashboard": { ...panels... } }` | **No** on v2 tabbed boards | One-shot **first import** of classic JSON only; never re-save tabbed dashboards this way |
| `local/scripts/patch-iface-bps-60s.py` (legacy HTTP) | **No** on tabbed boards | Avoid; kept for `rewrite_expr()` helper only |
| `local/scripts/audit-commvault-bps.py` | **No** | Deprecated — strips `TabsLayout` |

**Canonical workflow (gcx + v2 manifest):**

```bash
# 1) Read full manifest (note layout.kind)
gcx --context <stack> --agent dashboards get <uid> -o json > /tmp/dash.json

# 2) Patch spec.elements[*].spec (queries, descriptions, etc.) — not top-level panels[]
#    Example: interface bps — rate(kentik_snmp_ifHC*Octets[$__rate_interval])*8
#             → (kentik_snmp_ifHC*Octets{...}) * 8 / 60  (ktranslate delta gauges, 60s poll)

# 3) Write back via v2 update
gcx --context <stack> --agent dashboards update <uid> -f /tmp/dash.json

# 4) Verify layout survived
gcx --context <stack> --agent dashboards get <uid> -o json \
  | jq '.spec.layout.kind'    # expect "TabsLayout" when started as TabsLayout
```

**Fleet helper (interface BPS on kentik SNMP):**

```bash
# Dry-run scan (discovers ktranslate/network-lab dashboards on the stack)
python3 local/scripts/patch-iface-bps-fleet.py <gcx-context> --dry-run

# Patch explicit UIDs (live)
python3 local/scripts/patch-iface-bps-fleet.py networko11ydev mavgvqv magz6qw1
python3 local/scripts/patch-iface-bps-fleet.py marcnetterfield1 mavgvqv net-o11y-traffic-sankey
```

Reports: `local/.dash-payloads/bps-v2-patch-report-<context>.json`. Shared query rewrite: `rewrite_expr()` in `local/scripts/patch-iface-bps-60s.py`.

**Post-patch checklist:**

1. `spec.layout.kind` unchanged (`TabsLayout` vs `RowsLayout` / `GridLayout`).
2. `metadata.generation` incremented (update actually landed).
3. UI spot-check: e.g. **01. Network Device Details** still shows all tabs (Interfaces, BGP, …), not one flattened page.
4. For BPS panels: no remaining `rate(kentik_snmp_ifHCInOctets` / `ifHCOutOctets` in the manifest.

**If tabs were already flattened:** restore a pre-patch dashboard **version** in Grafana UI (Dashboard settings → Versions), then re-apply patches with the v2 path above.

**MCP note:** prefer read-only MCP (`get_dashboard_summary`, PromQL) for verification. For writes on tabbed v2 dashboards, use **gcx v2** until you have confirmed your MCP `patch_dashboard` / `update_dashboard` path preserves `TabsLayout` (legacy-shaped payloads are unsafe).

## Local lab (current phase)

- **Topology:** 1 spine (`spine1`) + 2 leaves (`leaf1`, `leaf2`) + 2 clients (`client1`, `client2`); all SR Linux `ixrd2l`
- **Talk track:** eBGP underlay + EVPN MAC-VRF; clients `172.17.0.1` / `172.17.0.2`
- **Collectors:** `ktranslate_snmp_srl` (golden-path poller), `ktranslate_flow`, `ktranslate_syslog`, **`gnmic`** (incl. LLDP neighbors). Optional: **`topology_exporter`** (`LAB_TOPOLOGY_EXPORTER=1`, `make topology-up`)
- **NetBox Cloud (optional):** `scripts/netbox-populate.py` + `update-netbox-mgmt-ips.py` when `DISCOVERY_SOURCE=netbox` in `groups/srl.env` (`groups/srl.env.netbox.sample`). Default bring-up uses **CIDR** discovery (`groups/srl.env.sample`). See `local/netbox/README.md`.
- **ktranslate model:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) golden path — `groups/*.env` → `make generate` → discovery/polling split (`discover_srl` profile + read-only poller). No root `snmp.yaml` + `snmp_discovery_on_start`
- **SNMP profiles:** bundled in the ktranslate image from [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles). Discovery matches `sysObjectID` → `mib_profile` automatically (e.g. Nokia SR Linux → `nokia-srlinux.yml`). Missing platform? [Profile tutorial](https://github.com/kentik/ktranslate/wiki/Tutorial:-Writing-a-custom-yaml-file-for-SNMP) → PR upstream — do not bind-mount local profile overrides in normal bring-up.
- **Alloy role:** OTLP receive + Docker log scrape (lab containers except ktranslate) → preprocess → OTLP HTTP to Grafana Cloud. ktranslate already tees its own logs (and device syslog/traps) over OTLP via `--tee_logs=true`.
- **Topology graph:** LLDP edges via **gnmic** → Alloy remap → `network_topology_edge_info`. Optional **topology_exporter** (off by default) adds SNMP `network_topology_device_info` + BGP walkers
- **Topology exporter image:** only when enabled — `make -C local topology-exporter-image` then `make topology-up`
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

**WSL (Windows):** clone inside WSL on ext4 (`git clone … ~/projects/network-o11y-demo`). Do **not** run the lab from `/mnt/c/...` — ContainerLab cannot reliably commit SR Linux config on drvfs. Agents on Windows invoke WSL explicitly, e.g. `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && make up'`, or use `.\oneclick\deploy.ps1`.

`make up` **staggers** fabric sr_cli readiness and collectors with `LAB_STAGGER_SECS`
(default 25) pauses. Use `make up-parallel` or `LAB_STAGGER=0` to disable.
`make stabilize` honors `LAB_STAGGER` for collector bring-up.

Optional NetBox Cloud discovery: `cp groups/srl.env.netbox.sample groups/srl.env`, set `NETBOX_*` in `.env`, then `make generate && make netbox-sync && make up`.

From repo root: `make local-up` / `make local-down` / `make local-help`.

Agents on Windows must use a WSL ext4 checkout — e.g. `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && make up'`.

### Operational gotchas

1. **ContainerLab mgmt network is `clab`** (v0.72+ shared bridge), not `srl-local`. Set `CLAB_NETWORK=clab` in `.env`.
2. **Shell scripts must be LF** (CRLF breaks `set -o pipefail`). `.gitattributes` forces LF under `local/`.
3. **Alloy comments are `//`**, not `#`.
4. **`state/devices-*.yaml` is mutable** (discovery writes device lists); never commit `config/` / `state/` / `groups/*.env`. UID 1000 must own `config/` and `state/`.
5. **Syslog / SNMP traps:** pipe into `sr_cli` via `docker exec -i` (non-interactive); see `local/scripts/syslog-config.sh` and `snmp-trap-config.sh`. Both must use **mgmt** (`system logging network-instance mgmt`, trap-group `network-instance mgmt`) or packets never leave the box. **Traps go to the SNMP poller** (`ktranslate_snmp_srl`, UDP `:1620` — same container as polling, not a separate ktranslate). One-shot: `make -C local emit-events`. Periodic: `make -C local events-loop` (synthetic traps ~3m, real flaps ~5m; `events-stop` / `events-status`).
6. **Windows / WSL:** clone and run the lab **only** on WSL native ext4 (`~/…`), never `/mnt/c/…`. drvfs breaks ContainerLab postdeploy for SR Linux startup config. **Do not** run `clab deploy --reconfigure` unless the user explicitly asks — it SIGTERM-stops all lab containers (exit 143), which looks like a crash but is not OOM.
7. **SNMP on mgmt:** fabric cfg + `enable-snmp-srl.sh` must set `network-instance mgmt` and `access-group ag1` + `community-entry ce1 community public`. Without both, SNMP/gNMI stay `oper-state down` and ktranslate gets `connection refused` on :161 — devices can look "up" while Grafana has no `kentik_snmp_*`. See playbook **SNMP diagnosis**.
8. **Recovery without redeploy:** `make -C local stabilize` — `docker start` stopped SRL nodes, apply fabric, NetBox sync, discover, softflowd/syslog/traps. Not a memory issue: SRL exits with code 143 (SIGTERM), `OOMKilled=false`.

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
| Mgmt API catalog | `srl_mgmt_api_capability_info{tester_id="network-lab"}` — live APIs (`enabled_in_lab="true"`) plus **mock** entries for documented APIs not turned on in the lab (NETCONF, JSON-RPC, gNOI, gRIBI). Catalog: `local/fixtures/srl-mgmt-api-catalog.json`; samples: `local/fixtures/srl-mock/`. Re-export: `make -C local mgmt-api-mock`. |
| Flex gap-fill (optional) | `srl_flex_poc_ssh_up` / `srl_flex_poc_bgp_peers_up` from `make -C local telegraf-poc` (SSH + jq parse → OTLP; nri-flex analog — `local/telegraf-flex-poc/`) |

**SR Linux management plane (lab vs platform):** devices expose northbound APIs on **`network-instance mgmt`** (ContainerLab `clab` bridge). **Enabled here:** gNMI `:57400` (gnmic), SNMP, syslog, traps, sFlow. **Not enabled but catalogued with mock fixtures:** NETCONF `:830`, JSON-RPC HTTPS `/jsonrpc`, gNOI/gRIBI (gRPC, same port as gNMI). See `local/fixtures/README.md`.

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

If the Grafana Cloud MCP server is available and authenticated, prefer it for Explore queries and deeplinks. Point MCP at **your** Grafana Cloud stack (the same one as `GRAFANA_URL` / `GC_OTLP_*` in `local/.env`).

**Dashboard writes on tabbed v2 boards:** use the [**v2 manifest / gcx path**](#grafana-dashboard-updates--preserve-tabslayout-v2-manifest-path) (`dashboards get` → edit `spec.elements` → `dashboards update`). Do **not** use `POST /api/dashboards/db` or legacy patch scripts on `TabsLayout` dashboards.

## Blog / docs map

Series outline: [`blog/blog-series-overview.md`](blog/blog-series-overview.md). Local lab does not yet map 1:1 to every post (posts 3–6 assume K8s/NetBox/Ansible).

## Agent maintenance rule

When a session changes bring-up, topology, collectors, network names, or metric contracts, update:

1. This file (`AGENTS.md`)
2. Relevant `.cursor/rules/*.mdc`
3. [`local/README.md`](local/README.md) if operator-facing steps changed
