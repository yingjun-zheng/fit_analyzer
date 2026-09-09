# 构建 Windows EXE（默认 onedir 目录版；加 -OneFile 打单文件版）
param(
    [switch]$OneFile
)

$ErrorActionPreference = "Stop"
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root

$python = "$root\.venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    Write-Error "未找到虚拟环境，请先执行: python -m venv .venv 并 pip install -r requirements.txt"
}

Write-Host "生成图标 ..."
& $python -c @"
from PIL import Image
src = Image.open(r'$root\imgs\logo.png').convert('RGBA')
# 以透明底居中，等比缩放为正方形（ico 要求方图）
w, h = src.size
s = max(w, h)
canvas = Image.new('RGBA', (s, s), (0, 0, 0, 0))
canvas.paste(src, ((s - w) // 2, (s - h) // 2))
canvas.save(r'$root\build\icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
print('icon ok')
"@

if ($OneFile) {
    $env:CRP_ONEFILE = "1"
    Write-Host "构建单文件 EXE ..."
} else {
    Remove-Item Env:CRP_ONEFILE -ErrorAction SilentlyContinue
    Write-Host "构建目录版 EXE ..."
}

& $python -m PyInstaller --noconfirm --clean build\fit_analyzer.spec

if ($LASTEXITCODE -ne 0) {
    Write-Error "PyInstaller 失败，退出码 $LASTEXITCODE"
}

Write-Host ""
Write-Host "构建完成："
Get-ChildItem "$root\dist" | ForEach-Object { Write-Host "  $($_.FullName)" }
Write-Host ""
Write-Host "启动：dist\骑行FIT数据分析器\骑行FIT数据分析器.exe"
