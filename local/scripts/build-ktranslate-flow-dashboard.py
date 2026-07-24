#!/usr/bin/env python3
"""Adapt Commvault/marcnetterfield ktranslate flow dashboard for the local lab stack."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / ".dash-payloads" / "ktranslate-import" / "be8hpir89dds0a.raw.json"
OUT = ROOT / ".dash-payloads" / "ktranslate-import" / "lab-ktranslate-flow.json"

# networko11ydev Grafana Cloud stack namespace (from gcx 403 error / stack id 1544961)
NAMESPACE = "stacks-1544961"
FOLDER = "network-lab"
UID = "lab-ktranslate-flow"
TITLE = "Network Flow Summary (ktranslate)"

DS_REPLACEMENTS = {
    "grafanacloud-commvault-prom": "grafanacloud-prom",
    "grafanacloud-commvault-logs": "grafanacloud-logs",
    "grafanacloud-commvault-alert-state-history": "grafanacloud-alert-state-history",
    "grafanacloud-marcnetterfield1-prom": "grafanacloud-prom",
    "grafanacloud-marcnetterfield1-logs": "grafanacloud-logs",
    "grafanacloud-networko11ydev-prom": "grafanacloud-prom",
}


def walk_replace_strings(obj):
    if isinstance(obj, str):
        s = obj
        for old, new in DS_REPLACEMENTS.items():
            s = s.replace(old, new)
        return s
    if isinstance(obj, list):
        return [walk_replace_strings(x) for x in obj]
    if isinstance(obj, dict):
        return {k: walk_replace_strings(v) for k, v in obj.items()}
    return obj


def adapt(data: dict) -> dict:
    data = walk_replace_strings(data)
    meta = data.setdefault("metadata", {})
    meta["name"] = UID
    meta["namespace"] = NAMESPACE
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = "Local lab ktranslate NetFlow/sFlow dashboard (from ktranslate flow summary)"
    meta["labels"] = {}

    spec = data.setdefault("spec", {})
    spec["title"] = TITLE
    if isinstance(spec.get("tags"), list):
        tags = [t for t in spec["tags"] if t not in ("commvault",)]
        for tag in ("network-lab", "ktranslate", "netflow"):
            if tag not in tags:
                tags.append(tag)
        spec["tags"] = tags

    # Datasource variable default should point at this stack's Prometheus UID.
    for var in spec.get("variables") or []:
        try:
            if var.get("kind") == "DatasourceVariable" and var["spec"].get("name") == "datasource":
                var["spec"]["current"] = {"text": "grafanacloud-prom", "value": "grafanacloud-prom"}
        except (KeyError, TypeError):
            pass

    return data


def main() -> None:
    if not RAW.is_file():
        raise SystemExit(
            f"missing {RAW}\n"
            "Export source: gcx --context commvault dashboards get be8hpir89dds0a -o json "
            f"> {RAW}"
        )
    data = json.loads(RAW.read_text(encoding="utf-8-sig"))
    data = adapt(data)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    blob = json.dumps(data).lower()
    leftovers = [w for w in ("commvault", "netgraff", "coeprod") if w in blob]
    print(f"wrote {OUT} title={TITLE} uid={UID} bytes={OUT.stat().st_size}")
    if leftovers:
        print(f"WARNING leftover tokens: {leftovers}")


if __name__ == "__main__":
    main()
