# 帮学助手 一键安装（Windows PowerShell）
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Base = Join-Path $env:USERPROFILE ".bangxue"
$Venv = Join-Path $Base "venv"
$Bin = Join-Path $Base "bin"
New-Item -ItemType Directory -Force -Path $Base, $Bin | Out-Null

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
  Write-Host "❌ 未找到 python，请先安装 Python 3.9+（https://www.python.org/downloads/），勾选 Add to PATH，然后重试。"
  exit 1
}

$vp = Join-Path $Venv "Scripts\python.exe"
$pip = Join-Path $Venv "Scripts\pip.exe"

if (-not (Test-Path $vp)) {
  Write-Host "1/4 创建运行环境…"
  & python -m venv $Venv
}

Write-Host "2/4 安装帮学助手…"
& $vp -m pip install -q --upgrade pip
$wheel = Get-ChildItem (Join-Path $Dir "dist\bangxue-*.whl") -ErrorAction SilentlyContinue | Select-Object -First 1
if ($wheel) { & $pip install -q $wheel.FullName } else { & $pip install -q $Dir }

Write-Host "3/4 安装 Playwright 与浏览器组件（可能需要几分钟）…"
& $pip install -q playwright
& $vp -m playwright install chromium

Write-Host "4/4 创建命令入口…"
$exe = Join-Path $Venv "Scripts\bangxue.exe"
$cmdPath = Join-Path $Bin "bangxue.cmd"
@"
@echo off
"$exe" %*
"@ | Set-Content -Encoding ASCII $cmdPath

Write-Host ""
Write-Host "✅ 安装完成！"
Write-Host "命令入口: $cmdPath"
Write-Host "请把 $Bin 加入 PATH（系统属性→环境变量→Path），或直接使用完整路径。"
Write-Host ""
Write-Host "下一步："
Write-Host "  1) 登录一次:  `"$cmdPath`" login"
Write-Host "  2) 环境自检:  `"$cmdPath`" doctor"
Write-Host "  3) 开始学习:  `"$cmdPath`" run --scope 范围文件.json --state-dir bangxue_classes --concurrency 5"
