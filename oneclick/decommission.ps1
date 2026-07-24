# One-click DECOMMISSION for Windows (WSL2). Run from PowerShell:
#     .\oneclick\decommission.ps1
# Tears down what deploy.ps1 created by running lab-linux.sh 'decommission' inside
# WSL (which also does the Grafana teardown: dashboards + only the plugins THIS
# deploy installed, asking first). Prompts before unregistering the distro.
$ErrorActionPreference = 'Stop'
$script:Self   = '.\oneclick\decommission.ps1'
$script:Action = 'decommission'
. (Join-Path $PSScriptRoot 'common.ps1')

function Decom-Local {
  Hdr "Tear down local lab (WSL)"
  if (-not (Get-Command wsl.exe -ErrorAction SilentlyContinue)) { Skip "WSL not installed - nothing local to remove"; return }
  $distros = @(Get-WslDistros)
  if ($distros -notcontains $script:Distro) { Skip "distro '$($script:Distro)' not present"; }
  elseif (WslQ "test -d ~/$($script:VmRepo)/local") {
    # gather the yes/no answers HERE (clean prompts), then run non-interactively in WSL
    $rmDash = 0; if (Confirm-Yes "Remove the network-lab dashboards + folder from Grafana Cloud?") { $rmDash = 1 }
    $rmPlugins = @()
    foreach ($p in ((WslOut "cat ~/.network-o11y-demo-oneclick/plugins-installed 2>/dev/null") -split "`n" | ForEach-Object { $_.Trim() } | Where-Object { $_ })) {
      if (Confirm-Yes "Remove panel plugin '$p' that THIS deploy installed? (may be used by other dashboards now)") { $rmPlugins += $p }
    }
    $rmP = ($rmPlugins -join ' ')
    Sync-Lab
    Step "Tearing down (lab + Grafana) via lab-linux.sh in WSL"
    $rc = Wsl "set -o pipefail; RM_DASHBOARDS=$rmDash RM_PLUGINS='$rmP' bash ~/$($script:VmRepo)/oneclick/lab-linux.sh decommission 2>&1 | cat -s"
    if ($rc -eq 2) { Write-Host "`nResolve the roadblock above, then re-run." -ForegroundColor Yellow; Final-Report "stopped at a roadblock"; exit 2 }
    elseif ($rc -eq 0) { Ok "lab torn down" } else { Fail "teardown returned exit $rc" }
  } else { Skip "repo not present in WSL" }

  if (($distros -contains $script:Distro) -and (Confirm-Yes "Also UNREGISTER the WSL distro '$($script:Distro)' (deletes repo, images, tools)?")) {
    Step "wsl --unregister $($script:Distro)"; wsl.exe --unregister $script:Distro; if ($LASTEXITCODE -eq 0) { Ok "distro unregistered" } else { Warn "could not unregister distro" }
  } else { Skip "WSL distro kept (re-deploy will be fast)" }
}

function Decom-Aws {
  Hdr "Tear down AWS / EKS (via WSL)"
  if (-not (WslQ 'aws sts get-caller-identity')) { Roadblock "AWS credentials not working in WSL" @("wsl -d $($script:Distro) then: aws configure") }
  Write-Host "  This destroys ALL AWS infrastructure (EKS, VPC, bastion)." -ForegroundColor Red
  if (-not (Confirm-Yes "Proceed with 'make destroy'?")) { Warn "aborted by user"; return }
  Step "make destroy (OpenTofu destroy) via WSL"
  if ((Wsl "cd ~/$($script:VmRepo) && make destroy") -ne 0) { Roadblock "make destroy failed" @("wsl -d $($script:Distro) then: cd ~/$($script:VmRepo)/terraform && tofu destroy") }
  Ok "AWS infrastructure destroyed"
}

Hdr "network-o11y-demo - one-click DECOMMISSION (Windows/WSL2)"
State-Init
$script:Target = State-Get 'TARGET'
if (-not $script:Target) { Choose-Target }
Write-Host "Target: $($script:Target)"
if ($script:Target -eq 'aws') { Decom-Aws } else { Decom-Local }
Final-Report "Decommission complete."
