@echo off
chcp 65001 > nul
title Pinterest Video Downloader Bot (@jurpinbot)
color 0A

echo ======================================================
echo       PINTEREST VIDEO DOWNLOADER & GEMINI AI BOT
echo ======================================================
echo.

python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [XATOLIK] Python tizimda topilmadi!
    echo Iltimos, Python-ni https://www.python.org saytidan o'rnating
    echo va o'rnatish paytida "Add Python to PATH" katakchasini belgilang.
    echo.
    pause
    exit /b
)

if not exist .env (
    if exist .env.example (
        copy .env.example .env > nul
        echo [.env yaratildi] .env fayli namunadan yaratildi.
    )
)

:loop
echo [%date% %time%] Bot ishga tushirilmoqda (@jurpinbot)...
python bot.py
echo.
echo [OGOHLANTIRISH] Bot to'xtadi yoki internet uzildi. 5 soniyadan keyin qayta ishga tushadi...
echo To'xtatish uchun ushbu oynani yoping yoki Ctrl + C bosing.
ping 127.0.0.1 -n 6 >nul
goto loop
