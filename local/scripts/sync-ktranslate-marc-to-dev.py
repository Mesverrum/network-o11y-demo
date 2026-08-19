#!/usr/bin/env python3
"""Compare + sync ktranslate 00–04 dashboards: marcnetterfield1 → networko11ydev.

Uses GRAFANA_URL/TOKEN (source) and GRAFANA_URL_2/TOKEN_2 (target) from local/.env.
v2 App Platform API — preserves TabsLayout.

Usage:
  python3 local/scripts/sync-ktranslate-marc-to-dev.py            # compare + sync
  python3 local/scripts/sync-ktranslate-marc-to-dev.py --compare  # compare only
"""
from __future__ import annotations

import argparse
import copy
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "sync-marc-to-dev"

UIDS = [
    "ktranslate-architecture",
    "ktranslate-health",
    "ktranslate-flow-summary",
    "ktranslate-device-summary",
    "ktranslate-device-details",
]

# Skip while iterating on Device Details experiments (marc-only).
# Override: python3 …sync-ktranslate-marc-to-dev.py --include-device-details
DEFAULT_SKIP = {"ktranslate-device-details"}

SRC_NS = "stacks-1061129"
DST_NS = "stacks-1544961"
# Marc's personal ktranslate folder on networko11ydev (NOT network-lab — that's Colin's)
FOLDER = "fxgv9q"

# Remap stack-specific datasource names/uids embedded in manifests.
REPLACEMENTS = {
    "grafanacloud-marcnetterfield1-prom": "grafanacloud-networko11ydev-prom",
    "grafanacloud-marcnetterfield1-logs": "grafanacloud-networko11ydev-logs",
    "grafanacloud-marcnetterfield1-traces": "grafanacloud-networko11ydev-traces",
    "grafanacloud-marcnetterfield1-alert-state-history": "grafanacloud-networko11ydev-alert-state-history",
    # common short UIDs on marc that may appear in panels
    '"uid":"grafanacloud-prom"': '"uid":"grafanacloud-prom"',  # often shared name; leave
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
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
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:3000]}
        return e.code, payload


def get_dash(base: str, token: str, ns: str, uid: str) -> dict | None:
    status, data = api(base, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{uid}")
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"GET {uid} on {base} -> {status}: {data}")
    return data


def meta_summary(dash: dict | None) -> dict[str, Any]:
    if not dash:
        return {"exists": False}
    meta = dash.get("metadata") or {}
    spec = dash.get("spec") or {}
    return {
        "exists": True,
        "title": spec.get("title"),
        "generation": meta.get("generation"),
        "resourceVersion": meta.get("resourceVersion"),
        "layout": (spec.get("layout") or {}).get("kind"),
        "updated": (meta.get("annotations") or {}).get("grafana.app/updatedTimestamp")
        or (meta.get("annotations") or {}).get("grafana.app/updatedBy"),
        "elements": len(spec.get("elements") or {}),
    }


def remap(obj: dict) -> dict:
    text = json.dumps(obj, separators=(",", ":"))
    for old, new in REPLACEMENTS.items():
        if old != new:
            text = text.replace(old, new)
    return json.loads(text)


def prepare_for_target(src: dict, uid: str, existing: dict | None) -> dict:
    dash = remap(copy.deepcopy(src))
    meta = dash.setdefault("metadata", {})
    meta["name"] = uid
    meta["namespace"] = DST_NS
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    # Drop managed fields / status from source
    dash.pop("status", None)
    meta.pop("managedFields", None)

    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = f"Sync from marcnetterfield1 live ({uid})"

    if existing:
        erv = (existing.get("metadata") or {}).get("resourceVersion")
        if erv:
            meta["resourceVersion"] = erv
        elabels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in elabels:
            meta.setdefault("labels", {})["grafana.app/deprecatedInternalID"] = elabels[
                "grafana.app/deprecatedInternalID"
            ]
    return dash


def ensure_folder(base: str, token: str) -> None:
    status, data = api(base, token, "GET", f"/api/folders/{FOLDER}")
    if status == 200:
        title = (data or {}).get("title")
        print(f"folder {FOLDER} exists on target ({title!r})")
        return
    raise SystemExit(
        f"target folder uid={FOLDER} missing on {base} (HTTP {status}). "
        "Do not fall back to network-lab — that folder is reserved."
    )


def upsert(base: str, token: str, uid: str, dash: dict, existing: dict | None) -> str:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{DST_NS}/dashboards/{uid}"
    create = f"/apis/dashboard.grafana.app/v2/namespaces/{DST_NS}/dashboards"
    if existing:
        status, data = api(base, token, "PUT", path, dash)
        if status in (200, 201):
            return f"updated gen={(data or {}).get('metadata', {}).get('generation')}"
        raise RuntimeError(f"PUT {uid} -> {status}: {data}")
    # create
    dash["metadata"].pop("resourceVersion", None)
    status, data = api(base, token, "POST", create, dash)
    if status in (200, 201):
        return f"created gen={(data or {}).get('metadata', {}).get('generation')}"
    # race: exists now
    if status == 409:
        existing2 = get_dash(base, token, DST_NS, uid)
        dash2 = prepare_for_target(dash, uid, existing2)
        # re-get source already remapped in dash - use dash with rv from existing2
        if existing2:
            dash2 = prepare_for_target(
                # undo: dash is already prepared; just set rv
                json.loads(json.dumps(dash)),
                uid,
                existing2,
            )
        status, data = api(base, token, "PUT", path, dash2)
        if status in (200, 201):
            return f"updated-after-409 gen={(data or {}).get('metadata', {}).get('generation')}"
    raise RuntimeError(f"POST {uid} -> {status}: {data}")


