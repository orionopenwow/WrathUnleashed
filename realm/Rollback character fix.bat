@echo off
setlocal
title WrathUnleashed - undo the character creation fix
rem Puts the six world tables and the profile file back from the backup "Fix character create.bat" made
rem (/root/charfix-backups/original, the state before the first fix) and restarts the world server. ONE ssh login.
rem Characters made with one of the 21 new race/class pairs can't log in while the fix is undone.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set /p OK=Type YES to undo the character creation fix: 
if /i not "%OK%"=="YES" (echo Cancelled. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST% "bash /srv/wrath/charfix/charfix_rollback.sh"
if errorlevel 1 (echo Rollback did not finish; see the lines above. & pause & exit /b 1)
pause
