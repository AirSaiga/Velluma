#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma 完整启动脚本 - 依次启动后端、前端、Electron
.DESCRIPTION
    1. 启动后端 (port 8002)
    2. 等待后端就绪
    3. 启动前端 Vite (port 5175)
    4. 等待前端就绪
    5. 启动 Electron
    
    特性：
    - 健康检查与超时等待
    - 端口冲突自动清理
    - 优雅的错误处理和日志
    - Ctrl+C 优雅关闭所有服务
#>

[CmdletBinding()]
param(
    [switch]$Force,           # 强制清理端口占用
    [switch]$SkipBackend,     # 跳过后端启动
    [switch]$SkipFrontend,    # 跳过前端启动
    [switch]$ElectronOnly     # 只启动 Electron（假设前后端已在运行）
)

$ErrorActionPreference = "Stop"

# =============================================================================
# 配置
# =============================================================================
$Config = @{
    BackendPort   = 8002
    FrontendPort  = 5175
    ProjectRoot   = Split-Path -Parent $PSScriptRoot
    BackendTimeout = 60        # 后端启动超时（秒）
    FrontendTimeout = 30       # 前端启动超时（秒）
    HealthCheckInterval = 500  # 健康检查间隔（毫秒）
    PythonModule  = "backend.main"
    VenvPaths     = @(
        ".venv\Scripts\python.exe"
        "venv\Scripts\python.exe"
    )
}

# 全局进程列表（用于清理）
$Global:ChildProcesses = @()
$Global:CleanupDone = $false

# =============================================================================
# 日志函数
# =============================================================================
function Write-Step {
    param([string]$Message)
    Write-Host "`n[>] $Message" -ForegroundColor Cyan
}

