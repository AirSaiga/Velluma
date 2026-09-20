@echo off
chcp 65001 >nul
REM 正式生产环境：单独启动 Electron（NODE_ENV=production 载入 dist，需先构建）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-electron.ps1" %*
