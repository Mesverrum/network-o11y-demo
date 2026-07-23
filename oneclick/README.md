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

## Local deployment — how it's structured

`deploy.sh` (macOS) and `deploy.ps1` (Windows) are **thin bootstrappers**. They
only do the platform-specific setup, then hand off to the shared
**`lab-linux.sh`** which runs *inside* the Linux env and does all the real work:

**Bootstrapper (per platform):** prepares the Linux env, clones the repo to
native ext4, syncs this checkout's `lab-linux.sh` in, seeds `.env`, then runs it.
- macOS: install/verify OrbStack + an arm64 Ubuntu VM; copy `.env` values from the
  Mac's `local/.env`; run `lab-linux.sh` in the VM.
- Windows: preflight WSL2 + distro; copy `.env` values; run `lab-linux.sh` in WSL.
- native Linux: run `lab-linux.sh` directly against this checkout.

**`lab-linux.sh` (shared, uid-aware — the single routine for all 3):** install
toolchain (docker, compose, ContainerLab, mikefarah yq, make, gettext, go) → seed
config + creds + patch Alloy (topology-health scrape + `tester_id`) →
`make generate`/`check` → build the topology-exporter image → `make up`/`stabilize`
→ discovery (as-you on uid 1000, via `sudo` on OrbStack's uid 501) → `make traffic`
→ `make join-app` → **Grafana Cloud step (token-based, no OAuth):** import the
`network-lab` dashboards via the in-stack API and install the panel plugins via the
Cloud API.

One Linux routine, three ways in — identical behavior across macOS, Windows, and
native Linux.

### Grafana Cloud tokens (set in `local/.env`)
Token auth is used everywhere so the exact same code runs on all platforms **and**
plugins can be installed (an OAuth user session cannot install plugins):

| Var | Type | Used for |
|-----|------|----------|
| `GC_OTLP_URL` / `GC_OTLP_ACCOUNT` / `GC_OTLP_KEY` | OTLP CAP token (`glc_`) | telemetry ingest (Alloy) |
| `GRAFANA_URL` + `GRAFANA_TOKEN` | service-account token (`glsa_`) | dashboard import (in-stack API) |
| `GC_STACK_TOKEN` | CAP token with `stack-plugins:write` (`glc_`) | panel-plugin install (Cloud API); falls back to `GC_OTLP_KEY` if that policy has the scope |

If a token is missing the script roadblocks with the exact portal steps, then
resumes on re-run.

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
