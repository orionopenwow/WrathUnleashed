@echo off
setlocal
title WrathUnleashed - faster downloads for far-away players
rem Server network tuning: BBR congestion control (much faster game-file streaming to players far from
rem Germany) and HTTP/3 (UDP 443). No restart of the game; the website restarts for a few seconds.
rem Backups first; Caddy is put back if the site doesn't answer. One SSH login.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
if not exist nettune.sh (echo nettune.sh is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "cat > /tmp/wu-nettune.sh && sed -i 's/\r$//' /tmp/wu-nettune.sh && bash /tmp/wu-nettune.sh 2>&1 | tee /tmp/wu-nettune.log; grep -q '^NETTUNE OK' /tmp/wu-nettune.log" < nettune.sh
if errorlevel 1 (echo. & echo It did not report success; see above. & pause & exit /b 1)
echo.
echo Done.
pause
exit /b 0
