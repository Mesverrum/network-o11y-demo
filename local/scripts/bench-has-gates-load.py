#!/usr/bin/env python3
"""A/B bench: Device Details has_* variable fan-out cost.

Compares wall-clock of the Prometheus label_values calls Grafana fires for
has_* variables on dashboard load:

  A) all has_* gates on live ktranslate-device-details
  B) short capability-only set (~25)

This isolates the has_* tax (the hypothesized bottleneck). It does not render
panels in a browser; variable fan-out is what scales with gate count.

Usage:
  python3 local/scripts/bench-has-gates-load.py
  python3 local/scripts/bench-has-gates-load.py --instance leaf1 --runs 5
"""
from __future__ import annotations

import argparse
import json
import os
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
UID = "ktranslate-device-details"

# Capability-first short list (what we'd keep if freezing Device Details)
SHORT_GATES = {
    "has_ping",
    "has_cpu",
    "has_cpu_percore",
    "has_memory",
    "has_memory_detail",
    "has_interfaces",
    "has_disk",
    "has_sensors",
    "has_polling",
    "has_temp",
    "has_fan_speed",
    "has_psu_state",
    "has_fan_state",
    "has_fru_fantray",
    "has_fru_module",
    "has_fru_power",
    "has_ospf",
    "has_bgp",
    "has_bgp4",
    "has_firewall",
    "has_ntp",
    "has_hsrp",
    "has_csw",
    "has_ipsla",
    "has_connections",
    "has_cie_drops",
    "has_ups",
    "has_entity_phy",
    "has_hr_storage",
    "has_lldp",
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), env[k.strip()])
    return env


def api(base: str, token: str, method: str, path: str, body: Any | None = None) -> tuple[int, Any, float]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=120) as resp:
            raw = resp.read()
            elapsed = time.perf_counter() - t0
            return resp.status, json.loads(raw.decode()) if raw else None, elapsed
    except urllib.error.HTTPError as e:
        elapsed = time.perf_counter() - t0
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw), elapsed
        except Exception:
            return e.code, {"raw": raw[:2000]}, elapsed


def extract_has_gates(dash: dict) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for v in (dash.get("spec") or {}).get("variables") or []:
        spec = v.get("spec") or {}
        name = spec.get("name") or ""
        if not name.startswith("has_"):
            continue
        qspec = ((spec.get("query") or {}).get("spec")) or {}
        metric = (qspec.get("metric") or "").strip()
        if metric:
            out.append((name, metric))
    return out


def prom_uid(env: dict[str, str], base: str, token: str) -> str:
    status, dss, _ = api(base, token, "GET", "/api/datasources")
    if status != 200 or not isinstance(dss, list):
        raise SystemExit(f"datasources failed {status}")
    prom = next((d for d in dss if d.get("type") == "prometheus" and d.get("isDefault")), None)
    if not prom:
        prom = next((d for d in dss if d.get("type") == "prometheus"), None)
    if not prom:
        raise SystemExit("no prometheus datasource")
    return prom["uid"]


def label_values_once(
    base: str, token: str, ds_uid: str, metric: str, instance: str
) -> tuple[bool, float, int]:
    """One label_values-equivalent call (same work as a has_* QueryVariable)."""
    match = f'{{__name__="{metric}",device_name=~"{instance}"}}'
    q = urllib.parse.urlencode({"match[]": match})
    path = f"/api/datasources/proxy/uid/{ds_uid}/api/v1/label/device_name/values?{q}"
    status, body, elapsed = api(base, token, "GET", path)
    n = 0
    if isinstance(body, dict):
        data = body.get("data")
        if isinstance(data, list):
            n = len(data)
    return status == 200, elapsed, n


def run_wave(
    base: str,
    token: str,
    ds_uid: str,
    gates: list[tuple[str, str]],
    instance: str,
    workers: int,
) -> dict[str, Any]:
    """Fire all gate queries concurrently (browser-like) and return timing stats."""
    t0 = time.perf_counter()
    results: list[tuple[str, bool, float, int]] = []
    errors = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {
            pool.submit(label_values_once, base, token, ds_uid, metric, instance): name
            for name, metric in gates
        }
        for fut in as_completed(futs):
            name = futs[fut]
            ok, elapsed, n = fut.result()
            if not ok:
                errors += 1
            results.append((name, ok, elapsed, n))
    wall = time.perf_counter() - t0
    per = [r[2] for r in results]
    hits = sum(1 for r in results if r[3] > 0)
    return {
        "wall_s": wall,
        "n_gates": len(gates),
        "errors": errors,
        "gates_with_data": hits,
        "per_query_p50_s": statistics.median(per) if per else 0,
        "per_query_p95_s": sorted(per)[max(0, int(len(per) * 0.95) - 1)] if per else 0,
        "per_query_max_s": max(per) if per else 0,
        "sum_s": sum(per),
    }


