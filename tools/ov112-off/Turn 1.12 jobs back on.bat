@echo off
setlocal
title Leyline - turn the 1.12 jobs back on
rem Undo: puts back what the newest /root/ov112-off-STAMP folder turned off.
rem Runs start-112-jobs.sh on the server over SSH: the same box and key as WrathUnleashed's server steps
rem (root@play.openvanilla.app, %USERPROFILE%\.ssh\openwow). One SSH login.
cd /d "%~dp0"
if not exist start-112-jobs.sh (echo start-112-jobs.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "sed 's/\r$//' > /tmp/ov112-start.sh && bash /tmp/ov112-start.sh --go 2>&1 | tee /tmp/ov112-start.sh.log; grep -q '^OV112 ON' /tmp/ov112-start.sh.log" < start-112-jobs.sh
if errorlevel 1 (echo. & echo It did not finish; see above. & pause & exit /b 1)
exit /b 0
