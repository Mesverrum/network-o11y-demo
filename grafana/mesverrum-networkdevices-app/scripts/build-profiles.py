#!/usr/bin/env python3
"""Build src/profiles.json from the Alloy image fingerprinter catalog.

Matches Alloy discovery.snmp loadFingerprintLibrary: SHA-256 of the file bytes
(first 8 bytes hex) plus one profile per comment name (first token).

  python3 grafana/mesverrum-networkdevices-app/scripts/build-profiles.py
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[3]
# Prefer snmp-sd (image library SoT); fall back to the alloy tree copy.
CANDIDATES = (
    ROOT.parent / "snmp-sd" / "snmp" / "fingerprinters.yml",
    ROOT.parent / "alloy" / "snmp" / "fingerprinters.yml",
)
OUT = Path(__file__).resolve().parents[1] / "src" / "profiles.json"


def mods(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return []


def main() -> None:
    src = next((path for path in CANDIDATES if path.is_file()), None)
    if src is None:
        raise SystemExit(f"missing fingerprinter catalog; tried {CANDIDATES}")
    raw = src.read_bytes()
    library_hash = hashlib.sha256(raw).hexdigest()[:16]
    data = yaml.safe_load(raw.decode("utf-8"))
    matchers = data["fingerprinters"]["network"]["matchers"]
    profiles: dict[str, dict[str, object]] = {}
    conflicts = 0
    for matcher in matchers:
        comment = str(matcher.get("comment") or "").strip()
        if not comment:
            continue
        name = comment.split()[0]
        if not name or not name[0].isalpha():
            continue
        hot = mods(matcher.get("modules_hot"))
        cold = mods(matcher.get("modules_cold"))
        topology = mods(matcher.get("modules_topology"))
        if not hot and not cold and not topology:
            continue
        entry = {"name": name, "hot": hot, "cold": cold, "topology": topology}
        prev = profiles.get(name)
        if prev and (prev["hot"], prev["cold"], prev["topology"]) != (hot, cold, topology):
            conflicts += 1
            prev_n = len(prev["hot"]) + len(prev["cold"]) + len(prev["topology"])  # type: ignore[arg-type]
            if len(hot) + len(cold) + len(topology) > prev_n:
                profiles[name] = entry
            continue
        profiles[name] = entry
    out = {
        "fingerprinter": "network",
        "library_hash": library_hash,
        "source": src.as_posix().split("/projects/")[-1] if "/projects/" in src.as_posix() else src.name,
        "profiles": sorted(profiles.values(), key=lambda item: str(item["name"])),
    }
    OUT.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(out['profiles'])} profiles hash={library_hash} from {src} to {OUT} ({conflicts} conflicts)")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    main()
