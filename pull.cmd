@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Apply the daily price files the Mac saved to iCloud Drive, then run the MA scan.
REM The first run (or after a long gap) installs the full bundle instead.
REM Personal records (data\tracking) are never touched. Default folder: %USERPROFILE%\iCloudDrive\KRX_FDR
python -u scripts\share_full_data.py import %*
set RC=%errorlevel%
if not "%RC%"=="0" pause
exit /b %RC%
