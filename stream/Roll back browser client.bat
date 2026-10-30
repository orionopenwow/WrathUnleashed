@echo off
setlocal
title WrathUnleashed - roll back the browser client
rem Puts the previous browser client back (the one before the last "Update browser client.bat").
rem The server keeps exactly one previous copy (www.old). Running this twice swaps back again.
rem Players in game keep running; new page loads get the previous client. One SSH login.
set "KEY=%USERPROFILE%\.ssh\openwow"
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "cd /srv/wrath/stream && [ -d www.old ] || { echo 'No previous client kept on the server (www.old missing).'; exit 1; }; mv www www.swap && mv www.old www && mv www.swap www.old && (docker restart wu-play >/dev/null && echo 'wu-play restarted') && echo ROLLBACK OK"
if errorlevel 1 (echo. & echo Rollback did not happen; see above. & pause & exit /b 1)
echo.
echo Done: the previous browser client is live. Reload the game page.
pause
exit /b 0
