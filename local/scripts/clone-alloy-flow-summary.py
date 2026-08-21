#!/usr/bin/env python3
"""Clone live 02 Flow Summary and retarget queries to Alloy-native flow.

Source: ktranslate-flow-summary (pulled live, RowsLayout).
Dest:   alloy-flow-summary

Alloy contract (see render-alloy-netflow.sh):
  alloy_network_io_by_flow_bytes{integration="alloy-netflow"}
  cumulative Sum → rate() / increase(), not ktranslate max_over_time / * 8 / 60
  Same OTel 5-tuple as ktranslate after rename: network_local_address / network_peer_address
  (+ ports), network_transport, device_name, src_device, dst_device, src_host, dst_host.

Geo / L7 app-id are still ktranslate-only. PTR hostnames use Alloy udp_host_cache_size
(same LRU as loki.source.syslog); catalog names fill src_host when PTR misses.

Usage:
  python local/scripts/clone-alloy-flow-summary.py
  python local/scripts/clone-alloy-flow-summary.py --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-flow-summary"
NS = os.environ.get("GRAFANA_NAMESPACE", "stacks-1061129")
SRC_UID = "ktranslate-flow-summary"
DST_UID = "alloy-flow-summary"
DST_TITLE = "A2. Alloy Flow Summary"
METRIC = "alloy_network_io_by_flow_bytes"
INTEGRATION = "alloy-netflow"

LABELS = [
    ("network_protocol_name", "network_transport"),
]
# Live Alloy board briefly used receiver names before the local/peer rename.
SOURCE_TO_OTEL = [
    ("source_address", "network_local_address"),
    ("destination_address", "network_peer_address"),
    ("source_port", "network_local_port"),
    ("destination_port", "network_peer_port"),
]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("GRAFANA_")})
    return env


def api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def rewrite_expr(expr: str) -> str:
    if "network_io_by_flow_bytes" not in expr and "alloy_network_io_by_flow_bytes" not in expr:
        return expr
    out = expr.replace("network_io_by_flow_bytes", METRIC)
    out = re.sub(
        r"\b" + re.escape(METRIC) + r"\{(?![^}]*integration=)",
        f'{METRIC}{{integration="{INTEGRATION}",',
        out,
    )
    out = re.sub(
        rf"label_values\({METRIC},",
        'label_values(' + METRIC + '{integration="' + INTEGRATION + '"},',
        out,
    )
    # Avoid doubling the selector if label_values already got {integration}
    out = out.replace(
        f'{METRIC}{{integration="{INTEGRATION}"}}{{integration="{INTEGRATION}"}}',
        f'{METRIC}{{integration="{INTEGRATION}"}}',
    )
    for old, new in LABELS:
        out = re.sub(rf"\b{old}\b", new, out)
    out = re.sub(
        rf"max_over_time\(({METRIC}\{{.*?\}})\[\$__range\]\)",
        r"increase(\1[$__range])",
        out,
        flags=re.S,
    )
    out = re.sub(
        rf"max_over_time\(({METRIC}\{{.*?\}})\[\$__rate_interval\]\)",
        r"rate(\1[$__rate_interval])",
        out,
        flags=re.S,
    )
    out = re.sub(
        rf"max_over_time\(({METRIC}\{{.*?\}})\[\$__interval\]\)",
        r"rate(\1[$__interval])",
        out,
        flags=re.S,
    )
    out = re.sub(rf"\b{re.escape(METRIC)}\b\s*\*\s*8\s*/\s*60", f"rate({METRIC}[$__rate_interval]) * 8", out)
    return out


def rewrite_source_to_otel(text: str) -> str:
    out = text
    for old, new in SOURCE_TO_OTEL:
        out = re.sub(rf"\b{old}\b", new, out)
    return out


def walk_source_to_otel(obj: Any) -> int:
    n = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k in ("expr", "query", "legendFormat") and isinstance(v, str):
                nv = rewrite_source_to_otel(v)
                if nv != v:
                    obj[k] = nv
                    n += 1
            else:
                n += walk_source_to_otel(v)
    elif isinstance(obj, list):
        for v in obj:
            n += walk_source_to_otel(v)
    return n


def rewrite_legend(text: str) -> str:
    out = text
    for old, new in LABELS:
        out = out.replace("{{" + old + "}}", "{{" + new + "}}")
    return out


def walk_rewrite(obj: Any) -> int:
    n = 0
    if isinstance(obj, dict):
        for k, v in list(obj.items()):
            if k == "expr" and isinstance(v, str):
                nv = rewrite_expr(v)
                if nv != v:
                    obj[k] = nv
                    n += 1
            elif k == "query" and isinstance(v, str):
                nv = rewrite_expr(v)
                if nv != v:
                    obj[k] = nv
                    n += 1
            elif k == "legendFormat" and isinstance(v, str):
                nv = rewrite_legend(v)
                if nv != v:
                    obj[k] = nv
                    n += 1
            else:
                n += walk_rewrite(v)
    elif isinstance(obj, list):
        for v in obj:
            n += walk_rewrite(v)
    return n


def clone_manifest(doc: dict) -> dict:
    out = copy.deepcopy(doc)
    meta = out.setdefault("metadata", {})
    folder = (meta.get("annotations") or {}).get("grafana.app/folder")
    meta["name"] = DST_UID
    meta["namespace"] = NS
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    labels = meta.setdefault("labels", {})
    labels.pop("grafana.app/deprecatedInternalID", None)
    ann = meta.setdefault("annotations", {})
    if folder:
        ann["grafana.app/folder"] = folder
    ann["grafana.app/message"] = (
        "Clone of ktranslate-flow-summary retargeted to alloy_network_io_by_flow_bytes"
    )

    spec = out.setdefault("spec", {})
    spec["title"] = DST_TITLE
    spec["description"] = (
        "Clone of 02. Network Flow Summary for Alloy-native flow "
        "(otelcol.receiver.netflow → signaltometrics). "
        "Metric: alloy_network_io_by_flow_bytes{integration=\"alloy-netflow\"}. "
        "Counters: rate() / increase(), not ktranslate max_over_time or * 8 / 60. "
        "No MaxMind geo or ktranslate L7 app-id on this path yet. "
        "src_host/dst_host come from Alloy reverse-DNS (udp_host_cache_size) "
        "with catalog names as fallback."
    )
    tags = list(spec.get("tags") or [])
    for t in ("alloy", "network-lab", "netflow", "in-progress"):
        if t not in tags:
            tags.append(t)
    spec["tags"] = tags

    links = list(spec.get("links") or [])
    extra = {
        "title": "Original 02 Flow Summary",
        "url": "/d/ktranslate-flow-summary",
        "type": "link",
        "icon": "dashboard",
        "tooltip": "Unmodified ktranslate Flow Summary",
        "tags": [],
        "asDropdown": False,
        "targetBlank": False,
        "includeVars": True,
        "keepTime": True,
    }
    titles = {ln.get("title") for ln in links if isinstance(ln, dict)}
    if extra["title"] not in titles:
        links.insert(0, extra)
    spec["links"] = links

    layout = spec.get("layout") or {}
    if layout.get("kind") != "RowsLayout":
        raise RuntimeError(f"expected RowsLayout, got {layout.get('kind')}")

    changed = walk_rewrite(spec)
    print(f"rewrote {changed} query/legend fields")
    return out


def upsert(env: dict[str, str], dash: dict) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{DST_UID}"
    code, existing = api(env, "GET", path)
    body = copy.deepcopy(dash)
    if code == 200 and isinstance(existing, dict):
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            body.setdefault("metadata", {})["resourceVersion"] = rv
        labels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in labels:
            body.setdefault("metadata", {}).setdefault("labels", {})[
                "grafana.app/deprecatedInternalID"
            ] = labels["grafana.app/deprecatedInternalID"]
        code2, out = api(env, "PUT", path, body)
        action = "updated"
    else:
        body.get("metadata", {}).get("labels", {}).pop(
            "grafana.app/deprecatedInternalID", None
        )
        create = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards"
        code2, out = api(env, "POST", create, body)
        action = "created"
        if code2 == 409:
            code, existing = api(env, "GET", path)
            rv = (existing.get("metadata") or {}).get("resourceVersion")
            if rv:
                body.setdefault("metadata", {})["resourceVersion"] = rv
            code2, out = api(env, "PUT", path, body)
            action = "updated"
    if code2 not in (200, 201):
        raise RuntimeError(f"{action} failed HTTP {code2}: {out}")
    kind = ((out or {}).get("spec") or {}).get("layout", {}).get("kind")
    gen = ((out or {}).get("metadata") or {}).get("generation")
    print(f"{action} {DST_UID} layout={kind} generation={gen}")
    if kind != "RowsLayout":
        raise RuntimeError("RowsLayout lost — restore from version history")
    return out


def self_check() -> None:
    samples = {
        'sum by(device_name) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}"}[$__range]))':
        f'sum by(device_name) (increase({METRIC}{{integration="{INTEGRATION}",device_name=~"${{device_name:pipe}}"}}[$__range]))',
        'sum by(network_protocol_name) (max_over_time(network_io_by_flow_bytes{network_local_address=~"${src_addr:pipe}"}[$__rate_interval]))':
        f'sum by(network_transport) (rate({METRIC}{{integration="{INTEGRATION}",network_local_address=~"${{src_addr:pipe}}"}}[$__rate_interval]))',
        "label_values(network_io_by_flow_bytes,src_host)":
        'label_values(' + METRIC + '{integration="' + INTEGRATION + '"},src_host)',
    }
    for src, expect in samples.items():
        got = rewrite_expr(src)
        if got != expect:
            raise RuntimeError(f"rewrite mismatch\n  in: {src}\n  got: {got}\n  exp: {expect}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--fix-live",
        action="store_true",
        help="Retarget live alloy-flow-summary source_* labels to network.local/peer",
    )
    args = ap.parse_args()
    self_check()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        print("GRAFANA_URL and GRAFANA_TOKEN required", file=sys.stderr)
        return 1

    if args.fix_live:
        path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{DST_UID}"
        code, doc = api(env, "GET", path)
        if code != 200 or not isinstance(doc, dict):
            print(f"GET {DST_UID} failed HTTP {code}: {doc}", file=sys.stderr)
            return 1
        kind = ((doc.get("spec") or {}).get("layout") or {}).get("kind")
        gen = (doc.get("metadata") or {}).get("generation")
        print(f"live {DST_UID} layout={kind} generation={gen}")
        if kind != "RowsLayout":
            print("refusing to patch a non-RowsLayout board", file=sys.stderr)
            return 1
        n = walk_source_to_otel(doc.get("spec") or {})
        print(f"rewrote {n} source_* → network.local/peer fields")
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{DST_UID}-fix-live.json").write_text(
            json.dumps(doc, indent=2), encoding="utf-8"
        )
        if args.dry_run:
            print("dry-run; not writing")
            return 0
        upsert(env, doc)
        return 0

    src_path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{SRC_UID}"
    code, src = api(env, "GET", src_path)
    if code != 200 or not isinstance(src, dict):
        print(f"GET {SRC_UID} failed HTTP {code}: {src}", file=sys.stderr)
        return 1

    src_kind = ((src.get("spec") or {}).get("layout") or {}).get("kind")
    src_gen = (src.get("metadata") or {}).get("generation")
    print(f"source {SRC_UID} layout={src_kind} generation={src_gen}")
    if src_kind != "RowsLayout":
        print("refusing to clone a non-RowsLayout board", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{SRC_UID}-live.json").write_text(json.dumps(src, indent=2), encoding="utf-8")

    clone = clone_manifest(src)
    (OUT / f"{DST_UID}-pre-upsert.json").write_text(
        json.dumps(clone, indent=2), encoding="utf-8"
    )
    leftover = json.dumps(clone.get("spec") or {})
    if "network_io_by_flow_bytes" in leftover and "alloy_network_io_by_flow_bytes" in leftover:
        # descriptions may mention the old name; queries must not
        pass
    query_blob = json.dumps(
        [
            q
            for q in leftover.split("network_io_by_flow_bytes")
            if False
        ]
    )
    # Fail if any PromQL still uses the ktranslate metric name.
    exprs = []

    def collect(obj: Any) -> None:
        if isinstance(obj, dict):
            if isinstance(obj.get("expr"), str):
                exprs.append(obj["expr"])
            if isinstance(obj.get("query"), str):
                exprs.append(obj["query"])
            for v in obj.values():
                collect(v)
        elif isinstance(obj, list):
            for v in obj:
                collect(v)

    collect(clone.get("spec") or {})
    leftover_q = [e for e in exprs if "network_io_by_flow_bytes" in e and not e.startswith("alloy_")]
    leftover_q = [e for e in exprs if re.search(r"(?<!alloy_)network_io_by_flow_bytes", e)]
    if leftover_q:
        print("leftover ktranslate flow exprs:", leftover_q[:5], file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"dry-run: wrote {OUT / f'{DST_UID}-pre-upsert.json'}")
        return 0

    out = upsert(env, clone)
    (OUT / f"{DST_UID}-live.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {OUT / f'{DST_UID}-live.json'}")
    print(f"open {env['GRAFANA_URL'].rstrip('/')}/d/{DST_UID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
