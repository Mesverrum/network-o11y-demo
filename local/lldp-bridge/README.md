# lldp-bridge (retired)

Replaced by **gnmic** subscription `lldp_neighbors` on
`/system/lldp/interface[name=*]/neighbor`.

Alloy remaps
`…lldp_interface_neighbor_system_name` → `network_topology_edge_info`
(`src_device`/`dst_device`/`src_port`, `tester_id=network-lab` by default).

This directory is kept only as a historical reference; it is no longer in Compose.
