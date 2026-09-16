#!/usr/bin/env python3
"""Clone live 04 Device Details to an Alloy rewrite board (TabsLayout-safe v2).

Source: ktranslate-device-details (pulled live).
Dest:   alloy-device-details

Does not rewrite queries. Panel retargeting is a follow-up (one panel at a time).

Usage:
  python local/scripts/clone-alloy-device-details.py
  python local/scripts/clone-alloy-device-details.py --dry-run
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-device-details"
NS = os.environ.get("GRAFANA_NAMESPACE", "stacks-1061129")
SRC_UID = "ktranslate-device-details"
DST_UID = "alloy-device-details"
DST_TITLE = "A4. Alloy Device Details"


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
        "Clone of ktranslate-device-details for Alloy SNMP/flow/trap/syslog rewrite"
    )

    spec = out.setdefault("spec", {})
    spec["title"] = DST_TITLE
    spec["description"] = (
        "Device-level Alloy SNMP, flow, traps, and syslog "
        "(`snmp_*` job=alloy-snmp, alloy-netflow, alloy-snmptrap, alloy-syslog)."
    )
    tags = list(spec.get("tags") or [])
    for t in ("alloy", "network-lab", "network-o11y", "snmp", "in-progress"):
        if t not in tags:
            tags.append(t)
    spec["tags"] = tags

    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from alloy_dash_nav import apply_alloy_nav_links, scrub_spec_prose

    apply_alloy_nav_links(spec, DST_UID)
    scrub_spec_prose(spec)

    layout = spec.get("layout") or {}
    if layout.get("kind") != "TabsLayout":
        raise RuntimeError(f"expected TabsLayout, got {layout.get('kind')}")
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
    if kind != "TabsLayout":
        raise RuntimeError("TabsLayout lost — restore from version history")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        print("GRAFANA_URL and GRAFANA_TOKEN required in local/.env", file=sys.stderr)
        return 1

    src_path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{SRC_UID}"
    code, src = api(env, "GET", src_path)
    if code != 200 or not isinstance(src, dict):
        print(f"GET {SRC_UID} failed HTTP {code}: {src}", file=sys.stderr)
        return 1

    src_kind = ((src.get("spec") or {}).get("layout") or {}).get("kind")
    src_gen = (src.get("metadata") or {}).get("generation")
    src_elems = len((src.get("spec") or {}).get("elements") or {})
    print(f"source {SRC_UID} layout={src_kind} generation={src_gen} elements={src_elems}")
    if src_kind != "TabsLayout":
        print("refusing to clone a non-TabsLayout board", file=sys.stderr)
        return 1

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{SRC_UID}-live.json").write_text(json.dumps(src, indent=2), encoding="utf-8")

    clone = clone_manifest(src)
    (OUT / f"{DST_UID}-pre-upsert.json").write_text(
        json.dumps(clone, indent=2), encoding="utf-8"
    )
    if args.dry_run:
        print(f"dry-run: wrote {OUT / f'{DST_UID}-pre-upsert.json'}")
        return 0

    out = upsert(env, clone)
    (OUT / f"{DST_UID}-live.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"wrote {OUT / f'{DST_UID}-live.json'}")
    base = env["GRAFANA_URL"].rstrip("/")
    print(f"open {base}/d/{DST_UID}?var-instance=spine1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
