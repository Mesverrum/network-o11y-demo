#!/usr/bin/env python3
"""Export ktranslate dashboards 00-02 from Commvault and import to target stacks."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "ktranslate-commvault-export"
STAGING = ROOT / ".dash-payloads" / "ktranslate-import"
FOLDER = "network-lab"

UIDS = [
    ("ktranslate-device-summary", "03. Network Device Summary"),
    ("ktranslate-device-details", "04. Network Device Details"),
    ("ktranslate-flow-summary", "02. Network Flow Summary"),
]

TARGETS = {
    "marcnetterfield1": {
        "url": "https://marcnetterfield1.grafana.net",
        "namespace": "stacks-1061129",
        "replacements": {
            "grafanacloud-commvault-prom": "grafanacloud-marcnetterfield1-prom",
            "grafanacloud-commvault-logs": "grafanacloud-marcnetterfield1-logs",
            "grafanacloud-commvault-alert-state-history": "grafanacloud-marcnetterfield1-alert-state-history",
        },
    },
    "networko11ydev": {
        "url": "https://networko11ydev.grafana.net",
        "namespace": "stacks-1544961",
        "replacements": {
            "grafanacloud-commvault-prom": "grafanacloud-networko11ydev-prom",
            "grafanacloud-commvault-logs": "grafanacloud-networko11ydev-logs",
            "grafanacloud-commvault-alert-state-history": "grafanacloud-networko11ydev-alert-state-history",
        },
    },
}


def parse_gcx_json(raw: str) -> dict:
    lines = [ln for ln in raw.splitlines() if not ln.startswith('{"class":"hint"')]
    body = "\n".join(lines).strip()
    if not body:
        raise RuntimeError("empty gcx output")
    return json.loads(body)


def gcx(context: str, *args: str, expect_json: bool = True) -> dict | list | None:
    cmd = ["gcx", "--context", context, *args]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(f"gcx {' '.join(args)} failed ({proc.returncode}): {err[:2000]}")
    if not expect_json or not (proc.stdout or "").strip():
        return None
    return parse_gcx_json(proc.stdout)


def export_from_commvault() -> list[Path]:
    OUT.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for uid, _title in UIDS:
        data = gcx("commvault", "dashboards", "get", uid, "-o", "json")
        path = OUT / f"{uid}.json"
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        got_title = (data.get("spec") or {}).get("title") or "?"
        print(f"exported {uid}: {got_title} -> {path}")
        written.append(path)
    return written


def remap(obj, replacements: dict[str, str]):
    text = json.dumps(obj, separators=(",", ":"))
    for old, new in replacements.items():
        text = text.replace(old, new)
    return json.loads(text)


def prepare_dash(data: dict, uid: str, namespace: str, replacements: dict[str, str]) -> dict:
    dash = remap(data, replacements)
    meta = dash.setdefault("metadata", {})
    meta["name"] = uid
    meta["namespace"] = namespace
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = f"Sync ktranslate dashboard from Commvault ({uid})"
    return dash


def upsert_via_gcx(context: str, uid: str, dash: dict) -> tuple[str, str]:
    STAGING.mkdir(parents=True, exist_ok=True)
    path = STAGING / f"{uid}.{context}.json"
    path.write_text(json.dumps(dash, separators=(",", ":")), encoding="utf-8")

    # Try update first if dashboard already exists on target.
    try:
        existing = gcx(context, "dashboards", "get", uid, "-o", "json")
        if isinstance(existing, dict):
            rv = (existing.get("metadata") or {}).get("resourceVersion")
            if rv:
                dash["metadata"]["resourceVersion"] = rv
            elabels = (existing.get("metadata") or {}).get("labels") or {}
            if "grafana.app/deprecatedInternalID" in elabels:
                dash.setdefault("metadata", {}).setdefault("labels", {})
                dash["metadata"]["labels"]["grafana.app/deprecatedInternalID"] = elabels[
                    "grafana.app/deprecatedInternalID"
                ]
            path.write_text(json.dumps(dash, separators=(",", ":")), encoding="utf-8")
            gcx(context, "dashboards", "update", uid, "-f", str(path), expect_json=False)
            return "updated", f"{TARGETS[context]['url']}/d/{uid}"
    except RuntimeError as e:
        if "404" not in str(e) and "NotFound" not in str(e):
            raise

    # Create fresh
    path.write_text(json.dumps(dash, separators=(",", ":")), encoding="utf-8")
    gcx(context, "dashboards", "create", "-f", str(path), expect_json=False)
    return "created", f"{TARGETS[context]['url']}/d/{uid}"


def import_to_target(context: str, exports: list[Path]) -> None:
    cfg = TARGETS[context]
    print(f"\n=== importing to {context} ({cfg['url']}, ns={cfg['namespace']}) ===")
    for path in exports:
        uid = path.stem
        data = json.loads(path.read_text(encoding="utf-8"))
        dash = prepare_dash(data, uid, cfg["namespace"], cfg["replacements"])
        action, url = upsert_via_gcx(context, uid, dash)
        title = (dash.get("spec") or {}).get("title")
        print(f"  {uid}: {action} title={title}")
        print(f"    {url}")


def main() -> None:
    targets = [t for t in sys.argv if t in TARGETS] or list(TARGETS.keys())
    only_uids = {a for a in sys.argv if a in {u for u, _ in UIDS}}

    exports = export_from_commvault()
    if only_uids:
        exports = [p for p in exports if p.stem in only_uids]

    for context in targets:
        import_to_target(context, exports)

    print("\nDone.")


if __name__ == "__main__":
    main()
