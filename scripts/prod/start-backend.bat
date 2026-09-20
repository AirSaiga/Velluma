@echo off
chcp 65001 >nul
REM 正式生产环境：单独启动后端（无热重载，端口后端自协商，前台运行，Ctrl+C 停止）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-backend.ps1" %*
