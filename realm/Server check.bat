@echo off
setlocal
title WrathUnleashed - server check (read-only)
rem Read-only report: memory, containers, Dungeon Finder state, players/bots, recent errors. One SSH login.
cd /d "%~dp0"
if not exist diag.sh (echo diag.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "sed 's/\r$//' > /tmp/wu-diag.sh && bash /tmp/wu-diag.sh 2>&1 | tee /tmp/wu-diag.log; grep -q '^DIAG OK' /tmp/wu-diag.log" < diag.sh
if errorlevel 1 (echo. & echo The check did not finish; see above. & pause & exit /b 1)
pause
exit /b 0
