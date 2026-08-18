#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 启动脚本（生产/开发/调试三模式）。
.DESCRIPTION
    Windows 启动编排（与 macos/start.sh 对称）。本脚本位于 scripts/windows/ 子目录，
    项目根 = $PSScriptRoot 的祖父目录。通过 -Mode 参数区分三种运行方式：
      - prod   : 生产体验模式。npm run build 预构建 dist，Electron 载入本地 dist 文件（NODE_ENV=production），
                 不启动 Vite dev server，不开 DevTools。后端仍用本地 .venv 启动。
      - dev    : 开发模式（默认）。后端 + Vite dev server + Electron（载入 http://localhost:vitePort，自动开 DevTools）。
      - debug  : 调试模式。当前实现等同 dev（main.cjs 在 dev 分支已自动 openDevTools），保留为语义入口，
                 便于未来挂接 debugpy / sourcemap 等增强。
.NOTES
    入口：scripts/windows/start-dev.bat / start-debug.bat / start-prod.bat（薄包装透传参数）。
#>
param(
    [ValidateSet('prod', 'dev', 'debug')]
    [string]$Mode = 'dev',
    [switch]$Force,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$ElectronOnly,
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# =============================================================================
# Config
# =============================================================================
# 脚本位于 scripts/windows/ 下，项目根是 $PSScriptRoot 的祖父目录
$ProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent

$Config = @{
    Mode                 = $Mode.ToLower()
    DefaultBackendPort   = 8002
    DefaultFrontendPort  = 5175   # 起始扫描端口（向后兼容）
    FrontendPortRange    = 100    # 从 5175 起最多扫描 100 个端口（5175~5275）
    FrontendPort         = $null  # 实际端口（运行时由 Resolve-FrontendPort 填充）
    ProjectRoot          = $ProjectRoot
    BackendTimeout       = 60
    FrontendTimeout      = 30
    BuildTimeout         = 600    # npm run build 超时（秒），生产模式专用
    HealthCheckInterval  = 500
    PythonModule         = "backend.main"
    VenvPaths            = @(
        ".venv\Scripts\python.exe"
        "venv\Scripts\python.exe"
    )
    PortFile             = Join-Path $ProjectRoot "data\port.txt"
    FrontendPortFile     = Join-Path $ProjectRoot "data\frontend_port.txt"
}

$Global:ChildProcesses = @()
$Global:CleanupDone = $false

# =============================================================================
# Port File Helpers
# =============================================================================
function Get-ActualBackendPort {
    # 优先从端口文件读取实际端口
    if (Test-Path $Config.PortFile) {
        try {
            $portStr = Get-Content $Config.PortFile -Raw
            $port = [int]$portStr.Trim()
            if ($port -gt 0) {
                return $port
            }
        } catch {}
    }
    # 回退到默认端口
    return $Config.DefaultBackendPort
}

function Get-ActualFrontendPort {
    # 优先从端口文件读取实际端口（与后端对称）
    if (Test-Path $Config.FrontendPortFile) {
        try {
            $portStr = Get-Content $Config.FrontendPortFile -Raw
            $port = [int]$portStr.Trim()
            if ($port -gt 0) {
                return $port
            }
        } catch {}
    }
    return $null
}

function Find-FreeFrontendPort {
    # 扫描 5175~(5175+Range) 找第一个空闲端口
    # 用于避免与其它项目（如 world-atlas）的 Vite 冲突
    $start = $Config.DefaultFrontendPort
    $maxOffset = $Config.FrontendPortRange
    for ($offset = 0; $offset -lt $maxOffset; $offset++) {
        $candidate = $start + $offset
        if (-not (Test-PortOpen -Port $candidate)) {
            return $candidate
        }
    }
    throw "No free frontend port in range $start..$($start + $maxOffset - 1)"
}

function Find-FreeBackendPort {
    # 扫描后端端口范围（与 backend/core/config.py 的 DEFAULT_PORT..MAX_PORT 对齐）
    # 用于 debug 热重载模式下抢占一个稳定端口，避免依赖 main.py 内部扫描
    $start = $Config.DefaultBackendPort
    $maxPort = 8100
    for ($port = $start; $port -le $maxPort; $port++) {
        if (-not (Test-PortOpen -Port $port)) {
            return $port
        }
    }
    throw "No free backend port in range $start..$maxPort"
}

function Resolve-BackendPort {
    # debug 热重载模式下协商后端端口，优先级：
    # 1. 环境变量 VELLUMA_PORT（用户强制指定，透传给后端）
    # 2. 已记录端口（data/port.txt）且该端口空闲 → 复用
    # 3. 扫描空闲端口（8002 起）
    # 选中后写入 data/port.txt，并设置 VELLUMA_PORT，使 main.py 跳过自动扫描
    # 固定端口是热重载的前提：reload 重启 worker 时端口不能漂移，否则前端断连
    $envPort = $env:VELLUMA_PORT
    if ($envPort) {
        $port = [int]$envPort
        if ($port -gt 0) {
            Set-BackendPortFile $port
            Log-Info "Backend port from env: $port"
            return $port
        }
    }

    $recorded = Get-ActualBackendPort
    if ($recorded -and $recorded -gt 0 -and -not (Test-PortOpen -Port $recorded)) {
        Set-BackendPortFile $recorded
        return $recorded
    }

    $freePort = Find-FreeBackendPort
    Set-BackendPortFile $freePort
    if ($freePort -ne $Config.DefaultBackendPort) {
        Log-Info "Default backend port $($Config.DefaultBackendPort) busy, using $freePort"
    }
    return $freePort
}

function Set-BackendPortFile($Port) {
    # 写入 data/port.txt，供前端 vite.config.js 代理与 electron/main.cjs 读取后端地址
    try {
        $portDir = Split-Path $Config.PortFile -Parent
        if (-not (Test-Path $portDir)) {
            New-Item -ItemType Directory -Path $portDir -Force | Out-Null
        }
        [System.IO.File]::WriteAllText($Config.PortFile, $Port.ToString())
    } catch {
        Log-Error "Failed to write backend port file: $_"
    }
}

function Resolve-FrontendPort {
    # 协商前端端口，优先级：
    # 1. 环境变量 VELLUMA_FRONTEND_PORT（用户强制指定）
    # 2. 已记录的端口（frontend_port.txt）且该端口空闲 → 复用
    # 3. 扫描空闲端口（5175 起）
    # 选中后写入 frontend_port.txt，供 vite.config.js 和 electron/main.cjs 读取
    $envPort = $env:VELLUMA_FRONTEND_PORT
    if ($envPort) {
        $port = [int]$envPort
        if ($port -gt 0) {
            Set-FrontendPortFile $port
            Log-Info "Frontend port from env: $port"
            return $port
        }
    }

    # 检查已记录端口是否仍空闲（可能是上次的残留记录）
    $recorded = Get-ActualFrontendPort
    if ($recorded -and -not (Test-PortOpen -Port $recorded)) {
        Set-FrontendPortFile $recorded
        return $recorded
    }

    # 扫描空闲端口
    $freePort = Find-FreeFrontendPort
    Set-FrontendPortFile $freePort
    if ($freePort -ne $Config.DefaultFrontendPort) {
        Log-Info "Default port $($Config.DefaultFrontendPort) busy, using $freePort"
    }
    return $freePort
}

function Set-FrontendPortFile($Port) {
    # 写入前端端口文件（供 vite.config.js / electron/main.cjs 协调）
    try {
        $portDir = Split-Path $Config.FrontendPortFile -Parent
        if (-not (Test-Path $portDir)) {
            New-Item -ItemType Directory -Path $portDir -Force | Out-Null
        }
        [System.IO.File]::WriteAllText($Config.FrontendPortFile, $Port.ToString())
    } catch {
        Log-Error "Failed to write frontend port file: $_"
    }
}

# =============================================================================
# Utility Functions
# =============================================================================
function Log-Step($Message) {
    Write-Host "`n[>] $Message" -ForegroundColor Cyan
}

function Log-Success($Message) {
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Log-Error($Message) {
    Write-Host "[ERR] $Message" -ForegroundColor Red
}

function Log-Info($Message) {
    Write-Host "[*] $Message" -ForegroundColor Gray
}

function Log-Wait($Message) {
    Write-Host "[...] $Message" -ForegroundColor Yellow -NoNewline
}

# =============================================================================
# Port and Process Management
# =============================================================================
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

function Kill-ProcessOnPort($Port, $Name) {
    $proc = Get-ProcessOnPort -Port $Port
    if ($proc) {
        Log-Info "Stopping $Name on port $Port (PID: $($proc.Id))..."
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Log-Success "$Name stopped"
            return $true
        } catch {
            Log-Error "Failed to stop process: $_"
            return $false
        }
    }
    return $false
}

function Stop-ProcessTree($ParentProcessId, $Name = "process") {
    # 递归终止进程树：先杀子进程再杀父进程
    # 用途：uvicorn --reload 的 reloader 父进程会 spawn 一个 worker 子进程，
    #       仅杀父进程会留下 worker 孤儿进程继续占用端口，导致下次启动端口冲突
    # 依赖：CIM_Process.ProcessId/ParentProcessId（Win32 内置，无需外部命令）
    if (-not $ParentProcessId) { return }
    try {
        $children = Get-CimInstance -ClassName Win32_Process -Filter "ParentProcessId=$ParentProcessId" -ErrorAction SilentlyContinue
        foreach ($child in $children) {
            Stop-ProcessTree -ParentProcessId $child.ProcessId -Name $Name
        }
        Stop-Process -Id $ParentProcessId -Force -ErrorAction SilentlyContinue
    } catch {
        # 父进程可能已自行退出，忽略
    }
}

function Wait-ForService($Port, $Name, $TimeoutSeconds = 30) {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $dots = 0

    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-PortOpen -Port $Port) {
            Write-Host " Ready!" -ForegroundColor Green
            return $true
        }

        Start-Sleep -Milliseconds $Config.HealthCheckInterval
        Write-Host "." -ForegroundColor DarkGray -NoNewline
        $dots++

        if ($dots % 10 -eq 0) {
            $elapsed = [math]::Round($sw.Elapsed.TotalSeconds)
            Write-Host " (${elapsed}s)" -ForegroundColor DarkGray -NoNewline
        }
    }

    Write-Host ""
    throw "$Name timeout on port $Port (${TimeoutSeconds}s)"
}

