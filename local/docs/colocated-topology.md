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

## Talk track

1. **HQ** — dual-homed leaves, EVPN MAC-VRF, client1↔client2 traffic (same as laptop demo).
2. **Branches** — single-homed edge leaves over “WAN” links; independent `/24` per site.
3. **Hub** — spine1 is BGP RR + WAN aggregation; syslog/traps/flows from all sites hit the same k3s collectors on the EC2 host.
