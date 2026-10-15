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

$mainExe = Join-Path $PSScriptRoot "dist\NVR Assistant.exe"
if (-not (Test-Path -LiteralPath $mainExe)) {
    throw "Standalone NVR Assistant.exe was not generated."
}

# v1.0.0 的旧更新助手只识别 NVRInspector.exe。ZIP 中保留一个兼容副本，
# 旧版本升级后仍使用单文件 EXE；v1.0.2 起不再依赖 NVRUpdater.exe。
$legacyExe = Join-Path $PSScriptRoot "dist\NVRInspector.exe"
Copy-Item -LiteralPath $mainExe -Destination $legacyExe -Force

$archive = Join-Path $PSScriptRoot "dist\NVRAssistant-windows-x64.zip"
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Compress-Archive -LiteralPath $mainExe, $legacyExe -DestinationPath $archive -CompressionLevel Optimal

$sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
$shaFile = "$archive.sha256"
Set-Content -LiteralPath $shaFile -Value $sha256 -Encoding ascii

Write-Host "Standalone EXE: $mainExe"
Write-Host "Archive: $archive"
Write-Host "SHA256: $sha256"
