# Conversation / Knowledge Graph fixtures

Source of truth is [`local/scripts/provision-conversation-kg.py`](../../scripts/provision-conversation-kg.py). This directory is the exported snapshot (`--export-only` or any live provision).

| File | Role |
|------|------|
| `recording-rules.yaml` | Grafana-managed rules: conversations, Endpoint/Device/Interface entities, fabric + iface cables |
| `model-rules.yaml` | Asserts custom model `network-lab-conversation` |

## What feeds what

```text
Alloy netflow (increase)   → conversation:* / Endpoint ROUTES Endpoint
snmp_CPU                   → NetworkDevice
snmp_ifAdminStatus WAN     → interface_info (if_Alias)
snmp_if* 1=up/2=down       → faulted ports
IFACE_LINKS catalog        → interface_info (peer_interface) + interface_connected
network_topology_edge_info → device_connected (always)
                           → interface_connected when src_port AND dst_port are named
KG model                   → Endpoint / NetworkDevice / Interface + HOSTS / ROUTES
```

Lab clients are type **Endpoint**, not Host. Grafana Host Monitoring (private preview) discovers machines from `node_uname_info` / `windows_os_info` and will own Host. Flow labels stay `src_host` / `dst_host`; series stay `network_lab:host_info`. Conversations are `increase(alloy_network_io_by_flow_bytes{integration="alloy-netflow"})` — Alloy reverse-DNS PTRs `ip-172-17-0-1*` / `ip-172-17-0-2*` rewrite to `client1` / `client2`. The `HOSTS` relation is the official verb (same as Node HOSTS Pod). Do not key new rules on `kentik_snmp_*`.

## Open: join Host Monitoring Host ↔ conversation Endpoint

`Mesverrum/network-o11y-demo` has GitHub issues off (public repo). Track this here until a Host lands on the stack.

When Host Monitoring is enabled, do **not** rename Endpoint back to Host. Add a join so a flow conversation can reach the native machine entity (CPU / process Service).

| Side | Type | Identity today |
|------|------|----------------|
| Conversation | **Endpoint** | `src_host` / `dst_host` / `network_lab:host_info` |
| Host o11y | **Host** (docs still say non-K8s node) | `node_uname_info{instance}`, `windows_os_info`, optional AWS `instance_id` |

Likely match keys (try in this order): `nodename` / hostname vs `src_host`, then IP, then `instance_id`. Lab `client*` Clos VMs may never scrape node_exporter — the join is for real hosts that also appear in NetFlow.

Relation TBD when we can see a live Host: `Host HOSTS Endpoint`, `Endpoint RUNS_ON Host`, or a PROPERTY_MATCH on a shared name. Success: expand an Endpoint conversation and land on the Host Monitoring entity without a second lab `Host` type.

Docs: [Host Monitoring dataset](https://grafana.com/docs/grafana-cloud/platform/knowledge-graph/get-started/manage-datasets/host-monitoring/) (private preview).

Topology-exporter extra labels are optional. Interface CONNECTS_TO needs `src_interface`/`dst_interface` (or `peer_interface` on the entity). The model lookup must alias those names — `interface` alone does not join the cable series. Endpoint conversations stay ROUTES; a cable is not a route.

gnmic live ports (`Eth-1/49`) are rewritten to `ethernet-1/49` in the recording rule so they match Interface entity names.

## Commands

```bash
python3 local/scripts/test-conversation-kg.py          # no Grafana token
python3 local/scripts/provision-conversation-kg.py --export-only
python3 local/scripts/provision-conversation-kg.py     # rules + model (needs GRAFANA_*)
python3 local/scripts/provision-conversation-kg.py --verify --wait 90
```

`make -C local conversation-kg` and `make -C local conversation-kg-test` wrap the first two live/unit paths.
