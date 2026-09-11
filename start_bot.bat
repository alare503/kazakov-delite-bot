@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Anti-Delete Bot - Start
cd /d "%~dp0"

"C:\Users\buzin\AppData\Local\Python\pythoncore-3.14-64\python.exe" bot.py

echo.
echo Bot stopped. Press any key to close...
pause >nul