@echo off
setlocal
title Leyline brand switch (check / on / off)
rem The Leyline brand switch (realm\brand.sh): everything players and visitors read says Leyline, and the main
rem realm is "Dalaran Hangout".
rem   "Leyline brand.bat" check     read only: what "on" (or "off", when it is on) would change
rem   "Leyline brand.bat" on        flips it on: realm scripts (no reload, no restart), the realm list name, the
rem                                 sign-in pages (wu-portal recreated), the streamed addon names, the hangout's
rem                                 relay listing text
rem   "Leyline brand.bat" off       the rollback: every name back as it was
rem Nobody is kicked and the world server is not restarted. One SSH login.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=check"
set "OK="
if /i "%MODE%"=="check" set "OK=1"
if /i "%MODE%"=="on" set "OK=1"
if /i "%MODE%"=="off" set "OK=1"
if not defined OK (echo Usage: "Leyline brand.bat" check ^| on ^| off & pause & exit /b 1)
if not exist brand.sh (echo brand.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp) && cat > $T && sed -i 's/\r$//' $T && bash $T %MODE% 2>&1 | tee /tmp/wu-brand.log; rm -f $T; grep -q -e '^BRAND OK' -e '^BRAND CHECK OK' /tmp/wu-brand.log" < brand.sh
if errorlevel 1 (echo. & echo It did not report success; see above. & pause & exit /b 1)
echo.
echo Done (%MODE%).
pause
exit /b 0