# =============================================================================
# Cleanup
# =============================================================================
function Invoke-Cleanup() {
    if ($Global:CleanupDone) { return }
    $Global:CleanupDone = $true

    Write-Host ""
    Log-Step "Cleaning up..."

    foreach ($proc in $Global:ChildProcesses) {
        if ($proc -and !$proc.HasExited) {
            try {
                # 用进程树清理：debug 模式下后端是 uvicorn --reload，
                # reloader 父进程会 spawn worker 子进程，必须先杀子再杀父，否则留下孤儿占用端口
                Stop-ProcessTree -ParentProcessId $proc.Id
                Log-Info "Stopped PID $($proc.Id)"
            } catch {}
        }
    }

    $backendPort = Get-ActualBackendPort
    # 前端端口：优先用已协商的 $Config.FrontendPort，否则读端口文件
    # 生产模式下没有 Vite 进程，不清理前端端口（避免误杀他人占用的端口）
    $ports = @($backendPort)
    if ($Config.Mode -ne 'prod') {
        $frontendPort = if ($Config.FrontendPort) { $Config.FrontendPort } else { Get-ActualFrontendPort }
        if ($frontendPort -and $frontendPort -gt 0) {
            $ports += $frontendPort
        }
    }
    foreach ($port in $ports) {
        Kill-ProcessOnPort -Port $port -Name "service" | Out-Null
    }

    Log-Success "Cleanup done"
}

