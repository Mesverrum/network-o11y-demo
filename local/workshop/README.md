# Workshop live SNMP

Live SNMP for the [Grafana Network Observability webinar](https://github.com/Mesverrum/grafana-network-observability-workshop). Students query this fleet as datasource `workshop-ktranslate` on their Brokkr stacks.

**Student story is the 3-site Clos** (HQ + two branches). Do **not** start the laptop Clos. Do **not** redeploy campus-core (`clab deploy --reconfigure`).

Student order on that repo: login → data sources → synthetics → import dashboards → explore (healthy) → you inject a Clos fault → they hunt → Infinity. Discovery is **your** share during Lab 1, not a student blocking lab.

## What students should see

| `tags_snmp_group` | Devices |
|---|---|
| `srl-hq` | `spine1`, `leaf1`, `leaf2` |
| `srl-branch1` | `leaf-br1` |
| `srl-branch2` | `leaf-br2` |

That is the colocated lab (`network-o11y-demo-colocated-lab`). Discovery is the golden path: `groups/srl-*.env` → `make discover GROUP=…` → `state/devices-srl-*.yaml`. Device Summary **SNMP group** lists those three values (All by default).

Restore collectors:

```text
python local/scripts/ssm-alloy-ktranslate-parallel.py
```

Facilitator share while they add data sources: `local/groups/srl-hq.env` (CIDR + community), then the matching `state/devices-srl-hq.yaml` on the colocated host (`/opt/network-o11y-demo/local/…`). Repeat the idea for the two branch groups.

## Lab 5 incident (after they have explored)

Sustained admin-disable of HQ `leaf1` `ethernet-1/1`. Do **not** name the box in chat. Public-VIP synthetics stay green.

```text
python local/scripts/ssm-workshop-inject-fault.py start
# wait ~90s, confirm on your Device Details, then paste Lab 5
python local/scripts/ssm-workshop-inject-fault.py stop
```

On the colocated host: `make -C local workshop-fault` / `workshop-fault-stop`. Stop `events-loop` before the healthy explore so background flaps are not the incident.

Building 4 / Check Point / EdgeConnect names (`bld4-*`, `wan-edge-01`) stay on the Infinity mock API (Lab 6), not this poller.

## Optional: campus vendors

A second fabric (`network-o11y-campus-lab`) still polls Forti / Arista / Nokia / Cisco as `tags_snmp_group=campus`. Workshop dashboards **hide** that group so HQ/branch stays the hunt. Leave it running if you want vendor extras in Explore; do not default the Device Summary hunt there (CPU/interfaces on that static list are often empty).

Restore campus only if you need those names:

```text
python local/scripts/campus-workshop-ktrans-up.py
```

Static list: [`campus-snmp.yaml`](campus-snmp.yaml). Discovery-on-start is off — that host cannot `chtimes` a bind-mounted snmp.yaml.
