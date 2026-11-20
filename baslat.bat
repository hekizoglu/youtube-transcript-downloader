@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
set PYTHONUTF8=1

title YouTube Transkript Indirici Pro
cd /d "%~dp0"

echo ====================================================================
echo          YouTube Toplu Transkript Indirici Baslatiliyor...
echo ====================================================================
echo.
echo Tarayicinizda acilacak adres: http://localhost:5500
echo.
echo Kapatmak icin bu pencereyi kapatabilir veya CTRL+C yapabilirsiniz.
echo.

python app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Bir hata olustu. Hata kodu: %ERRORLEVEL%
    pause
)
