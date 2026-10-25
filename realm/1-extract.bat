@echo off
rem Step 1 (once): extract dbc + maps from YOUR 3.3.5a install into a Docker volume for the server.
rem Takes a few minutes. Nothing leaves this PC.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it, then run this again. & pause & exit /b 1)
docker volume create ov-client-data >nul
docker run --rm --user root -v "C:\Users\campw\Downloads\World of Warcraft 3.3.5a:/wow:ro" -v ov-client-data:/out -w /out acore/ac-wotlk-tools:master /azerothcore/env/dist/bin/map_extractor -i /wow -o /out
echo.
echo Done. Next: 2-start-realm.bat
pause
