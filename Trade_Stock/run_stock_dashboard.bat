@echo off
title Price Action Stock Dashboard (Port 5051)
cd /d "%~dp0"
if exist "..\.venv\Scripts\python.exe" (
    "..\.venv\Scripts\python.exe" app_Stock_Trade.py
) else if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" app_Stock_Trade.py
) else (
    python app_Stock_Trade.py
)
pause
