@echo off
chcp 65001 >nul
REM 调试模式：后端 uvicorn --reload 热重载 + Vite dev server + Electron（自动开 DevTools）
REM 保存 backend/ 下任意 .py 即自动重启后端，前端无需手动刷新 API。
cd /d "%~dp0\..\.."
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0\start.ps1" -Mode debug %*
