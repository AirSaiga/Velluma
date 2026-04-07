#Requires -Version 5.1
param(
    [switch]$Force,
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$ElectronOnly
)

$ErrorActionPreference = "Stop"

# Config
$Config = @{
    BackendPort   = 8002
    FrontendPort  = 5175
    ProjectRoot   = $PSScriptRoot
    BackendTimeout = 60
    FrontendTimeout = 30
    HealthCheckInterval = 500
    PythonModule  = "backend.main"
    VenvPaths     = @(
        ".venv\Scripts\python.exe"
        "venv\Scripts\python.exe"
    )
}

$Global:ChildProcesses = @()
$Global:CleanupDone = $false

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
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                Log-Info "Stopped PID $($proc.Id)"
            } catch {}
        }
    }
    
    $ports = @($Config.BackendPort, $Config.FrontendPort)
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
    if ($SkipBackend -or $ElectronOnly) {
        if (Test-PortOpen -Port $Config.BackendPort) {
            Log-Success "Backend already running on port $($Config.BackendPort)"
            return
        }
        throw "Backend not running but skip flag set"
    }
    
    Log-Step "Starting Backend..."
    
    if (Test-PortOpen -Port $Config.BackendPort) {
        if ($Force) {
            Kill-ProcessOnPort -Port $Config.BackendPort -Name "backend" | Out-Null
        } else {
            Log-Success "Backend already running on port $($Config.BackendPort)"
            return
        }
    }
    
    $pythonPath = Find-Python
    Log-Info "Using Python: $pythonPath"
    
    $env:VELLUMA_PORT = $Config.BackendPort.ToString()
    $env:PYTHONUNBUFFERED = "1"
    
    $proc = Start-Process -FilePath $pythonPath `
        -ArgumentList "-m", $Config.PythonModule `
        -WorkingDirectory $Config.ProjectRoot `
        -WindowStyle Hidden `
        -PassThru
    
    $Global:ChildProcesses += $proc
    
    Log-Wait "Waiting for backend (port $($Config.BackendPort))..."
    Wait-ForService -Port $Config.BackendPort -Name "Backend" -TimeoutSeconds $Config.BackendTimeout
    Log-Success "Backend ready at http://127.0.0.1:$($Config.BackendPort)"
}

function Start-Frontend() {
    if ($SkipFrontend -or $ElectronOnly) {
        if (Test-PortOpen -Port $Config.FrontendPort) {
            Log-Success "Frontend already running on port $($Config.FrontendPort)"
            return
        }
        throw "Frontend not running but skip flag set"
    }
    
    Log-Step "Starting Frontend..."
    
    $frontendDir = Join-Path $Config.ProjectRoot "frontend"
    
    if (!(Test-Path (Join-Path $frontendDir "node_modules"))) {
        throw "node_modules not found. Please run: cd frontend && npm install"
    }
    
    if (Test-PortOpen -Port $Config.FrontendPort) {
        if ($Force) {
            Kill-ProcessOnPort -Port $Config.FrontendPort -Name "frontend" | Out-Null
        } else {
            Log-Success "Frontend already running on port $($Config.FrontendPort)"
            return
        }
    }
    
    Log-Info "Starting Vite dev server..."
    
    $proc = Start-Process -FilePath "cmd.exe" `
        -ArgumentList "/c", "npm", "run", "dev" `
        -WorkingDirectory $frontendDir `
        -WindowStyle Hidden `
        -PassThru
    
    $Global:ChildProcesses += $proc
    
    Log-Wait "Waiting for frontend (port $($Config.FrontendPort))..."
    Wait-ForService -Port $Config.FrontendPort -Name "Frontend" -TimeoutSeconds $Config.FrontendTimeout
    Log-Success "Frontend ready at http://127.0.0.1:$($Config.FrontendPort)"
}

function Start-Electron() {
    Log-Step "Starting Electron..."
    
    $frontendDir = Join-Path $Config.ProjectRoot "frontend"
    
    $env:VELLUMA_BACKEND_PORT = $Config.BackendPort.ToString()
    $env:VELLUMA_FRONTEND_PORT = $Config.FrontendPort.ToString()
    $env:VELLUMA_SERVICES_READY = "1"
    
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
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

function Main() {
    Show-Banner
    
    if ($Force) {
        Log-Info "Force mode: will clean port conflicts"
    }
    
    try {
        Start-Backend
        Start-Frontend
        $electronProc = Start-Electron
        
        Write-Host "`n============================================================" -ForegroundColor Green
        Log-Success "All services started!"
        Write-Host ""
        Write-Host "  Backend:  http://127.0.0.1:$($Config.BackendPort)" -ForegroundColor Gray
        Write-Host "  Frontend: http://127.0.0.1:$($Config.FrontendPort)" -ForegroundColor Gray
        Write-Host "  API Docs: http://127.0.0.1:$($Config.BackendPort)/docs" -ForegroundColor Gray
        Write-Host ""
        Write-Host "  Electron is running. Close window to stop all services." -ForegroundColor Yellow
        Write-Host "============================================================" -ForegroundColor Green
        
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
