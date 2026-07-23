# Telegraf Flex-style gap-fill PoC

Optional proof-of-concept for **“I used to write nri-flex integrations”** conversations.
Not started by default `make up`.

Telegraf is the closest thing in the Prometheus/OTLP world to [New Relic nri-flex](https://github.com/newrelic/nri-flex):
run arbitrary commands (`inputs.exec`), parse output in the script, export metrics. Unlike Flex,
the script must emit **valid Prometheus exposition text** (Flex would keep jq/regex in YAML).

## What it demonstrates

| Flex concept | This PoC |
|--------------|----------|
| Remote `commands:` | `sshpass` + `ssh admin@device 'show … \| as json'` |
| Parse → samples | `jq` counts `State == "established"` → Prometheus gauges |
| Ship to backend | `outputs.opentelemetry` → `alloy:4317` → Grafana Cloud |

**Metrics:**

- `srl_flex_poc_ssh_up` — SSH session succeeded
- `srl_flex_poc_bgp_peers_up` — established BGP peers (from `show … bgp neighbor \| as json`)

Credentials match ContainerLab SR Linux defaults (`admin` / `NokiaSrl1!`, same as gnmic).
Override with `SRL_SSH_USER` / `SRL_SSH_PASSWORD` in `local/.env`.

## Run

```bash
make -C local telegraf-poc          # build image + start container
make -C local telegraf-poc-status
make -C local telegraf-poc-stop
```

Requires the main lab up (`make up`) so Alloy and SRL nodes exist on the `clab` network.

## Verify in Grafana Cloud Explore

```promql
srl_flex_poc_ssh_up{collector="telegraf-flex-poc"}
srl_flex_poc_bgp_peers_up{collector="telegraf-flex-poc"}
```

Expect `service.name="telegraf-flex-poc"` on the OTLP resource. Leaves should show `srl_flex_poc_bgp_peers_up` > 0 (eBGP + EVPN peers).

## When to use this vs golden path

| Situation | Prefer |
|-----------|--------|
| OID/MIB exists | Extend `snmp-profiles/nokia/nokia-srlinux.yml` + ktranslate |
| YANG path exists | gnmic subscription |
| Structured API | JSON-RPC / NETCONF (see `fixtures/srl-mgmt-api-catalog.json`) |
| One-off `show` / legacy CLI | Telegraf exec (this PoC) or script_exporter |
