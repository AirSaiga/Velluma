#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 正式生产环境 · 单独启动后端（无热重载，前台运行）。
.DESCRIPTION
    scripts/prod/ 四件套之一，与本目录 start-all.ps1 互不依赖、逻辑各自独立。
    走 main.py 的 __main__：内部 find_available_port 扫描（8002~8100，与全端契约
    一致，check_launcher_contract.py 对拍）并自写 data/port.txt——无需脚本侧协商。
    前台运行：日志直接打在本窗口，Ctrl+C 停止（收摊兜底 scripts\stop-velluma.bat）。

    端口段常量仅用于「已在运行」判定与提示；实际协商在后端内部完成。
#>
param(
    [switch]$DryRun    # 仅打印将执行的命令
)

$ErrorActionPreference = "Stop"

# 脚本位于 scripts/prod/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$DefaultBackendPort = 8002
$BackendPortMax     = 8100   # 与 backend/core/config.py、stop-velluma.ps1 孤儿清扫段对齐
$PortFile           = Join-Path $ProjectRoot "data\port.txt"
$VenvPaths          = @(".venv\Scripts\python.exe", "venv\Scripts\python.exe")

function Test-PortOpen($Port) {
    try {
        $client = New-Object System.Net.Sockets.TcpClient
        $result = $client.BeginConnect("127.0.0.1", $Port, $null, $null)
        $success = $result.AsyncWaitHandle.WaitOne(1000, $false)
        if ($success) {
            $client.EndConnect($result)
            $client.Close()
            return $true
        }
        $client.Close()
        return $false
    } catch {
        return $false
    }
}

function Read-PortFile([string]$Path) {
    if (Test-Path $Path) {
        try {
            $port = [int]((Get-Content $Path -Raw).Trim())
            if ($port -gt 0) { return $port }
        } catch {}
    }
    return 0
}

function Find-Python() {
    foreach ($path in $VenvPaths) {
        $fullPath = Join-Path $ProjectRoot $path
        if (Test-Path $fullPath) { return $fullPath }
    }
    throw "Python venv not found. Please ensure .venv or venv exists."
}

$recorded = Read-PortFile $PortFile

Write-Host ""
if ($recorded -gt 0) {
    Write-Host "  Velluma · PROD 后端（端口由后端自协商，上次记录 :$recorded）" -ForegroundColor Cyan
} else {
    Write-Host "  Velluma · PROD 后端（端口由后端自协商，默认 ${DefaultBackendPort} 起）" -ForegroundColor Cyan
}
Write-Host ""

if ($recorded -gt 0 -and (Test-PortOpen -Port $recorded)) {
    Write-Host "[OK] 后端已在运行 http://127.0.0.1:$recorded" -ForegroundColor Green
    return
}

$pythonPath = Find-Python

if ($DryRun) {
    Write-Host "[DryRun] Would run: $pythonPath -m backend.main (cwd: $ProjectRoot)" -ForegroundColor Gray
    return
}

# 前台直跑：输出实时进本窗口；main.py 自己扫描空闲端口并写 data/port.txt
$env:PYTHONUNBUFFERED = "1"
$env:PYTHONIOENCODING = "utf-8"
Push-Location $ProjectRoot
try {
    & $pythonPath -m backend.main
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
