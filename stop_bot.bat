@echo off
chcp 65001 > nul
title Botni to'xtatish
color 0C

echo ======================================================
echo                BOTNI TO'XTATISH
echo ======================================================
echo.
echo Orqa fonda ishlayotgan bot jarayoni to'xtatilmoqda...

taskkill /F /FI "WINDOWTITLE eq Pinterest Video Downloader Bot*" /T >nul 2>&1
taskkill /F /IM python.exe >nul 2>&1
taskkill /F /IM pythonw.exe >nul 2>&1

echo.
echo [OK] Bot muvaffaqiyatli to'xtatildi!
echo.
pause
