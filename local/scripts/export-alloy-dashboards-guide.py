#!/usr/bin/env python3
"""Pull live A0–A4 from networko11ydev and write portable v2 JSON to the guide repo.

Always GET live first. Strips stack metadata, remaps Cloud DS names to
${datasource} / ${loki}, keeps TabsLayout / RowsLayout / GridLayout as-is.
Never POST /api/dashboards/db.

  python local/scripts/export-alloy-dashboards-guide.py
  python local/scripts/export-alloy-dashboards-guide.py --out /path/to/grafana-network-o11y-guide/dashboards
"""
from __future__ import annotations

import argparse
import copy
import json
import re
import sys
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from alloy_dash_nav import apply_alloy_nav_links

ROOT = Path(__file__).resolve().parents[1]
NS = "stacks-1544961"
DEFAULT_OUT = Path.home() / "projects" / "grafana-network-o11y-guide" / "dashboards"
# Windows clone next to this repo
WIN_OUT = Path(r"c:\Users\mesve\projects\grafana-network-o11y-guide\dashboards")

UIDS = [
    ("alloy-architecture", "a0-alloy-architecture.json"),
    ("alloy-health", "a1-alloy-health.json"),
    ("alloy-flow-summary", "a2-alloy-flow-summary.json"),
    ("alloy-device-summary", "a3-alloy-device-summary.json"),
    ("alloy-device-details", "a4-alloy-device-details.json"),
]

PROM_NAMES = {
    "grafanacloud-prom",
    "grafanacloud-networko11ydev-prom",
    "grafanacloud-marcnetterfield1-prom",
}
LOKI_NAMES = {
    "grafanacloud-logs",
    "grafanacloud-networko11ydev-logs",
    "grafanacloud-marcnetterfield1-logs",
}
DROP_TAGS = {"network-lab", "in-progress", "ktranslate"}
LAB_SENTENCE = re.compile(
    r"\s*spine1 intermittently reports[^.]*\."
    r"|\s*each is merged across spine1's two snmp_group values[^.]*\."
    r"|\s*spine1 may show both hq and colocated[^.]*\.",
    re.I,
)
LAB_HOSTS = {
    "spine1",
    "leaf1",
    "leaf2",
    "leaf-br1",
    "leaf-br2",
    "client1",
    "client2",
    "client-br1",
    "client-br2",
}
DEMO_DOC = (
    "https://github.com/Mesverrum/network-o11y-demo/blob/main/docs/alloy-network-fork.md"
)
GUIDE_DOC = "https://github.com/Mesverrum/grafana-network-o11y-guide/blob/main/docs/architecture.md"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def get_live(base: str, token: str, uid: str) -> dict:
    req = urllib.request.Request(
        f"{base.rstrip('/')}/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}",
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode())


def walk_replace(obj: Any) -> None:
    if isinstance(obj, dict):
        if obj.get("name") in PROM_NAMES and (
            "datasource" in json.dumps({k: obj[k] for k in obj if k == "name"})
        ):
            # handled below via key walk
            pass
        for k, v in list(obj.items()):
            if k in {"name", "text", "value"} and isinstance(v, str):
                if v in PROM_NAMES:
                    obj[k] = "${datasource}" if k == "name" else ""
                elif v in LOKI_NAMES:
                    obj[k] = "${loki}" if k == "name" else ""
            elif isinstance(v, str):
                nv = LAB_SENTENCE.sub("", v)
                nv = nv.replace(DEMO_DOC, GUIDE_DOC)
                nv = nv.replace(
                    " in folder alloy network fork (fb9d2s)",
                    "",
                )
                nv = re.sub(
                    r"\s*Provision with provision-network-alerts\.py --alloy \(folder fb9d2s\)\.",
                    "",
                    nv,
                )
                if nv == "fb9d2s":
                    nv = ""
                if nv != v:
                    obj[k] = nv
            else:
                walk_replace(v)
    elif isinstance(obj, list):
        for v in obj:
            walk_replace(v)


A0_LAB_GROUPS = """| Lab job (`snmp_group`) | Devices |
|---|---|
| `hq` | spine1, leaf1, leaf2 |
| `branch1` | leaf-br1 |
| `branch2` | leaf-br2 |"""

A0_GUIDE_GROUPS = """| Example `snmp_group` | What it is |
|---|---|
| `hq` | One discovery job / site (your names) |
| `branch1` | Another CIDR or credential set |"""


