@echo off
chcp 65001 >nul
REM 开发调试环境：单独启动 Electron（连 Vite dev server，自动开 DevTools；需先起前端）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-electron.ps1" %*
