param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $PSScriptRoot
$solution = Join-Path $projectRoot "Cartomize.ArcGISPro.sln"
$releaseFolder = Join-Path $projectRoot "release"
$nugetConfig = Join-Path $projectRoot "NuGet.Config"

if (-not (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    throw ".NET SDK 10 est introuvable. Installez Visual Studio 2026 avec le développement desktop .NET."
}

$sdkVersion = (& dotnet --version).Trim()
if (-not $sdkVersion.StartsWith("10.")) {
    throw "Le SDK .NET 10 est requis. Version détectée : $sdkVersion"
}

$vsWhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vsWhere)) {
    throw "Visual Studio Installer (vswhere.exe) est introuvable. Installez Visual Studio 2026."
}
$msBuild = & $vsWhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" |
    Select-Object -First 1
if (-not $msBuild) {
    throw "MSBuild Visual Studio est introuvable."
}

Push-Location $projectRoot
try {
    & $msBuild $solution /restore /t:Rebuild /m `
        /p:Configuration=$Configuration `
        /p:RestoreConfigFile=$nugetConfig
    if ($LASTEXITCODE -ne 0) { throw "La compilation de l'add-in a échoué." }

    $addIn = Get-ChildItem -Path (Join-Path $projectRoot "src") -Filter "*.esriAddInX" -Recurse |
        Sort-Object LastWriteTimeUtc -Descending |
        Select-Object -First 1
    if (-not $addIn) {
        throw "Aucun .esriAddInX n'a été produit. Vérifiez que le SDK ArcGIS Pro 3.7 est installé dans Visual Studio 2026."
    }

    New-Item -ItemType Directory -Path $releaseFolder -Force | Out-Null
    $destination = Join-Path $releaseFolder "Cartomize-ArcGISPro-10.5.1.esriAddInX"
    Copy-Item $addIn.FullName $destination -Force
    Write-Host "Add-in prêt : $destination" -ForegroundColor Green
}
finally {
    Pop-Location
}
