# Shared helpers for the Windows one-click scripts (deploy.ps1 / decommission.ps1).
# Dot-sourced by those scripts. Windows path = WSL2 (ContainerLab runs natively in
# WSL2's Linux kernel; no OrbStack). The heavy lifting lives in oneclick/lab-linux.sh,
# which these scripts run *inside* the WSL distro.

$ErrorActionPreference = 'Stop'
$script:Distro   = if ($env:WSL_DISTRO) { $env:WSL_DISTRO } else { 'Ubuntu' }
$script:VmRepo   = 'network-o11y-demo'
$script:GFolder  = 'network-lab'
$script:StateDir = Join-Path $env:USERPROFILE '.network-o11y-demo'
$script:StateFile= Join-Path $script:StateDir 'oneclick.state'
$script:RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path

function Hdr ($m){ Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Step($m){ Write-Host "> $m" -ForegroundColor White }
function Ok  ($m){ Write-Host "  [ok] $m"   -ForegroundColor Green;  $script:Done  += ,$m }
function Skip($m){ Write-Host "  [skip] $m" -ForegroundColor DarkGray; $script:Skipped += ,$m }
function Warn($m){ Write-Host "  [!] $m"    -ForegroundColor Yellow }
function Fail($m){ Write-Host "  [x] $m"    -ForegroundColor Red;    $script:Failed += ,$m }
$script:Done=@(); $script:Skipped=@(); $script:Failed=@()

function Roadblock {
  param([string]$Title,[string[]]$Steps)
  Write-Host ""
  Write-Host "+-- ROADBLOCK: $Title" -ForegroundColor Yellow
  $i=1; foreach($s in $Steps){ Write-Host ("|  {0,2}. {1}" -f $i,$s) -ForegroundColor Yellow; $i++ }
  Write-Host "|  Then re-run: $script:Self  (it resumes where it stopped)" -ForegroundColor Yellow
  Write-Host "+--" -ForegroundColor Yellow
  $script:Failed += ,$Title
  Final-Report "stopped at a roadblock"
  exit 2
}

# --- state -----------------------------------------------------------------
function State-Init { if(!(Test-Path $script:StateDir)){ New-Item -ItemType Directory -Force -Path $script:StateDir | Out-Null } }
function State-Get([string]$k){ if(Test-Path $script:StateFile){ (Get-Content $script:StateFile | Where-Object { $_ -like "$k=*" } | Select-Object -Last 1) -replace "^$k=","" } }
function State-Set([string]$k,[string]$v){ State-Init; $lines=@(); if(Test-Path $script:StateFile){ $lines=Get-Content $script:StateFile | Where-Object { $_ -notlike "$k=*" } }; ($lines + "$k=$v") | Set-Content $script:StateFile }

# --- WSL helpers (wsl.exe emits UTF-16; fix the console encoding while reading) ---
function Get-WslDistros {
  $prev=[Console]::OutputEncoding
  try { [Console]::OutputEncoding=[Text.Encoding]::Unicode; (wsl.exe -l -q) | ForEach-Object { ($_ -replace "`0","").Trim() } | Where-Object { $_ } }
  finally { [Console]::OutputEncoding=$prev }
}
function Wsl  ([string]$cmd){ wsl.exe -d $script:Distro -- bash -lc $cmd; return $LASTEXITCODE }
function WslQ ([string]$cmd){ wsl.exe -d $script:Distro -- bash -lc $cmd *> $null; return ($LASTEXITCODE -eq 0) }
function WslOut([string]$cmd){ (wsl.exe -d $script:Distro -- bash -lc $cmd) 2>$null }

# Inject THIS checkout's lab-linux.sh into the WSL clone (so it works even before
# the scripts are merged upstream). Uses wslpath to avoid stdin-encoding issues.
function Sync-Lab {
  $labWin = Join-Path $script:RepoRoot 'oneclick\lab-linux.sh'
  if (-not (Test-Path $labWin)) { return }
  $labWsl = (wsl.exe -d $script:Distro -- wslpath -u "$labWin").Trim()
  Wsl "mkdir -p ~/$($script:VmRepo)/oneclick && tr -d '\r' < '$labWsl' > ~/$($script:VmRepo)/oneclick/lab-linux.sh && chmod +x ~/$($script:VmRepo)/oneclick/lab-linux.sh" | Out-Null
  # Inject the fixed dashboard-retarget script (upstream's copy points Fabric Map at
  # deleted 404 URLs -> "Extra content at the end of the document"; Sankey grouped wrong).
  $retWin = Join-Path $script:RepoRoot 'oneclick\dashboards-retarget-local.py'
  if (Test-Path $retWin) {
    $retWsl = (wsl.exe -d $script:Distro -- wslpath -u "$retWin").Trim()
    Wsl "mkdir -p ~/$($script:VmRepo)/local/scripts && tr -d '\r' < '$retWsl' > ~/$($script:VmRepo)/local/scripts/retarget-dashboards-local.py" | Out-Null
  }
}

function Confirm-Yes([string]$q){ $a=Read-Host "  $q [y/N]"; return ($a -match '^[Yy]') }

function Choose-Target {
  $t = State-Get 'TARGET'
  if ($t){
    $script:Target = $t
    if ([Console]::IsInputRedirected) { return }   # non-interactive: keep saved target silently
    Hdr "Deployment target"
    Write-Host "  Saved target: $t"
    $c = Read-Host "  Press Enter to keep, or type 'local' / 'aws' to change"
    switch ($c) {
      ''      { $script:Target = $t }
      'local' { $script:Target = 'local' }
      '1'     { $script:Target = 'local' }
      'aws'   { $script:Target = 'aws' }
      '2'     { $script:Target = 'aws' }
      default { Warn "unrecognized '$c' - keeping saved target '$t'"; $script:Target = $t }
    }
    if ($script:Target -ne $t){ State-Set 'TARGET' $script:Target }
    return
  }
  Hdr "Choose deployment target"
  Write-Host "  1) local  - WSL2 Linux distro on this PC (ContainerLab + ktranslate -> Grafana Cloud)"
  Write-Host "  2) aws    - EKS / Clabbernetes via the repo's terraform + 'make all' (run inside WSL)"
  switch (Read-Host "  Select 1 or 2"){ '1'{$script:Target='local'} '2'{$script:Target='aws'} default{ Fail 'invalid'; exit 1 } }
  State-Set 'TARGET' $script:Target
}

function Access-Instructions {
  Hdr "How to access the components"
  if ($script:Target -eq 'aws'){
@"
  AWS / EKS
    * kubeconfig: (inside WSL) cd ~/$($script:VmRepo)/terraform; tofu output; aws eks update-kubeconfig --name <cluster>
    * pods:       wsl -d $($script:Distro) -- bash -lc 'cd ~/$($script:VmRepo) && make status'
    * tunnels:    wsl -d $($script:Distro) -- bash -lc 'cd ~/$($script:VmRepo) && make access'
  Grafana Cloud
    * UI: https://<your-stack>.grafana.net  ->  Dashboards -> folder '$($script:GFolder)'
"@ | Write-Host
  } else {
@"
  Local WSL distro
    * Shell:    wsl -d $($script:Distro)
    * One cmd:  wsl -d $($script:Distro) -- bash -lc 'docker ps'
    * Lab dir:  ~/$($script:VmRepo)/local   (inside WSL, on native ext4)
    * Controls: wsl -d $($script:Distro) -- bash -lc 'cd ~/$($script:VmRepo)/local && make status | traffic | stabilize'
  Grafana Cloud
    * UI:  https://<your-stack>.grafana.net  ->  Dashboards -> folder '$($script:GFolder)'
    * Explore: kentik_snmp_CPU  |  topk(20, network_io_by_flow_bytes)  |  network_topology_device_info
  AWS
    * Not used in a local deployment.
"@ | Write-Host
  }
}

function Final-Report([string]$note){
  Hdr "Report - $($script:Action) ($($script:Target))"
  if ($script:Done.Count)   { Write-Host "Completed:" -ForegroundColor Green;    $script:Done    | ForEach-Object { Write-Host "  [ok] $_" } }
  if ($script:Skipped.Count){ Write-Host "Already in place:" -ForegroundColor DarkGray; $script:Skipped | ForEach-Object { Write-Host "  [skip] $_" } }
  if ($script:Failed.Count) { Write-Host "Not completed:" -ForegroundColor Red;  $script:Failed  | ForEach-Object { Write-Host "  [x] $_" } }
  if ($note){ Write-Host "`n$note" -ForegroundColor Yellow }
  if ($script:Action -eq 'decommission'){
    Hdr "Next steps"; Write-Host "  Re-deploy: .\oneclick\deploy.ps1"; Write-Host "  Forget target choice: Remove-Item '$($script:StateFile)'"
  } elseif ($script:Failed.Count -eq 0) {
    # only show access instructions on a clean deploy; on a roadblock the remediation is the guidance
    Access-Instructions
  }
}