# =============================================================================
# Service Startup
# =============================================================================
function Find-Python() {
    foreach ($path in $Config.VenvPaths) {
        $fullPath = Join-Path $Config.ProjectRoot $path
        if (Test-Path $fullPath) {
            return $fullPath
        }
    }
    throw "Python venv not found. Please ensure .venv or venv exists."
}

function Start-Backend() {
    $backendPort = Get-ActualBackendPort
    if ($SkipBackend -or $ElectronOnly) {
        if (Test-PortOpen -Port $backendPort) {
            Log-Success "Backend already running on port $backendPort"
            return
        }
        throw "Backend not running but skip flag set"
    }

    # debug 模式启用 uvicorn --reload 后端热重载：保存 Python 文件即自动重启
    # 热重载的关键约束：
    #   1. --reload 必须传 import path（backend.main:app），不能传 app 对象（main.py 的 __main__ 不走）
    #   2. reload 重启 worker 时端口必须固定，否则前端断连 → 由脚本侧协商端口并设 VELLUMA_PORT
    #   3. main.py 的 __main__ 不会执行 → save_port 不会被调用 → port.txt 必须由脚本侧写好
    $useReload = ($Config.Mode -eq 'debug')

    if ($useReload) {
        # 先抢占固定端口并写 data/port.txt + 设环境变量，让 main.py 跳过内部扫描
        $backendPort = Resolve-BackendPort
        $env:VELLUMA_PORT = $backendPort.ToString()
        Log-Info "Debug mode: backend hot-reload enabled (VELLUMA_PORT=$backendPort)"
    }

    Log-Step "Starting Backend..."

    if (Test-PortOpen -Port $backendPort) {
        if ($Force) {
            Kill-ProcessOnPort -Port $backendPort -Name "backend" | Out-Null
        } else {
            if ($useReload) {
                Log-Success "Backend already running on port $backendPort (reload disabled for existing process)"
            } else {
                Log-Success "Backend already running on port $backendPort"
            }
            return
        }
    }

    $pythonPath = Find-Python
    Log-Info "Using Python: $pythonPath"

    $env:PYTHONUNBUFFERED = "1"

    if ($DryRun) {
        if ($useReload) {
            Log-Info "[DryRun] Would start (reload): $pythonPath -m uvicorn backend.main:app --host 127.0.0.1 --port $backendPort --reload --reload-dir backend --app-dir ."
        } else {
            Log-Info "[DryRun] Would start: $pythonPath -m $($Config.PythonModule)"
        }
        return
    }

    if ($useReload) {
        # uvicorn --reload：reloader 父进程 + worker 子进程
        # --app-dir .：让 backend.main 可作为顶层模块 import（cwd 已是项目根）
        # --reload-dir backend：仅监听 backend/ 下的 .py 变更，避免 frontend/data/logs 触发误重启
        # 不用 -NoNewWindow：reload 输出量大，独占窗口便于观察重启日志，Ctrl+C 也能直达 reloader
        $backendDir = Join-Path $Config.ProjectRoot "backend"
        $argList = @(
            "-m", "uvicorn", "backend.main:app",
            "--host", "127.0.0.1",
            "--port", $backendPort.ToString(),
            "--reload",
            "--reload-dir", $backendDir,
            "--app-dir", $Config.ProjectRoot
        )
        $proc = Start-Process -FilePath $pythonPath `
            -ArgumentList $argList `
            -WorkingDirectory $Config.ProjectRoot `
            -PassThru

        $Global:ChildProcesses += $proc

        Log-Wait "Waiting for backend (reload)..."
        $waitStart = Get-Date
        $ready = $false
        while (((Get-Date) - $waitStart).TotalSeconds -lt $Config.BackendTimeout) {
            Start-Sleep -Milliseconds $Config.HealthCheckInterval
            if (Test-PortOpen -Port $backendPort) {
                $ready = $true
                break
            }
        }
        if (-not $ready) {
            throw "Backend (reload) failed to start within $($Config.BackendTimeout)s"
        }
        Log-Success "Backend ready at http://127.0.0.1:$backendPort (hot-reload ON)"
        return
    }

    # dev/prod 模式：走 main.py 的 __main__（内部 find_available_port + save_port）
    # -NoNewWindow：后端继承当前控制台，uvicorn 访问日志 / print / traceback 实时输出到运行
    # start.bat 的窗口，方便边用 Electron 边盯后端。PYTHONUNBUFFERED=1 已在上方设置，日志无缓冲延迟。
    $proc = Start-Process -FilePath $pythonPath `
        -ArgumentList "-m", $Config.PythonModule `
        -WorkingDirectory $Config.ProjectRoot `
        -NoNewWindow `
        -PassThru

    $Global:ChildProcesses += $proc

    # 轮询端口文件等待后端启动
    Log-Wait "Waiting for backend..."
    $waitStart = Get-Date
    $actualPort = $null
    while (((Get-Date) - $waitStart).TotalSeconds -lt $Config.BackendTimeout) {
        Start-Sleep -Milliseconds $Config.HealthCheckInterval
        $actualPort = Get-ActualBackendPort
        if ($actualPort -and (Test-PortOpen -Port $actualPort)) {
            break
        }
        $actualPort = $null
    }

    if (-not $actualPort) {
        throw "Backend failed to start within $($Config.BackendTimeout)s"
    }

    Log-Success "Backend ready at http://127.0.0.1:$actualPort"
}

function Start-FrontendBuild() {
    # 生产模式专用：npm run build 生成 dist/ 供 Electron loadFile 载入
    # 不启动 Vite dev server
    if ($SkipFrontend) {
        Log-Info "SkipFrontend set, assuming dist/ already built"
        return
    }

    Log-Step "Building frontend (npm run build)..."

    $frontendDir = Join-Path $Config.ProjectRoot "frontend"

    if (!(Test-Path (Join-Path $frontendDir "node_modules"))) {
        throw "node_modules not found. Please run: cd frontend && npm install"
    }

    if ($DryRun) {
        Log-Info "[DryRun] Would run: npm run build (cwd: $frontendDir)"
        return
    }

    # 同步执行 npm run build，捕获退出码
    $buildInfo = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm", "run", "build" `
        -WorkingDirectory $frontendDir `
        -Wait -PassThru -NoNewWindow

    if ($buildInfo.ExitCode -ne 0) {
        throw "npm run build failed with exit code $($buildInfo.ExitCode)"
    }

    $distIndex = Join-Path $frontendDir "dist\index.html"
    if (!(Test-Path $distIndex)) {
        throw "Build completed but dist/index.html not found at $distIndex"
    }

    Log-Success "Frontend built to dist/"
}

function Start-Frontend() {
    # 开发/调试模式：启动 Vite dev server（端口动态协商）
    # 协商前端端口（动态扫描空闲端口，避免与其它项目冲突）
    $frontendPort = Resolve-FrontendPort
    $Config.FrontendPort = $frontendPort

    if ($SkipFrontend -or $ElectronOnly) {
        if (Test-PortOpen -Port $frontendPort) {
            Log-Success "Frontend already running on port $frontendPort"
            return
        }
        throw "Frontend not running but skip flag set"
    }

    Log-Step "Starting Frontend (port $frontendPort)..."

    $frontendDir = Join-Path $Config.ProjectRoot "frontend"

    if (!(Test-Path (Join-Path $frontendDir "node_modules"))) {
        throw "node_modules not found. Please run: cd frontend && npm install"
    }

    if (Test-PortOpen -Port $frontendPort) {
        if ($Force) {
            Kill-ProcessOnPort -Port $frontendPort -Name "frontend" | Out-Null
        } else {
            Log-Success "Frontend already running on port $frontendPort"
            return
        }
    }

    Log-Info "Starting Vite dev server..."

    # 设置环境变量供 vite.config.js 读取（双保险：env + frontend_port.txt）
    $env:VELLUMA_FRONTEND_PORT = $frontendPort.ToString()

    if ($DryRun) {
        Log-Info "[DryRun] Would start: npm run dev (cwd: $frontendDir, port $frontendPort)"
        return
    }

    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm", "run", "dev" `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -PassThru

    $Global:ChildProcesses += $proc

    Log-Wait "Waiting for frontend (port $frontendPort)..."
    Wait-ForService -Port $frontendPort -Name "Frontend" -TimeoutSeconds $Config.FrontendTimeout
    Log-Success "Frontend ready at http://127.0.0.1:$frontendPort"
}

function Start-Electron() {
    Log-Step "Starting Electron..."

    $frontendDir = Join-Path $Config.ProjectRoot "frontend"
    $backendPort = Get-ActualBackendPort

    # 公共环境变量
    $env:VELLUMA_BACKEND_PORT = $backendPort.ToString()
    # 生产模式不启动 Vite，FrontendPort 可能为 null——读端口文件兜底，再不行留空
    $fePort = if ($Config.FrontendPort) { $Config.FrontendPort } elseif ($Config.Mode -eq 'prod') { Get-ActualFrontendPort } else { $null }
    if ($fePort) {
        $env:VELLUMA_FRONTEND_PORT = $fePort.ToString()
    } else {
        Remove-Item Env:\VELLUMA_FRONTEND_PORT -ErrorAction SilentlyContinue
    }
    $env:VELLUMA_SERVICES_READY = "1"

    # 模式差异：生产模式设 NODE_ENV=production，让 main.cjs 走 loadFile('../dist/index.html') 分支
    # 开发/调试模式保持 NODE_ENV 不设（main.cjs 的 isDev = true，走 loadURL + openDevTools）
    if ($Config.Mode -eq 'prod') {
        $env:NODE_ENV = "production"
        Log-Info "NODE_ENV=production (Electron will load dist/index.html)"
    } else {
        # 显式清掉，避免外部环境残留 NODE_ENV=production 导致 main.cjs 误判
        Remove-Item Env:\NODE_ENV -ErrorAction SilentlyContinue
        Log-Info "NODE_ENV unset (Electron will load Vite dev server, DevTools auto-open)"
    }

    if ($DryRun) {
        Log-Info "[DryRun] Would run: npm run electron:dev (cwd: $frontendDir)"
        return
    }

    # 注意：electron:dev = "npm run build && electron ."
    #   - 生产模式：build 已由 Start-FrontendBuild 完成，这里再 build 一次是幂等的（vite build 增量）
    #     之所以不直接 "electron ."，是为了复用现有 npm script，避免引入新 script 增加维护面
    #   - 开发/调试模式：build 产物不会被 main.cjs 使用（走 loadURL），仅浪费数秒，可接受
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm", "run", "electron:dev" `
        -WorkingDirectory $frontendDir `
        -PassThru

    $Global:ChildProcesses += $proc

    Log-Success "Electron started (PID: $($proc.Id))"

    return $proc
}

# =============================================================================
# Main
# =============================================================================
function Show-Banner() {
    Write-Host "`n============================================================" -ForegroundColor Cyan
    Write-Host "     Velluma AI Novel Writing Assistant" -ForegroundColor Cyan
    Write-Host "     Mode: $($Config.Mode.ToUpper())" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Main() {
    Show-Banner

    Log-Info "Project root: $($Config.ProjectRoot)"
    if ($DryRun) {
        Log-Info "DryRun mode: no processes will be started"
    }
    if ($Force) {
        Log-Info "Force mode: will clean port conflicts"
    }

    try {
        Start-Backend

        # 按模式分流前端阶段
        if ($Config.Mode -eq 'prod') {
            Start-FrontendBuild
        } else {
            Start-Frontend
        }

        $electronProc = Start-Electron

        Write-Host "`n============================================================" -ForegroundColor Green
        Log-Success "All services started!"
        Write-Host ""
        $backendPort = Get-ActualBackendPort
        Write-Host "  Backend:  http://127.0.0.1:$backendPort" -ForegroundColor Gray
        Write-Host "  API Docs: http://127.0.0.1:$backendPort/docs" -ForegroundColor Gray
        if ($Config.Mode -eq 'prod') {
            Write-Host "  Frontend: dist/index.html (built)" -ForegroundColor Gray
        } else {
            Write-Host "  Frontend: http://127.0.0.1:$($Config.FrontendPort) (Vite dev)" -ForegroundColor Gray
        }
        Write-Host ""
        Write-Host "  Electron is running. Close window to stop all services." -ForegroundColor Yellow
        Write-Host "============================================================" -ForegroundColor Green

        if ($DryRun) {
            Log-Info "DryRun complete, skipping wait"
            return
        }

        # Wait for Electron to exit
        $null = $electronProc.WaitForExit()

        Write-Host ""
        Log-Info "Electron exited"

    } catch {
        Write-Host ""
        Log-Error "Startup failed: $_"
        exit 1
    } finally {
        Invoke-Cleanup
    }
}

# Run
Main
