@echo off
setlocal
title WrathUnleashed - Leyline Sample Hangout (check / on / off)
rem The temporary Leyline Sample Hangout (realm\sampler.sh, realm\profiles\sampler.env):
rem   "Sample hangout.bat" check     read only: what "on" would change, and where streamed players stand
rem   "Sample hangout.bat" on        lighter realm, browser fence to Dalaran + starting areas + every instance,
rem                                  realm name "Leyline Sample Hangout"; 5-minute warning, then a restart
rem   "Sample hangout.bat" off       the rollback: the main realm exactly as before; same warning and restart
rem   add "now" (for example: "Sample hangout.bat" on now) to restart without the 5-minute warning
rem Characters are never changed. One SSH login.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "MODE=%~1"
if "%MODE%"=="" set "MODE=check"
set "WARN=5"
if /i "%~2"=="now" set "WARN=0"
set "OK="
if /i "%MODE%"=="check" set "OK=1"
if /i "%MODE%"=="on" set "OK=1"
if /i "%MODE%"=="off" set "OK=1"
if not defined OK (echo Usage: "Sample hangout.bat" check ^| on ^| off [now] & pause & exit /b 1)
if not exist sampler.sh (echo sampler.sh is missing next to this file. & pause & exit /b 1)
if not exist "profiles\sampler.env" (echo profiles\sampler.env is missing. & pause & exit /b 1)
set "T=%TEMP%\wu-sampler"
if exist "%T%" rmdir /s /q "%T%"
mkdir "%T%"
copy /y sampler.sh "%T%\sampler.sh" >nul
copy /y "profiles\sampler.env" "%T%\sampler.env" >nul
tar -cf "%TEMP%\wu-sampler.tar" -C "%T%" . || (echo Packing failed. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -x -C $T -f - && sed -i 's/\r$//' $T/sampler.sh $T/sampler.env && SAMPLER_WARN_MIN=%WARN% bash $T/sampler.sh %MODE% $T/sampler.env 2>&1 | tee /tmp/wu-sampler.log; rm -rf $T; grep -q -e '^SAMPLER OK' -e '^SAMPLER CHECK OK' /tmp/wu-sampler.log" < "%TEMP%\wu-sampler.tar"
if errorlevel 1 (echo. & echo It did not report success; see above. & del /q "%TEMP%\wu-sampler.tar" & rmdir /s /q "%T%" & pause & exit /b 1)
del /q "%TEMP%\wu-sampler.tar" & rmdir /s /q "%T%"
echo.
echo Done (%MODE%).
pause
exit /b 0
