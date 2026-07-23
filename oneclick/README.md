# One-click deploy / decommission

Stand up (or tear down) the whole demo in one command, with pre-flight checks,
resumable steps, roadblock remediation, and a final report. Each run first asks
**local** vs **AWS** and remembers the choice.

## Pick your entrypoint by OS

| Host OS | Command | Linux environment it uses |
|---------|---------|---------------------------|
| **macOS** | `make deploy` / `make teardown` (or `./oneclick/deploy.sh`) | **OrbStack** Linux VM (ContainerLab has no macOS binary) |
| **Windows** | `.\oneclick\deploy.ps1` / `.\oneclick\decommission.ps1` (PowerShell) | **WSL2** distro (ContainerLab runs natively in WSL2) |
| **native Linux** | `bash oneclick/lab-linux.sh deploy` / `… decommission` | the host itself |

Why the split: **ContainerLab needs a Linux kernel.** On macOS there's no native
binary, so the lab runs inside an OrbStack VM; on Windows, WSL2 already provides a
real Linux kernel, so ContainerLab runs there directly (no OrbStack). The shared
Linux bring-up logic lives in **`lab-linux.sh`**, which the macOS and Windows
bootstrappers run inside their respective Linux env.

```bash
# macOS / Linux
make deploy            # = ./oneclick/deploy.sh (asks local vs AWS)
make teardown          # = ./oneclick/decommission.sh
```
```powershell
# Windows (PowerShell)
.\oneclick\deploy.ps1
.\oneclick\decommission.ps1
```

State is remembered in `~/.config/network-o11y-demo/oneclick.state` (macOS/Linux)
or `%USERPROFILE%\.network-o11y-demo\oneclick.state` (Windows).

### Key per-platform differences the scripts handle for you
- **uid:** OrbStack maps your Mac user to **501**, so discovery runs via `sudo`;
  WSL/native Linux run as **1000** (matches ktranslate), so discovery runs as you.
- **Docker:** installed inside the VM (macOS) / provided by Docker Desktop-WSL
  integration or `docker.io`+systemd (Windows) / native (Linux).
- **repo location:** cloned to the Linux env's native disk (ext4) to avoid the
  `/mnt/c` (drvfs) ContainerLab config-commit issues on Windows.

## How they behave

- **Pre-flight:** verify the required tools/resources are present before doing
  anything (Homebrew, OrbStack, the VM, ContainerLab, yq, docker, go for local;
  aws + OpenTofu + kubectl + tfvars for AWS).
- **Idempotent + resumable:** every step checks real state and skips what's
  already done. Safe to run repeatedly.
- **Roadblocks:** if the script hits something only you can do (approve the
  OrbStack admin prompt, paste Grafana Cloud OTLP creds, install a panel plugin,
  fix `terraform.tfvars`, …) it prints numbered step-by-step instructions and
  exits. Fix it, re-run the same script, and it continues from where it stopped.
- **Report:** ends with what was deployed/decommissioned, what wasn't, and how to
  access each component (VM, Grafana Cloud, AWS).

## Local deployment — what `deploy.sh` does

1. Install/verify OrbStack + an arm64 Ubuntu VM.
2. Install the VM toolchain (docker, docker-compose, ContainerLab, mikefarah yq,
   make, gettext, go).
3. Clone the repo into the VM's native disk; seed `.env` + `groups/srl.env`
   (strip CRLF); copy `GC_OTLP_*` from this Mac's `local/.env` if present, else
   roadblock for you to paste them.
4. Patch Alloy for the topology-health scrape + `tester_id` (until PR #5 merges).
5. `make generate` → `make check` → build topology-exporter image →
   `make up` / `make stabilize` → `sudo make discover` (uid fix) → `make traffic`
   → `make join-app`.
6. If `gcx` is authenticated: import the `network-lab` dashboards, check the panel
   plugins, and verify SNMP metrics are landing in Grafana Cloud.

## AWS deployment

Drives the repo's existing automation: `make infra` (OpenTofu: VPC/EKS/bastion)
then `make all` (Posts 3–6: lab, NetBox, dashboards, Ansible). Requires AWS
credentials, OpenTofu, kubectl, and a filled-in `terraform/terraform.tfvars`.
> Note: the AWS path is wired to the repo's documented targets but was not
> end-to-end validated in the session that produced these scripts.

## Access after deploy

Printed by the report, but in short:
- **VM:** `orb -m ubuntu` (shell) · `ssh -p 32222 -i ~/.orbstack/ssh/id_ed25519 default@localhost`
- **Grafana Cloud:** `https://<stack>.grafana.net` → Dashboards → `network-lab`
- **AWS:** `make status` / `make access` (SSH tunnels) · `tofu output` in `terraform/`
