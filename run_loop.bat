@echo off
chcp 65001 > nul
cd /d "%~dp0"

:loop
"C:\Users\PC\AppData\Local\Programs\Python\Python312\python.exe" bot.py
ping 127.0.0.1 -n 6 >nul
goto loop
