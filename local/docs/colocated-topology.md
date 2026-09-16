# Colocated topology — HQ + two branch offices

Used when `LAB_FABRIC_PROFILE=colocated` (AWS demo). Laptop labs use `topology.clab.yml` instead.

## Files

| File | Purpose |
|------|---------|
| `topology-colocated.clab.yml` | ContainerLab manifest (9 nodes) |
| `configs/fabric-colocated/` | SR Linux startup configs (incl. `leaf-br1.cfg`, `leaf-br2.cfg`) |
| `gnmic/gnmic-colocated.yaml` | gNMI targets for all 5 SRL nodes |
| `scripts/stage-fabric-profile.sh` | Copies colocated topology → `topology.clab.yml` before deploy |

## Staging on EC2

Bootstrap is fully automated via `userdata.sh.tpl` → systemd. Manual steps are only needed for debugging:

```bash
export LAB_FABRIC_PROFILE=colocated
bash scripts/stage-fabric-profile.sh
bash scripts/colocated-fabric-up.sh    # staggered deploy + sanity
bash scripts/colocated-telemetry-bringup.sh
```

Or rely on `colocated-fabric-bringup.sh` / systemd on AWS.

## Observability labels

| Label | Laptop (`laptop` profile) | Colocated (`colocated` profile) |
|-------|---------------------------|----------------------------------|
| `site` (topology-exporter) | `hq` (all nodes) | `hq`, `branch1`, `branch2` |
| `tags_snmp_group` (SNMP) | `srl-hq` | `srl-hq` / `srl-branch1` / `srl-branch2` |
| `device_role` (SNMP via Alloy) | `spine`, `leaf` | + `branch-edge` on `leaf-br*` |
| `device_name` (SNMP) | spine1, leaf1, leaf2 | + leaf-br1, leaf-br2 |
| `tester_id` | `LAB_TESTER_ID` or `KTRANS_HOST` | e.g. `aws-colocated-lab` |
| `deployment_host` | `KTRANS_HOST` | e.g. `aws-colocated-lab` |

SNMP discovery still scans per-group `TARGETS` (site-scoped `/32`s when `SITE=` is set in `groups/srl-*.env`) — all five SRL nodes appear after `make snmp-discover` / `make discover-all`.

### Multi-group SNMP (colocated demo)

Three credential groups → three SNMP pollers (KtransToGrafana pattern):

| Group | `snmp_group` | Devices | Trap port |
|-------|--------------|---------|-----------|
| `srl-hq` | `srl-hq` | spine1, leaf1, leaf2 | 1620 |
| `srl-branch1` | `srl-branch1` | leaf-br1 | 1621 |
| `srl-branch2` | `srl-branch2` | leaf-br2 | 1622 |

Install: `LAB_FABRIC_PROFILE=colocated bash scripts/colocated-snmp-groups.sh` (runs automatically on colocated telemetry bring-up).

## NetBox intended topology (SoT overlay)

Orb/Diode still owns **observed** device + interface inventory. Seed **intent** with:

```bash
python3 local/scripts/netbox-populate.py --profile colocated
```

That overlay creates HQ / Branch 1 / Branch 2 sites, spine/leaf/branch-edge/client roles, four EVPN clients, IPAM prefixes, HQ fabric cables (`lab-fabric`), access attach (`lab-access`), and WAN circuits `WAN-HQ-BR1` / `WAN-HQ-BR2` (`lab-wan` SMF to circuit terminations). Re-run is idempotent and prunes same-name Orb ghosts at site `network-lab` (Diode identity is name+site until Orb is redeployed without a default site).

## Talk track

1. **HQ** — dual-homed leaves, EVPN MAC-VRF, client1↔client2 traffic (same as laptop demo).
2. **Branches** — single-homed edge leaves over “WAN” links; independent `/24` per site.
3. **Hub** — spine1 is BGP RR + WAN aggregation; syslog/traps/flows from all sites hit the same k3s collectors on the EC2 host.

## Alloy topology glue (observed graph)

Neighbor tables stay off Mimir. Alloy scrapes the SNMP topology tier and forks gnmic `*lldp_interface_neighbor*` to topology-exporter `POST /v1/metrics` (OTLP protobuf). The exporter maps samples through `families.yaml` and Reconciles `network_topology_edge_info` (`inference=alloy_otlp`, `evidence=gnmi_lldp` or `nokia_bgp_peer`). It does not re-hunt UDP/161 for catalogued devices (`skip_native_snmp: true`).

| File | Purpose |
|------|---------|
| `topology-exporter/config-alloy-glue.yaml` | Glue-mode exporter (no native SNMP modules) |
| `topology-exporter/aliases-colocated.yml` | system0 / WAN `/31` IP → device_name |
| `scripts/alloy-topology-glue-colocated.sh` | On-host apply (Alloy prefix + systemd exporter) |
| `scripts/ssm-alloy-topology-glue.py` | Sync files + linux amd64 binary, then apply |

Restore from Windows: `python local/scripts/ssm-alloy-topology-glue.py` (needs `local/topology-exporter/topology-exporter-linux-amd64`).

Expect `count by (evidence, src_device, dst_device) (network_topology_edge_info)` — BGP sessions plus LLDP when both ports are named. Placeholder `INTERFACE_NAME` port-ids are dropped. gnmic `Eth-1/49` is the live port spelling; KG rewrites that to `ethernet-1/49`.

## Knowledge Graph Interface ROUTES

KG does **not** read `network_topology_edge_info` labels directly. Recording rules in `local/scripts/provision-conversation-kg.py` emit:

- `network_lab:interface_info` — access / WAN / fabric catalog / currently faulted ports (`interface=device:ifName`, optional `peer_interface`)
- `network_lab:interface_connected:info` — catalog Clos cables **or** live topology edges with both ports (`Eth-*` → `ethernet-*`)

The model (`local/fixtures/conversation-kg/model-rules.yaml`) aliases Interface lookup `interface | src_interface | dst_interface` and PROPERTY_MATCHes `peer_interface` → peer name. Unit test: `make -C local conversation-kg-test`. Provision: `make -C local conversation-kg`.
