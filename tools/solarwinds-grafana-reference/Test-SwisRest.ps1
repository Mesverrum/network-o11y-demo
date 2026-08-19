# Fast SWIS REST probe on port 17774 using swis.env (never echo password).
$ErrorActionPreference = 'Stop'
$envFile = Join-Path $PSScriptRoot 'swis.env'
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
$port = if ($map['SW_PORT']) { [int]$map['SW_PORT'] } else { 17774 }

Write-Host "Host=$hostName Port=$port User=$user"

# Ignore self-signed Orion cert
if (-not ([System.Management.Automation.PSTypeName]'TrustAllCertsPolicy').Type) {
  Add-Type @"
using System.Net;
using System.Security.Cryptography.X509Certificates;
public class TrustAllCertsPolicy : ICertificatePolicy {
  public bool CheckValidationResult(ServicePoint srvPoint, X509Certificate certificate, WebRequest request, int certificateProblem) { return true; }
}
"@
}
[System.Net.ServicePointManager]::CertificatePolicy = New-Object TrustAllCertsPolicy
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.SecurityProtocolType]::Tls12

$pair = "{0}:{1}" -f $user, $pass
$b64 = [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($pair))
$headers = @{ Authorization = "Basic $b64"; Accept = 'application/json' }
$query = [uri]::EscapeDataString('SELECT TOP 1 ServerName FROM Orion.Websites')
$url = "https://${hostName}:${port}/SolarWinds/InformationService/v3/Json/Query?query=$query"

Write-Host "GET $url"
try {
  $resp = Invoke-RestMethod -Uri $url -Headers $headers -Method Get -TimeoutSec 30
  Write-Host "OK REST auth"
  $resp | ConvertTo-Json -Depth 5 | Write-Host

  $q2 = [uri]::EscapeDataString('SELECT COUNT(ViewID) AS C FROM Orion.Views')
  $r2 = Invoke-RestMethod -Uri "https://${hostName}:${port}/SolarWinds/InformationService/v3/Json/Query?query=$q2" -Headers $headers -TimeoutSec 30
  Write-Host ("Classic views: " + ($r2.results | ConvertTo-Json -Compress))

  $q3 = [uri]::EscapeDataString("SELECT COUNT(DashboardID) AS C FROM Orion.Dashboards.Instances WHERE ParentID IS NULL AND IsSystem = 'FALSE'")
  try {
    $r3 = Invoke-RestMethod -Uri "https://${hostName}:${port}/SolarWinds/InformationService/v3/Json/Query?query=$q3" -Headers $headers -TimeoutSec 30
    Write-Host ("Modern dashboards: " + ($r3.results | ConvertTo-Json -Compress))
  } catch {
    Write-Host "Modern dashboard count failed: $($_.Exception.Message)"
  }
  exit 0
} catch {
  Write-Host "FAIL: $($_.Exception.Message)"
  if ($_.Exception.Response) {
    try {
      $reader = New-Object IO.StreamReader($_.Exception.Response.GetResponseStream())
      Write-Host ("Body: " + $reader.ReadToEnd())
    } catch {}
  }
  exit 1
}
