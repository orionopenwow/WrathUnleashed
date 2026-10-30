@echo off
setlocal
title Open Vanilla - build the custom WotLK realm
rem Builds AzerothCore (mod-playerbots fork) with the modules in custom\sources.lock, then
rem switches this realm to it. First run: about 1 hour (sources ~1 GB, then a full compile).
rem Later runs only rebuild what changed. Characters and accounts are kept.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it, then run this again. & pause & exit /b 1)
docker run --rm -v ov-client-data:/d alpine:3.20 test -d /d/dbc >nul 2>&1 || (echo Run 1-extract.bat first. & pause & exit /b 1)

echo [1/5] Sources (AzerothCore + modules at the pinned commits)
docker run --rm --entrypoint sh -v "%~dp0custom:/w" alpine/git:latest /w/fetch.sh || (echo Fetching the sources failed. & pause & exit /b 1)

echo [2/5] Compiling the images (long: about 30-90 minutes the first time)
docker compose -f docker-compose.yml -f docker-compose.build.yml build || (echo. & echo The build failed. Scroll up for the first "error:" line. & pause & exit /b 1)

echo [3/5] All-races-all-classes server data (mod-arac)
docker run --rm -v ov-client-data:/d -v "%~dp0custom\acore\modules\mod-arac\patch-contents\DBFilesContent:/s:ro" alpine:3.20 sh -c "mkdir -p /d/dbc-stock && for f in /s/*.dbc; do b=$(basename $f); [ -f /d/dbc-stock/$b ] || cp /d/dbc/$b /d/dbc-stock/$b; cp $f /d/dbc/$b; done" || (echo Copying the mod-arac data failed. & pause & exit /b 1)

echo [4/5] Switching the realm to the custom images
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_IMAGE ov/ac-wotlk
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_TAG custom

echo [5/5] Restarting (the database import adds the modules' tables, a few minutes)
docker compose up -d || (echo The realm did not start. Run collect-logs.bat and send logs.txt. & pause & exit /b 1)
:wait
timeout /t 10 >nul
docker logs ov-ac-worldserver 2>&1 | findstr /c:"ready..." >nul || goto wait
echo.
echo Done. The custom realm is up. Profile: see "Switch profile.bat". Auction bot: set-ahbot.bat.
echo Client side: ..\addons\install-gm-addons.bat (GM window, addon pack, all-races patch).
pause