def _rewrite_a0_example_groups(spec: dict) -> None:
    for el in (spec.get("elements") or {}).values():
        viz = ((el.get("spec") or {}).get("vizConfig") or {}).get("spec") or {}
        opts = viz.get("options") or {}
        content = opts.get("content")
        if isinstance(content, str) and A0_LAB_GROUPS in content:
            opts["content"] = content.replace(A0_LAB_GROUPS, A0_GUIDE_GROUPS)


def has_var(spec: dict, name: str) -> bool:
    for v in spec.get("variables") or []:
        if (v.get("spec") or {}).get("name") == name:
            return True
    return False


def ds_var(name: str, plugin_id: str, label: str) -> dict:
    return {
        "kind": "DatasourceVariable",
        "spec": {
            "name": name,
            "pluginId": plugin_id,
            "refresh": "onDashboardLoad",
            "regex": "",
            "current": {"text": "", "value": ""},
            "options": [],
            "multi": False,
            "includeAll": False,
            "label": label,
            "hide": "dontHide",
            "skipUrlSync": False,
            "allowCustomValue": True,
        },
    }


def sanitize(doc: dict) -> dict:
    uid = (doc.get("metadata") or {}).get("name")
    spec = copy.deepcopy(doc.get("spec") or {})
    walk_replace(spec)
    _rewrite_a0_example_groups(spec)
    tags = [t for t in (spec.get("tags") or []) if t not in DROP_TAGS]
    if "alloy" not in tags:
        tags.append("alloy")
    spec["tags"] = tags
    apply_alloy_nav_links(spec, uid or "")
    variables = list(spec.get("variables") or [])
    if not has_var(spec, "datasource"):
        variables.insert(0, ds_var("datasource", "prometheus", "Prometheus data source"))
    needs_loki = "${loki}" in json.dumps(spec)
    if needs_loki and not has_var(spec, "loki"):
        # after prometheus so the picker order is metrics then logs
        idx = 1 if (variables and (variables[0].get("spec") or {}).get("name") == "datasource") else 0
        variables.insert(idx, ds_var("loki", "loki", "Loki data source"))
    for v in variables:
        s = v.get("spec") or {}
        if s.get("name") in {"datasource", "loki"}:
            s["current"] = {"text": "", "value": ""}
        cur = s.get("current") or {}
        raw_vals = cur.get("value")
        raw_texts = cur.get("text")
        check = []
        for item in (raw_vals, raw_texts):
            if isinstance(item, list):
                check.extend(item)
            elif isinstance(item, str):
                check.append(item)
        if any(x in LAB_HOSTS for x in check):
            if s.get("includeAll"):
                s["current"] = {"text": "All", "value": ["$__all"]}
            else:
                s["current"] = {"text": "", "value": ""}
        q = s.get("query")
        if isinstance(q, dict):
            ds = q.get("datasource")
            if isinstance(ds, dict) and ds.get("name") in PROM_NAMES | {"grafanacloud-prom"}:
                ds["name"] = "${datasource}"
    spec["variables"] = variables
    return {
        "kind": "Dashboard",
        "apiVersion": "dashboard.grafana.app/v2",
        "metadata": {"name": uid},
        "spec": spec,
    }


def leftover(blob: str) -> list[str]:
    bad = []
    for needle in (
        "stacks-1544961",
        "fb9d2s",
        "networko11ydev",
        "marcnetterfield",
        "kentik_snmp",
        "grafanacloud-networko11ydev",
    ):
        if needle in blob:
            bad.append(needle)
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=None)
    args = ap.parse_args()
    out_dir = args.out
    if out_dir is None:
        out_dir = WIN_OUT if WIN_OUT.parent.is_dir() else DEFAULT_OUT
    if not out_dir.parent.is_dir():
        print(f"guide repo not found next to {out_dir}", file=sys.stderr)
        return 1
    env = load_env()
    base, token = env["GRAFANA_URL_2"], env["GRAFANA_TOKEN_2"]
    out_dir.mkdir(parents=True, exist_ok=True)
    for uid, fname in UIDS:
        live = get_live(base, token, uid)
        kind = ((live.get("spec") or {}).get("layout") or {}).get("kind")
        gen = (live.get("metadata") or {}).get("generation")
        portable = sanitize(live)
        pkind = ((portable.get("spec") or {}).get("layout") or {}).get("kind")
        if pkind != kind:
            print(f"{uid}: layout {kind} -> {pkind}", file=sys.stderr)
            return 1
        text = json.dumps(portable, indent=2) + "\n"
        hits = leftover(text)
        if hits:
            print(f"{uid}: leftover {hits}", file=sys.stderr)
            return 1
        dest = out_dir / fname
        dest.write_text(text, encoding="utf-8")
        print(f"wrote {dest.name}  live_gen={gen} layout={pkind} bytes={len(text)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
