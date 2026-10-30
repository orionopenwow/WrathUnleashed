@echo off
setlocal
title WrathUnleashed - diagnose character creation
rem Read-only report from play.openvanilla.app over ONE ssh login: world server log lines about character
rem creation, the playercreateinfo count, whether mod-arac's data is in, and the creation settings.
rem Writes the report to charfix-diagnose.txt next to this file as well. Changes nothing on the server.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
if not exist diagnose.sh (echo diagnose.sh is missing next to this file. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST% "tr -d '\r' | bash -s" < diagnose.sh > charfix-diagnose.txt 2>&1
type charfix-diagnose.txt
echo.
echo (saved to %~dp0charfix-diagnose.txt)
pause
