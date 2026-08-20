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
from PIL import Image, ImageDraw
img = Image.new('RGBA', (64, 64), (0, 0, 0, 0))
d = ImageDraw.Draw(img)
d.ellipse([4, 4, 60, 60], fill=(30, 144, 255, 255))
d.line([(10,44),(20,26),(30,34),(40,16),(52,26)], fill=(255,255,255,255), width=5, joint='curve')
d.ellipse([36,11,45,20], fill=(255,220,60,255))
d.ellipse([46,21,58,33], fill=(255,255,255,255))
img.save(r'$root\build\icon.ico', sizes=[(16,16),(32,32),(48,48),(64,64),(128,128),(256,256)])
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
