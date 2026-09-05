@echo off
title Price Action Strategy -- Sync Token to Oracle Cloud VM
color 0A
cls
echo ===============================================================================
echo        PRICE ACTION STRATEGY -- SYNC KITE TOKEN TO ORACLE CLOUD VM
echo ===============================================================================
echo.
python "%~dp0sync_token_to_vm.py"
echo.
pause
