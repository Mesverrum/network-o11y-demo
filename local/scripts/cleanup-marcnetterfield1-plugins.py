#!/usr/bin/env python3
"""List/remove Cloud-managed plugins on marcnetterfield1 ONLY.

Uses Grafana Cloud API (GCOM), not the instance API — works even when the
stack is slow to boot.

Requires a Cloud access policy token with stack-plugins:read/delete scoped to
marcnetterfield1. Pass via env (never commit tokens):

  export MARC_GCOM_TOKEN='glc_...'
  python3 scripts/cleanup-marcnetterfield1-plugins.py --list
  python3 scripts/cleanup-marcnetterfield1-plugins.py --remove-all --confirm-marcnetterfield1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

# Hard-coded — this script must never target another stack.
STACK = "marcnetterfield1"
EXPECTED_INSTANCE_URL = "https://marcnetterfield1.grafana.net"
GCOM = "https://grafana.com/api"


def token() -> str:
    tok = os.environ.get("MARC_GCOM_TOKEN", "").strip()
    if not tok:
        raise SystemExit(
            "Set MARC_GCOM_TOKEN to a Cloud access policy token for marcnetterfield1 "
            "(stack-plugins:read + stack-plugins:delete)."
        )
    return tok


def gcom(method: str, path: str, tok: str, retries: int = 5):
    for attempt in range(retries):
        req = urllib.request.Request(
            GCOM + path,
            method=method,
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/json",
                "User-Agent": "marcnetterfield1-plugin-cleanup",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read().decode()
                return resp.status, json.loads(raw) if raw else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode(errors="replace")
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw[:500]}
            if e.code == 429 and attempt + 1 < retries:
                time.sleep(2 * (attempt + 1))
                continue
            return e.code, payload
    return 0, {}


def list_plugins(tok: str) -> list[dict]:
    status, out = gcom("GET", f"/instances/{STACK}/plugins", tok)
    if status != 200:
        raise SystemExit(f"list failed http={status} {json.dumps(out)[:800]}")
    items = out.get("items", out if isinstance(out, list) else [])
    bad = [p for p in items if p.get("instanceUrl") != EXPECTED_INSTANCE_URL]
    if bad:
        raise SystemExit(
            f"ABORT: {len(bad)} plugin(s) have unexpected instanceUrl "
            f"(expected {EXPECTED_INSTANCE_URL})"
        )
    return items


def delete_plugin(tok: str, slug: str) -> tuple[int, dict]:
    return gcom("DELETE", f"/instances/{STACK}/plugins/{slug}", tok)


def main() -> int:
    ap = argparse.ArgumentParser(description=f"Plugin cleanup for {STACK} only")
    ap.add_argument("--list", action="store_true", help="list installed plugins")
    ap.add_argument("--remove-all", action="store_true", help="remove every installed plugin")
    ap.add_argument("--remove", action="append", default=[], metavar="SLUG")
    ap.add_argument(
        "--confirm-marcnetterfield1",
        action="store_true",
        help="required safety flag for any delete operation",
    )
    ap.add_argument("--delay", type=float, default=0.75, help="seconds between deletes")
    args = ap.parse_args()

    tok = token()
    items = list_plugins(tok)
    print(f"stack={STACK} url={EXPECTED_INSTANCE_URL} plugins={len(items)}")

    for p in sorted(items, key=lambda x: x.get("pluginSlug", "")):
        print(f"  {p.get('pluginSlug')}  ({p.get('pluginName', '').strip()})  v{p.get('version', '')}")

    targets = list(args.remove)
    if args.remove_all:
        targets.extend(p["pluginSlug"] for p in items)

    seen: set[str] = set()
    targets = [t for t in targets if t and not (t in seen or seen.add(t))]

    if not targets:
        return 0

    if not args.confirm_marcnetterfield1:
        raise SystemExit(
            f"Refusing to delete {len(targets)} plugin(s) without --confirm-marcnetterfield1"
        )

    ok = fail = 0
    for i, slug in enumerate(targets, 1):
        status, out = delete_plugin(tok, slug)
        if 200 <= status < 300:
            ok += 1
            print(f"deleted {slug}")
        else:
            fail += 1
            print(f"FAILED {slug} http={status} {json.dumps(out)[:200]}")
        if i < len(targets):
            time.sleep(max(0.0, args.delay))

    remaining = len(list_plugins(tok))
    print(f"done ok={ok} fail={fail} remaining={remaining}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
