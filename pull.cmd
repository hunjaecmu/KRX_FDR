@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
REM Install the full data bundle that the Mac saved to iCloud Drive.
REM Personal records (data\tracking) are never touched. Default folder: %USERPROFILE%\iCloudDrive\KRX_FDR
python -u scripts\share_full_data.py import %*
set RC=%errorlevel%
if not "%RC%"=="0" pause
exit /b %RC%
