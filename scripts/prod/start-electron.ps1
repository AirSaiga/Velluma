#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 正式生产环境 · 单独启动 Electron（NODE_ENV=production，loadFile 载入 dist）。
.DESCRIPTION
    scripts/prod/ 四件套之一，与本目录 start-all.ps1 互不依赖、逻辑各自独立。
    前台运行：关掉 Electron 窗口即退出（只退 Electron，后端是独立进程不受影响）。

    前置检查：
      - dist/index.html 必须在（先跑本目录 start-frontend.bat 构建或 start-all.bat）；
      - 后端不强求：未检测到时 main.cjs 会尝试自行拉起（venv python -m backend.main）。

    electron:nobuild（= 直接 "electron ."）：dist 已构建时 electron:dev/preview 系
    脚本再 build 一次纯属浪费；NODE_ENV=production 让 main.cjs 走 loadFile 分支、
    不开 DevTools。
#>
param(
    [switch]$DryRun    # 仅打印将执行的命令
)

$ErrorActionPreference = "Stop"

# 脚本位于 scripts/prod/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$PortFile        = Join-Path $ProjectRoot "data\port.txt"
$FrontendDir     = Join-Path $ProjectRoot "frontend"
$DistIndex       = Join-Path $FrontendDir "dist\index.html"

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

if (-not (Test-Path $DistIndex)) {
    throw "frontend\dist\index.html 不存在——先跑 scripts\prod\start-frontend.bat 构建（或 start-all.bat）"
}

$backendPort = Read-PortFile $PortFile
$backendNote = "已连接"
if (-not $backendPort -or -not (Test-PortOpen -Port $backendPort)) {
    $backendNote = "未检测到后端——Electron 将尝试自行拉起"
    Write-Host "[*] $backendNote" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "  Velluma · PROD Electron  →  dist\index.html  （后端 $backendNote）" -ForegroundColor Yellow
Write-Host ""

if ($DryRun) {
    Write-Host "[DryRun] Would run: npm run electron:nobuild (cwd: $FrontendDir, NODE_ENV=production)" -ForegroundColor Gray
    return
}

# 按进程精确注入环境变量；NODE_ENV=production → main.cjs 走 loadFile('../dist/index.html')
if ($backendPort -gt 0) {
    $env:VELLUMA_BACKEND_PORT = $backendPort.ToString()
} else {
    Remove-Item Env:\VELLUMA_BACKEND_PORT -ErrorAction SilentlyContinue
}
$env:VELLUMA_SERVICES_READY = "1"
$env:NODE_ENV = "production"

Push-Location $FrontendDir
try {
    & cmd.exe /c npm run electron:nobuild
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
