#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 开发调试环境 · 单独启动前端（Vite dev server，前台运行）。
.DESCRIPTION
    scripts/dev/ 四件套之一，与本目录 start-all.ps1 互不依赖、逻辑各自独立。
    前台运行：Vite 输出直接打在本窗口，Ctrl+C 停止（收摊兜底 scripts\stop-velluma.bat）。

    端口契约（与 start-all / prod / macos / monitor 监督者一致，check_launcher_contract.py 对拍）：
      - 协商优先级：环境变量 VELLUMA_FRONTEND_PORT → data/frontend_port.txt 已记录且空闲
        → 扫描 5175~5285；
      - 选中即写 data/frontend_port.txt 并设同名环境变量（vite.config.js strictPort 读它，
        Electron 的 main.cjs 也读端口文件——两处双保险）。

    只起前端；要后端/Electron 另跑同目录 start-backend.bat / start-electron.bat。
#>
param(
    [switch]$Force,    # 端口被占时强制清理（只杀命令行含本项目路径的监听者）
    [switch]$DryRun    # 仅打印将执行的命令
)

$ErrorActionPreference = "Stop"

# 脚本位于 scripts/dev/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$DefaultFrontendPort = 5175
$FrontendPortMax     = 5285   # 与 stop-velluma.ps1 孤儿清扫段对齐
$FrontendPortFile    = Join-Path $ProjectRoot "data\frontend_port.txt"
$FrontendDir         = Join-Path $ProjectRoot "frontend"

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
    # 只杀「自己的」监听者：进程命令行须含本项目路径（vite 真正监听的 node 是
    # node_modules 绝对脚本路径，自带项目路径；他人进程占口 → 拒杀留活）
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

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    throw "node_modules not found. Please run: cd frontend && npm install"
}

# ---- 端口协商（环境变量 → 已记录且空闲 → 扫描）----
$envPort = 0
if ($env:VELLUMA_FRONTEND_PORT) { [int]::TryParse([string]$env:VELLUMA_FRONTEND_PORT, [ref]$envPort) | Out-Null }
if ($envPort -gt 0) {
    $frontendPort = $envPort
} else {
    $recorded = Read-PortFile $FrontendPortFile
    if ($recorded -gt 0 -and -not (Test-PortOpen -Port $recorded)) {
        $frontendPort = $recorded
    } else {
        $frontendPort = Find-FreePort -Start $DefaultFrontendPort -End $FrontendPortMax
    }
}

if (-not $DryRun) { Write-PortFile $FrontendPortFile $frontendPort }

Write-Host ""
Write-Host "  Velluma · DEV 前端（Vite）  http://127.0.0.1:$frontendPort" -ForegroundColor Green
Write-Host ""

if (Test-PortOpen -Port $frontendPort) {
    if ($Force) {
        if (-not $DryRun) { Kill-ProcessOnPort -Port $frontendPort }
    } else {
        Write-Host "[OK] 前端已在运行 http://127.0.0.1:$frontendPort（-Force 可强制重开）" -ForegroundColor Green
        return
    }
}

if ($DryRun) {
    Write-Host "[DryRun] Would run: npm run dev (cwd: $FrontendDir, port $frontendPort)" -ForegroundColor Gray
    return
}

# 前台直跑：输出实时进本窗口；stdin 挂在真终端上，vite 的交互快捷键（r 重启等）可用
$env:VELLUMA_FRONTEND_PORT = $frontendPort.ToString()
Push-Location $FrontendDir
try {
    & cmd.exe /c npm run dev
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
