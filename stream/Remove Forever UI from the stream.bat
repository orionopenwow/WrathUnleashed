@echo off
setlocal
title WrathUnleashed - remove Forever UI from the streamed browser client
rem Takes Forever UI off the streamed slice again: the files "Add Forever UI to the stream.bat" put
rem there are removed, the slice's stock GlueXML.toc and tier list come back, and the client's boot
rem list loses its Forever UI names. Your own WoW folder is not touched. ONE SSH connection.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST%"
%SSH% "if [ -f /srv/wrath/stream/fui-install.sh ]; then bash /srv/wrath/stream/fui-install.sh remove; else echo Forever UI is not on the stream.; fi" || goto fail
echo.
echo Done. The stream has the stock interface again.
pause
exit /b 0
:fail
echo.
echo Something failed above. If it says "Connection timed out", the server is pausing SSH after
echo many quick logins: wait 2 minutes, then run this again.
pause
exit /b 1
