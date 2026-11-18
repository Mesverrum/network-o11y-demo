#!/usr/bin/env python3
"""Run every panel LogQL expression from the staged Halvorsen boards against live Loki.

Variables are substituted with the defaults a viewer would get on load.
Results go to verify-report.json and a summary goes to stdout.
"""
import json
import pathlib
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

HERE = pathlib.Path(__file__).resolve().parent
DASH = HERE / "dashboards"
CTX = "marc-lab-oauth"
DS = "grafanacloud-logs"

SUBS = {
    "$__range": "3h",
    "$__interval": "5m",
    "$site": "riverside-assembly",
    "$asset": "PLC-PAINT-L2-07",
    "$api_key": "ak_fleetpartner07",
    "$user": "jakub.kowalski",
    "$host": "WKS-NTC-1072",
    "$entity": "jakub.kowalski",
}


def substitute(expr):
    for k in sorted(SUBS, key=len, reverse=True):
        expr = expr.replace(k, SUBS[k])
    return expr


def run(expr):
    cmd = ["gcx", "--context", CTX, "datasources", "loki", "query", "-d", DS, expr,
           "--limit", "1000", "--since", "3h", "-o", "json"]
    p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    out = p.stdout.strip()
    err = p.stderr.strip()
    if p.returncode != 0:
        msg = out or err
        m = re.search(r'"details":"([^"]*)"', msg)
        return {"ok": False, "error": (m.group(1) if m else msg)[:300]}
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return {"ok": True, "rows": None, "raw": out[:200]}
    rows = count_rows(data)
    return {"ok": True, "rows": rows}


def count_rows(data):
    if isinstance(data, dict):
        if "data" in data and isinstance(data["data"], dict) and "result" in data["data"]:
            return len(data["data"]["result"])
        for key in ("result", "streams", "series", "values", "items"):
            if isinstance(data.get(key), list):
                return len(data[key])
    if isinstance(data, list):
        return len(data)
    return None


def collect():
    jobs = []
    for f in sorted(DASH.glob("*.json")):
        board = json.loads(f.read_text(encoding="utf-8"))
        for p in board["panels"]:
            panels = [p] + p.get("panels", [])
            for q in panels:
                if q.get("type") in ("row", "text"):
                    continue
                for t in q.get("targets", []):
                    expr = t.get("expr")
                    if not expr:
                        continue
                    jobs.append({"board": board["uid"], "panel": q.get("title", ""), "expr": substitute(expr)})
    return jobs


def main():
    jobs = collect()
    print(f"{len(jobs)} panel queries", flush=True)
    with ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(lambda j: {**j, **run(j["expr"])}, jobs))
    (HERE / "verify-report.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
    bad = [r for r in results if not r["ok"]]
    empty = [r for r in results if r["ok"] and r.get("rows") == 0]
    print(f"ok={len(results) - len(bad)} error={len(bad)} empty={len(empty)}")
    for r in bad:
        print("ERROR", r["board"], "|", r["panel"], "|", r["error"][:200])
    for r in empty:
        print("EMPTY", r["board"], "|", r["panel"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
