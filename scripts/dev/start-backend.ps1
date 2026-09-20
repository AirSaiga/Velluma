#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 开发调试环境 · 单独启动后端（uvicorn --reload 热重载，前台运行）。
.DESCRIPTION
    scripts/dev/ 四件套之一，与本目录 start-all.ps1 互不依赖、逻辑各自独立。
    前台运行：日志直接打在本窗口，Ctrl+C 停止（收摊兜底 scripts\stop-velluma.bat）。

    端口契约（与 start-all / prod / macos / monitor 监督者一致，check_launcher_contract.py 对拍）：
      - 协商优先级：环境变量 VELLUMA_PORT → data/port.txt 已记录且空闲 → 扫描 8002~8100；
      - 选中即写 data/port.txt——uvicorn 直启不走 main.py 的 __main__（save_port 不会执行），
        端口文件必须脚本侧写好；固定端口是热重载期间端口不漂移、前端不断连的前提。

    只起后端；要前端/Electron 另跑同目录 start-frontend.bat / start-electron.bat。
#>
param(
    [switch]$Force,    # 端口被占时强制清理（只杀命令行含本项目路径的监听者）
    [switch]$DryRun    # 仅打印将执行的命令
)

$ErrorActionPreference = "Stop"

# 脚本位于 scripts/dev/ 下，项目根是 $PSScriptRoot 的祖父目录
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

function Write-PortFile([string]$Path, $Port) {
    # DryRun 绝不落盘：试跑改写端口文件会把正在运行的实例与下次启动的协商带偏
    if ($DryRun) { return }
    try {
        $dir = Split-Path $Path -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        [System.IO.File]::WriteAllText($Path, ([int]$Port).ToString())
    } catch {
        Write-Host "[ERR] Failed to write port file: $_" -ForegroundColor Red
    }
}

function Find-FreePort([int]$Start, [int]$End) {
    for ($port = $Start; $port -le $End; $port++) {
        if (-not (Test-PortOpen -Port $port)) { return $port }
    }
    throw "No free port in range $Start..$End"
}

function Get-ProcessOnPort($Port) {
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
                Where-Object { $_.State -eq "Listen" } |
                Select-Object -First 1
        if ($conn) {
            return Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        }
    } catch {}
    return $null
}

function Kill-ProcessOnPort($Port) {
    # 只杀「自己的」监听者：进程命令行须含本项目路径（他人项目/无关进程占口 → 拒杀留活）
    $proc = Get-ProcessOnPort -Port $Port
    if ($proc) {
        $cim = Get-CimInstance Win32_Process -Filter "ProcessId=$($proc.Id)" -ErrorAction SilentlyContinue
        $marker = "*" + $ProjectRoot + "*"
        if (-not $cim -or -not $cim.CommandLine -like $marker) {
            Write-Host "[*] Port $Port held by non-Velluma process (pid $($proc.Id), $($proc.Name)) - not killing" -ForegroundColor Gray
            return
        }
        Write-Host "[*] Stopping listener on port $Port (PID: $($proc.Id))..." -ForegroundColor Gray
        try { Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue; Start-Sleep -Seconds 2 } catch {}
    }
}

function Find-Python() {
    foreach ($path in $VenvPaths) {
        $fullPath = Join-Path $ProjectRoot $path
        if (Test-Path $fullPath) { return $fullPath }
    }
    throw "Python venv not found. Please ensure .venv or venv exists."
}

# ---- 端口协商（环境变量 → 已记录且空闲 → 扫描）----
$envPort = 0
if ($env:VELLUMA_PORT) { [int]::TryParse([string]$env:VELLUMA_PORT, [ref]$envPort) | Out-Null }
$backendPort = 0
if ($envPort -gt 0) {
    $backendPort = $envPort
} else {
    $recorded = Read-PortFile $PortFile
    if ($recorded -gt 0 -and -not (Test-PortOpen -Port $recorded)) {
        $backendPort = $recorded
    } else {
        $backendPort = Find-FreePort -Start $DefaultBackendPort -End $BackendPortMax
    }
}

if (-not $DryRun) { Write-PortFile $PortFile $backendPort }

Write-Host ""
Write-Host "  Velluma · DEV 后端（热重载）  http://127.0.0.1:$backendPort" -ForegroundColor Cyan
Write-Host ""

if (Test-PortOpen -Port $backendPort) {
    if ($Force) {
        if (-not $DryRun) { Kill-ProcessOnPort -Port $backendPort }
    } else {
        Write-Host "[OK] 后端已在运行 http://127.0.0.1:$backendPort（-Force 可强制重开）" -ForegroundColor Green
        return
    }
}

$pythonPath = Find-Python

# uvicorn --reload：reloader 父进程 + worker 子进程
#   --reload 必须传 import path（backend.main:app），不能走 main.py 的 __main__
#   --reload-dir backend：仅监听 backend/ 下的 .py 变更，避免误重启
#   --app-dir：让 backend.main 可作为顶层模块 import
$backendDir = Join-Path $ProjectRoot "backend"
$argList = @(
    "-m", "uvicorn", "backend.main:app",
    "--host", "127.0.0.1",
    "--port", $backendPort.ToString(),
    "--reload",
    "--reload-dir", $backendDir,
    "--app-dir", $ProjectRoot
)

if ($DryRun) {
    Write-Host "[DryRun] Would run: $pythonPath $($argList -join ' ')" -ForegroundColor Gray
    return
}

# 前台直跑：输出实时进本窗口；Ctrl+C 由 uvicorn reloader 正常收敛（无需脚本侧树杀）
$env:VELLUMA_PORT       = $backendPort.ToString()
$env:PYTHONUNBUFFERED   = "1"
$env:PYTHONIOENCODING   = "utf-8"
Push-Location $ProjectRoot
try {
    & $pythonPath @argList
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
