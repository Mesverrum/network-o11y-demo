#!/usr/bin/env python3
"""Patch interface BPS panels: rate()*8 -> *8/60, note 60s poll in description."""
from __future__ import annotations

import copy
import json
import re
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NOTE = (
    "Interface bps assumes ktranslate delta gauges with a 60s SNMP poll "
    "(octets × 8 / 60). When poll_duration_sec is absent, 60s is assumed."
)

# Match rate(...ifHCIn/OutOctets...) * 8 variants
RATE_RE = re.compile(
    r"rate\s*\(\s*(kentik_snmp_ifHC(?:In|Out)Octets[^)]*)\s*\[\s*\$__rate_interval\s*\]\s*\)\s*\*\s*8"
    r"|"
    r"rate\s*\(\s*(kentik_snmp_ifHC(?:In|Out)Octets[^)]*)\s*\[\s*\$__rate_interval\s*\]\s*\)\s*\)\s*\*\s*8",
    re.IGNORECASE | re.DOTALL,
)

# Simpler stepwise replacement patterns
PATTERNS = [
    # rate(METRIC{...}[$__rate_interval]) * 8
    (
        re.compile(
            r"rate\(\s*(kentik_snmp_ifHC(?:In|Out)Octets(\{[^}]*\})?)\s*\[\$__rate_interval\]\s*\)\s*\*\s*8",
            re.IGNORECASE,
        ),
        r"(\1) * 8 / 60",
    ),
    # rate(METRIC{...}[$__rate_interval]) *8
    (
        re.compile(
            r"rate\(\s*(kentik_snmp_ifHC(?:In|Out)Octets(\{[^}]*\})?)\s*\[\$__rate_interval\]\s*\)\s*\*\s*8",
            re.IGNORECASE,
        ),
        r"(\1) * 8 / 60",
    ),
]


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
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        raise RuntimeError(f"{method} {path} -> {e.code}: {err[:500]}") from e


def rewrite_expr(expr: str) -> tuple[str, bool]:
    if "kentik_snmp_ifHC" not in expr or "rate(" not in expr:
        return expr, False
    if "ifHCInOctets" not in expr and "ifHCOutOctets" not in expr:
        return expr, False
    orig = expr
    # rate(METRIC{sel}[$__rate_interval]) * 8  OR  rate(...) )* 8 with parens
    new = re.sub(
        r"rate\(\s*(kentik_snmp_ifHC(?:In|Out)Octets(?:\{[^{}]*\})?)\s*\[\$__rate_interval\]\s*\)",
        r"(\1)",
        expr,
    )
    # After removing rate(), ensure * 8 becomes * 8 / 60 (avoid double)
    if new == expr:
        return expr, False
    # If we still have * 8 without / 60 nearby for these metrics
    if "* 8 / 60" in new or "*8/60" in new.replace(" ", ""):
        return new, new != orig
    new2 = re.sub(r"\*\s*8\b(?!\s*/\s*60)", "* 8 / 60", new)
    return new2, new2 != orig


def ensure_desc(desc: str | None) -> str:
    base = (desc or "").strip()
    if "60s SNMP poll" in base or "octets × 8 / 60" in base or "octets x 8 / 60" in base:
        return base
    if not base:
        return NOTE
    return base.rstrip() + "\n\n" + NOTE


def walk_panels(panels: list, hits: list, path: str = "") -> None:
    for i, p in enumerate(panels or []):
        title = p.get("title") or f"panel[{i}]"
        here = f"{path}/{title}"
        panel_changed = False
        for t in p.get("targets") or []:
            expr = t.get("expr")
            if not isinstance(expr, str):
                continue
            new, changed = rewrite_expr(expr)
            if changed:
                t["expr"] = new
                panel_changed = True
                hits.append({"panel": here, "from": expr, "to": new})
        # Annotate only panels whose queries we rewrote (interface octet → bps)
        if panel_changed:
            new_desc = ensure_desc(p.get("description"))
            if new_desc != (p.get("description") or ""):
                p["description"] = new_desc
                hits.append({"panel": here, "desc_updated": True})

        if p.get("panels"):
            walk_panels(p["panels"], hits, here)


