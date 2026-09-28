#!/usr/bin/env python3
"""Expose the colocated dev Grafana (Instrumentation Hub app) on the NetBox NLB :3000.

Only the given /32 (default: this machine's public IP) and the VPC health checks may
reach :3000. Run from Windows with the `mvr` SSO profile.

    python3 local/scripts/hub-ui-expose.py up [--cidr 203.0.113.10/32]
    python3 local/scripts/hub-ui-expose.py down
"""
from __future__ import annotations

import argparse
import json
import subprocess
import urllib.request

REGION = "us-east-1"
IID = "i-0639d827b3ecf3b82"
NLB = "network-o11y-netbox-ui"
TG = "network-o11y-hub-ui"
SG = "sg-0d4a29db498435db0"
VPC_CIDR = "192.168.0.0/16"
PORT = 3000


def aws(*args: str, check: bool = True) -> dict:
    p = subprocess.run(
        ["aws", "--profile", "mvr", "--region", REGION, "--output", "json", *args],
        text=True, capture_output=True,
    )
    if check and p.returncode != 0:
        raise SystemExit(p.stderr.strip())
    return json.loads(p.stdout) if p.returncode == 0 and p.stdout.strip() else {}


def nlb() -> dict:
    return aws("elbv2", "describe-load-balancers", "--names", NLB)["LoadBalancers"][0]


def listener_arn(lb_arn: str) -> str | None:
    for li in aws("elbv2", "describe-listeners", "--load-balancer-arn", lb_arn)["Listeners"]:
        if li["Port"] == PORT:
            return li["ListenerArn"]
    return None


def tg_arn() -> str | None:
    out = aws("elbv2", "describe-target-groups", "--names", TG, check=False)
    groups = out.get("TargetGroups") or []
    return groups[0]["TargetGroupArn"] if groups else None


def sg_rules(cidrs: list[str]) -> str:
    return json.dumps([{
        "IpProtocol": "tcp", "FromPort": PORT, "ToPort": PORT,
        "IpRanges": [{"CidrIp": c, "Description": "Dev Grafana hub app"} for c in cidrs],
    }])


def up(cidr: str) -> None:
    lb = nlb()
    arn = tg_arn() or aws(
        "elbv2", "create-target-group", "--name", TG, "--protocol", "TCP", "--port", str(PORT),
        "--vpc-id", lb["VpcId"], "--target-type", "instance",
        "--health-check-protocol", "TCP", "--health-check-port", str(PORT),
    )["TargetGroups"][0]["TargetGroupArn"]
    aws("elbv2", "register-targets", "--target-group-arn", arn, "--targets", f"Id={IID},Port={PORT}")
    if not listener_arn(lb["LoadBalancerArn"]):
        aws("elbv2", "create-listener", "--load-balancer-arn", lb["LoadBalancerArn"],
            "--protocol", "TCP", "--port", str(PORT),
            "--default-actions", f"Type=forward,TargetGroupArn={arn}")
    for c in (cidr, VPC_CIDR):
        aws("ec2", "authorize-security-group-ingress", "--group-id", SG,
            "--ip-permissions", sg_rules([c]), check=False)
    print(f"http://{lb['DNSName']}:{PORT}/  (allowed: {cidr})")


def down() -> None:
    lb = nlb()
    li = listener_arn(lb["LoadBalancerArn"])
    if li:
        aws("elbv2", "delete-listener", "--listener-arn", li)
    arn = tg_arn()
    if arn:
        aws("elbv2", "delete-target-group", "--target-group-arn", arn)
    perms = aws("ec2", "describe-security-groups", "--group-ids", SG)["SecurityGroups"][0]["IpPermissions"]
    cidrs = [r["CidrIp"] for p in perms if p.get("FromPort") == PORT for r in p.get("IpRanges", [])]
    if cidrs:
        aws("ec2", "revoke-security-group-ingress", "--group-id", SG, "--ip-permissions", sg_rules(cidrs))
    print("removed :3000 listener, target group, and SG rules")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["up", "down"])
    ap.add_argument("--cidr")
    a = ap.parse_args()
    if a.action == "up":
        cidr = a.cidr or urllib.request.urlopen("https://checkip.amazonaws.com", timeout=10).read().decode().strip() + "/32"
        up(cidr)
    else:
        down()


if __name__ == "__main__":
    main()
