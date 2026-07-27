#!/usr/bin/env python3
"""Patch Network Flow Summary: add src_host/dst_host alongside IP labels.

Keeps ``network_local_address`` / ``network_peer_address`` for drill-down and
variables; adds hostname labels to group-by and legends — no label_replace.

Playbook: docs/grafana-dashboard-playbook.md (v2 manifest PUT — safe for RowsLayout).

Usage:
  python3 local/scripts/patch-ktranslate-flow-dashboard.py --dry-run
  python3 local/scripts/patch-ktranslate-flow-dashboard.py
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "ktranslate-flow-hostname-patched.json"
DEFAULT_UID = "ktranslate-flow-summary"
DEFAULT_NS = "stacks-1061129"

METRIC_SELECTOR_RE = re.compile(
    r"network_io_by_flow_bytes(\{(?:[^{}]|\$\{[^}]*\})*\})"
)
RANGE_RE = re.compile(r"\[(\$__range|\$__rate_interval)\]")

NOTE = (
    "Endpoint panels: group by IP + src_host/dst_host; legends show hostname (ip)."
)

LEGEND_REPLACEMENTS: list[tuple[str, str]] = [
    ("{{src_display}} → {{dst_display}}", "{{src_host}} ({{network_local_address}}) → {{dst_host}} ({{network_peer_address}})"),
    ("{{src}} → {{dst}}", "{{src_host}} ({{network_local_address}}) → {{dst_host}} ({{network_peer_address}})"),
    (
        "{{network_local_address}} → {{network_peer_address}}",
        "{{src_host}} ({{network_local_address}}) → {{dst_host}} ({{network_peer_address}})",
    ),
    (
        "{{network_local_address}} \u2192 {{network_peer_address}}",
        "{{src_host}} ({{network_local_address}}) \u2192 {{dst_host}} ({{network_peer_address}})",
    ),
    ("{{dst_display}}", "{{dst_host}} ({{network_peer_address}})"),
    ("{{dst}}", "{{dst_host}} ({{network_peer_address}})"),
    ("{{network_peer_address}}", "{{dst_host}} ({{network_peer_address}})"),
    ("{{src_display}}", "{{src_host}} ({{network_local_address}})"),
    ("{{src}}", "{{src_host}} ({{network_local_address}})"),
    ("{{network_local_address}}", "{{src_host}} ({{network_local_address}})"),
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _max_over_time_core(expr: str) -> tuple[str, str] | None:
    sel_m = METRIC_SELECTOR_RE.search(expr)
    range_m = RANGE_RE.search(expr)
    if not sel_m or not range_m:
        return None
    return sel_m.group(0), range_m.group(1)


def _topk_k(expr: str) -> str | None:
    m = re.search(r"topk\(\s*(\d+)\s*,", expr, re.I)
    return m.group(1) if m else None


def strip_broken_inner_coalesce(expr: str) -> str:
    """Remove invalid label_replace nested inside max_over_time."""
    if "max_over_time(label_replace" not in expr and "max_over_time((label_replace" not in expr:
        return expr
    sel_m = METRIC_SELECTOR_RE.search(expr)
    range_m = RANGE_RE.search(expr)
    if not sel_m or not range_m:
        return expr
    selector = sel_m.group(0)
    range_tok = range_m.group(1)
    start = expr.find("max_over_time(")
    if start < 0:
        return expr
    close = expr.find(f"[{range_tok}]", start)
    if close < 0:
        return expr
    close = expr.find(")", close + len(range_tok) + 2)
    if close < 0:
        return expr
    return expr[:start] + f"max_over_time({selector}[{range_tok}])" + expr[close + 1 :]


def sum_by_before_mot(expr: str) -> str | None:
    """Innermost ``sum by`` that wraps ``max_over_time``."""
    matches = list(
        re.finditer(r"sum\s+by\s*\(([^)]+)\)\s*\(\s*max_over_time", expr, re.I)
    )
    return matches[-1].group(1) if matches else None


def classify_endpoint_expr(expr: str) -> str:
    by = sum_by_before_mot(strip_broken_inner_coalesce(expr))
    if not by:
        m = re.search(r"topk\(\s*\d+\s*,\s*sum\s+by\s*\(([^)]+)\)", expr, re.I)
        by = m.group(1) if m else ""
    raw = {re.sub(r"\s+", "", x.lower()) for x in by.split(",")}
    if "src" in raw and "dst" in raw:
        return "pair"
    if "dst" in raw and "src" not in raw:
        return "dst_only"
    if "src" in raw and "dst" not in raw:
        return "src_only"

    labels = raw - {"src", "dst", "src_display", "dst_display", "src_host", "dst_host"}

    has_local = "network_local_address" in labels
    has_peer = "network_peer_address" in labels
    has_device = "device_name" in labels
    has_proto = "network_protocol_name" in labels

    if has_device and has_proto and has_local and has_peer:
        return "device_pair_proto"
    if has_device and has_local and has_peer:
        return "device_pair"
    if has_local and has_peer:
        return "pair"
    if has_peer:
        return "dst_only"
    if has_local:
        return "src_only"
    return "unknown"


def rebuild_endpoint_expr(expr: str) -> str:
    """Rebuild endpoint topk queries with IP + hostname labels (no label_replace)."""
    core = _max_over_time_core(expr)
    if not core:
        return expr
    selector, range_tok = core
    mot = f"max_over_time({selector}[{range_tok}])"
    k = _topk_k(expr)
    if not k:
        return expr

    kind = classify_endpoint_expr(expr)
    if kind == "device_pair_proto":
        inner = (
            "sum by(device_name, network_local_address, network_peer_address, "
            f"src_host, dst_host, network_protocol_name) ({mot})"
        )
    elif kind == "device_pair":
        inner = (
            "sum by(device_name, network_local_address, network_peer_address, "
            f"src_host, dst_host) ({mot})"
        )
    elif kind == "pair":
        inner = (
            "sum by(network_local_address, network_peer_address, src_host, "
            f"dst_host) ({mot})"
        )
    elif kind == "dst_only":
        inner = f"sum by(network_peer_address, dst_host) ({mot})"
    elif kind == "src_only":
        inner = f"sum by(network_local_address, src_host) ({mot})"
    else:
        return strip_broken_inner_coalesce(expr)

    return f"topk({k}, {inner})"


def patch_expr(expr: str) -> str:
    if not isinstance(expr, str) or "network_io_by_flow_bytes" not in expr:
        return expr

    # Skip panels that aggregate without endpoint dimensions.
    if re.search(
        r"sum\s*\(\s*max_over_time|sum\s+by\s*\(\s*device_name\s*\)\s*\(|"
        r"sum\s+by\s*\(\s*network_(local|peer)_country\s*\)|"
        r"sum\s+by\s*\(\s*network_protocol_name\s*\)",
        expr,
        re.I,
    ):
        return expr

    cleaned = strip_broken_inner_coalesce(expr)
    if _topk_k(cleaned) and _max_over_time_core(cleaned):
        return rebuild_endpoint_expr(cleaned)
    return cleaned


def patch_legend(legend: str) -> str:
    if not isinstance(legend, str) or not legend:
        return legend
    out = legend
    out = out.replace(
        "{{src_host}} ({{src_host}} ({{network_local_address}}))",
        "{{src_host}} ({{network_local_address}})",
    )
    out = out.replace(
        "{{dst_host}} ({{dst_host}} ({{network_peer_address}}))",
        "{{dst_host}} ({{network_peer_address}})",
    )
    if re.search(r"\{\{src_host\}\}.*\{\{network_local_address\}\}", out) or re.search(
        r"\{\{dst_host\}\}.*\{\{network_peer_address\}\}", out
    ):
        return out
    for old, new in LEGEND_REPLACEMENTS:
        out = out.replace(old, new)
    return out


def patch_table_fields(obj: dict[str, Any]) -> int:
    """Add src_host/dst_host column titles on table panels when IPs are present."""
    changes = 0
    opts = obj.get("fieldConfig", {}).get("defaults", {})
    if not isinstance(opts, dict):
        return 0
    by_name = opts.setdefault("custom", {}).get("displayNameFromDS")
    # v2 manifests store overrides under fieldConfig.overrides
    overrides = obj.get("fieldConfig", {}).get("overrides", [])
    if not isinstance(overrides, list):
        return 0
    have = {o.get("matcher", {}).get("options") for o in overrides if isinstance(o, dict)}
    additions = [
        ("src_host", "Source host"),
        ("dst_host", "Dest host"),
    ]
    for field, title in additions:
        if field in have:
            continue
        overrides.append(
            {
                "matcher": {"id": "byName", "options": field},
                "properties": [{"id": "displayName", "value": title}],
            }
        )
        changes += 1
    return changes


def walk_patch(obj: Any) -> tuple[Any, int]:
    changes = 0
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        kind = obj.get("kind")
        for k, v in obj.items():
            if k == "expr" and isinstance(v, str):
                new_v = patch_expr(v)
                if new_v != v:
                    changes += 1
                out[k] = new_v
            elif k == "legendFormat" and isinstance(v, str):
                new_v = patch_legend(v)
                if new_v != v:
                    changes += 1
                out[k] = new_v
            else:
                patched, n = walk_patch(v)
                changes += n
                out[k] = patched
        if kind == "Panel":
            changes += patch_table_fields(out.get("spec", out))
        return out, changes
    if isinstance(obj, list):
        out_list = []
        for v in obj:
            patched, n = walk_patch(v)
            changes += n
            out_list.append(patched)
        return out_list, changes
    return obj, changes


def patch_dashboard(dash: dict) -> dict:
    out = json.loads(json.dumps(dash))
    spec = out.setdefault("spec", {})
    ann = out.setdefault("metadata", {}).setdefault("annotations", {})
    msg = ann.get("grafana.app/message", "")
    if NOTE not in msg:
        ann["grafana.app/message"] = (msg.rstrip() + "\n" + NOTE).strip()

    patched_spec, changes = walk_patch(spec)
    out["spec"] = patched_spec
    out["_patch_stats"] = {"expr_or_legend_changes": changes}
    return out


def http_api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    token = env["GRAFANA_TOKEN"]
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def get_dashboard(env: dict[str, str], uid: str, namespace: str) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{namespace}/dashboards/{uid}"
    status, data = http_api(env, "GET", path)
    if status != 200:
        raise RuntimeError(f"GET {uid} -> {status}: {data}")
    return data


def put_dashboard(env: dict[str, str], uid: str, namespace: str, dash: dict) -> None:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{namespace}/dashboards/{uid}"
    status, existing = http_api(env, "GET", path)
    if status == 200 and isinstance(existing, dict):
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash["metadata"]["resourceVersion"] = rv
    dash.pop("_patch_stats", None)
    status, out = http_api(env, "PUT", path, dash)
    if not (200 <= int(status) < 300):
        raise RuntimeError(f"PUT {uid} -> {status}: {out}")


def parse_gcx_json(raw: str) -> dict:
    start = raw.find('{\n  "apiVersion"')
    if start < 0:
        start = raw.find("{")
    if start < 0:
        raise RuntimeError(f"gcx returned no JSON: {raw[:500]}")
    obj, _ = json.JSONDecoder().raw_decode(raw, start)
    return obj


def gcx_get(context: str, uid: str) -> dict:
    raw = subprocess.check_output(
        ["gcx", "--context", context, "--agent", "dashboards", "get", uid, "-o", "json"],
        stderr=subprocess.STDOUT,
    ).decode("utf-8", errors="replace")
    return parse_gcx_json(raw)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--context", help="gcx context (optional; default HTTP via local/.env)")
    ap.add_argument("--uid", default=DEFAULT_UID)
    ap.add_argument("--namespace", default=DEFAULT_NS)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    uid = args.uid
    namespace = args.namespace

    if args.context:
        dash = gcx_get(args.context, uid)
    else:
        if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
            raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env (or pass --context)")
        dash = get_dashboard(env, uid, namespace)

    layout_kind = dash.get("spec", {}).get("layout", {}).get("kind")
    gen = dash.get("metadata", {}).get("generation", "?")
    print(f"Fetched {uid} layout={layout_kind} generation={gen}")

    patched = patch_dashboard(dash)
    changes = patched.pop("_patch_stats", {}).get("expr_or_legend_changes", 0)
    print(f"Patched {changes} expr/legend field(s)")

    out_path = OUT if uid == DEFAULT_UID else ROOT / ".dash-payloads" / f"{uid}-hostname-patched.json"
    out_path.write_text(json.dumps(patched, indent=2), encoding="utf-8")
    print(f"Wrote {out_path}")

    if args.dry_run:
        print("dry-run: not pushing to Grafana")
        return 0

    if args.context:
        tmp = Path(tempfile.gettempdir()) / f"{uid}-hostname-patched.json"
        tmp.write_text(json.dumps(patched, indent=2), encoding="utf-8")
        subprocess.run(
            ["gcx", "--context", args.context, "--agent", "dashboards", "update", uid, "-f", str(tmp)],
            check=True,
        )
    else:
        put_dashboard(env, uid, namespace, patched)

    base = (env.get("GRAFANA_URL") or "https://marcnetterfield1.grafana.net").rstrip("/")
    print(f"Patched {base}/d/{uid}")
    kind = patched.get("spec", {}).get("layout", {}).get("kind")
    print(f"post-patch layout={kind} elements={len(patched.get('spec', {}).get('elements') or {})}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