function Write-Success {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Err {
    param([string]$Message)
    Write-Host "[ERR] $Message" -ForegroundColor Red
}

function Write-Info {
    param([string]$Message)
    Write-Host "[*] $Message" -ForegroundColor Gray
}

function Write-Wait {
    param([string]$Message)
    Write-Host "[...] $Message" -ForegroundColor Yellow -NoNewline
}

# =============================================================================
# 端口和进程管理
# =============================================================================
function Test-PortOpen {
    param([int]$Port)
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

function Get-ProcessUsingPort {
    param([int]$Port)
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

function Stop-ProcessOnPort {
    param([int]$Port, [string]$Name)
    $proc = Get-ProcessUsingPort -Port $Port
    if ($proc) {
        Write-Info "正在停止占用端口 $Port 的 $Name (PID: $($proc.Id))..."
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Write-Success "$Name 已停止"
            return $true
        } catch {
            Write-Err "无法停止进程: $_"
            return $false
        }
    }
    return $false
}

function Wait-ForService {
    param(
        [int]$Port,
        [string]$Name,
        [int]$TimeoutSeconds = 30
    )
    
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $dots = 0
    
    while ($sw.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        if (Test-PortOpen -Port $Port) {
            Write-Host " 就绪!" -ForegroundColor Green
            return $true
        }
        
        Start-Sleep -Milliseconds $Config.HealthCheckInterval
        Write-Host "." -ForegroundColor DarkGray -NoNewline
        $dots++
        
        if ($dots % 10 -eq 0) {
            Write-Host " ($([math]::Round($sw.Elapsed.TotalSeconds))s)" -ForegroundColor DarkGray -NoNewline
        }
    }
    
    Write-Host ""  # New line
    throw "$Name 在端口 $Port 启动超时 (${TimeoutSeconds}秒)"
}

# =============================================================================
# 清理函数
# =============================================================================
function Invoke-Cleanup {
    if ($Global:CleanupDone) { return }
    $Global:CleanupDone = $true
    
    Write-Host ""
    Write-Step "正在清理进程..."
    
    # 停止记录的子进程
    foreach ($proc in $Global:ChildProcesses) {
        if ($proc -and !$proc.HasExited) {
            try {
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Write-Info "已停止 PID $($proc.Id)"
            } catch {
                # Ignore errors during cleanup
            }
        }
    }
    
    # 清理可能残留的 Python 和 Node 进程
    $ports = @($Config.BackendPort, $Config.FrontendPort)
    foreach ($port in $ports) {
        Stop-ProcessOnPort -Port $port -Name "服务" | Out-Null
    }
    
    Write-Success "清理完成"
}

# 注册 Ctrl+C 处理器
try {
    [Console]::TreatControlCAsInput = $false
} catch {}

# =============================================================================
# 服务启动函数
# =============================================================================
function Find-PythonPath {
    foreach ($path in $Config.VenvPaths) {
        $fullPath = Join-Path $Config.ProjectRoot $path
        if (Test-Path $fullPath) {
            return $fullPath
        }
    }
    throw "找不到 Python 虚拟环境。请确保 .venv 或 venv 存在。"
}

function Start-BackendService {
    if ($SkipBackend -or $ElectronOnly) {
        if (Test-PortOpen -Port $Config.BackendPort) {
            Write-Success "后端已在端口 $($Config.BackendPort) 运行"
            return
        }
        throw "后端未运行且指定了跳过参数"
    }
    
    Write-Step "启动后端服务..."
    
    # 检查是否已在运行
    if (Test-PortOpen -Port $Config.BackendPort) {
        if ($Force) {
            Stop-ProcessOnPort -Port $Config.BackendPort -Name "后端服务" | Out-Null
        } else {
            Write-Success "后端已在端口 $($Config.BackendPort) 运行"
            return
        }
    }
    
    $pythonPath = Find-PythonPath
    Write-Info "使用 Python: $pythonPath"
    
    # 设置环境变量
    $env:VELLUMA_PORT = $Config.BackendPort.ToString()
    $env:PYTHONUNBUFFERED = "1"
    
    # 启动后端进程
    $proc = Start-Process -FilePath $pythonPath `
        -ArgumentList "-m", $Config.PythonModule `
        -WorkingDirectory $Config.ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
    
    $Global:ChildProcesses += $proc
    
    Write-Wait "等待后端就绪 (端口 $($Config.BackendPort))..."
    Wait-ForService -Port $Config.BackendPort -Name "后端服务" -TimeoutSeconds $Config.BackendTimeout
    Write-Success "后端服务已就绪 http://127.0.0.1:$($Config.BackendPort)"
}

function Start-FrontendService {
    if ($SkipFrontend -or $ElectronOnly) {
        if (Test-PortOpen -Port $Config.FrontendPort) {
            Write-Success "前端已在端口 $($Config.FrontendPort) 运行"
            return
        }
        throw "前端未运行且指定了跳过参数"
    }
    
    Write-Step "启动前端服务..."
    
    $frontendDir = Join-Path $Config.ProjectRoot "frontend"
    
    # 检查 node_modules
    if (!(Test-Path (Join-Path $frontendDir "node_modules"))) {
        throw "找不到 node_modules。请先运行: cd frontend && npm install"
    }
    
    # 检查是否已在运行
    if (Test-PortOpen -Port $Config.FrontendPort) {
        if ($Force) {
            Stop-ProcessOnPort -Port $Config.FrontendPort -Name "前端服务" | Out-Null
        } else {
            Write-Success "前端已在端口 $($Config.FrontendPort) 运行"
            return
        }
    }
    
    Write-Info "启动 Vite 开发服务器..."
    
    # 启动前端进程（使用 cmd 来正确执行 npm）
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm", "run", "dev" `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -PassThru
    
    $Global:ChildProcesses += $proc
    
    Write-Wait "等待前端就绪 (端口 $($Config.FrontendPort))..."
    Wait-ForService -Port $Config.FrontendPort -Name "前端服务" -TimeoutSeconds $Config.FrontendTimeout
    Write-Success "前端服务已就绪 http://127.0.0.1:$($Config.FrontendPort)"
}

function Start-ElectronApp {
    Write-Step "启动 Electron..."
    
    $frontendDir = Join-Path $Config.ProjectRoot "frontend"
    
    # 设置环境变量让 Electron 知道服务已就绪
    $env:VELLUMA_BACKEND_PORT = $Config.BackendPort.ToString()
    $env:VELLUMA_FRONTEND_PORT = $Config.FrontendPort.ToString()
    $env:VELLUMA_SERVICES_READY = "1"
    
    # 启动 Electron - 使用 -Wait 参数让 PowerShell 等待进程退出
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm", "run", "electron:dev" `
        -WorkingDirectory $frontendDir `
        -PassThru
    
    $Global:ChildProcesses += $proc
    
    Write-Success "Electron 已启动 (PID: $($proc.Id))"
    
    return $proc
}

# =============================================================================
# 主程序
# =============================================================================
function Show-Banner {
    Write-Host "`n============================================================" -ForegroundColor Cyan
    Write-Host "     Velluma AI Novel Writing Assistant" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Main {
    Show-Banner
    
    # 检查参数
    if ($Force) {
        Write-Info "强制模式: 将清理端口占用"
    }
    
    # 设置清理钩子
    $null = Register-EngineEvent -SourceIdentifier PowerShell.Exiting -Action {
        Invoke-Cleanup
    }
    
    try {
        # 1. 启动后端
        Start-BackendService
        
        # 2. 启动前端
        Start-FrontendService
        
        # 3. 启动 Electron
        $electronProc = Start-ElectronApp
        
        # 显示状态
        Write-Host "`n============================================================" -ForegroundColor Green
        Write-Success "所有服务已启动!"
        Write-Host ""
        Write-Host "  后端 API:   http://127.0.0.1:$($Config.BackendPort)" -ForegroundColor Gray
        Write-Host "  前端 Dev:   http://127.0.0.1:$($Config.FrontendPort)" -ForegroundColor Gray
        Write-Host "  API 文档:   http://127.0.0.1:$($Config.BackendPort)/docs" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Electron 正在运行，关闭窗口将停止所有服务" -ForegroundColor Yellow
        Write-Host "============================================================" -ForegroundColor Green
        
        # 等待 Electron 退出（使用同步等待）
        $null = $electronProc.WaitForExit()
        
        Write-Host ""
        Write-Info "Electron 已退出"
        
    } catch {
        Write-Host ""
        Write-Err "启动失败: $_"
        exit 1
    } finally {
        Invoke-Cleanup
    }
}

# 运行主程序
Main
