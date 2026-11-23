@echo off
chcp 65001 >nul
title Transkript Klasorunu Ac
cd /d "%~dp0"
echo Transkriptler klasoru aciliyor...
start "" explorer.exe "%~dp0transkriptler"
exit
