@echo off
setlocal
title WrathUnleashed - carry over old 1.12 logins
rem Lets players use their old Open Vanilla (1.12) username and password in the 3.3.5a client.
rem First a dry run (counts and names, nothing changed), then it asks before copying anything.
rem Existing Wrath accounts are never changed; acore_auth.account is backed up first (/root/wrath-backups).
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
if not exist "carry-112-logins.sh" (echo carry-112-logins.sh is missing next to this file. & pause & exit /b 1)
echo Dry run (changes nothing)...
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 %HOST% "tr -d '\r' > /srv/wrath/carry-112-logins.sh && bash /srv/wrath/carry-112-logins.sh" < carry-112-logins.sh
if errorlevel 1 (echo. & echo The dry run stopped; see above. Nothing was changed. & pause & exit /b 1)
echo.
set "OK="
set /p OK=Type yes to copy these logins to the Wrath realm (anything else cancels): 
if /i not "%OK%"=="yes" (echo Cancelled. Nothing was changed. & pause & exit /b 0)
ssh -i "%KEY%" -o ConnectTimeout=15 %HOST% "bash /srv/wrath/carry-112-logins.sh --apply"
pause
