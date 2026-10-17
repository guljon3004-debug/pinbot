@echo off
chcp 65001 > nul
title GitHub-ga yuklash (Push to GitHub)
color 0B

echo ======================================================
echo           PROYEKTNI GITHUB-GA YUKLASH (PUSH)
echo ======================================================
echo.

set PATH=C:\Users\PC\AppData\Local\Microsoft\WinGet\Packages\Git.MinGit_Microsoft.Winget.Source_8wekyb3d8bbwe\cmd;%PATH%

echo Repozitoriy: https://github.com/guljon3004-debug/pinbot
echo.
echo Iltimos, GitHub Personal Access Token (PAT) kiriting.
echo (Token olish: https://github.com/settings/tokens)
echo.
set /p GITHUB_TOKEN="GitHub Token (yoki to'g'ridan-to'g'ri Enter): "

if "%GITHUB_TOKEN%"=="" (
    echo.
    echo Standart git push bajarilmoqda...
    git push -u origin main
) else (
    echo.
    echo Token orqali GitHub-ga yuklanmoqda...
    git push -u https://%GITHUB_TOKEN%@github.com/guljon3004-debug/pinbot.git main
)

echo.
if %errorlevel% equ 0 (
    echo [OK] Barcha kodlar GitHub-ga muvaffaqiyatli yuklandi!
    echo Havola: https://github.com/guljon3004-debug/pinbot
) else (
    echo [XATOLIK] Yuklashda muammo yuz berdi.
    echo Token to'g'riligi va repozitoriyga yozish huquqi borligini tekshiring.
)
echo.
pause
