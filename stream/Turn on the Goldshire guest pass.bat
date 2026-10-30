@echo off
setlocal
title Leyline - open the Goldshire Inn guest pass to everyone
rem "Try Leyline in the Goldshire Inn": visitors play a ready-made guest character in the inn, no sign-up.
rem Run this yourself, once, after you have:
rem   1. made the template character in the game: a new level-1 human on an ordinary (non-GM) account,
rem      walked into the Lion's Pride Inn in Goldshire, and logged out there (its gear is what guests get);
rem   2. let Autopilot deploy ov_demo.lua (the "scripts" step) and the browser client (the "client" step).
rem It makes 12 guest accounts (LYDEMO01..12, random passwords nobody sees; the website resets them for
rem every visit), copies the template into each, and switches the guest pass on. One SSH connection.
rem Off again: "Turn off the Goldshire guest pass.bat".
set "KEY=%USERPROFILE%\.ssh\openwow"
set "NAME=%~1"
if "%NAME%"=="" set /p NAME=Template character's name (letters only): 
echo %NAME%| findstr /r /x "[A-Za-z][A-Za-z]*" >nul || (echo Letters only, please. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "cd /srv/wrath/stream && test -f demo-pool.sh || { echo demo-pool.sh is not on the server yet: let Autopilot run the client step first.; exit 1; }; sed -i 's/\r$//' demo-pool.sh && bash demo-pool.sh make 12 %NAME% && bash demo-pool.sh on && bash demo-pool.sh list"
if errorlevel 1 (echo. & echo The guest pass was not switched on; see above. & pause & exit /b 1)
echo.
echo Done. Try it: https://play.openvanilla.app/wrath?demo=1   (a private window works best)
pause
exit /b 0
