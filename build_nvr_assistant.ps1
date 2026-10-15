$ErrorActionPreference = "Stop"

Set-Location $PSScriptRoot

$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    $python = "py"
}

& $python -m PyInstaller --clean --noconfirm nvr_inspector.spec
if ($LASTEXITCODE -ne 0) {
    throw "NVRInspector build failed."
}

& $python -m PyInstaller --clean --noconfirm nvr_updater.spec
if ($LASTEXITCODE -ne 0) {
    throw "NVRUpdater build failed."
}

$bundleDir = Join-Path $PSScriptRoot "dist\NVRInspector"
$updaterExe = Join-Path $PSScriptRoot "dist\NVRUpdater.exe"
$bundleUpdater = Join-Path $bundleDir "NVRUpdater.exe"
Copy-Item -LiteralPath $updaterExe -Destination $bundleUpdater -Force

$archive = Join-Path $PSScriptRoot "dist\NVRAssistant-windows-x64.zip"
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $bundleDir -DestinationPath $archive -CompressionLevel Optimal

$sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
$shaFile = "$archive.sha256"
Set-Content -LiteralPath $shaFile -Value $sha256 -Encoding ascii

Write-Host "Bundle: $bundleDir"
Write-Host "Archive: $archive"
Write-Host "SHA256: $sha256"
