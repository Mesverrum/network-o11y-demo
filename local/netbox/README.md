# NetBox for the network-o11y lab

SNMP discovery works **without NetBox** (`DISCOVERY_SOURCE=cidr`). Use NetBox when you want
inventory-driven discovery, Orb/Diode ingest demos, or SoT → Grafana validation.

## Preferred: NetBox on AWS colocated (self-contained)

Runs on the same EC2 host as ContainerLab + k3s collectors — **no laptop dependency**.

**Public UI (home IP and/or Grafana Cloud lab access):**  
http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000/  

Login: **`admin` / see `NETBOX_ADMIN_PASSWORD` in `local/.env`** (not `admin/admin`).  
Rotate: `python3 local/scripts/rotate-netbox-admin-password.py`  

SG: set `netbox_ui_cidrs` (home `/32`) and/or `netbox_ui_allow_grafana_cloud = true` in terraform so Grafana Cloud Infinity can reach the API. API access still requires `NETBOX_TOKEN`.

```bash
make -C local netbox-colocated   # NetBox OSS + Diode plugin + Diode + live Orb
```

| | |
|--|--|
| UI | public NLB `:8000` (above) or SSM tunnel |
| Path on host | `/opt/network-o11y-demo/local/netbox-oss/netbox-docker/` |
| Diode | `/opt/diode/` (`grpc://127.0.0.1:8080/diode`) |
| Orb | live Diode ingest + OTLP to Alloy `:4317` |

### What lands in Grafana Cloud

| Signal | Where it shows |
|--------|------------------|
| NetBox SoT (live REST) | Infinity datasource `netbox-api` on dashboards 20 / 22 / 24 / 25 |
| Orb agent OTLP | metrics with `deployment_host=orb-agent` / `collector=orb` |
| Lab SNMP (unchanged) | `kentik_snmp_*` from ktranslate — **not** from Orb |

Orb SNMP discovery can feed **NetBox** via Diode (`ORB_DRY_RUN=0`), but the live lab keeps Orb on **dry-run** so populate stays the SoT (no `network-lab` ghosts / unused IF-MIB ports). Grafana Cloud reads NetBox **live** through Infinity (no inventory-OTLP sidecar). Device changelog/journal in NetBox is the inventory audit trail; a Prometheus recording rule is optional if someone later wants Grafana-side history of those counts.

## Option B — NetBox OSS on laptop (heavy; avoid if RAM-constrained)

```bash
make -C local netbox-oss-up
make -C local netbox-sync
```

## Option C — NetBox Cloud

See earlier Cloud trial notes; set `NETBOX_*` in `.env` and `groups/srl-hq.env.netbox.sample`.

## Enable NetBox-driven ktranslate SNMP discovery (optional)

After NetBox has devices (Orb ingest or `make netbox-sync`):

```bash
# On colocated: point groups at NetBox API, then rediscover
cp groups/srl.env.netbox.sample groups/srl-hq.env   # adjust NETBOX_* URLs for 127.0.0.1:8000
```bash
make generate && COLLECTOR_RUNTIME=k3s bash scripts/run-colocated-discovery.sh
```

## Intended topology overlay (cables / sites / IPAM)

**Current lab inventory is the populate overlay**, not a live Orb IF-MIB dump. Colocated SoT:

```bash
python3 local/scripts/netbox-populate.py --profile colocated
python3 local/scripts/orb-deploy-colocated.py --dry-diode   # stop Diode recreating ghosts
```

Laptop Clos stays `LAB_FABRIC_PROFILE=laptop` / `make netbox-populate`. The colocated profile is **9 devices / 25 role-bearing interfaces / 10 cables / 2 WAN circuits**:

- Sites `hq`, `branch1`, `branch2` with racks
- Roles spine / leaf / branch-edge / client
- SRL: `spine1`, `leaf1`, `leaf2`, `leaf-br1`, `leaf-br2` (mgmt + fabric/access/WAN ports only)
- Clients `client1`/`client2`/`client-br1`/`client-br2` (`eth0` mgmt, `eth1` overlay)
- Prefixes + client/underlay IPs
- Cables: HQ fabric (MMF), access attach (Cat6), WAN circuits `WAN-HQ-BR1`/`WAN-HQ-BR2` (SMF to circuit terminations)

Live Orb `snmp_discovery` → Diode (`ORB_DRY_RUN=0`) recreates same-name copies at site `network-lab` (NetBox uniqueness is per-site) and dumps unused IF-MIB ports. Populate `--tidy` (colocated default) deletes those; it only stays clean if Diode is dry-run:

```bash
python3 local/scripts/netbox-populate.py --profile colocated --tidy-only
make -C local orb-dry-diode-colocated
```

Re-enable live Diode only when you want that crawl demo: `ORB_DRY_RUN=0 make -C local orb-colocated`, then tidy again afterward.

## Scripts

| Target | Purpose |
|--------|---------|
| `make netbox-colocated` | AWS: NetBox + Diode + live Orb (Grafana reads NetBox via Infinity) |
| `make netbox-ui-tunnel` | SSM port-forward UI to laptop |
| `make netbox-oss-up` / `down` | Laptop sidecar only |
| `make netbox-populate` / `sync` | Seed Clos SoT (devices, roles, sites, cables, IPAM, WAN circuits) + mgmt IP sync. Colocated: `python3 scripts/netbox-populate.py --profile colocated` |
| `make orb-colocated` | Orb only (dry-run or live if Diode creds set) |
| `make orb-dry-diode-colocated` | Keep Orb/pktvisor; stop Diode writing devices/ifaces into NetBox |