def main() -> None:
    env = load_env()
    search = api(env, "GET", "/api/search?type=dash-db&limit=200")
    # Focus on ktranslate / netterfield / network lab dashboards that use kentik_snmp
    candidates = []
    for d in search:
        title = (d.get("title") or "").lower()
        uid = d.get("uid") or ""
        folder = (d.get("folderTitle") or "").lower()
        if any(
            k in title or k in folder or k in uid.lower()
            for k in (
                "ktrans",
                "kentik",
                "netterfield",
                "snmp",
                "device",
                "interface",
                "network lab",
                "summary",
                "detail",
            )
        ):
            candidates.append(d)

    # Also always check known UIDs from import
    known = [
        "mavgvqv",
        "magz6qw1",
        "ma7zxqw",
        "mah4cjt",
        "marhvmb",
        "masvw96",
        "ktrans-arch-replication",
        "ktrans-preserved-summary",
        "ktrans-preserved-details",
        "ktrans-preserved-flows",
        "ktrans-preserved-health",
        "be8hpir89dds0a",
        "masjqrs",
    ]
    by_uid = {d["uid"]: d for d in search}
    for uid in known:
        if uid in by_uid and by_uid[uid] not in candidates:
            candidates.append(by_uid[uid])

    print(f"Scanning {len(candidates)} candidate dashboards...")
    report = []

    for d in candidates:
        uid = d["uid"]
        # Prefer k8s API get
        try:
            full = api(env, "GET", f"/apis/dashboard.grafana.app/v1beta1/namespaces/default/dashboards/{uid}")
            spec = full.get("spec") or {}
            # v1beta1 wraps dashboard differently
            dash = spec if "panels" in spec or "titlepage" in spec else (spec.get("dashboard") or full.get("dashboard"))
            if not dash or "panels" not in dash:
                # try classic
                classic = api(env, "GET", f"/api/dashboards/uid/{uid}")
                dash = classic["dashboard"]
                meta = classic.get("meta") or {}
                full = None
                use_classic = True
            else:
                meta = full.get("metadata") or {}
                use_classic = False
        except Exception:
            classic = api(env, "GET", f"/api/dashboards/uid/{uid}")
            dash = classic["dashboard"]
            meta = classic.get("meta") or {}
            full = None
            use_classic = True

        hits: list = []
        dash = copy.deepcopy(dash)
        walk_panels(dash.get("panels") or [], hits)
        # also templating? skip
        expr_hits = [h for h in hits if "to" in h]
        desc_hits = [h for h in hits if h.get("desc_updated")]
        if not expr_hits and not desc_hits:
            continue

        print(f"\n{uid} | {d.get('title')}: {len(expr_hits)} expr, {len(desc_hits)} desc")
        for h in expr_hits[:5]:
            print(f"  PANEL {h['panel']}")
            print(f"    FROM: {h['from'][:120]}...")
            print(f"    TO:   {h['to'][:120]}...")

        if use_classic:
            payload = {
                "dashboard": dash,
                "folderUid": meta.get("folderUid") or "",
                "message": "Assume 60s poll for interface bps (delta*8/60); document in panel descriptions",
                "overwrite": True,
            }
            # preserve id
            result = api(env, "POST", "/api/dashboards/db", payload)
            print(f"  saved classic: {result.get('status')} version={result.get('version')}")
        else:
            # PUT k8s style — preserve metadata labels like deprecatedInternalID
            body = copy.deepcopy(full)
            if "panels" in (body.get("spec") or {}):
                body["spec"] = dash
            elif "dashboard" in (body.get("spec") or {}):
                body["spec"]["dashboard"] = dash
            else:
                body["spec"] = dash
            result = api(
                env,
                "PUT",
                f"/apis/dashboard.grafana.app/v1beta1/namespaces/default/dashboards/{uid}",
                body,
            )
            print(f"  saved k8s api: ok resourceVersion={((result.get('metadata') or {}).get('resourceVersion'))}")

        report.append(
            {
                "uid": uid,
                "title": d.get("title"),
                "expr_changes": len(expr_hits),
                "desc_changes": len(desc_hits),
            }
        )

    out = ROOT / ".dash-payloads" / "bps-60s-patch-report.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nWrote {out}")
    print(f"Patched {len(report)} dashboards")


if __name__ == "__main__":
    main()
