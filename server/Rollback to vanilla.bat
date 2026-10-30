@echo off
rem Stops WrathUnleashed on play.openvanilla.app and starts the vanilla realms again.
cd /d "%~dp0"
set /p OK=Type YES to switch the server back to vanilla: 
if /i not "%OK%"=="YES" exit /b 1
ssh -i "%USERPROFILE%\.ssh\openwow" root@play.openvanilla.app "bash /srv/wrath/rollback.sh"
pause
