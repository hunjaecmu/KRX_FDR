@echo off
setlocal
"C:\Users\hunja\miniconda3\python.exe" -B "D:\Coding\260314 KRX_FDR\portfolio_dashboard.py" --launch
if errorlevel 1 (
 echo Unable to start KRX Portfolio. See the message above.
 pause
)
