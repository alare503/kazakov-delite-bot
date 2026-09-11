@echo off
chcp 65001 >nul
title Anti-Delete Bot - Install
cd /d "%~dp0"

echo Installing libraries... this may take 1-2 minutes.
echo.

"C:\Users\buzin\AppData\Local\Python\pythoncore-3.14-64\python.exe" -m pip install -r requirements.txt

echo.
echo Done. Press any key to close...
pause >nul