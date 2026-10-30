@echo off
setlocal
rem Optional, once: line-of-sight (vmaps) and pathing (mmaps) data from your own install, so mobs
rem and playerbots stop walking through walls. Takes hours and several GB. Then turns them on.
cd /d "%~dp0"
set "WOW=C:\Users\campw\Downloads\World of Warcraft 3.3.5a"
if not "%~1"=="" set "WOW=%~1"
if not exist "%WOW%\Data\common.MPQ" (echo No 3.3.5a install at "%WOW%". Pass your client folder as the argument. & pause & exit /b 1)
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
set "TOOLS=docker run --rm --user root -v "%WOW%:/wow:ro" -v ov-client-data:/out -w /out acore/ac-wotlk-tools:master"
echo [1/3] vmaps: extracting buildings...
%TOOLS% sh -c "/azerothcore/env/dist/bin/vmap4_extractor -d /wow/Data" > pathing.log 2>&1 || (echo Failed, see pathing.log & pause & exit /b 1)
echo [2/3] vmaps: assembling...
%TOOLS% sh -c "mkdir -p vmaps && /azerothcore/env/dist/bin/vmap4_assembler Buildings vmaps && rm -rf Buildings" >> pathing.log 2>&1 || (echo Failed, see pathing.log & pause & exit /b 1)
echo [3/3] mmaps: generating paths (the long part, hours)...
%TOOLS% sh -c "mkdir -p mmaps && /azerothcore/env/dist/bin/mmaps_generator" >> pathing.log 2>&1 || (echo Failed, see pathing.log & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_PATHING 1
docker compose up -d ac-worldserver
echo Done: line-of-sight and pathing are on.
pause
