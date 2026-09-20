@echo off
chcp 65001 >nul
REM 正式生产环境：一键三端（后端 + npm run build + Electron 生产壳），编排核心带监控台
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-all.ps1" %*
