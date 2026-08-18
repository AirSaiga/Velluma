@echo off
chcp 65001 >nul
REM 生产体验模式：npm run build 预构建 dist，Electron 载入本地 dist（NODE_ENV=production）
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0\start.ps1" -Mode prod %*