def summarize(label: str, samples: list[dict[str, Any]]) -> None:
    walls = [s["wall_s"] for s in samples]
    print(f"\n=== {label} ===")
    print(f"  gates:           {samples[0]['n_gates']}")
    print(f"  runs:            {len(samples)}")
    print(f"  wall p50:        {statistics.median(walls)*1000:.0f} ms")
    print(f"  wall p95:        {sorted(walls)[max(0, int(len(walls)*0.95)-1)]*1000:.0f} ms")
    print(f"  wall min/max:    {min(walls)*1000:.0f} / {max(walls)*1000:.0f} ms")
    print(f"  per-query p50:   {statistics.median([s['per_query_p50_s'] for s in samples])*1000:.0f} ms")
    print(f"  per-query p95:   {statistics.median([s['per_query_p95_s'] for s in samples])*1000:.0f} ms")
    print(f"  gates w/ data:   {samples[0]['gates_with_data']} (instance-dependent)")
    print(f"  errors (last):   {samples[-1]['errors']}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="leaf1", help="device_name regex for gate queries")
    ap.add_argument("--runs", type=int, default=5)
    ap.add_argument("--workers", type=int, default=32, help="concurrent label_values (browser-ish)")
    ap.add_argument("--warmup", type=int, default=1)
    args = ap.parse_args()

    env = load_env()
    base = env["GRAFANA_URL"]
    token = env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"

    print(f"pulling live {UID} …")
    status, dash, get_s = api(
        base, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    if status != 200:
        raise SystemExit(f"GET dashboard failed {status}")
    print(f"  GET dashboard: {get_s*1000:.0f} ms  gen={dash['metadata'].get('generation')}")

    all_gates = extract_has_gates(dash)
    short_gates = [(n, m) for n, m in all_gates if n in SHORT_GATES]
    # If some SHORT_GATES missing from dash, still ok
    missing = SHORT_GATES - {n for n, _ in all_gates}
    if missing:
        print(f"  note: {len(missing)} short-list gates not on dash (ignored)")

    print(f"  A (current): {len(all_gates)} has_*")
    print(f"  B (short):   {len(short_gates)} has_* capability set")
    print(f"  instance:    {args.instance}")
    print(f"  workers:     {args.workers}")

    ds = prom_uid(env, base, token)
    print(f"  prom uid:    {ds}")

    # Warmup
    for i in range(args.warmup):
        run_wave(base, token, ds, short_gates[:5] or all_gates[:5], args.instance, workers=8)
        print(f"  warmup {i+1}/{args.warmup} done")

    samples_a: list[dict[str, Any]] = []
    samples_b: list[dict[str, Any]] = []
    for i in range(args.runs):
        # Alternate order to reduce bias
        if i % 2 == 0:
            samples_a.append(run_wave(base, token, ds, all_gates, args.instance, args.workers))
            samples_b.append(run_wave(base, token, ds, short_gates, args.instance, args.workers))
        else:
            samples_b.append(run_wave(base, token, ds, short_gates, args.instance, args.workers))
            samples_a.append(run_wave(base, token, ds, all_gates, args.instance, args.workers))
        print(
            f"  run {i+1}/{args.runs}: "
            f"A={samples_a[-1]['wall_s']*1000:.0f}ms  B={samples_b[-1]['wall_s']*1000:.0f}ms"
        )

    summarize(f"A current ({len(all_gates)} gates)", samples_a)
    summarize(f"B short ({len(short_gates)} gates)", samples_b)

    a_p50 = statistics.median([s["wall_s"] for s in samples_a])
    b_p50 = statistics.median([s["wall_s"] for s in samples_b])
    if b_p50 > 0:
        speedup = a_p50 / b_p50
        delta_ms = (a_p50 - b_p50) * 1000
    else:
        speedup = float("inf")
        delta_ms = 0

    print("\n=== verdict ===")
    print(f"  A p50 wall: {a_p50*1000:.0f} ms   ({len(all_gates)} label_values, parallel/{args.workers})")
    print(f"  B p50 wall: {b_p50*1000:.0f} ms   ({len(short_gates)} label_values, parallel/{args.workers})")
    print(f"  delta:      {delta_ms:.0f} ms faster on short list  ({speedup:.2f}x)")
    print()
    if delta_ms < 200:
        print(
            "  Interpretation: has_* fan-out difference is small (<200ms p50). "
            "Premature to optimize gate count for load time alone on this stack;"
            " panel queries / JSON size may dominate real page load."
        )
    elif delta_ms < 1000:
        print(
            "  Interpretation: measurable but modest. Worth freezing growth; "
            "not urgent to slash existing gates for speed."
        )
    else:
        print(
            "  Interpretation: material load-time tax. Prefer capability consolidation "
            "before adding more vendor has_* to Device Details."
        )

    out = ROOT / ".dash-payloads" / "mib-coverage" / "bench-has-gates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "instance": args.instance,
                "workers": args.workers,
                "runs": args.runs,
                "A": samples_a,
                "B": samples_b,
                "A_gates": len(all_gates),
                "B_gates": len(short_gates),
                "A_p50_s": a_p50,
                "B_p50_s": b_p50,
                "delta_ms": delta_ms,
                "speedup": speedup,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
