@echo off
chcp 65001 >nul
REM 兼容入口：默认开发模式，等价于 scripts\start-dev.bat
REM 如需生产/调试模式，请直接调用 scripts\start-prod.bat 或 scripts\start-debug.bat
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\start.ps1" -Mode dev %*
