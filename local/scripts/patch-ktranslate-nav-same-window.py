#!/usr/bin/env python3
"""Set ktranslate 'Network Dashboards' links to open in the same window.

Patches KtransToGrafana dashboards/*.json (spec.links only) and live v2
manifests. Does not change panel data links or the Architecture GitHub link.

Usage:
  python3 local/scripts/patch-ktranslate-nav-same-window.py
  python3 local/scripts/patch-ktranslate-nav-same-window.py --files-only
"""
from __future__ import annotations

from grafana_env import apply_grafana_aliases

import argparse
import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from ktranslate_upstream import resolve_upstream  # noqa: E402

CTX = ssl.create_default_context()
NAV_TITLE = "Network Dashboards"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / "local" / ".env"
    if not path.is_file():
        return apply_grafana_aliases(env)
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def patch_links(links) -> int:
    n = 0
    if not isinstance(links, list):
        return 0
    for link in links:
        if not isinstance(link, dict):
            continue
        if link.get("title") != NAV_TITLE:
            continue
        if link.get("type") not in (None, "", "dashboards"):
            continue
        if link.get("targetBlank") is True:
            link["targetBlank"] = False
            n += 1
    return n


NAV_BLOCK = re.compile(
    r'("title": "Network Dashboards",(?:.|\n){0,400}?"asDropdown": true,\s*)"targetBlank": true',
    re.MULTILINE,
)


def patch_file(path: Path) -> int:
    raw = path.read_text(encoding="utf-8")
    patched, n = NAV_BLOCK.subn(r'\1"targetBlank": false', raw)
    if n:
        path.write_text(patched, encoding="utf-8")
    return n


def req(url: str, token: str, method: str = "GET", body=None):
    data = None if body is None else json.dumps(body).encode()
    request = urllib.request.Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, context=CTX, timeout=90) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            parsed = json.loads(raw)
        except Exception:
            parsed = raw.decode("utf-8", "replace")[:800]
        raise RuntimeError(f"{e.code} {method} {url}: {parsed}") from e


def stack_pairs(env: dict[str, str]) -> list[tuple[str, str, str]]:
    pairs = []
    seen = set()
    for label, url_key, token_key in (
        ("primary", "GRAFANA_URL", "GRAFANA_TOKEN"),
        ("stack2", "GRAFANA_URL_2", "GRAFANA_TOKEN_2"),
        ("stack3", "GRAFANA_URL_3", "GRAFANA_TOKEN_3"),
        ("workshop", "GRAFANA_URL_WORKSHOP", "GRAFANA_TOKEN_WORKSHOP"),
    ):
        url = env.get(url_key, "").rstrip("/")
        token = env.get(token_key, "")
        if not url or not token or url in seen:
            continue
        seen.add(url)
        pairs.append((url, token, label))
    return pairs


def namespace_for(url: str, token: str) -> str:
    _, settings = req(f"{url}/api/frontend/settings", token)
    ns = (settings or {}).get("namespace")
    if not ns:
        raise RuntimeError(f"could not read stack namespace from {url}/api/frontend/settings")
    return ns


def search_ktranslate(url: str, token: str) -> list[dict]:
    q = urllib.parse.urlencode({"type": "dash-db", "tag": "ktranslate"})
    _, items = req(f"{url}/api/search?{q}", token)
    if not isinstance(items, list):
        return []
    return [i for i in items if i.get("uid")]


def patch_live(url: str, token: str) -> None:
    host = url.replace("https://", "").replace("http://", "")
    ns = namespace_for(url, token)
    found = search_ktranslate(url, token)
    print(f"{host} ns={ns} tagged={len(found)}")
    for item in found:
        uid = item["uid"]
        path = f"{url}/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{uid}"
        _, dash = req(path, token)
        spec = dash.get("spec") or {}
        layout = (spec.get("layout") or {}).get("kind")
        gen = (dash.get("metadata") or {}).get("generation")
        n = patch_links(spec.get("links"))
        if not n:
            print(f"  skip {uid} gen={gen} layout={layout} (no Network Dashboards targetBlank)")
            continue
        rv = (dash.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash.setdefault("metadata", {})["resourceVersion"] = rv
        _, out = req(path, token, "PUT", dash)
        out_layout = ((out or {}).get("spec") or {}).get("layout") or {}
        out_gen = ((out or {}).get("metadata") or {}).get("generation")
        if out_layout.get("kind") != layout:
            raise RuntimeError(f"{uid} layout changed {layout} -> {out_layout.get('kind')}")
        print(f"  put  {uid} gen {gen} -> {out_gen} layout={layout}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--files-only", action="store_true")
    args = parser.parse_args()

    upstream = resolve_upstream()
    dash_dir = upstream / "dashboards"
    print(f"files {dash_dir}")
    for path in sorted(dash_dir.glob("*.json")):
        n = patch_file(path)
        print(f"  {path.name}: {n} link(s)")

    if args.files_only:
        return 0

    env = load_env()
    pairs = stack_pairs(env)
    if not pairs:
        print("no GRAFANA_URL/TOKEN pairs in local/.env")
        return 1
    for url, token, label in pairs:
        print(f"live {label}")
        try:
            patch_live(url, token)
        except Exception as exc:
            print(f"  skip {label}: {exc}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
