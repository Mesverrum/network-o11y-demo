#!/usr/bin/env python3
import json, urllib.parse, urllib.request
from pathlib import Path

env = {}
for line in (Path(".env").read_text().splitlines()):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

def api(path):
    req = urllib.request.Request(
        f"{env['GRAFANA_URL'].rstrip('/')}{path}",
        headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

def pq(expr):
    q = urllib.parse.urlencode({"query": expr})
    url = (
        f"{env['GRAFANA_URL'].rstrip('/')}"
        f"/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{q}"
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)

print("=== dashboards matching bgp ===")
for d in api("/api/search?type=dash-db&limit=200"):
    t = (d.get("title") or "") + " " + (d.get("uid") or "")
    if "bgp" in t.lower():
        print(f"  {d['uid']}\t{d['title']}")

print("\n=== prom metric names with bgp ===")
d = pq('count by (__name__) ({__name__=~"(?i).*bgp.*"})')
for x in sorted(d["data"]["result"], key=lambda z: z["metric"].get("__name__", "")):
    print(f"  {x['metric'].get('__name__')}: {x['value'][1]}")

print("\n=== gnmi neighbor-ish ===")
d = pq('count by (__name__) ({__name__=~"(?i)gnmi_.*", __name__=~"(?i).*neighbor|.*bgp|.*session.*"})')
# simpler
d = pq('count by (__name__) ({__name__=~"gnmi_.*bgp.*|gnmi_.*neighbor.*"})')
for x in d["data"]["result"]:
    print(f"  {x['metric'].get('__name__')}: {x['value'][1]}")
