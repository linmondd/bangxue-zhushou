param([switch]$Mcp)
$ErrorActionPreference = "Stop"
$Base = if ($env:BANGXUE_HOME) { $env:BANGXUE_HOME } else { Join-Path $env:USERPROFILE ".bangxue" }
$Venv = Join-Path $Base "venv"
$Bin = Join-Path $Base "bin"
New-Item -ItemType Directory -Force -Path $Base, $Bin | Out-Null
function Invoke-Checked($Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "安装步骤失败（$LASTEXITCODE），请检查上方提示后重试。" }
}
$Python = Join-Path $Venv "Scripts\python.exe"
if (!(Test-Path $Python)) {
    if (Get-Command py -ErrorAction SilentlyContinue) { Invoke-Checked "py" @("-3", "-m", "venv", $Venv) }
    else { Invoke-Checked "python" @("-m", "venv", $Venv) }
}
$Extra = if ($Mcp) { 'playwright,mcp' } else { 'playwright' }
$Minor = if ($Mcp) { 10 } else { 9 }
Invoke-Checked $Python @("-c", "import sys; sys.exit(0 if sys.version_info >= (3,$Minor) else 'Python 3.$Minor+ required')")
Invoke-Checked $Python @("-m","pip","install","$PSScriptRoot[$Extra]")
Invoke-Checked $Python @("-c",'from bangxue.panel import BrowserBackend; backend = BrowserBackend(__name__); backend.repair(); assert backend.setup()[''chromium'']')
$Commands = @("bangxue")
if ($Mcp) { $Commands += "bangxue-mcp" }
foreach ($cmd in $Commands) {
    $shim = "@echo off`r`n`"%~dp0..\venv\Scripts\$cmd.exe`" %*"
    Set-Content -Encoding ASCII -Path (Join-Path $Bin "$cmd.cmd") -Value $shim
}
Write-Host "安装完成。打开控制面板："
Write-Host "& `"$(Join-Path $Bin 'bangxue.cmd')`" panel"
