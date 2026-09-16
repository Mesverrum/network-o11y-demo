# Conversation / Knowledge Graph fixtures

Source of truth is [`local/scripts/provision-conversation-kg.py`](../../scripts/provision-conversation-kg.py). This directory is the exported snapshot (`--export-only` or any live provision).

| File | Role |
|------|------|
| `recording-rules.yaml` | Grafana-managed rules: conversations, Host/Device/Interface entities, fabric + iface cables |
| `model-rules.yaml` | Asserts custom model `network-lab-conversation` |

## What feeds what

```text
ktranslate flows          → conversation:* / Host ROUTES Host
kentik_snmp_CPU / snmp_CPU → NetworkDevice
IFACE_LINKS catalog       → interface_info (peer_interface) + interface_connected
network_topology_edge_info → device_connected (always)
                           → interface_connected when src_port AND dst_port are named
KG model                   → Host / NetworkDevice / Interface + HOSTS / ROUTES
```

Topology-exporter extra labels are optional. Interface ROUTES needs `src_interface`/`dst_interface` (or `peer_interface` on the entity). The model lookup must alias those names — `interface` alone does not join the cable series.

gnmic live ports (`Eth-1/49`) are rewritten to `ethernet-1/49` in the recording rule so they match Interface entity names.

## Commands

```bash
python3 local/scripts/test-conversation-kg.py          # no Grafana token
python3 local/scripts/provision-conversation-kg.py --export-only
python3 local/scripts/provision-conversation-kg.py     # rules + model (needs GRAFANA_*)
python3 local/scripts/provision-conversation-kg.py --verify --wait 90
```

`make -C local conversation-kg` and `make -C local conversation-kg-test` wrap the first two live/unit paths.
