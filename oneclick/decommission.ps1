# One-click DECOMMISSION for Windows (WSL2). Run from PowerShell:
#     .\oneclick\decommission.ps1
# Tears down what deploy.ps1 created. Prompts before destructive extras
# (unregistering the distro, removing dashboards). Roadblocks exit 2 to re-run.
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
    Step "Stopping lab (traffic, join-app, make down) via lab-linux.sh"
    $rc = Wsl "bash ~/$($script:VmRepo)/oneclick/lab-linux.sh decommission"
    if ($rc -eq 2) { Write-Host "`nResolve the roadblock above, then re-run." -ForegroundColor Yellow; Final-Report "stopped at a roadblock"; exit 2 }
    elseif ($rc -eq 0) { Ok "lab torn down" } else { Fail "teardown returned exit $rc" }
  } else { Skip "repo not present in WSL" }

  if (($distros -contains $script:Distro) -and (Confirm-Yes "Also UNREGISTER the WSL distro '$($script:Distro)' (deletes repo, images, tools)?")) {
    Step "wsl --unregister $($script:Distro)"; wsl.exe --unregister $script:Distro; if ($LASTEXITCODE -eq 0) { Ok "distro unregistered" } else { Warn "could not unregister distro" }
  } else { Skip "WSL distro kept (re-deploy will be fast)" }

  # optional: remove dashboards from Grafana Cloud (via gcx inside WSL)
  if ((WslQ 'command -v gcx') -and (WslQ 'gcx config check')) {
    if (Confirm-Yes "Remove the '$($script:GFolder)' dashboards from Grafana Cloud?") {
      Step "Deleting dashboards + folder"
      $uids = 'net-o11y-topology net-o11y-bgp-status net-o11y-device-details net-o11y-iface-health net-o11y-traffic-flows net-o11y-traffic-sankey lab-topology-graph lab-topology-health lab-network-join-demo'
      Wsl "for u in $uids; do gcx api /api/dashboards/uid/`$u -X DELETE >/dev/null 2>&1; done; gcx api /api/folders/$($script:GFolder) -X DELETE >/dev/null 2>&1; true" | Out-Null
      Ok "dashboards/folder removed (installed panel plugins left in place)"
    } else { Skip "dashboards kept in Grafana Cloud" }
  } else { Warn "gcx not authenticated in WSL - left Grafana Cloud dashboards untouched" }
  Warn "Metrics already ingested are retained per your stack's retention; nothing is deleted from the TSDB."
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
