#!/usr/bin/env python3
"""Rewrite BGP PromQL from Alloy-renamed srl_bgp_* to gnmic OTEL names.

Also maps:
  job="integrations/gnmi"  -> job="gnmic"
  device= / device=~       -> source= / source=~  (only on BGP-related exprs)
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BGP_PREFIX = (
    "gnmi_bgp_neighbors_srl_nokia_network_instance:"
    "network_instance_protocols_srl_nokia_bgp:bgp_neighbor_"
)

# Short names that Netterfield / older dashboards may use
ALIAS = {
    "srl_bgp_neighbor_received_updates": "received_messages_total_updates",
    "srl_bgp_neighbor_sent_updates": "sent_messages_total_updates",
}

SRL_BGP_RE = re.compile(r"srl_bgp_neighbor_([A-Za-z0-9_]+)")


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def api(env: dict[str, str], method: str, path: str, body: dict | None = None):
    url = env["GRAFANA_URL"].rstrip("/") + path
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:800]}") from e


def _split_metric_selector(expr: str, start: int) -> tuple[str, str, int] | None:
    """At expr[start] beginning a metric{labels}, return (metric, labels_inner, end_idx)."""
    m = re.match(r"([A-Za-z_][A-Za-z0-9_:]*)(\{)?", expr[start:])
    if not m:
        return None
    metric = m.group(1)
    if m.group(2) != "{":
        return metric, "", start + len(metric)
    i = start + len(metric) + 1
    depth = 1
    while i < len(expr) and depth:
        if expr[i] == "{":
            depth += 1
        elif expr[i] == "}":
            depth -= 1
        elif expr[i] in ('"', "'"):
            q = expr[i]
            i += 1
            while i < len(expr) and expr[i] != q:
                if expr[i] == "\\":
                    i += 1
                i += 1
        i += 1
    labels = expr[start + len(metric) + 1 : i - 1]
    return metric, labels, i


def _rewrite_labels(labels: str) -> str:
    labels = labels.replace('job="integrations/gnmi"', 'job="gnmic"')
    labels = labels.replace("job='integrations/gnmi'", "job='gnmic'")
    # device -> source (Netterfield)
    labels = re.sub(r"\bdevice\s*=", "source=", labels)
    labels = re.sub(r"\bdevice\s*=~", "source=~", labels)
    if "job=" not in labels and "job=~" not in labels:
        labels = ('job="gnmic", ' + labels) if labels.strip() else 'job="gnmic"'
    return labels


def rewrite_expr(expr: str) -> tuple[str, bool]:
    if "srl_bgp_neighbor" not in expr and "integrations/gnmi" not in expr:
        # still fix bare job on up{job=integrations/gnmi} only if mixed with bgp context — skip
        return expr, False
    if "srl_bgp_neighbor" not in expr:
        return expr, False

    out: list[str] = []
    i = 0
    changed = False
    while i < len(expr):
        if expr.startswith("srl_bgp_neighbor_", i):
            parsed = _split_metric_selector(expr, i)
            if not parsed:
                out.append(expr[i])
                i += 1
                continue
            metric, labels, end = parsed
            if metric in ALIAS:
                suffix = ALIAS[metric]
            else:
                m = SRL_BGP_RE.fullmatch(metric)
                if not m:
                    out.append(expr[i])
                    i += 1
                    continue
                suffix = m.group(1)
            full = BGP_PREFIX + suffix
            new_labels = _rewrite_labels(labels)
            out.append('{' + f'__name__="{full}", {new_labels}' + '}')
            i = end
            changed = True
            continue
        out.append(expr[i])
        i += 1
    new = "".join(out)
    # catch leftover job on non-metric parts already handled inside labels
    return new, changed or new != expr


def walk(obj, hits: list, path: str = "") -> int:
    n = 0
    if isinstance(obj, dict):
        if "expr" in obj and isinstance(obj["expr"], str):
            new, ch = rewrite_expr(obj["expr"])
            if ch:
                hits.append({"path": path, "old": obj["expr"], "new": new})
                obj["expr"] = new
                n += 1
        if "query" in obj and isinstance(obj["query"], str) and "srl_bgp" in obj["query"]:
            new, ch = rewrite_expr(obj["query"])
            # label_values(..., device) -> ..., source
            new2 = re.sub(
                r"(label_values\s*\(.+),\s*device\s*\)",
                r"\1, source)",
                new,
                flags=re.DOTALL,
            )
            if new2 != new:
                ch = True
                new = new2
            if ch:
                hits.append({"path": path + ".query", "old": obj["query"], "new": new})
                obj["query"] = new
                n += 1
        # templating definition
        if "definition" in obj and isinstance(obj["definition"], str) and "srl_bgp" in obj["definition"]:
            new, ch = rewrite_expr(obj["definition"])
            new2 = re.sub(
                r"(label_values\s*\(.+),\s*device\s*\)",
                r"\1, source)",
                new,
                flags=re.DOTALL,
            )
            if new2 != new:
                ch = True
                new = new2
            if ch:
                hits.append({"path": path + ".definition", "old": obj["definition"], "new": new})
                obj["definition"] = new
                n += 1
        for k, v in obj.items():
            n += walk(v, hits, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            n += walk(v, hits, f"{path}[{i}]")
    return n


def patch_uid(env: dict, uid: str) -> dict:
    meta = api(env, "GET", f"/api/dashboards/uid/{uid}")
    dash = meta["dashboard"]
    hits: list = []
    n = walk(dash, hits)
    if n == 0:
        return {"uid": uid, "title": dash.get("title"), "changed": 0, "hits": []}
    payload = {
        "dashboard": dash,
        "folderUid": meta.get("meta", {}).get("folderUid") or "",
        "message": "Rewrite BGP queries to gnmic OTEL metric names (job=gnmic, source)",
        "overwrite": True,
    }
    api(env, "POST", "/api/dashboards/db", payload)
    return {
        "uid": uid,
        "title": dash.get("title"),
        "changed": n,
        "samples": hits[:8],
    }


def main():
    env = load_env()
    uids = [
        "net-o11y-bgp-status",
        "net-o11y-device-details",
        "net-o11y-topology",
        "mah4cjt",
    ]
    report = []
    for uid in uids:
        try:
            report.append(patch_uid(env, uid))
            print(f"OK {uid}: {report[-1]['changed']} exprs")
        except Exception as e:
            print(f"FAIL {uid}: {e}")
            report.append({"uid": uid, "error": str(e)})
    out = ROOT / ".dash-payloads" / "bgp-otel-patch-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print("wrote", out)


if __name__ == "__main__":
    main()
