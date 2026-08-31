@echo off
title Kill Price Action Strategy
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0kill_all.ps1"
pause
