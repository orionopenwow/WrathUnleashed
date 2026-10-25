@echo off
rem Goes back to AzerothCore's stock images (no modules). Run "Build custom realm.bat" to return.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_IMAGE acore/ac-wotlk
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_TAG master
docker compose up -d
echo Switched to the stock images.
pause
