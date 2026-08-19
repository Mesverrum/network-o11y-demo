#!/usr/bin/env python3
"""Pad Device Details has_* count (marc) for load-fanout experiments.

Adds hidden QueryVariables named has_bench_pad_NNN with unique synthetic
metrics so each gate is a real Prom label_values call. Does not add panels.

Usage:
  python3 local/scripts/pad-has-gates.py --target 300 --push
  python3 local/scripts/pad-has-gates.py --strip --push   # remove pads
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ktranslate_upstream import load_local_env, path_for_uid  # noqa: E402

UID = "ktranslate-device-details"
PAD_PREFIX = "has_bench_pad_"

_sib = Path(__file__).with_name("patch-mib-rudimentary-coverage.py")
_spec = importlib.util.spec_from_file_location("mib_rudimentary", _sib)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["mib_rudimentary"] = _mod
_spec.loader.exec_module(_mod)
make_gate = _mod.make_gate


def load_env() -> dict[str, str]:
    load_local_env()
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(base: str, token: str, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
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
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:3000]}


def has_vars(dash: dict) -> list[dict]:
    out = []
    for v in dash["spec"]["variables"]:
        n = (v.get("spec") or {}).get("name") or ""
        if n.startswith("has_"):
            out.append(v)
    return out


def strip_pads(dash: dict) -> int:
    before = len(dash["spec"]["variables"])
    dash["spec"]["variables"] = [
        v
        for v in dash["spec"]["variables"]
        if not str((v.get("spec") or {}).get("name") or "").startswith(PAD_PREFIX)
    ]
    return before - len(dash["spec"]["variables"])


def pad_to(dash: dict, target: int) -> int:
    strip_pads(dash)  # idempotent re-pad
    current = len(has_vars(dash))
    if current >= target:
        print(f"already at {current} has_* (>= {target}); no pad added")
        return 0
    need = target - current
    # Unique synthetic metrics (empty series) so each query is distinct work
    for i in range(1, need + 1):
        name = f"{PAD_PREFIX}{i:03d}"
        metric = f"kentik_snmp_BenchPadMetric{i:03d}"
        dash["spec"]["variables"].append(make_gate(name, metric))
    print(f"padded +{need} -> {len(has_vars(dash))} has_*")
    return need


def push(dash: dict) -> None:
    env = load_env()
    url = env["GRAFANA_URL"]
    token = env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, existing = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    if status != 200:
        raise SystemExit(f"GET failed {status}")
    body = copy.deepcopy(dash)
    body["metadata"]["namespace"] = ns
    body["metadata"]["name"] = UID
    body["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
    for k in ("generation", "creationTimestamp", "uid", "managedFields"):
        body["metadata"].pop(k, None)
    body.pop("status", None)
    ann = body["metadata"].setdefault("annotations", {})
    ann["grafana.app/folder"] = existing.get("metadata", {}).get("annotations", {}).get(
        "grafana.app/folder", "network-lab"
    )
    status, data = api(
        url, token, "PUT", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}", body
    )
    print(f"PUT marc -> {status} gen={(data or {}).get('metadata', {}).get('generation')}")
    if status not in (200, 201):
        raise SystemExit(data)
    status2, after = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    kind = ((after or {}).get("spec") or {}).get("layout", {}).get("kind")
    n_has = len(has_vars(after or {}))
    print(f"verify layout={kind} has_*= {n_has}")
    if kind != "TabsLayout":
        raise SystemExit(f"layout degraded to {kind}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", type=int, default=300)
    ap.add_argument("--strip", action="store_true", help="Remove has_bench_pad_* only")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--write-local", action="store_true", help="Also write KtransToGrafana JSON")
    args = ap.parse_args()

    env = load_env()
    url = env["GRAFANA_URL"]
    token = env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, live = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    if status != 200:
        raise SystemExit(f"GET live failed {status}")
    print(f"pulled gen={live['metadata'].get('generation')} has_*={len(has_vars(live))}")

    dash = copy.deepcopy(live)
    if args.strip:
        n = strip_pads(dash)
        print(f"stripped {n} pad gates -> has_*={len(has_vars(dash))}")
    else:
        pad_to(dash, args.target)

    if args.write_local:
        path = path_for_uid(UID)
        # Prefer not to bake pads into upstream by default
        path.write_text(json.dumps(dash, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    if args.push:
        push(dash)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
