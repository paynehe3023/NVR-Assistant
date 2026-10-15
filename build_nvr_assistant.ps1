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

$bundleDir = Join-Path $PSScriptRoot "dist\NVR Assistant"
$legacyUpdater = Join-Path $bundleDir "NVRUpdater.exe"
Remove-Item -LiteralPath $legacyUpdater -Force -ErrorAction SilentlyContinue

# v1.0.0 的旧更新助手只识别 NVRInspector.exe。保留一个兼容启动副本，
# 让旧版本能够正常升级；v1.0.2 起更新安装由主程序内置完成。
$mainExe = Join-Path $bundleDir "NVR Assistant.exe"
$legacyExe = Join-Path $bundleDir "NVRInspector.exe"
Copy-Item -LiteralPath $mainExe -Destination $legacyExe -Force

$archive = Join-Path $PSScriptRoot "dist\NVRAssistant-windows-x64.zip"
Remove-Item -LiteralPath $archive -Force -ErrorAction SilentlyContinue
Compress-Archive -Path $bundleDir -DestinationPath $archive -CompressionLevel Optimal

$sha256 = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLower()
$shaFile = "$archive.sha256"
Set-Content -LiteralPath $shaFile -Value $sha256 -Encoding ascii

Write-Host "Bundle: $bundleDir"
Write-Host "Archive: $archive"
Write-Host "SHA256: $sha256"
