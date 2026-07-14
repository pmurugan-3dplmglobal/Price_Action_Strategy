@echo off
echo Shutting down all trading services...
powershell -NoProfile -Command "Get-WmiObject Win32_Process -Filter \"Name like 'python%%'\" | Where-Object { $_.CommandLine -like '*app.py*' -or $_.CommandLine -like '*trade_engine*' -or $_.CommandLine -like '*scanner*' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force; Write-Host ('  Killed ' + $_.ProcessId) }"
echo Done.
pause
