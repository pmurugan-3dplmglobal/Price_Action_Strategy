@echo off
title Price Action Strategy -- Oracle Cloud Sync & Deploy
color 0A
cls
echo ===============================================================================
echo        PRICE ACTION STRATEGY -- SYNC AND START ORACLE CLOUD VM
echo ===============================================================================
echo.
echo Running sync engine...
echo.
python "%~dp0sync_to_oracle_cloud.py"
echo.
echo ===============================================================================
echo Done!
echo ===============================================================================
pause
