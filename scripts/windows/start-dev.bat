@echo off
chcp 65001 >nul
REM 开发模式：后端 + Vite dev server + Electron（自动开 DevTools）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0\start.ps1" -Mode dev %*
