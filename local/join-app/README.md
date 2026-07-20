# Clos join-app

Minimal OpenTelemetry HTTP **client** (client1) and **server** (client2) for the SIG
network↔app join demo.

- Data plane: `172.17.0.1` → Clos EVPN → `172.17.0.2:8080`
- Control / OTLP: mgmt `clab` network → `alloy:4317`
- Join keys on spans: `network.peer.address`, `network.peer.port`, `server.address`, `server.port`
- Entity overlay metrics (for Clos nodeGraph): `clos_join_entity_info`, `clos_join_edge_info`
  (`service` —runs_on→ `client1`/`client2` —attached→ `leaf1`/`leaf2`)
- Identity prove/disprove datasets (`entity_demo_*`, label `demo_model=`): hostname / hostname_poison /
  mac_alias / address / iface / **edge_attrs** (Q3 ✗) / **vrf** (Q3 ✓ MAC-VRF) — dashboard **Identity tab**
- `service.name=clos-join-demo`

```bash
make -C local join-app          # build, deploy, start
make -C local join-app-status
make -C local join-fault        # netem 200ms/1% on client eth1
make -C local join-fault-stop
make -C local join-app-stop
```

Dashboard Investigation row: app p95 → matched flows → Clos path → path CPU/errors.

TraceQL: `{ resource.service.name = "clos-join-demo" }`  
PromQL: `network_io_by_flow_bytes{network_peer_port="8080"}`
