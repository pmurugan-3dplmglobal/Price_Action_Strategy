@echo off
title Start Price Action Strategy Services
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0start_services.py"
) else (
    python "%~dp0start_services.py"
)
pause
