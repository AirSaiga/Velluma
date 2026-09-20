@echo off
chcp 65001 >nul
REM 开发调试环境：单独启动后端（uvicorn --reload 热重载，前台运行，Ctrl+C 停止）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-backend.ps1" %*
