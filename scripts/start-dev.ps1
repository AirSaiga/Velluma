#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma Development Environment Launcher
#>

[CmdletBinding()]
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$ElectronOnly,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendPort = 8002
$FrontendPort = 5175
$Processes = @()

# =============================================================================
# Functions
# =============================================================================

function Test-PortAvailable {
    param([int]$Port)
    
    # Method 1: HTTP GET request (Vite doesn't support HEAD well)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -Method GET -TimeoutSec 3 -ErrorAction Stop
        return $true
    } catch {
        # Any HTTP response means service is up
        if ($_.Exception.Response -ne $null) { return $true }
    }
    
    # Method 2: Check if port is listening via netstat
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
        if ($conn) { return $true }
    } catch {}
    
    return $false
}

function Get-ProcessUsingPort {
    param([int]$Port)
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($conn) { return Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue }
    } catch {}
    return $null
}

function Stop-ProcessOnPort {
    param([int]$Port, [string]$Name)
    $proc = Get-ProcessUsingPort -Port $Port
    if ($proc) {
        Write-Host "      Stopping $Name (PID: $($proc.Id))..." -ForegroundColor DarkYellow -NoNewline
        try {
            Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
            Write-Host " [OK]" -ForegroundColor Green
            return $true
        } catch {
            Write-Host " [FAILED]" -ForegroundColor Red
            return $false
        }
    }
    return $false
}

function Wait-Port {
    param([int]$Port, [int]$Timeout = 120, [string]$Name)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $dots = 0
    while ($sw.Elapsed.TotalSeconds -lt $Timeout) {
        if (Test-PortAvailable -Port $Port) { return }
        Start-Sleep -Milliseconds 600
        Write-Host "." -NoNewline
        $dots++
        if ($dots -gt 40) { 
            Write-Host ""
            Write-Host "      Still waiting..." -ForegroundColor DarkGray -NoNewline
            $dots = 0
        }
    }
    throw "$Name failed on port $Port (timeout: ${Timeout}s)"
}

function Stop-All {
    Write-Host "`n[WARN] Stopping services..." -ForegroundColor Yellow
    foreach ($p in $Processes) {
        if ($p -and !$p.HasExited) {
            try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
        }
    }
    Get-NetTCPConnection -LocalPort $BackendPort -ErrorAction SilentlyContinue | 
        Select-Object -ExpandProperty OwningProcess | 
        ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} }
    Get-Process -Name "node" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Write-Host "[OK] All stopped" -ForegroundColor Green
}

# =============================================================================
# Main
# =============================================================================

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "     Velluma AI Novel Writing Assistant - Dev Launcher      " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if (!(Test-Path $ProjectRoot)) { throw "Project not found: $ProjectRoot" }

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) { $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe" }
if (!(Test-Path $VenvPython)) { throw "Python venv not found" }

$FrontendDir = Join-Path $ProjectRoot "frontend"
if (!(Test-Path (Join-Path $FrontendDir "node_modules"))) { 
    throw "node_modules not found. Run: cd frontend && npm install" 
}

try {
    # Clean ports if Force mode
    if ($Force) {
        Write-Host "[INFO] Force mode: Cleaning ports..." -ForegroundColor Cyan
        Stop-ProcessOnPort -Port $BackendPort -Name "Backend"
        Stop-ProcessOnPort -Port $FrontendPort -Name "Frontend"
        Start-Sleep -Seconds 2
    }

    # Backend
    if (!$SkipBackend -and !$ElectronOnly) {
        if (Test-PortAvailable $BackendPort) {
            Write-Host "[INFO] Backend already running on port $BackendPort" -ForegroundColor Yellow
        } else {
            Write-Host "[INFO] Starting Backend on port $BackendPort..." -ForegroundColor Cyan
            $env:VELLUMA_PORT = "$BackendPort"
            $env:PYTHONUNBUFFERED = "1"
            $proc = Start-Process -FilePath $VenvPython -ArgumentList "-m","backend.main" -WorkingDirectory $ProjectRoot -WindowStyle Hidden -PassThru
            $Processes += $proc
            Write-Host "      Waiting" -NoNewline
            Wait-Port -Port $BackendPort -Name "Backend"
            Write-Host " [OK]" -ForegroundColor Green
            Start-Sleep -Seconds 2
        }
    }

    # Frontend
    if (!$SkipFrontend -and !$ElectronOnly) {
        if (Test-PortAvailable $FrontendPort) {
            Write-Host "[INFO] Frontend already running on port $FrontendPort" -ForegroundColor Yellow
        } else {
            Write-Host "[INFO] Starting Frontend on port $FrontendPort..." -ForegroundColor Cyan
            $env:NODE_ENV = "development"
            $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm","run","dev" -WorkingDirectory $FrontendDir -WindowStyle Hidden -PassThru
            $Processes += $proc
            Write-Host "      Waiting (may take 10-30s)" -NoNewline
            Wait-Port -Port $FrontendPort -Name "Frontend"
            Write-Host " [OK]" -ForegroundColor Green
            Start-Sleep -Seconds 2
        }
    }

    # Electron
    Write-Host "[INFO] Starting Electron..." -ForegroundColor Cyan
    $env:NODE_ENV = "development"
    $proc = Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm","run","electron:dev" -WorkingDirectory $FrontendDir -PassThru
    $Processes += $proc
    Start-Sleep -Seconds 5
    Write-Host "[OK] Electron started" -ForegroundColor Green

    # Summary
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host "[OK] All services started!" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Backend:  http://127.0.0.1:$BackendPort" -ForegroundColor Gray
    Write-Host "  Frontend: http://127.0.0.1:$FrontendPort" -ForegroundColor Gray
    Write-Host "  API Docs: http://127.0.0.1:$BackendPort/docs" -ForegroundColor Gray
    Write-Host ""
    Write-Host "[WARN] Press Ctrl+C to stop" -ForegroundColor Yellow
    Write-Host "============================================================" -ForegroundColor Green
    Write-Host ""

    while ($true) { Start-Sleep -Seconds 1 }

} catch {
    Write-Host "`n[ERROR] $($_.Exception.Message)" -ForegroundColor Red
    Stop-All
    exit 1
} finally {
    Stop-All
}
