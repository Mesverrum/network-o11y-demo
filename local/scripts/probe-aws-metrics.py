#!/usr/bin/env python3
"""Probe marcnetterfield1 for AWS CloudWatch metric names vs dashboard expectations."""
from __future__ import annotations

import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV = ROOT / ".env"

EXPECTED = [
    "aws_natgateway_bytes_out_to_destination_sum",
    "aws_natgateway_bytes_in_from_source_sum",
    "aws_applicationelb_processed_bytes_sum",
    "aws_applicationelb_request_count_sum",
    "aws_firehose_delivery_to_http_endpoint_bytes_sum",
    "aws_ec2_network_packets_in_sum",
]

DASHBOARD_METRICS = {
    "hybrid-network-boundary": ["aws_vpn_tunnelstate_average", "aws_vpn_tunneldata_in_sum"],
    "aws-egress-transit-economics": [
        "aws_natgateway_bytes_out_to_destination_sum",
        "aws_natgateway_error_port_allocation_sum",
    ],
    "aws-cross-zone-traffic": ["aws_ec2_networkin_sum", "aws_ec2_networkout_sum"],
    "aws-network-limits-saturation": [
        "aws_natgateway_active_connection_count_maximum",
        "aws_applicationelb_httpcode_target_5xx_count_sum",
    ],
    "aws-observability-tax": [
        "aws_firehose_deliverytohttpendpoint_bytes_sum",
        "aws_firehose_deliverytos3_bytes_sum",
    ],
}


def load_env() -> dict[str, str]:
    out: dict[str, str] = {}
    if not ENV.is_file():
        return out
    for line in ENV.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def grafana_prom_query(expr: str, token: str, base_url: str) -> dict:
    # Resolve default Prometheus datasource UID via Grafana API, then query.
    ds_url = f"{base_url.rstrip('/')}/api/datasources"
    req = urllib.request.Request(ds_url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        datasources = json.loads(resp.read().decode())
    prom = next((d for d in datasources if d.get("type") == "prometheus"), None)
    if not prom:
        raise RuntimeError("No Prometheus datasource on stack")
    uid = prom["uid"]
    qurl = f"{base_url.rstrip('/')}/api/datasources/proxy/uid/{uid}/api/v1/query"
    body = urllib.parse.urlencode({"query": expr}).encode()
    req = urllib.request.Request(qurl, data=body, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def prom_label_values(match: str, token: str, base_url: str) -> list[str]:
    ds_url = f"{base_url.rstrip('/')}/api/datasources"
    req = urllib.request.Request(ds_url)
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=60) as resp:
        datasources = json.loads(resp.read().decode())
    prom = next((d for d in datasources if d.get("type") == "prometheus"), None)
    if not prom:
        raise RuntimeError("No Prometheus datasource on stack")
    uid = prom["uid"]
    enc = urllib.parse.quote(match)
    path = f"/api/datasources/proxy/uid/{uid}/api/v1/label/__name__/values?match[]={enc}"
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}")
    req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode())
    return sorted(data.get("data", []))


def main() -> int:
    env = load_env()
    token = env.get("GRAFANA_TOKEN", "")
    base_url = env.get("GRAFANA_URL", "")
    if not token or not base_url:
        print("Missing GRAFANA_URL or GRAFANA_TOKEN in local/.env")
        return 1

    names = prom_label_values('{__name__=~"aws_.*"}', token, base_url)
    print(f"aws_* metric count: {len(names)}")
    if not names:
        print("No aws_* series found — check Cloud Provider Observability ingest.")
        return 0

    # Group by service prefix (aws_natgateway_, aws_ec2_, etc.)
    by_prefix: dict[str, list[str]] = {}
    for n in names:
        m = re.match(r"(aws_[a-z0-9]+)_", n)
        prefix = m.group(1) if m else "aws_other"
        by_prefix.setdefault(prefix, []).append(n)

    print("\nPrefixes:")
    for p in sorted(by_prefix):
        print(f"  {p}: {len(by_prefix[p])} metrics")

    print("\nExpected vs actual:")
    for e in EXPECTED:
        status = "FOUND" if e in names else "MISSING"
        close = [n for n in names if e.replace("_sum", "") in n or e.split("aws_")[1].split("_")[0] in n][:3]
        print(f"  {status:7} {e}")
        if status == "MISSING" and close:
            print(f"           near: {close[:5]}")

    # Sample NAT names if any
    nat = [n for n in names if "natgateway" in n.lower() or "nat_gateway" in n.lower()]
    if nat:
        print("\nNAT-related sample:")
        for n in nat[:15]:
            print(f"  {n}")

    # Quick instant query for one NAT metric variant
    for candidate in names:
        if "natgateway" in candidate and "bytes_out" in candidate:
            q = f"count({candidate})"
            inst = grafana_prom_query(q, token, base_url)
            val = inst.get("data", {}).get("result", [])
            print(f"\nSample series count for {candidate}: {val[0]['value'][1] if val else 0}")
            break

    print("\nDashboard coverage (key metrics present?):")
    for dash, metrics in DASHBOARD_METRICS.items():
        found = sum(1 for m in metrics if m in names)
        print(f"  {dash}: {found}/{len(metrics)} key metrics")

    print("\nPattern search (actual names on stack):")
    for pat in [
        "processed",
        "network",
        "delivery",
        "vpn",
        "transit",
        "tunnel",
        "bytes",
    ]:
        hits = [n for n in names if pat in n.lower()]
        print(f"  {pat}: {len(hits)}")
        for h in hits[:8]:
            print(f"    {h}")

    # Data presence (not just metric catalog)
    probes = [
        "aws_natgateway_bytes_out_to_destination_sum",
        "aws_natgateway_bytes_out_to_destination_average",
        "aws_ec2_network_packets_in_sum",
        "aws_applicationelb_request_count_sum",
        "aws_firehose_incoming_records_sum",
    ]
    print("\nActive series (count over 24h):")
    for p in probes:
        if p not in names:
            # try fuzzy
            fuzzy = [n for n in names if p.split("aws_")[1].split("_")[0] in n]
            print(f"  {p}: metric name absent")
            continue
        q = f'count(count_over_time({p}[24h]))'
        try:
            inst = grafana_prom_query(q, token, base_url)
            val = inst.get("data", {}).get("result", [])
            n = val[0]["value"][1] if val else "0"
            print(f"  {p}: {n} series with data")
        except Exception as e:
            print(f"  {p}: query error {e}")

    q = 'label_values(aws_ec2_network_packets_in_sum, dimension_InstanceId)'
    try:
        enc = __import__("urllib.parse").parse.quote('{__name__="aws_ec2_network_packets_in_sum"}')
        # use label values via instant query on one series
        inst = grafana_prom_query(
            "count by (dimension_InstanceId, dimension_AutoScalingGroupName) (aws_ec2_network_packets_in_sum)",
            token,
            base_url,
        )
        print("\nEC2 grouping labels:")
        for r in inst.get("data", {}).get("result", [])[:8]:
            print(f"  {r.get('metric', {})}")
    except Exception as e:
        print(f"  failed: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
