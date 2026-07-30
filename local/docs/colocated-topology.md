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

```bash
export LAB_FABRIC_PROFILE=colocated
bash scripts/stage-fabric-profile.sh
make fabric-up
```

Or rely on `colocated-fabric-bringup.sh` (systemd on AWS).

## Observability labels

| Label | Laptop (`laptop` profile) | Colocated (`colocated` profile) |
|-------|---------------------------|----------------------------------|
| `site` (topology-exporter) | `hq` (all nodes) | `hq`, `branch1`, `branch2` |
| `site` (SNMP via Alloy) | `hq` on spine1/leaf1/leaf2 | `hq` / `branch1` / `branch2` on matching devices |
| `device_role` (SNMP via Alloy) | `spine`, `leaf` | + `branch-edge` on `leaf-br*` |
| `device_name` (SNMP) | spine1, leaf1, leaf2 | + leaf-br1, leaf-br2 |
| `tester_id` | `LAB_TESTER_ID` or `KTRANS_HOST` | e.g. `aws-colocated-lab` |
| `deployment_host` | `KTRANS_HOST` | e.g. `aws-colocated-lab` |

SNMP discovery still scans `172.20.20.0/24` (clab mgmt) — all five SRL nodes appear after `make snmp-discover`.

## Talk track

1. **HQ** — dual-homed leaves, EVPN MAC-VRF, client1↔client2 traffic (same as laptop demo).
2. **Branches** — single-homed edge leaves over “WAN” links; independent `/24` per site.
3. **Hub** — spine1 is BGP RR + WAN aggregation; syslog/traps/flows from all sites hit the same k3s collectors on the EC2 host.
