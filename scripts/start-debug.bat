@echo off
chcp 65001 >nul
REM 调试模式：当前等同 dev（DevTools 自动开），预留语义入口便于未来挂接 debugpy/sourcemap
cd /d "%~dp0\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0\start.ps1" -Mode debug %*
