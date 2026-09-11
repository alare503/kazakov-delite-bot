@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title YooMoney - Get token
cd /d "%~dp0"

"C:\Users\buzin\AppData\Local\Python\pythoncore-3.14-64\python.exe" get_token.py

echo.
echo Done. Press any key to close...
pause >nul