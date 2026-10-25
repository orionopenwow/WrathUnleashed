@echo off
setlocal
title WrathUnleashed - the Dalaran Hangout on Leyline (the realm as a Beacon)
rem Makes the WrathUnleashed realm itself reachable as a Leyline Beacon, "Dalaran Hangout", through the relay on
rem the same server: players on any Leyline realm can hop to it, and hops land in Dalaran. You host it; nothing runs
rem anywhere else. One SSH login: the agent's source (our own code only: no game data, no secrets) goes over stdin
rem as one small tarball, and hangout-up.sh inside it backs up, builds, starts, checks and rolls back on failure.
rem Safe to run again. Needs the relay step first. It never changes the realm list, accounts or GM rights.
rem To take the hangout off Leyline: run this file with  remove  (the realm's key is kept).
cd /d "%~dp0.."
if not exist "hangout\hangout-up.sh" (echo hangout\hangout-up.sh is missing next to this file. & pause & exit /b 1)
where tar >nul 2>&1 || (echo tar.exe is missing ^(Windows 10 1803 or later has it^). & pause & exit /b 1)
set "MODE="
if /i "%~1"=="remove" set "MODE=--remove"
set "TGZ=%TEMP%\wu-hangout-src.tgz"
if exist "%TGZ%" del /q "%TGZ%"
tar -czf "%TGZ%" --exclude=__pycache__ --exclude=*.pyc --exclude=state kit/tools/wunet kit/tools/wuhost kit/tools/Dockerfile hangout || (echo Packing the hangout failed. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -xzf - -C $T && sed 's/\r$//' $T/hangout/hangout-up.sh > $T/hangout-up.sh && bash $T/hangout-up.sh $T %MODE% 2>&1 | tee /tmp/wu-hangout-up.log; rm -rf $T; grep -q -e '^HANGOUT OK' -e '^HANGOUT REMOVED' /tmp/wu-hangout-up.log && exit 0; exit 1" < "%TGZ%"
set "RC=%ERRORLEVEL%"
del /q "%TGZ%" >nul 2>&1
if not "%RC%"=="0" (echo. & echo The hangout step did not finish; see above. Nothing is left half-done: it rolled back. & pause & exit /b 1)
pause
exit /b 0
