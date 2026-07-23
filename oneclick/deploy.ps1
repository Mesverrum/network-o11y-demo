# One-click DEPLOY for Windows (WSL2). Run from PowerShell:
#     .\oneclick\deploy.ps1
# Windows uses WSL2 (ContainerLab runs natively in WSL2's Linux kernel — no
# OrbStack). This is a thin bootstrapper: it prepares WSL and then runs
# oneclick/lab-linux.sh INSIDE the distro (shared with native Linux). Idempotent
# and resumable; roadblocks print remediation and exit so you fix + re-run.
$ErrorActionPreference = 'Stop'
$script:Self   = '.\oneclick\deploy.ps1'
$script:Action = 'deploy'
. (Join-Path $PSScriptRoot 'common.ps1')
$RepoUrl = if ($env:REPO_URL) { $env:REPO_URL } else { 'https://github.com/Mesverrum/network-o11y-demo.git' }

function Ensure-Wsl {
  Hdr "Pre-flight - Windows / WSL2"
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) {
    Roadblock "WSL is not installed" @(
      "Open an ELEVATED PowerShell (Run as administrator) and run:  wsl --install",
      "Reboot when prompted, finish creating your Linux username/password.")
  }
  Ok "WSL present"
  $distros = @(Get-WslDistros)
  if ($distros.Count -eq 0) {
    Roadblock "No WSL Linux distribution installed" @(
      "Install Ubuntu:  wsl --install -d Ubuntu",
      "Launch it once to create your UNIX user, then re-run this script.")
  }
  if ($distros -notcontains $script:Distro) {
    if ($distros.Count -eq 1) { $script:Distro = $distros[0]; Warn "using distro '$($script:Distro)'" }
    else { Roadblock "Distro '$($script:Distro)' not found" @("Installed: $($distros -join ', ')","Pick one: `$env:WSL_DISTRO='<name>'; then re-run.") }
  }
  Ok "WSL distro: $($script:Distro)"
  if (-not (WslQ 'command -v git')) { Step "Installing git in WSL"; Wsl 'sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq && sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq git' | Out-Null }
}

function Ensure-Repo {
  Hdr "Repo (in WSL, on native ext4)"
  if (WslQ "test -d ~/$($script:VmRepo)/.git") { Wsl "cd ~/$($script:VmRepo) && git pull -q || true" | Out-Null; Skip "repo present (pulled latest)" }
  else { Step "Cloning repo into WSL"; if ((Wsl "git clone -q $RepoUrl ~/$($script:VmRepo)") -eq 0) { Ok "cloned ~/$($script:VmRepo)" } else { Roadblock "git clone failed in WSL" @("wsl -d $($script:Distro)","git clone $RepoUrl ~/$($script:VmRepo)") } }
  Step "Syncing lab-linux.sh into WSL"; Sync-Lab; Ok "lab-linux.sh synced"
}

function Copy-Creds {
  # Best-effort: seed the WSL .env with GC_OTLP_* from this Windows repo's local\.env.
  $winEnv = Join-Path $script:RepoRoot 'local\.env'
  if (-not (Test-Path $winEnv)) { return }
  $kv = @{}
  Get-Content $winEnv | ForEach-Object { if ($_ -match '^(GC_OTLP_URL|GC_OTLP_ACCOUNT|GC_OTLP_KEY|LAB_TESTER_ID)=(.*)$') { $kv[$Matches[1]] = $Matches[2].Trim() } }
  if (-not ($kv['GC_OTLP_KEY'] -like 'glc_*')) { return }
  Step "Seeding WSL .env with GC_OTLP_* from Windows local\.env"
  Wsl "cd ~/$($script:VmRepo)/local && [ -f .env ] || cp .env.example .env" | Out-Null
  foreach ($k in $kv.Keys) {
    $v = $kv[$k]; if ([string]::IsNullOrWhiteSpace($v)) { continue }
    Wsl "cd ~/$($script:VmRepo)/local && grep -v '^$k=' .env > .env.t && printf '%s\n' '$k=$v' >> .env.t && mv .env.t .env" | Out-Null
  }
  Ok "credentials seeded"
}

function Deploy-Local {
  Ensure-Wsl; Ensure-Repo; Copy-Creds
  Hdr "Lab bring-up (inside WSL)"
  Step "Running oneclick/lab-linux.sh deploy in WSL (installs toolchain, brings up the lab, imports dashboards)"
  $rc = Wsl "bash ~/$($script:VmRepo)/oneclick/lab-linux.sh deploy"
  if ($rc -eq 2) { Write-Host "`nResolve the roadblock shown above, then re-run .\oneclick\deploy.ps1" -ForegroundColor Yellow; $script:Failed += ,'lab bring-up (roadblock)'; Final-Report "stopped at a roadblock"; exit 2 }
  elseif ($rc -ne 0) { Fail "lab bring-up failed (exit $rc)"; }
  else { Ok "lab up + telemetry flowing (see Explore in Grafana Cloud)" }
}

function Deploy-Aws {
  Hdr "Pre-flight - AWS / EKS (run via WSL)"
  Warn "The AWS path drives the repo's terraform + 'make all' inside WSL (not validated in this session)."
  Ensure-Wsl; Ensure-Repo
  foreach ($t in 'aws','kubectl') { if (-not (WslQ "command -v $t")) { Roadblock "$t missing in WSL" @("wsl -d $($script:Distro)","sudo apt-get install -y $t (or the vendor installer)") } }
  if (-not (WslQ 'command -v tofu' ) -and -not (WslQ 'command -v terraform')) { Roadblock "OpenTofu/Terraform missing in WSL" @("Install OpenTofu in WSL: https://opentofu.org/docs/intro/install/") }
  if (-not (WslQ 'aws sts get-caller-identity')) { Roadblock "AWS credentials not working in WSL" @("wsl -d $($script:Distro) then: aws configure") }
  if (-not (WslQ "test -f ~/$($script:VmRepo)/terraform/terraform.tfvars")) { Roadblock "terraform.tfvars missing" @("wsl -d $($script:Distro)","cd ~/$($script:VmRepo)/terraform && cp terraform.tfvars.example terraform.tfvars","Edit it (region, cluster, SSH key, allowed CIDRs).") }
  Step "make infra (OpenTofu apply)"; if ((Wsl "cd ~/$($script:VmRepo) && make infra") -ne 0) { Roadblock "make infra failed" @("wsl -d $($script:Distro) then: cd ~/$($script:VmRepo)/terraform && tofu plan") }
  Ok "AWS infra provisioned"
  Step "make all (Posts 3-6)"; if ((Wsl "cd ~/$($script:VmRepo) && make all") -ne 0) { Roadblock "make all failed" @("wsl -d $($script:Distro) then: cd ~/$($script:VmRepo) && make status") }
  Ok "EKS lab + telemetry + dashboards deployed"
}

Hdr "network-o11y-demo - one-click DEPLOY (Windows/WSL2)"
State-Init; Choose-Target
Write-Host "Target: $($script:Target)"
if ($script:Target -eq 'aws') { Deploy-Aws } else { Deploy-Local }
Final-Report "Deploy complete."
