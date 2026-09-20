@echo off
chcp 65001 >nul
REM 开发调试环境：一键三端（后端热重载 + Vite + Electron），编排核心带监控台
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-all.ps1" %*
