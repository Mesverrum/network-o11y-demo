<#
.SYNOPSIS
  Bulk-export SolarWinds classic views + modern dashboards for Grafana recreation docs.

.DESCRIPTION
  Non-interactive inventory dump inspired by Mesverrum ViewExporter / sw_backupViews.ps1
  (https://github.com/Mesverrum/MyPublicWork/blob/master/ViewExporter.ps1) plus Orion SDK
  modern dashboard Export verbs.

  Writes:
    <OutDir>/raw/classic-views/<ViewGroup>/<ViewTitle>/view.json
    <OutDir>/raw/classic-views/index.json
    <OutDir>/raw/modern-dashboards/<id>_<name>.json
    <OutDir>/raw/modern-dashboards/index.json
    <OutDir>/raw/manifest.json

  Then run:  python build_grafana_reference_docs.py --input <OutDir>/raw --output <OutDir>/docs

.PARAMETER Hostname
  Orion / SolarWinds Platform host (FQDN or IP).

.PARAMETER Credential
  Explicit credentials. If omitted, prompts (Explicit) unless -Trusted.

.PARAMETER Trusted
  Use Windows/Trusted SWIS auth (Connect-Swis -Trusted).

.PARAMETER OutDir
  Root output folder. Default: .\out\<yyyyMMdd_HHmm>\

.PARAMETER IncludeSystemModern
  Also export IsSystem modern dashboards.

.PARAMETER ClassicOnly / ModernOnly
  Limit which surfaces to export.

.PARAMETER EnvFile
  Path to gitignored swis.env (SW_HOST / SW_USER / SW_PASSWORD). Default: .\swis.env next to this script.

.EXAMPLE
  # After filling tools/solarwinds-grafana-reference/swis.env:
  .\Export-SwReferenceInventory.ps1

.EXAMPLE
  .\Export-SwReferenceInventory.ps1 -Hostname orion.lab.local -Trusted

.EXAMPLE
  $c = Get-Credential
  .\Export-SwReferenceInventory.ps1 -Hostname orion.lab.local -Credential $c -OutDir D:\sw-export
#>
[CmdletBinding()]
param(
    [Parameter()]
    [string]$Hostname,

    [Parameter()]
    [pscredential]$Credential,

    [Parameter()]
    [switch]$Trusted,

    [Parameter()]
    [string]$OutDir,

    [Parameter()]
    [string]$EnvFile,

    [Parameter()]
    [switch]$IncludeSystemModern,

    [Parameter()]
    [switch]$ClassicOnly,

    [Parameter()]
    [switch]$ModernOnly
)

#Requires -Modules SwisPowerShell

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Import-SwisEnvFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) { return @{} }
    $map = @{}
    foreach ($raw in Get-Content -LiteralPath $Path) {
        $line = $raw.Trim()
        if (-not $line -or $line.StartsWith('#')) { continue }
        $eq = $line.IndexOf('=')
        if ($eq -lt 1) { continue }
        $key = $line.Substring(0, $eq).Trim()
        $val = $line.Substring($eq + 1).Trim().Trim('"').Trim("'")
        $map[$key] = $val
    }
    return $map
}

function Get-SafeName {
    param([string]$Name, [string]$Fallback = 'unnamed')
    if ([string]::IsNullOrWhiteSpace($Name)) { $Name = $Fallback }
    $invalid = [System.IO.Path]::GetInvalidFileNameChars() + @('[', ']')
    foreach ($ch in $invalid) {
        $Name = $Name.Replace([string]$ch, '_')
    }
    return ($Name.Trim() -replace '\s+', ' ')
}

function Write-JsonFile {
    param([Parameter(Mandatory)]$Object, [Parameter(Mandatory)][string]$Path)
    $json = $Object | ConvertTo-Json -Depth 40
    # UTF-8 without BOM so Python/json tooling doesn't choke on Windows PowerShell 5.x
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $json, $utf8NoBom)
}

