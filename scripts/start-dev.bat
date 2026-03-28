@echo off
chcp 65001 >nul
title Velluma Dev Launcher
echo.
echo ============================================================
echo    Velluma AI Novel Writing Assistant - Dev Launcher
echo ============================================================
echo.

where powershell >nul 2>nul
if %errorlevel% neq 0 (
    echo [ERROR] PowerShell not found.
    pause
    exit /b 1
)

set "SCRIPT_DIR=%~dp0"

if "%~1"=="--force" (
    echo [INFO] Force mode: Will kill existing processes on ports
echo.
    powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_DIR%start-dev.ps1" -Force
) else (
    echo [INFO] Starting development environment...
    echo [TIP] Use --force to kill existing processes on ports
echo.
    powershell -ExecutionPolicy Bypass -NoProfile -File "%SCRIPT_DIR%start-dev.ps1"
)

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Startup failed.
    echo [TIP] Try running with --force flag to clean up ports
    echo       Or use start-dev-debug.bat to see detailed errors
    pause
    exit /b %errorlevel%
)

echo.
echo [INFO] Services stopped
pause
