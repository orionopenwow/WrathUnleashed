@echo off
setlocal
title WrathUnleashed - deploy the Beacons relay (relay.openvanilla.app)
rem Installs or updates the Beacons relay on the server, next to the realm and the website. One SSH login:
rem the relay's source (our own code only: no game data, no secrets) goes over stdin as one small tarball,
rem and relay-up.sh inside it backs up, builds, starts, health-checks and rolls back on failure.
rem Safe to run again. If DNS for relay.openvanilla.app is missing it says exactly what record to add.
cd /d "%~dp0.."
if not exist "relay\deploy\relay-up.sh" (echo relay\deploy\relay-up.sh is missing next to this file. & pause & exit /b 1)
where tar >nul 2>&1 || (echo tar.exe is missing ^(Windows 10 1803 or later has it^). & pause & exit /b 1)
set "TGZ=%TEMP%\wu-relay-src.tgz"
if exist "%TGZ%" del /q "%TGZ%"
tar -czf "%TGZ%" --exclude=__pycache__ --exclude=*.pyc kit/tools/wunet relay/wurelay relay/Dockerfile relay/deploy || (echo Packing the relay failed. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -xzf - -C $T && sed 's/\r$//' $T/relay/deploy/relay-up.sh > $T/relay-up.sh && bash $T/relay-up.sh $T 2>&1 | tee /tmp/wu-relay-up.log; rm -rf $T; grep -q '^RELAY OK' /tmp/wu-relay-up.log && exit 0; grep -q '^RELAY WAITING FOR DNS' /tmp/wu-relay-up.log && exit 3; exit 1" < "%TGZ%"
set "RC=%ERRORLEVEL%"
del /q "%TGZ%" >nul 2>&1
rem Read-only, from this PC (outside the box): are the game ports 40000-40999 reachable? A Hetzner Cloud
rem Firewall can't be seen from the box; this prints the console clicks when the ports are blocked.
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not "%RC%"=="1" if defined PY (echo. & %PY% relay\deploy\portcheck.py)
if "%RC%"=="3" (echo. & echo The relay is installed, but relay.openvanilla.app has no DNS record pointing at the server yet. & echo Add the A record shown above, then run this step again. & pause & exit /b 3)
if not "%RC%"=="0" (echo. & echo The relay step did not finish; see above. Nothing is left half-done: it rolled back. & pause & exit /b 1)
pause
exit /b 0
