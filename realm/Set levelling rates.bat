@echo off
setlocal
title WrathUnleashed - levelling rates (3x XP)
rem Main realm: 3x XP (kills, quests, exploring), 2x rested, 2x reputation, 2x skill-ups; gold and drops 1x.
rem Announces a 5-minute restart in game, then restarts the world server (2-10 min). One SSH login.
rem   Set levelling rates.bat now     restart without the 5-minute warning
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "WARN=5"
if /i "%~1"=="now" set "WARN=0"
if not exist rates.sh (echo rates.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "cat > /tmp/wu-rates.sh && sed -i 's/\r$//' /tmp/wu-rates.sh && RATES_WARN_MIN=%WARN% bash /tmp/wu-rates.sh 2>&1 | tee /tmp/wu-rates.log; grep -q '^RATES OK' /tmp/wu-rates.log" < rates.sh
if errorlevel 1 (echo. & echo It did not report success; see above. & pause & exit /b 1)
echo.
echo Done.
pause
exit /b 0
