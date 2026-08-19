# Probe Orion SWIS using gitignored swis.env — never echo password.
$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot 'swis.env'
if (-not (Test-Path $envFile)) { throw "Missing $envFile" }

$map = @{}
Get-Content $envFile | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) { return }
  $i = $line.IndexOf('=')
  if ($i -lt 1) { return }
  $map[$line.Substring(0, $i).Trim()] = $line.Substring($i + 1).Trim().Trim('"').Trim("'")
}

$hostName = $map['SW_HOST']
$user = $map['SW_USER']
$pass = $map['SW_PASSWORD']
if (-not $hostName -or -not $user -or -not $pass -or $pass -eq 'REPLACE_ME') {
  throw "swis.env incomplete (need SW_HOST/SW_USER/SW_PASSWORD)"
}

Write-Host "Host: $hostName"
Write-Host "User: $user"
Write-Host "Password: (set, len=$($pass.Length))"

# TCP reachability (SWIS typically 17777/17778)
foreach ($port in 17777, 17778, 443, 80) {
  try {
    $tcp = Test-NetConnection -ComputerName $hostName -Port $port -WarningAction SilentlyContinue
    Write-Host ("TCP {0}:{1} -> TcpTestSucceeded={2}" -f $hostName, $port, $tcp.TcpTestSucceeded)
  } catch {
    Write-Host ("TCP {0}:{1} -> error: {2}" -f $hostName, $port, $_)
  }
}

$mod = Get-Module -ListAvailable SwisPowerShell | Select-Object -First 1
if (-not $mod) {
  Write-Host "SwisPowerShell module: NOT INSTALLED"
  Write-Host "Install: Install-Module SwisPowerShell -Scope CurrentUser"
  exit 2
}
Write-Host "SwisPowerShell: $($mod.Version) @ $($mod.ModuleBase)"
Import-Module SwisPowerShell -ErrorAction Stop

$sec = ConvertTo-SecureString $pass -AsPlainText -Force
$cred = New-Object System.Management.Automation.PSCredential ($user, $sec)

Write-Host "Connecting via Connect-Swis..."
try {
  $swis = Connect-Swis -Hostname $hostName -Credential $cred
  $row = Get-SwisData $swis 'SELECT TOP 1 ServerName FROM Orion.Websites'
  Write-Host "OK connected. Orion.Websites.ServerName=$row"

  $viewCount = Get-SwisData $swis 'SELECT COUNT(ViewID) AS C FROM Orion.Views'
  Write-Host "Classic views: $viewCount"
  try {
    $mdCount = Get-SwisData $swis "SELECT COUNT(DashboardID) AS C FROM Orion.Dashboards.Instances WHERE ParentID IS NULL AND IsSystem = 'FALSE'"
    Write-Host "Modern dashboards (non-system): $mdCount"
  } catch {
    Write-Host "Modern dashboards query failed: $_"
  }
  exit 0
} catch {
  Write-Host "CONNECT FAILED: $($_.Exception.Message)"
  if ($_.Exception.InnerException) {
    Write-Host "Inner: $($_.Exception.InnerException.Message)"
  }
  exit 1
}
