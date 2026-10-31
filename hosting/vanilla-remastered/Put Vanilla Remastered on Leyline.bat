@echo off
setlocal
title Leyline - Vanilla Remastered on Leyline (the 1.12 realm as an official Beacon)
rem Lists the old 1.12 realm on the Leyline network as "Vanilla Remastered", an official Beacon like the Dalaran
rem Hangout: signup off, its own sign-in (the old 1.12 logins). We host it; the plan is a community host later
rem (docs\VANILLA-REMASTERED.md). Needs the ov112-on step first. One SSH login: the agent's source (our own code
rem only: no game data, no secrets) goes over stdin as one small tarball, and vr-beacon-up.sh inside it backs up,
rem builds, starts, checks and rolls back on failure. Safe to run again.
rem To take it off Leyline: run this file with  remove  (the realm's key is kept).
cd /d "%~dp0.."
if not exist "vanilla-remastered\vr-beacon-up.sh" (echo vanilla-remastered\vr-beacon-up.sh is missing next to this file. & pause & exit /b 1)
where tar >nul 2>&1 || (echo tar.exe is missing ^(Windows 10 1803 or later has it^). & pause & exit /b 1)
set "MODE="
if /i "%~1"=="remove" set "MODE=--remove"
set "TGZ=%TEMP%\wu-vr-beacon-src.tgz"
if exist "%TGZ%" del /q "%TGZ%"
tar -czf "%TGZ%" --exclude=__pycache__ --exclude=*.pyc --exclude=state --exclude=tests kit/tools/wunet kit/tools/wuhost kit/tools/Dockerfile vanilla-remastered || (echo Packing failed. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -xzf - -C $T && sed 's/\r$//' $T/vanilla-remastered/vr-beacon-up.sh > $T/vr-beacon-up.sh && bash $T/vr-beacon-up.sh $T %MODE% 2>&1 | tee /tmp/wu-vr-beacon.log; rm -rf $T; grep -q -e '^VR BEACON OK' -e '^VR BEACON REMOVED' /tmp/wu-vr-beacon.log && exit 0; exit 1" < "%TGZ%"
set "RC=%ERRORLEVEL%"
del /q "%TGZ%" >nul 2>&1
if not "%RC%"=="0" (echo. & echo The Vanilla Remastered step did not finish; see above. Nothing is left half-done: it rolled back. & pause & exit /b 1)
exit /b 0
