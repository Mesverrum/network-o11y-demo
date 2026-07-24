#!/usr/bin/env python3
"""One-shot: point srl group at current clab mgmt IPs and rediscover."""
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLAB = "clab"
targets = []
for node in ("spine1", "leaf1", "leaf2"):
    fmt = f'{{{{(index .NetworkSettings.Networks "{CLAB}").IPAddress}}}}'
    ip = subprocess.check_output(["docker", "inspect", "-f", fmt, node], text=True).strip()
    print(f"{node} -> {ip}")
    targets.append(f"{ip}/32")
joined = ",".join(targets)
env = ROOT / "groups" / "srl.env"
text = env.read_text(encoding="utf-8")
text = re.sub(r"(?m)^DISCOVERY_SOURCE=.*$", "DISCOVERY_SOURCE=cidr", text, count=1)
text = re.sub(r"(?m)^TARGETS=.*$", f"TARGETS={joined}", text, count=1)
env.write_text(text, encoding="utf-8")
print(f"updated TARGETS={joined}")
subprocess.run(["make", "generate"], cwd=ROOT, check=True)
subprocess.run(["make", "discover", "GROUP=srl"], cwd=ROOT, check=True)
