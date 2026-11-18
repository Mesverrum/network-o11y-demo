#!/usr/bin/env python3
"""Wrap the classic dashboard JSON from build_dashboards.py in gcx resource manifests.

Writes <out>/folder.json and <out>/dashboards/<uid>.json so
`gcx resources push -p <out>` can create the folder first, then the boards.
"""
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SRC = HERE / "dashboards"
OUT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else HERE / "gcx-staging")
FOLDER_UID = "halvorsen-soc"
FOLDER_TITLE = "Halvorsen Motors SOC (demo)"
API = "dashboard.grafana.app/v1beta1"

out_dash = OUT / "dashboards"
out_dash.mkdir(parents=True, exist_ok=True)
for old in out_dash.glob("*.json"):
    old.unlink()

(OUT / "folder.json").write_text(json.dumps({
    "apiVersion": "folder.grafana.app/v1",
    "kind": "Folder",
    "metadata": {"name": FOLDER_UID},
    "spec": {"title": FOLDER_TITLE},
}, indent=2), encoding="utf-8")

count = 0
for src in sorted(SRC.glob("*.json")):
    board = json.loads(src.read_text(encoding="utf-8"))
    uid = board["uid"]
    manifest = {
        "apiVersion": API,
        "kind": "Dashboard",
        "metadata": {"name": uid, "annotations": {"grafana.app/folder": FOLDER_UID}},
        "spec": board,
    }
    (out_dash / f"{uid}.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    count += 1
print(f"staged {count} dashboards + folder in {OUT}")
