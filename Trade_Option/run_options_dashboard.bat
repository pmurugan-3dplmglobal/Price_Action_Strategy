@echo off
title Price Action Options Dashboard (Port 5050)
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" app_option_Trade.py
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app_option_Trade.py
) else (
    python app_option_Trade.py
)
pause
