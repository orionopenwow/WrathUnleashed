@echo off
setlocal
title Leyline - bots: the roaming bots back (the count from before)
rem Autopilot step. Sets the roaming bots back (the count from before): realm\bots.sh back on the server (backup first, a 5-minute warning in game,
rem then the world server is recreated and checked; rolled back by itself if it doesn't come back). One SSH login.
rem   "Bots - back on.bat" now     without the 5-minute warning
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "WARN=5"
if /i "%~1"=="now" set "WARN=0"
if not exist bots.sh (echo bots.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "cat > /srv/wrath/bots.sh && sed -i 's/\r$//' /srv/wrath/bots.sh && BOTS_WARN_MIN=%WARN% bash /srv/wrath/bots.sh back 2>&1 | tee /tmp/wu-bots.log; grep -q '^BOTS OK' /tmp/wu-bots.log" < bots.sh
if errorlevel 1 (echo. & echo It did not report success; see above. & exit /b 1)
echo Done.
exit /b 0
