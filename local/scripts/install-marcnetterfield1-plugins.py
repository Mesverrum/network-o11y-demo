#!/usr/bin/env python3
"""Install selected plugins on marcnetterfield1 ONLY via Grafana Cloud API."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

STACK = "marcnetterfield1"
EXPECTED_INSTANCE_URL = "https://marcnetterfield1.grafana.net"
GCOM = "https://grafana.com/api"
CATALOG = "https://grafana.com/api/plugins"

# Volkov Labs Business Suite (+ related Marcus Olsson panels) used on this stack.
VOLKOV_LABS_PLUGINS = [
    "marcusolsson-dynamictext-panel",  # Business Text
    "marcusolsson-calendar-panel",   # Business Calendar
    "marcusolsson-static-datasource",  # Business Input
    "volkovlabs-echarts-panel",        # Business Charts
    "volkovlabs-table-panel",          # Business Table
    "volkovlabs-form-panel",           # Business Forms
    "volkovlabs-variable-panel",       # Business Variable
    "volkovlabs-image-panel",          # Business Media
    "volkovlabs-rss-datasource",       # Business News
    "volkovlabs-grapi-datasource",     # Business Satellite
    "volkovlabs-links-panel",          # Business Links
]

SANKEY_PLUGIN = "netsage-sankey-panel"


def token() -> str:
    tok = os.environ.get("MARC_GCOM_TOKEN", "").strip()
    if not tok:
        raise SystemExit("Set MARC_GCOM_TOKEN (Cloud access policy for marcnetterfield1 plugins).")
    return tok


def http(method: str, url: str, tok: str, body: dict | None = None, retries: int = 5):
    data = None if body is None else json.dumps(body).encode()
    for attempt in range(retries):
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {tok}",
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "marcnetterfield1-plugin-install",
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


def latest_version(slug: str) -> str:
    status, out = http("GET", f"{CATALOG}/{slug}", "")
    if status != 200:
        return "latest"
    version = (out.get("version") or out.get("latestVersion") or "latest")
    return str(version)


def list_installed(tok: str) -> set[str]:
    status, out = http("GET", f"{GCOM}/instances/{STACK}/plugins", tok)
    if status != 200:
        raise SystemExit(f"list failed http={status} {json.dumps(out)[:500]}")
    items = out.get("items", [])
    bad = [p for p in items if p.get("instanceUrl") != EXPECTED_INSTANCE_URL]
    if bad:
        raise SystemExit(f"ABORT: unexpected instanceUrl on {len(bad)} plugin(s)")
    return {p["pluginSlug"] for p in items}


def install_plugin(tok: str, slug: str, version: str | None = None) -> tuple[int, dict]:
    ver = version or latest_version(slug)
    body = {"plugin": slug, "version": ver}
    status, out = http("POST", f"{GCOM}/instances/{STACK}/plugins", tok, body)
    return status, out


def main() -> int:
    ap = argparse.ArgumentParser(description=f"Install plugins on {STACK} only")
    ap.add_argument("--volkov-labs", action="store_true", help="install Business Suite")
    ap.add_argument("--sankey", action="store_true", help="install netsage-sankey-panel")
    ap.add_argument("--all-requested", action="store_true", help="volkov-labs + sankey")
    ap.add_argument("--list", action="store_true", help="list installed plugins")
    args = ap.parse_args()

    tok = token()
    installed = list_installed(tok)
    print(f"stack={STACK} url={EXPECTED_INSTANCE_URL} installed={len(installed)}")

    if args.list:
        for slug in sorted(installed):
            print(f"  {slug}")
        return 0

    targets: list[str] = []
    if args.all_requested or args.volkov_labs:
        targets.extend(VOLKOV_LABS_PLUGINS)
    if args.all_requested or args.sankey:
        targets.append(SANKEY_PLUGIN)

    if not targets:
        ap.print_help()
        return 0

    ok = skip = fail = 0
    for slug in targets:
        if slug in installed:
            print(f"skip {slug} (already installed)")
            skip += 1
            continue
        status, out = install_plugin(tok, slug)
        if 200 <= status < 300:
            ver = out.get("version", "?")
            print(f"installed {slug} v{ver}")
            ok += 1
        elif status == 409:
            print(f"exists {slug} (409)")
            skip += 1
        else:
            print(f"FAILED {slug} http={status} {json.dumps(out)[:250]}")
            fail += 1
        time.sleep(0.5)

    final = list_installed(tok)
    print(f"done ok={ok} skip={skip} fail={fail} total={len(final)}")
    return 1 if fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
