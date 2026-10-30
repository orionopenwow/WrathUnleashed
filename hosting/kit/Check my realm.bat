@echo off
title Leyline - check my realm
rem Tests your realm the way a player would: the servers on this PC, the tunnel to the relay, a login
rem through the relay, your invite link and (public realms) the Beacons listing. Plain-language results.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it, then run this again. & pause & exit /b 1)
if not exist "state\host.json" (echo This PC is not hosting a realm yet. Run "Host a Wrath realm.bat" first. & pause & exit /b 1)
call "%~dp0profiles\pick-compose.bat"
docker compose -f "%CF%" --project-directory "%~dp0." run --rm --no-deps wu-agent python -m wuhost.selfcheck --state /state %*
pause
