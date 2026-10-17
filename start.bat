@echo off
chcp 65001 > nul
title Pinterest Video Downloader Bot
color 0A

echo ======================================================
echo       PINTEREST VIDEO DOWNLOADER TELEGRAM BOT
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

echo Bot ishga tushirilmoqda...
echo To'xtatish uchun: Ctrl + C
echo.

python bot.py

if %errorlevel% neq 0 (
    echo.
    echo [OGOHLANTIRISH] Bot xatolik bilan to'xtadi.
    pause
)
