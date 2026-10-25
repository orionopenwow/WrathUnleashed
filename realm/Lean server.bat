@echo off
setlocal
title WrathUnleashed - lean server (fewer bots, idle areas unload)
rem 60 -> 30 roaming bots and idle map areas unloading after 1 minute: less memory, steadier Dalaran and starter zones.
rem Announces a 5-minute restart in game, then restarts the world server (2-10 min). One SSH login.
rem   "Lean server.bat" now     restart without the 5-minute warning
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "WARN=5"
if /i "%~1"=="now" set "WARN=0"
if not exist lean.sh (echo lean.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "cat > /tmp/wu-lean.sh && sed -i 's/\r$//' /tmp/wu-lean.sh && LEAN_WARN_MIN=%WARN% bash /tmp/wu-lean.sh 2>&1 | tee /tmp/wu-lean.log; grep -q '^LEAN OK' /tmp/wu-lean.log" < lean.sh
if errorlevel 1 (echo. & echo It did not report success; see above. & pause & exit /b 1)
echo.
echo Done.
pause
exit /b 0
