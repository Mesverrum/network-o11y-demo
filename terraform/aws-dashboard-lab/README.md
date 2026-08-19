# AWS dashboard lab (Cloud Network folder)

Light NLB + traffic hosts in an existing VPC to exercise Grafana Cloud AWS dashboards.
Uses SSO profile **mvr** by default. Tear down between sessions to limit cost.

## Quick start

```bash
aws sso login --profile mvr
make -C local aws-lab-up
# wait 5–15m for CloudWatch → Grafana
make -C local aws-lab-down   # between sessions
```

## What it creates

| Resource | Purpose |
|----------|---------|
| Internal **NLB** | Unlocks NLB panels when streamed |
| **2× t3.micro** (private subnets, 2 AZs) | NAT egress + cross-AZ traffic |
| IAM + SSM | Ops without SSH keys |

Default VPC: `eksctl-ai-o11y-mg-cluster/VPC` (`vpc-07905dc0ab6652b64`) — has NAT and private subnets.

Regenerate `terraform.tfvars` after VPC changes:

```bash
bash local/scripts/aws-lab-discover.sh
```

## Cost notes

- NLB ~$16/mo + LCUs while running
- 2× t3.micro ~$15/mo each if left on 24×7
- **`aws-lab-down` destroys all lab resources** — run between sessions

Budget guardrail: keep under ~$100/mo by tearing down when not demoing.
