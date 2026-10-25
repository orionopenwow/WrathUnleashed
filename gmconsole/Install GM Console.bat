@echo off
setlocal
title WrathUnleashed - install or update the GM console
rem Installs (or updates) the GM console on play.openvanilla.app: ONE ssh login, the kit as a tar on stdin.
rem It runs in its own container (wu-gmconsole) listening on the server's 127.0.0.1:8099 only: nothing public.
rem Safe to run again: the previous version is backed up, the login token is kept. The game keeps running.
rem Then use "Open GM Console.bat". Undo: "Uninstall GM Console.bat".
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
for %%f in (gmconsole.py gmconsole-install.sh gmconsole-uninstall.sh Dockerfile static\app.js static\app.css) do if not exist "server\%%f" (echo server\%%f is missing next to this file. & pause & exit /b 1)
set "T=%TEMP%\wu-gmconsole.tar"
if exist "%T%" del /q "%T%"
tar -cf "%T%" -C server gmconsole.py gmconsole-install.sh gmconsole-uninstall.sh Dockerfile static || (echo Packing failed. & pause & exit /b 1)
echo Installing on the server (one SSH login; the first time builds a small image, about a minute)...
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -x -C $T -f - && sed -i 's/\r$//' $T/*.sh && bash $T/gmconsole-install.sh $T 2>&1 | tee /tmp/wu-gmconsole.log; rm -rf $T; grep -q '^GMCONSOLE OK' /tmp/wu-gmconsole.log" < "%T%"
if errorlevel 1 (echo. & echo It did not report success; see above. If it says "Connection timed out", wait 2 minutes and run it again. & del /q "%T%" & pause & exit /b 1)
del /q "%T%"
echo.
echo Done. Now run "Open GM Console.bat".
pause
exit /b 0
