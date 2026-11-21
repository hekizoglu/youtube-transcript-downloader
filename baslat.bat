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

where python >nul 2>nul
if %ERRORLEVEL% NEQ 0 (
    echo [HATA] Python bulunamadi. https://www.python.org/downloads/ adresinden kurun
    echo        ve kurulumda "Add Python to PATH" kutusunu isaretleyin.
    pause
    exit /b 1
)

echo yt-dlp en son surume guncelleniyor, lutfen bekleyin...
python -m pip install --upgrade --quiet --disable-pip-version-check -r requirements.txt
if %ERRORLEVEL% NEQ 0 (
    echo [UYARI] yt-dlp guncellenemedi. Internet baglantinizi kontrol edin. Mevcut surumle devam ediliyor...
)
echo.

python app.py

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo Bir hata olustu. Hata kodu: %ERRORLEVEL%
    pause
)
