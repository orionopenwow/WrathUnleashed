@echo off
setlocal
title Leyline - game data killswitch ON (no game data from our server)
rem Stops our server (play.openvanilla.app / wrath.openvanilla.app) serving ANY game data to players:
rem   - every game-data address (/data, the streamed slice, the tier lists, the boot and world file lists,
rem     Forever UI's art inside the slice) answers "410 Gone: this realm needs your own game folder";
rem   - Play in the browser then asks every player for their own 3.3.5a game folder (read on their PC,
rem     never uploaded); the launcher's BROWSER mode says "needs your game folder";
rem   - no one stays held to the streamed slice on the realm.
rem The browser client itself (our code), the website, the realm and desktop players are not affected.
rem It prints what was served before and after and checks the answers. Logged on the server in
rem /srv/wrath/gamedata-switch.log. Undo any time: "Game data killswitch OFF.bat".
rem
rem   "Game data killswitch ON.bat"          switch it off (the files stay on the server, unserved)
rem   "Game data killswitch ON.bat" park     also move the slice files off the served folders into
rem                                          /srv/wrath/offline-gamedata/ (never deleted; OFF.bat moves them back)
rem One upload and one SSH login. Autopilot step: gamedata-off.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
for %%f in (server\gamedata-switch.sh server\gamedata-caddy.py) do if not exist "%%f" (echo %%f is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
set "PARK="
if /i "%~1"=="park" set "PARK=--park"
echo Switching game data OFF on the server %PARK%...
tar -cf - -C server gamedata-switch.sh gamedata-caddy.py | ssh %OPTS% %HOST% "mkdir -p /srv/wrath/stream && tar -xf - -C /srv/wrath/stream --no-same-owner && cd /srv/wrath/stream && sed -i 's/\r$//' gamedata-switch.sh gamedata-caddy.py && WU_GAMEDATA_BY=owner bash gamedata-switch.sh off %PARK% 2>&1 | tee /tmp/wu-gamedata.log; grep -q '^GAMEDATA OFF OK' /tmp/wu-gamedata.log"
if errorlevel 1 (
  echo.
  echo It did not report success; see the lines above. What was switched off stays off (it never
  echo switches game data back on by itself). Send Claude a screenshot of this window.
  pause
  exit /b 1
)
echo.
echo Done: our server serves no game data. Players play with their own 3.3.5a game folder.
echo On again: "Game data killswitch OFF.bat".
pause
exit /b 0
