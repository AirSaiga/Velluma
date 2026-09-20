@echo off
chcp 65001 >nul
REM 开发调试环境：单独启动前端（Vite dev server，前台运行，Ctrl+C 停止）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-frontend.ps1" %*
