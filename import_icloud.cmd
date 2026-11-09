@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
if not exist ".app_data\data\logs" mkdir ".app_data\data\logs"
python -u scripts\import_icloud_data.py %* >> ".app_data\data\logs\icloud_import.log" 2>&1
exit /b %errorlevel%
