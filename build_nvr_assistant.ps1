$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "py"
}

& $python -m PyInstaller --clean --noconfirm nvr_inspector.spec
if ($LASTEXITCODE -ne 0) {
    throw "NVR Assistant build failed."
}

$mainExe = Join-Path $PSScriptRoot "dist\NVR.Assistant.exe"
if (-not (Test-Path -LiteralPath $mainExe)) {
    throw "Standalone NVR.Assistant.exe was not generated."
}

$sha256 = (Get-FileHash -LiteralPath $mainExe -Algorithm SHA256).Hash.ToLower()
$shaFile = "$mainExe.sha256"
Set-Content -LiteralPath $shaFile -Value $sha256 -Encoding ascii

Write-Host "Standalone EXE: $mainExe"
Write-Host "Checksum: $shaFile"
Write-Host "SHA256: $sha256"
