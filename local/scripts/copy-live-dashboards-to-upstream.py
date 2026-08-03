#!/usr/bin/env python3
"""Copy pulled marcnetterfield-live dashboards into KtransToGrafana dashboards/."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".dash-payloads" / "marcnetterfield-live"

sys.path.insert(0, str(ROOT / "scripts"))
from ktranslate_upstream import DASHBOARD_FILES, resolve_upstream  # noqa: E402


def sanitize_manifest(manifest: dict) -> dict:
    out = json.loads(json.dumps(manifest))
    out.pop("status", None)
    meta = out.get("metadata")
    if isinstance(meta, dict):
        for k in ("resourceVersion", "generation", "creationTimestamp", "managedFields"):
            meta.pop(k, None)
    return out


def main() -> int:
    upstream = resolve_upstream()
    dash_dir = upstream / "dashboards"
    written: list[str] = []
    for uid, filename in DASHBOARD_FILES.items():
        src = LIVE / f"{uid}.json"
        if not src.is_file():
            print(f"MISSING live pull: {src}")
            return 1
        manifest = sanitize_manifest(json.loads(src.read_text(encoding="utf-8")))
        manifest.pop("_source_uid", None)
        dst = dash_dir / filename
        dst.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        layout = (manifest.get("spec") or {}).get("layout", {}).get("kind", "?")
        print(f"  {filename}  uid={uid}  layout={layout}")
        written.append(filename)
    print(f"\nWrote {len(written)} files to {dash_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
