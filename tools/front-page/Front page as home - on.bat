@echo off
setlocal
title Leyline front page as home - on
cd /d "%~dp0"
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "sed 's/\r$//' > /tmp/front-page.sh && bash /tmp/front-page.sh on" < front-page.sh
exit /b %ERRORLEVEL%
