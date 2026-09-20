#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 开发调试环境 · 单独启动 Electron（loadURL 连 Vite，自动开 DevTools）。
.DESCRIPTION
    scripts/dev/ 四件套之一，与本目录 start-all.ps1 互不依赖、逻辑各自独立。
    前台运行：关掉 Electron 窗口即退出（只退 Electron，后端/前端是独立进程不受影响）。

    前置检查：
      - 前端（Vite）必须在跑——dev 模式 main.cjs 走 loadURL，没有 Vite 就是白屏；
        端口取 data/frontend_port.txt（本目录 start-frontend.bat / start-all.bat 写入）。
      - 后端不强求：未检测到时 main.cjs 会尝试自行拉起（venv python -m backend.main）。

    electron:nobuild（= 直接 "electron ."）：vite build 产物在 dev 模式根本不会被加载，
    白等 30~60 秒；loadURL/loadFile 由 NODE_ENV 决定——此处显式清掉 NODE_ENV，
    外部环境残留会让 main.cjs 误判走 loadFile 分支。
#>
param(
    [switch]$DryRun    # 仅打印将执行的命令
)

$ErrorActionPreference = "Stop"

# 脚本位于 scripts/dev/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$PortFile           = Join-Path $ProjectRoot "data\port.txt"
$FrontendPortFile   = Join-Path $ProjectRoot "data\frontend_port.txt"
$FrontendDir        = Join-Path $ProjectRoot "frontend"

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

if (-not (Test-Path (Join-Path $FrontendDir "node_modules"))) {
    throw "node_modules not found. Please run: cd frontend && npm install"
}

$frontendPort = Read-PortFile $FrontendPortFile
if (-not $frontendPort -or -not (Test-PortOpen -Port $frontendPort)) {
    throw "前端（Vite）未在运行——先跑 scripts\dev\start-frontend.bat 或 start-all.bat（dev 模式 Electron 必须连 Vite，否则白屏）"
}

$backendPort = Read-PortFile $PortFile
$backendNote = "已连接"
if (-not $backendPort -or -not (Test-PortOpen -Port $backendPort)) {
    $backendNote = "未检测到后端——Electron 将尝试自行拉起"
    Write-Host "[*] $backendNote" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  Velluma · DEV Electron  →  http://127.0.0.1:$frontendPort  （后端 $backendNote）" -ForegroundColor Yellow
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] Would run: npm run electron:nobuild (cwd: $FrontendDir)" -ForegroundColor Gray
    return
}

# 按进程精确注入环境变量（不污染脚本会话外的东西）；NODE_ENV 显式清空走 loadURL 分支
$env:VELLUMA_FRONTEND_PORT = $frontendPort.ToString()
if ($backendPort -gt 0) {
    $env:VELLUMA_BACKEND_PORT = $backendPort.ToString()
} else {
    Remove-Item Env:\VELLUMA_BACKEND_PORT -ErrorAction SilentlyContinue
}
$env:VELLUMA_SERVICES_READY = "1"
Remove-Item Env:\NODE_ENV -ErrorAction SilentlyContinue

Push-Location $FrontendDir
try {
    & cmd.exe /c npm run electron:nobuild
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
