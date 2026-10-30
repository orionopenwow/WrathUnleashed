@echo off
setlocal
title Leyline - turn off the 1.12 jobs
rem Turns off the 1.12 Open Vanilla jobs (crontab lines, openvanilla-* units, 1.12 containers); backup in /root/ov112-off-STAMP.
rem Runs stop-112-jobs.sh on the server over SSH: the same box and key as WrathUnleashed's server steps
rem (root@play.openvanilla.app, %USERPROFILE%\.ssh\openwow). One SSH login.
cd /d "%~dp0"
if not exist stop-112-jobs.sh (echo stop-112-jobs.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "sed 's/\r$//' > /tmp/ov112-stop.sh && bash /tmp/ov112-stop.sh --go 2>&1 | tee /tmp/ov112-stop.sh.log; grep -q '^OV112 OFF' /tmp/ov112-stop.sh.log" < stop-112-jobs.sh
if errorlevel 1 (echo. & echo It did not finish; see above. & pause & exit /b 1)
exit /b 0
