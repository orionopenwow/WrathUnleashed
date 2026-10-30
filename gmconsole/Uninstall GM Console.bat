@echo off
setlocal
title WrathUnleashed - remove the GM console
rem Removes the GM console's container and image from play.openvanilla.app (ONE ssh login). The game, the
rem website and their data are not touched. The audit log stays; the login token is retired.
set "KEY=%USERPROFILE%\.ssh\openwow"
set /p OK=Type YES to remove the GM console from the server:
if /i not "%OK%"=="YES" (echo Cancelled. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "if [ -f /srv/wrath/gmconsole/gmconsole-uninstall.sh ]; then bash /srv/wrath/gmconsole/gmconsole-uninstall.sh; else docker rm -f wu-gmconsole; echo GMCONSOLE REMOVED; fi"
if errorlevel 1 (echo. & echo It did not finish; see above. & pause & exit /b 1)
echo.
echo Done.
pause
exit /b 0
