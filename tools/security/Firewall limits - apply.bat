@echo off
setlocal
title Leyline - firewall limits (apply)
rem Connection-flood limits for the game, relay and web ports Docker publishes (DOCKER-USER), and a fail2ban jail
rem for wrong passwords at the login server. See firewall.sh. Applies it (players already in game are not touched); bash firewall.sh --remove undoes it.
rem Runs firewall.sh on the server over SSH (root@play.openvanilla.app, %USERPROFILE%\.ssh\openwow). One SSH login.
cd /d "%~dp0"
if not exist firewall.sh (echo firewall.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "sed 's/\r$//' > /tmp/wu-firewall.sh && bash /tmp/wu-firewall.sh --apply 2>&1 | tee /tmp/wu-firewall.log; grep -q '^FIREWALL OK' /tmp/wu-firewall.log" < firewall.sh
if errorlevel 1 (echo. & echo It did not finish; see above. & pause & exit /b 1)
exit /b 0
