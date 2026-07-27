#!/usr/bin/env python3
"""One-shot: dual softflowd (eth0+eth1) + internet probes on running lab clients."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS_FILE = ROOT / "fixtures" / "internet-probe-targets.txt"
CLAB_NET = "clab"
CLIENTS = ("client1", "client2")
INTERVAL = 45
TAG = "lab-internet-probes"
SOFTFLOWD_SH = """
which softflowd >/dev/null 2>&1 || apk add --no-cache softflowd >/dev/null 2>&1
pkill softflowd 2>/dev/null || true
sleep 1
SOFT_ARGS="-v 9 -P udp -n {kt_ip}:9995 -t udp=30 -t expint=30 -t general=60 -t maxlife=300"
softflowd -i eth0 -c /var/run/softflowd-eth0.ctl -p /var/run/softflowd-eth0.pid $SOFT_ARGS
softflowd -i eth1 -c /var/run/softflowd-eth1.ctl -p /var/run/softflowd-eth1.pid $SOFT_ARGS
pgrep -a softflowd
[ -f /tmp/softflowd-export-loop.pid ] && kill $(cat /tmp/softflowd-export-loop.pid) 2>/dev/null || true
nohup sh -c 'while sleep 30; do
  softflowctl -c /var/run/softflowd-eth0.ctl expire-all >/dev/null 2>&1
  softflowctl -c /var/run/softflowd-eth1.ctl expire-all >/dev/null 2>&1
done' >/dev/null 2>&1 &
echo $! >/tmp/softflowd-export-loop.pid
"""


def run(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd[:6]), "..." if len(cmd) > 6 else "")
    return subprocess.run(cmd, text=True, check=check, capture_output=True)


def load_targets() -> list[str]:
    lines: list[str] = []
    for raw in TARGETS_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            lines.append(line)
    return lines


def main() -> int:    kt = run(
        [
            "docker",
            "inspect",
            "-f",
            f"{{{{(index .NetworkSettings.Networks \"{CLAB_NET}\").IPAddress}}}}",
            "ktranslate_flow",
        ]
    )
    kt_ip = kt.stdout.strip()
    if not kt_ip:
        print("ERROR: ktranslate_flow not on clab network", file=sys.stderr)
        return 1
    print(f"collector={kt_ip}:9995")

    softflowd_cmd = SOFTFLOWD_SH.format(kt_ip=kt_ip)
    for c in CLIENTS:
        print(f"==> softflowd on {c}")
        out = run(["docker", "exec", c, "sh", "-c", softflowd_cmd])
        print(out.stdout.strip() or out.stderr.strip())

    targets = load_targets()

    probe_script = f"""#!/bin/sh
INTERVAL={INTERVAL}
TARGETS="{' '.join(targets)}"
OFFSET=$1
sleep $OFFSET
probe_one() {{
  line="$1"
  host="${{line%%|*}}"
  pin="${{line#*|}}"
  if [ "$pin" = "$line" ]; then pin=""; fi
  if [ -n "$pin" ]; then
    wget -q -O /dev/null -T 20 --no-check-certificate \\
      --header="Host: ${{host}}" "https://${{pin}}/" >>/tmp/{TAG}.log 2>&1 || true
  else
    wget -q -O /dev/null -T 20 --no-check-certificate \\
      "https://${{host}}/" >>/tmp/{TAG}.log 2>&1 || true
  fi
}}
while true; do
  for line in $TARGETS; do
    probe_one "$line"
    sleep $INTERVAL
  done
done
"""
    for i, c in enumerate(CLIENTS):
        offset = 0 if i == 0 else 30
        print(f"==> internet probes on {c}")
        run(["docker", "exec", c, "sh", "-c", f"pkill -f {TAG} 2>/dev/null || true"], check=False)
        inner = (
            f"cat > /tmp/{TAG}.sh << 'EOF'\n{probe_script}\nEOF\n"
            f"chmod +x /tmp/{TAG}.sh\n"
            f": > /tmp/{TAG}.log\n"
            f"nohup /tmp/{TAG}.sh {offset} >/dev/null 2>&1 &\n"
            f"pgrep -cf {TAG} || true"
        )
        out = run(["docker", "exec", c, "sh", "-c", inner])
        print(out.stdout.strip())

    for c, url in (("client1", "https://grafana.com/"), ("client2", "https://github.com/")):
        r = run(
            ["docker", "exec", c, "wget", "-q", "-O", "/dev/null", "-T", "15", "--no-check-certificate", url],
            check=False,
        )
        print(f"{c} -> {url}: {'ok' if r.returncode == 0 else 'failed'}")

    print("Done. Public flows in ~30s after softflowd export.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
