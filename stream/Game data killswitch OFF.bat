@echo off
setlocal
title Leyline - game data killswitch OFF (streaming the slim sampler again)
rem Undoes "Game data killswitch ON.bat": the slim streamed sampler is served again from our server
rem (behind the sign-in, as before), and files an earlier "park" moved off the served folders come back.
rem It prints what was served before and after and checks that /data is behind the sign-in gate again.
rem Logged on the server in /srv/wrath/gamedata-switch.log. One upload and one SSH login.
rem Autopilot step: gamedata-on.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
for %%f in (server\gamedata-switch.sh server\gamedata-caddy.py) do if not exist "%%f" (echo %%f is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
echo Switching game data streaming back ON on the server...
tar -cf - -C server gamedata-switch.sh gamedata-caddy.py | ssh %OPTS% %HOST% "mkdir -p /srv/wrath/stream && tar -xf - -C /srv/wrath/stream --no-same-owner && cd /srv/wrath/stream && sed -i 's/\r$//' gamedata-switch.sh gamedata-caddy.py && WU_GAMEDATA_BY=owner bash gamedata-switch.sh on 2>&1 | tee /tmp/wu-gamedata.log; grep -q '^GAMEDATA ON OK' /tmp/wu-gamedata.log"
if errorlevel 1 (
  echo.
  echo It did not report success; see the lines above. Send Claude a screenshot of this window.
  pause
  exit /b 1
)
echo.
echo Done: the slim streamed sampler is served again (behind the sign-in).
pause
exit /b 0
