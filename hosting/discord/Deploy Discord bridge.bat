@echo off
setlocal
title Leyline - install the Discord bridge on the server
rem Installs or updates the Discord bridge (World chat and the bug feed) on the realm box. One SSH login: the
rem bridge's source (our own code only: no secrets) goes over stdin as one small tarball, and discord-up.sh
rem inside it installs it. It never turns the bridge on: that is one command on the server, shown at the end.
rem The game side (realm\custom\lua_scripts\ov_discord.lua) goes with the realm scripts as usual.
cd /d "%~dp0.."
if not exist "discord\deploy\discord-up.sh" (echo discord\deploy\discord-up.sh is missing next to this file. & pause & exit /b 1)
where tar >nul 2>&1 || (echo tar.exe is missing ^(Windows 10 1803 or later has it^). & pause & exit /b 1)
set "TGZ=%TEMP%\wu-discord-src.tgz"
if exist "%TGZ%" del /q "%TGZ%"
tar -czf "%TGZ%" --exclude=__pycache__ --exclude=*.pyc discord/wudiscord discord/deploy || (echo Packing the bridge failed. & pause & exit /b 1)
ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -xzf - -C $T && sed 's/\r$//' $T/discord/deploy/discord-up.sh > $T/discord-up.sh && bash $T/discord-up.sh $T 2>&1 | tee /tmp/wu-discord-up.log; rm -rf $T; grep -q '^DISCORD BRIDGE OK' /tmp/wu-discord-up.log && exit 0; grep -q '^DISCORD BRIDGE INSTALLED' /tmp/wu-discord-up.log && exit 3; exit 1" < "%TGZ%"
set "RC=%ERRORLEVEL%"
del /q "%TGZ%" >nul 2>&1
if "%RC%"=="3" (echo. & echo Installed, not turned on. Put the bot token and channel ids in /opt/wu-discord/discord.env on the server, & echo then run: systemctl enable --now wu-discord & pause & exit /b 0)
if not "%RC%"=="0" (echo. & echo The Discord bridge step did not finish; see above. & pause & exit /b 1)
pause
exit /b 0
