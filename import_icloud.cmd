@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM GitHub upload of the web data bundle is done by the Mac only; skip it on this PC.
set KRX_DATA_TOKEN=
REM Scheduled (Mon-Fri 21:30): apply the daily price files the Mac shared to iCloud Drive,
REM then run the MA scan and keep the results locally.
REM The first run, or a gap in the daily files, installs the full bundle instead.
if not exist ".app_data\data\logs" mkdir ".app_data\data\logs"
echo ===== %date% %time% >> ".app_data\data\logs\icloud_import.log"
python -u scripts\share_full_data.py import --dir "D:\iCloud Drive\iCloudDrive\KRX_FDR" %* >> ".app_data\data\logs\icloud_import.log" 2>&1
exit /b %errorlevel%
