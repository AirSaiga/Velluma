@echo off
REM Stop all Velluma services (logic in stop-velluma.ps1).
REM Keep this file ASCII-only: cmd parses batch lines in the OEM codepage,
REM and chcp + multibyte comments can desync the parser into executing
REM mojibake fragments as commands (seen in the field 2026-09-05).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-velluma.ps1"
timeout /t 2 >nul