function Get-RelativePathSafe {
    param([string]$Base, [string]$Target)
    if ([System.IO.Path]::DirectorySeparatorChar -eq '\') {
        $baseFull = [System.IO.Path]::GetFullPath($Base).TrimEnd('\') + '\'
        $targetFull = [System.IO.Path]::GetFullPath($Target)
        if ($targetFull.StartsWith($baseFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $targetFull.Substring($baseFull.Length).Replace('\', '/')
        }
    }
    try {
        return [System.IO.Path]::GetRelativePath($Base, $Target).Replace('\', '/')
    }
    catch {
        return $Target
    }
}

function Connect-SwisSession {
    if ($Trusted) {
        return Connect-Swis -Trusted -Hostname $Hostname
    }
    if (-not $Credential) {
        $Credential = Get-Credential -Message "SolarWinds / Orion credentials for $Hostname"
    }
    return Connect-Swis -Credential $Credential -Hostname $Hostname
}

# ---- resolve connection from swis.env if needed ----
if (-not $EnvFile) {
    $EnvFile = Join-Path $PSScriptRoot 'swis.env'
}
$envMap = Import-SwisEnvFile -Path $EnvFile
if (-not $Hostname -and $envMap['SW_HOST']) { $Hostname = $envMap['SW_HOST'] }
if (-not $Hostname) {
    throw "Hostname required. Pass -Hostname or set SW_HOST in $EnvFile"
}
if (-not $Trusted -and -not $Credential -and $envMap['SW_USER'] -and $envMap['SW_PASSWORD']) {
    $sec = ConvertTo-SecureString -String $envMap['SW_PASSWORD'] -AsPlainText -Force
    $Credential = New-Object System.Management.Automation.PSCredential ($envMap['SW_USER'], $sec)
}

function Get-ResourceProperties {
    param($Swis, [int]$ResourceId)
    # ViewExporter used Orion.Reporting ExecuteSQL against ResourceProperties.
    # Prefer SWIS entity when available; fall back to ExecuteSQL.
    try {
        $rows = Get-SwisData $Swis @"
SELECT PropertyName, PropertyValue
FROM Orion.ResourceProperties
WHERE ResourceID = $ResourceId
"@
        if ($rows) {
            return @(
                foreach ($r in @($rows)) {
                    [pscustomobject]@{
                        PropertyName  = [string]$r.PropertyName
                        PropertyValue = [string]$r.PropertyValue
                    }
                }
            )
        }
    }
    catch {
        Write-Verbose "Orion.ResourceProperties unavailable for $ResourceId — falling back to ExecuteSQL"
    }

    $sql = @"
SELECT propertyname, propertyvalue
FROM resourceproperties
WHERE resourceid = $ResourceId
"@
    $xml = Invoke-SwisVerb $Swis 'Orion.Reporting' 'ExecuteSQL' @($sql)
    $nodes = @($xml.ChildNodes.DocumentElement.ExecuteSqlResults)
    return @(
        foreach ($n in $nodes) {
            if (-not $n) { continue }
            [pscustomobject]@{
                PropertyName  = [string]$n.propertyname
                PropertyValue = [string]$n.propertyvalue
            }
        }
    )
}

function Export-ClassicViews {
    param($Swis, [string]$Root)

    $viewsRoot = Join-Path $Root 'classic-views'
    New-Item -ItemType Directory -Force -Path $viewsRoot | Out-Null

    $views = @(Get-SwisData $Swis @"
SELECT
  v.ViewID,
  v.ViewTitle,
  v.ViewKey,
  v.ViewType,
  v.ViewGroup,
  v.ViewGroupName,
  v.ViewGroupPosition,
  v.ViewIcon,
  v.Columns,
  v.Column1Width, v.Column2Width, v.Column3Width,
  v.Column4Width, v.Column5Width, v.Column6Width,
  v.Customizable,
  v.NOCView,
  v.NOCViewRotationInterval
FROM Orion.Views v
ORDER BY v.ViewGroupName, v.ViewGroupPosition, v.ViewTitle
"@)

    $index = @()
    $i = 0
    foreach ($v in $views) {
        $i++
        $groupName = if ($v.ViewGroupName) { [string]$v.ViewGroupName } else { 'NoViewGroup' }
        $title = [string]$v.ViewTitle
        $folder = Join-Path $viewsRoot (Join-Path (Get-SafeName $groupName) (Get-SafeName $title "view_$($v.ViewID)"))
        New-Item -ItemType Directory -Force -Path $folder | Out-Null

        Write-Host ("[{0}/{1}] Classic view {2} :: {3}" -f $i, $views.Count, $v.ViewID, $title)

        $resources = @(Get-SwisData $Swis @"
SELECT
  ResourceID, ViewID, ViewColumn, Position,
  ResourceName, ResourceFile, ResourceTitle, ResourceSubTitle
FROM Orion.Resources
WHERE ViewID = $($v.ViewID)
ORDER BY ViewColumn, Position
"@)

        $resourceObjs = @()
        foreach ($r in $resources) {
            $props = Get-ResourceProperties -Swis $Swis -ResourceId ([int]$r.ResourceID)
            $propMap = [ordered]@{}
            foreach ($p in $props) {
                if (-not $p.PropertyName) { continue }
                $propMap[[string]$p.PropertyName] = [string]$p.PropertyValue
            }
            $resourceObjs += [ordered]@{
                resourceId       = [int]$r.ResourceID
                viewColumn       = $r.ViewColumn
                position         = $r.Position
                resourceName     = [string]$r.ResourceName
                resourceFile     = [string]$r.ResourceFile
                resourceTitle    = [string]$r.ResourceTitle
                resourceSubTitle = [string]$r.ResourceSubTitle
                properties       = $propMap
            }
        }

        $viewObj = [ordered]@{
            kind                 = 'classic-view'
            viewId               = [int]$v.ViewID
            viewTitle            = $title
            viewKey              = [string]$v.ViewKey
            viewType             = $v.ViewType
            viewGroup            = $v.ViewGroup
            viewGroupName        = $groupName
            viewGroupPosition    = $v.ViewGroupPosition
            viewIcon             = [string]$v.ViewIcon
            columns              = $v.Columns
            columnWidths         = @(
                $v.Column1Width, $v.Column2Width, $v.Column3Width,
                $v.Column4Width, $v.Column5Width, $v.Column6Width
            )
            customizable         = $v.Customizable
            nocView              = $v.NOCView
            nocViewRotationInterval = $v.NOCViewRotationInterval
            resources            = $resourceObjs
        }

        $viewPath = Join-Path $folder 'view.json'
        Write-JsonFile -Object $viewObj -Path $viewPath

        $index += [ordered]@{
            viewId        = [int]$v.ViewID
            viewTitle     = $title
            viewGroupName = $groupName
            resourceCount = $resourceObjs.Count
            path          = Get-RelativePathSafe -Base $Root -Target $viewPath
        }
    }

    Write-JsonFile -Object $index -Path (Join-Path $viewsRoot 'index.json')
    Write-Host "Classic views exported: $($index.Count)"
    return $index.Count
}

function Export-ModernDashboards {
    param($Swis, [string]$Root)

    $mdRoot = Join-Path $Root 'modern-dashboards'
    New-Item -ItemType Directory -Force -Path $mdRoot | Out-Null

    if ($IncludeSystemModern) {
        $ids = @(Get-SwisData $Swis "SELECT DashboardID, DisplayName, UniqueKey, IsSystem FROM Orion.Dashboards.Instances WHERE ParentID IS NULL")
    }
    else {
        $ids = @(Get-SwisData $Swis "SELECT DashboardID, DisplayName, UniqueKey, IsSystem FROM Orion.Dashboards.Instances WHERE ParentID IS NULL AND IsSystem = 'FALSE'")
    }

    $index = @()
    $i = 0
    foreach ($row in $ids) {
        $i++
        $id = [int]$row.DashboardID
        $name = [string]$row.DisplayName
        Write-Host ("[{0}/{1}] Modern dashboard {2} :: {3}" -f $i, $ids.Count, $id, $name)

        try {
            $exported = Invoke-SwisVerb $Swis 'Orion.Dashboards.Instances' 'Export' @($id)
            $jsonText = $exported.'#text'
            if (-not $jsonText) {
                # Some SWIS versions return the string as InnerText / ToString
                $jsonText = [string]$exported
            }
            $obj = $jsonText | ConvertFrom-Json
            $dashName = $obj.dashboards.name
            if (-not $dashName) { $dashName = $name }
            if ($row.IsSystem) { $dashName = "SYSTEM_$dashName" }

            $fileName = '{0}_{1}.json' -f $id, (Get-SafeName $dashName)
            $path = Join-Path $mdRoot $fileName
            Write-JsonFile -Object $obj -Path $path

            $index += [ordered]@{
                dashboardId = $id
                name        = $dashName
                uniqueKey   = [string]$row.UniqueKey
                isSystem    = [bool]$row.IsSystem
                path        = Get-RelativePathSafe -Base $Root -Target $path
            }
        }
        catch {
            Write-Warning "Failed modern dashboard $id ($name): $_"
            $index += [ordered]@{
                dashboardId = $id
                name        = $name
                error       = "$_"
            }
        }
    }

    Write-JsonFile -Object $index -Path (Join-Path $mdRoot 'index.json')
    Write-Host "Modern dashboards exported: $($index.Count)"
    return $index.Count
}

# ---- main ----
$probe = $null
$swis = Connect-SwisSession
$probe = Get-SwisData $swis 'SELECT TOP 1 ServerName FROM Orion.Websites'
Write-Host "Connected to $Hostname ($probe)"

if (-not $OutDir) {
    $stamp = Get-Date -Format 'yyyyMMdd_HHmm'
    $OutDir = Join-Path $PSScriptRoot (Join-Path 'out' $stamp)
}
$raw = Join-Path $OutDir 'raw'
New-Item -ItemType Directory -Force -Path $raw | Out-Null

$classicCount = 0
$modernCount = 0
if (-not $ModernOnly) {
    $classicCount = Export-ClassicViews -Swis $swis -Root $raw
}
if (-not $ClassicOnly) {
    $modernCount = Export-ModernDashboards -Swis $swis -Root $raw
}

$manifest = [ordered]@{
    exportedAt     = (Get-Date).ToString('o')
    hostname       = $Hostname
    classicViews   = $classicCount
    modernDashboards = $modernCount
    sourceScripts  = @(
        'Mesverrum ViewExporter / sw_backupViews pattern',
        'OrionSDK Export-ModernDashboard (Orion.Dashboards.Instances.Export)'
    )
}
Write-JsonFile -Object $manifest -Path (Join-Path $raw 'manifest.json')

Write-Host ""
Write-Host "Raw export: $raw"
Write-Host "Next: python `"$PSScriptRoot\build_grafana_reference_docs.py`" --input `"$raw`" --output `"$(Join-Path $OutDir 'docs')`""
