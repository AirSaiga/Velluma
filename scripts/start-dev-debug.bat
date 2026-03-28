@echo off
chcp 65001 >nul
title Velluma Dev Launcher - DEBUG
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0start-dev-debug.ps1"
