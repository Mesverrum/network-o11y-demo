#!/usr/bin/env python3
"""Sample live AWS throughput for dashboard design."""
from __future__ import annotations

import importlib.util
from pathlib import Path

p = Path(__file__).resolve().parents[1] / "scripts" / "probe-aws-metrics.py"
spec = importlib.util.spec_from_file_location("probe", p)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)

env = probe.load_env()
token = env["GRAFANA_TOKEN"]
base = env["GRAFANA_URL"]

queries = {
    "nat_egress_bps": f"sum(rate(aws_natgateway_bytes_out_to_destination_sum[5m])) * 8",
    "nat_total_bps": (
        "sum(rate(aws_natgateway_bytes_in_from_destination_sum[5m])"
        "+ rate(aws_natgateway_bytes_in_from_source_sum[5m])"
        "+ rate(aws_natgateway_bytes_out_to_destination_sum[5m])"
        "+ rate(aws_natgateway_bytes_out_to_source_sum[5m])) * 8"
    ),
    "nat_active_conn": "max(aws_natgateway_active_connection_count_maximum)",
    "nlb_bytes_bps": "sum(rate(aws_networkelb_processed_bytes_sum[5m])) * 8",
    "nlb_lcus": "sum(rate(aws_networkelb_consumed_lcus_sum[5m]))",
    "alb_bytes_bps": "sum(rate(aws_applicationelb_processed_bytes_sum[5m])) * 8",
    "alb_requests": "sum(rate(aws_applicationelb_request_count_sum[5m]))",
}

for name, q in queries.items():
    try:
        r = probe.grafana_prom_query(q, token, base)
        res = r.get("data", {}).get("result", [])
        if res:
            print(f"{name}: {res[0].get('value', ['', 'n/a'])[1]}")
        else:
            print(f"{name}: (no data)")
    except Exception as e:
        print(f"{name}: error {e}")

names = probe.prom_label_values('{__name__=~"aws_networkelb.*"}', token, base)
print("\nnlb metrics sample:", [n for n in names if "processed" in n or "consumed" in n][:12])
