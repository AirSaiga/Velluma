@echo off
chcp 65001 >nul
REM 正式生产环境：构建前端（npm run build 产 dist，前台运行）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-frontend.ps1" %*
