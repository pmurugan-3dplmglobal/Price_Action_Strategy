@echo off
title Price Action Strategy -- Sync Scans and Radar to Oracle Cloud VMs
color 0A
cls
echo ===============================================================================
echo        PRICE ACTION STRATEGY -- 1-CLICK SCAN AND RADAR VM SYNC
echo ===============================================================================
echo:
python "%~dp0scratch\push_scans_to_vm.py" all
if errorlevel 1 goto :error_handler

echo:
echo ===============================================================================
echo [SUCCESS] Scan and radar sync completed successfully!
echo ===============================================================================
goto :end

:error_handler
color 0C
echo:
echo ===============================================================================
echo [ERROR] Scan sync encountered errors (Exit Code: %ERRORLEVEL%).
echo ===============================================================================

:end
echo:
pause
