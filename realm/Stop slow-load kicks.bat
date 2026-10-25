@echo off
setlocal
title WrathUnleashed - stop slow-load kicks
rem The world server drops a player who sends nothing for 60 seconds, and the browser client's first
rem world load can take longer than that. This raises the limit to 10 minutes and restarts the world
rem server (players online are disconnected for 2-10 minutes). One upload and one SSH login.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
if not exist timeout.sh (echo timeout.sh is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
echo Applying it on the server...
ssh %OPTS% %HOST% "cat > /tmp/wu-timeout.sh && sed -i 's/\r$//' /tmp/wu-timeout.sh && bash /tmp/wu-timeout.sh 2>&1 | tee /tmp/wu-timeout.log; grep -q '^TIMEOUT OK' /tmp/wu-timeout.log" < timeout.sh
if errorlevel 1 (echo. & echo It did not report success; see above. & pause & exit /b 1)
echo.
echo Done.
pause
exit /b 0
