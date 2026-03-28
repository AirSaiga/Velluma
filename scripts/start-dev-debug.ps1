#Requires -Version 5.1
<#
.SYNOPSIS
    Velluma Dev Launcher - Debug Mode
#>

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$BackendPort = 8002
$FrontendPort = 5175

function Test-PortAvailable {
    param([int]$Port)
    
    # Method 1: HTTP GET request (Vite doesn't support HEAD well)
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/" -Method GET -TimeoutSec 3 -ErrorAction Stop
        Write-Host " (HTTP OK)" -NoNewline
        return $true
    } catch {
        # 503, 404, etc. means service is responding
        if ($_.Exception.Response -ne $null) {
            Write-Host " (HTTP response)" -NoNewline
            return $true
        }
    }
    
    # Method 2: Netstat check
    try {
        $conn = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue | Where-Object { $_.State -eq "Listen" }
        if ($conn) {
            Write-Host " (TCP listening)" -NoNewline
            return $true
        }
    } catch {}
    
    return $false
}

function Wait-Port {
    param([int]$Port, [int]$Timeout = 120)
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    while ($sw.Elapsed.TotalSeconds -lt $Timeout) {
        if (Test-PortAvailable -Port $Port) { return }
        Write-Host "." -NoNewline
        Start-Sleep -Milliseconds 600
    }
    throw "Port $Port not ready after ${Timeout}s"
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Velluma Dev Launcher - DEBUG MODE" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (!(Test-Path $VenvPython)) { $VenvPython = Join-Path $ProjectRoot "venv\Scripts\python.exe" }
$FrontendDir = Join-Path $ProjectRoot "frontend"

# Backend
if (!(Test-PortAvailable $BackendPort)) {
    Write-Host "[1/3] Starting Backend on port $BackendPort..." -ForegroundColor Green
    Write-Host "      Window will open - Keep it open for logs" -ForegroundColor Yellow
    $env:VELLUMA_PORT = "$BackendPort"
    Start-Process -FilePath $VenvPython -ArgumentList "-m","backend.main" -WorkingDirectory $ProjectRoot
    Write-Host "      Waiting" -NoNewline
    Wait-Port -Port $BackendPort
    Write-Host " [READY]" -ForegroundColor Green
    Start-Sleep -Seconds 2
} else {
    Write-Host "[1/3] Backend already running on port $BackendPort" -ForegroundColor Yellow
}

# Frontend
if (!(Test-PortAvailable $FrontendPort)) {
    Write-Host "`n[2/3] Starting Frontend on port $FrontendPort..." -ForegroundColor Green
    Write-Host "      Window will open - Keep it open for logs" -ForegroundColor Yellow
    $env:NODE_ENV = "development"
    Start-Process -FilePath "cmd.exe" -ArgumentList "/k","npm","run","dev" -WorkingDirectory $FrontendDir
    Write-Host "      Waiting" -NoNewline
    Wait-Port -Port $FrontendPort
    Write-Host " [READY]" -ForegroundColor Green
    Start-Sleep -Seconds 2
} else {
    Write-Host "[2/3] Frontend already running on port $FrontendPort" -ForegroundColor Yellow
}

# Electron
Write-Host "`n[3/3] Starting Electron..." -ForegroundColor Green
Start-Process -FilePath "cmd.exe" -ArgumentList "/c","npm","run","electron:dev" -WorkingDirectory $FrontendDir

Write-Host "`n============================================================" -ForegroundColor Green
Write-Host "All services started!" -ForegroundColor Green
Write-Host "  Backend:  http://127.0.0.1:$BackendPort" -ForegroundColor White
Write-Host "  Frontend: http://127.0.0.1:$FrontendPort" -ForegroundColor White
Write-Host "`nClose this window to stop all services..." -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Green

Read-Host "`nPress Enter to stop all services"

# Cleanup
Write-Host "`nStopping services..." -ForegroundColor Yellow
Get-NetTCPConnection -LocalPort $BackendPort -ErrorAction SilentlyContinue | Select-Object -ExpandProperty OwningProcess | ForEach-Object { try { Stop-Process -Id $_ -Force -ErrorAction SilentlyContinue } catch {} }
Get-Process -Name "node" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
Write-Host "Done!" -ForegroundColor Green
