@echo off
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
python -u scripts\scan_market.py %*
exit /b %errorlevel%
