# SR Linux management API fixtures (mock)

Catalog and sample payloads for northbound APIs that exist on **Nokia SR Linux**
but are **not enabled** in the local ContainerLab fabric (NETCONF, JSON-RPC, gNOI, gRIBi).

## Files

| File | Purpose |
|------|---------|
| `srl-mgmt-api-catalog.json` | Machine-readable API matrix (transport, port, docs URL, `enabled_in_lab`, `mock`) |
| `srl-mock/jsonrpc-get-system-state.json` | Representative JSON-RPC `get` response |
| `srl-mock/netconf-get-config-snippet.xml` | Representative NETCONF `<get-config>` excerpt |
| `srl-mock/gnoi-ping-mock.json` | Illustrative gNOI Ping payload |

## OTLP export

After `make up` (or `make mgmt-api-mock`), metrics land in Grafana Cloud as:

```promql
srl_mgmt_api_capability_info{tester_id="network-lab"}
```

Filter mock APIs not wired in the lab:

```promql
srl_mgmt_api_capability_info{mock="true"}
```

Live APIs in this stack (`enabled_in_lab="true"`): gNMI, SNMP, syslog, traps, sFlow.

## References

- [SR Linux JSON-RPC](https://documentation.nokia.com/srlinux/24-10/books/jsonrpc/jsonrpc-overview.html)
- [SR Linux NETCONF](https://documentation.nokia.com/srlinux/24-10/books/netconf/netconf-overview.html)
- [SR Linux gNMI](https://documentation.nokia.com/srlinux/24-10/books/gnmi/gnmi-intro.html)