def list_datasources(base: str, token: str) -> list[dict]:
    status, data = api(base, token, "GET", "/api/datasources")
    if status != 200:
        return []
    return data if isinstance(data, list) else []


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compare", action="store_true", help="compare only, do not sync")
    parser.add_argument(
        "--include-device-details",
        action="store_true",
        help="also sync ktranslate-device-details (default: skip — marc-only experiments)",
    )
    args = parser.parse_args()

    env = load_env()
    src_url = env.get("GRAFANA_URL") or ""
    src_tok = env.get("GRAFANA_TOKEN") or ""
    dst_url = env.get("GRAFANA_URL_2") or ""
    dst_tok = env.get("GRAFANA_TOKEN_2") or ""
    if not all([src_url, src_tok, dst_url, dst_tok]):
        print("Need GRAFANA_URL/TOKEN and GRAFANA_URL_2/TOKEN_2 in local/.env", file=sys.stderr)
        return 1

    print(f"source: {src_url} (ns={SRC_NS})")
    print(f"target: {dst_url} (ns={DST_NS})")
    skip = set() if args.include_device_details else set(DEFAULT_SKIP)
    if skip:
        print(f"skipping (marc-only iterate): {', '.join(sorted(skip))}")

    # Discover target default prom/logs names for sanity
    dst_ds = list_datasources(dst_url, dst_tok)
    print(
        "target datasources:",
        [f"{d.get('name')}({d.get('uid')})" for d in dst_ds if d.get("type") in ("prometheus", "loki", "tempo")][:12],
    )

    rows = []
    for uid in UIDS:
        if uid in skip:
            print(f"\n{uid}\n  SKIP: marc-only (pass --include-device-details to sync)")
            continue
        src = get_dash(src_url, src_tok, SRC_NS, uid)
        dst = get_dash(dst_url, dst_tok, DST_NS, uid)
        ss, ds = meta_summary(src), meta_summary(dst)
        same_gen = ss.get("generation") == ds.get("generation") and ss.get("exists") and ds.get("exists")
        same_title = ss.get("title") == ds.get("title")
        print(f"\n{uid}")
        print(f"  marc:  exists={ss.get('exists')} gen={ss.get('generation')} layout={ss.get('layout')} title={ss.get('title')!r} elements={ss.get('elements')}")
        print(f"  dev:   exists={ds.get('exists')} gen={ds.get('generation')} layout={ds.get('layout')} title={ds.get('title')!r} elements={ds.get('elements')}")
        if not ss.get("exists"):
            print("  SKIP: missing on marc")
            continue
        drift = (not ds.get("exists")) or (ss.get("elements") != ds.get("elements")) or (not same_title)
        # generation alone is not comparable across stacks; use element count + title + layout
        if ds.get("exists") and ss.get("layout") == ds.get("layout") and ss.get("elements") == ds.get("elements") and same_title:
            # still sync — user asked to sync versions from marc; element count equal may still drift in queries
            drift = True  # force sync of marc content
        rows.append((uid, src, dst, drift))

    if args.compare:
        print("\n--compare only; not writing")
        return 0

    ensure_folder(dst_url, dst_tok)
    OUT.mkdir(parents=True, exist_ok=True)

    for uid, src, dst, _drift in rows:
        prepared = prepare_for_target(src, uid, dst)
        (OUT / f"{uid}.src.json").write_text(json.dumps(src, indent=2), encoding="utf-8")
        (OUT / f"{uid}.dst.json").write_text(json.dumps(prepared, indent=2), encoding="utf-8")
        try:
            result = upsert(dst_url, dst_tok, uid, prepared, dst)
            print(f"SYNC {uid}: {result}")
        except Exception as e:
            print(f"FAIL {uid}: {e}", file=sys.stderr)
            return 1

        # verify layout preserved
        after = get_dash(dst_url, dst_tok, DST_NS, uid)
        al = ((after or {}).get("spec") or {}).get("layout", {}).get("kind")
        sl = (src.get("spec") or {}).get("layout", {}).get("kind")
        ae = len(((after or {}).get("spec") or {}).get("elements") or {})
        se = len((src.get("spec") or {}).get("elements") or {})
        print(f"  verify layout {al} (want {sl}) elements {ae} (want {se})")
        if al != sl or ae != se:
            print(f"FAIL {uid}: layout/elements mismatch after sync", file=sys.stderr)
            return 1

    print("\nDone. Open https://networko11ydev.grafana.net/dashboards/f/fxgv9q")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
