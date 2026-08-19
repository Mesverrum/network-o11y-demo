#!/usr/bin/env python3
"""Sanity-check: does section-scoped interface_name query on Overview open?

Opens Device Details with Playwright, injects SA Bearer for API calls,
lands on Overview (default tab), watches network for the Interfaces-tab
variable query (if_OperStatus / if_interface_name), then clicks Interfaces
and watches again.

Usage:
  python3 local/scripts/bench-section-var-lazy.py
  python3 local/scripts/bench-section-var-lazy.py --instance leaf1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), env[k.strip()])
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--instance", default="leaf1")
    ap.add_argument("--uid", default="ktranslate-device-details")
    ap.add_argument("--timeout-ms", type=int, default=45000)
    args = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("Installing playwright package…")
        os.system(f"{sys.executable} -m pip install playwright --quiet")
        from playwright.sync_api import sync_playwright

    env = load_env()
    base = env["GRAFANA_URL"].rstrip("/")
    token = env["GRAFANA_TOKEN"]
    # Force Overview tab via URL key if present; leave default otherwise
    url = (
        f"{base}/d/{args.uid}/network-device-details"
        f"?orgId=1&from=now-1h&to=now&timezone=browser"
        f"&var-instance={args.instance}"
    )

    # Match section var query for interface_name
    iface_markers = (
        "if_interface_name",
        "if_OperStatus",
        "kentik_snmp_if_OperStatus",
        "interface_name",
    )
    # Dashboard-level has_* still expected on load
    has_markers = ("kentik_snmp_CPU", "label_values")

    overview_hits: list[str] = []
    interfaces_hits: list[str] = []
    phase = {"name": "overview"}

    def on_request(req):
        u = req.url
        if "prometheus" not in u and "/api/ds/query" not in u and "label" not in u:
            # still capture ds/query bodies via route - request URL alone
            if "/api/" not in u:
                return
        blob = u
        try:
            if req.post_data:
                blob += " " + req.post_data[:800]
        except Exception:
            pass
        low = blob.lower()
        # iface section var
        if any(m.lower() in low for m in iface_markers) and (
            "label" in low or "values" in low or "query" in low or "operstatus" in low
        ):
            hit = blob[:300].replace("\n", " ")
            if phase["name"] == "overview":
                overview_hits.append(hit)
            else:
                interfaces_hits.append(hit)

    print(f"opening {url}")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        # Inject SA token on Grafana API calls (UI shell + datasource proxy)
        def handle_route(route):
            headers = {**route.request.headers, "Authorization": f"Bearer {token}"}
            # Drop cookie auth conflicts
            headers.pop("cookie", None)
            route.continue_(headers=headers)

        page.route("**/*", handle_route)
        page.on("request", on_request)

        page.goto(url, wait_until="domcontentloaded", timeout=args.timeout_ms)
        # Wait for dashboard chrome / variables wave
        page.wait_for_timeout(8000)

        # Detect login wall
        body = page.content()
        if "login" in page.url.lower() or "Invalid username" in body or 'id="login"' in body.lower():
            print("WARN: may have hit login wall; Bearer inject may be insufficient for UI")
            print(f"  url now: {page.url}")

        # Snapshot overview phase
        print(f"\n=== phase Overview (default tab), {len(overview_hits)} iface-related requests ===")
        for h in overview_hits[:8]:
            print(" ", h[:200])

        # Click Interfaces tab
        phase["name"] = "interfaces"
        clicked = False
        for sel in (
            'role=tab[name="Interfaces"]',
            'text=Interfaces',
            '[data-testid*="Interfaces"]',
            'button:has-text("Interfaces")',
            'a:has-text("Interfaces")',
        ):
            try:
                loc = page.locator(sel).first
                if loc.count() and loc.is_visible():
                    loc.click(timeout=5000)
                    clicked = True
                    print(f"clicked Interfaces via {sel}")
                    break
            except Exception:
                continue
        if not clicked:
            # try URL partial for tabs layout
            page.evaluate(
                """() => {
                  const tabs = [...document.querySelectorAll('[role=tab], button, a')];
                  const t = tabs.find(el => (el.textContent||'').trim() === 'Interfaces');
                  if (t) t.click();
                }"""
            )
            print("clicked Interfaces via evaluate fallback")

        page.wait_for_timeout(8000)
        print(f"\n=== phase Interfaces tab, {len(interfaces_hits)} iface-related requests ===")
        for h in interfaces_hits[:8]:
            print(" ", h[:200])

        # Screenshot for debugging
        out_png = ROOT / ".dash-payloads" / "mib-coverage" / "section-var-lazy.png"
        out_png.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_png), full_page=False)
        print(f"\nscreenshot {out_png}")

        browser.close()

    print("\n=== verdict ===")
    ov = len(overview_hits)
    iv = len(interfaces_hits)
    if ov == 0 and iv > 0:
        print(
            f"LAZY: interface_name-style queries NOT seen on Overview ({ov}), "
            f"seen after Interfaces click ({iv}). Section vars appear deferred."
        )
    elif ov > 0 and iv >= 0:
        print(
            f"NOT LAZY (or ambiguous): iface queries already on Overview ({ov}); "
            f"after click ({iv}). Section scoping may not defer QueryVariable refresh."
        )
    elif ov == 0 and iv == 0:
        print(
            "INCONCLUSIVE: no iface variable queries captured in either phase "
            "(auth/UI may have blocked dashboard render)."
        )
    else:
        print(f"unexpected ov={ov} iv={iv}")

    out = ROOT / ".dash-payloads" / "mib-coverage" / "section-var-lazy.json"
    out.write_text(
        json.dumps(
            {
                "overview_hits": overview_hits,
                "interfaces_hits": interfaces_hits,
                "url": url,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
