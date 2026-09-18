# Grafana Cloud Synthetic Monitoring (network-o11y-demo)

Replaces the deprecated custom `local/hybrid-probe/` script agents. Checks and private probes appear under **Testing & synthetics → Synthetics**.

## Credential files (`local/state/` — gitignored)

**Two roles — easy to confuse:**

### 1. Private probe agent creds (you already have these)

`sm-probe-laptop.env` and `sm-probe-colocated.env` — `api_token` + `api_server` (gRPC host).

| Purpose | Lets the **probe agent software** (Docker on laptop, k3s on EC2) register with Grafana Cloud and run checks assigned to that probe |
| Where from | Synthetics → **Probes** → add private probe → **Probe authentication token** (shown once) |
| Used by | `make synthetic-agent-laptop`, `make synthetic-agent-colocated` |

This is **not** what creates rows in the Checks list by itself — the agent only executes checks Grafana assigns to that probe.

### 2. SM API access token (optional — automation only)

`sm-api.token` — a single bearer token for the **Synthetic Monitoring management API**.

| Purpose | Lets **scripts/tools** (`gcx`, Terraform, REST) create/edit/delete **checks** and probes without clicking in the UI |
| Where from | Synthetic Monitoring app **Config** → **Access tokens** (URL may be hidden until you have checks — deep link pattern: `/a/grafana-synthetic-monitoring-app/config/access-tokens` on your stack) |
| Used by | `make synthetic-checks-up` only |

**If you cannot find Config → Access tokens:** your stack may use a different nav label (`Observe & Act` → `Testing`), or you may lack Admin / `access-tokens:write`. You do **not** need this token to use Synthetics in the product — create checks in the UI instead (below).

**Do not** put probe `api_token` values in `sm-api.token` — they are different tokens for different APIs.

## Create checks (pick one path)

### A. Grafana UI (no `sm-api.token` needed)

1. **Testing & synthetics** → **Synthetics** → **Checks** → **Add check**
2. Match targets in `local/synthetic-monitoring/checks/*.yaml` (HTTP/TCP, DNS, traceroute)
3. Under **Probes**, select public probes (e.g. Ohio) plus your private probes (`network-o11y-laptop-wsl`, `network-o11y-colocated-ec2`)

Check families (filter by `check_type` / `direction` labels in Explore):

| Family | Laptop probe (`laptop_to_aws`) | Colocated probe (`aws_to_*`) |
|--------|-------------------------------|------------------------------|
| HTTP/TCP | Public ALBs + internet | ALBs, NLB, local Alloy OTLP |
| DNS | `8.8.4.4` resolver (WSL often blocks `8.8.8.8` UDP/53) | VPC resolver `169.254.169.253` |
| Traceroute | *not on WSL* (SM mtr only sees hop 1) | Path inside VPC + NAT egress |

**SE demo (networko11ydev):** public-probe traceroute `se-demo-netpath-traceroute` (Ohio + North Virginia → `grafana.com`) — [check 7294](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294). Recreate: `python3 local/scripts/provision-se-netpath-check.py`. This is the NetPath stand-in in [`docs/ktranslate-se-demo-talk-track.md`](../../docs/ktranslate-se-demo-talk-track.md).

**WSL laptop probe notes:** outbound HTTPS usually works; DNS checks that hardcode `8.8.8.8` fail on this host — prefer `8.8.4.4`. Agent must run `--network host --user 0:0 --cap-add NET_RAW` (image user `sm` cannot open SOCK_RAW). **SM traceroute does not work on WSL** — the agent’s mtr only sees the first hop (`172.31.32.1`) even when `traceroute(8)` completes; use the colocated probe for traceroute. AKC ALB and ALB traceroute checks were removed (unreachable / silent ICMP).

Metrics: `probe_success`, `probe_duration_seconds`, `probe_dns_lookup_time_seconds`, traceroute hop metrics.

### B. Automation (`gcx` — needs `sm-api.token`)

```bash
make -C local synthetic-checks-up   # uses local/state/sm-api.token + SM REST API
```

## Bring-up (agents)

```bash
make -C local synthetic-agent-laptop
make -C local synthetic-agent-colocated
```

```bash
make -C local hybrid-probe-teardown
```
