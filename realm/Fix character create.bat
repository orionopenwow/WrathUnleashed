@echo off
setlocal
title WrathUnleashed - fix character creation
rem Fixes character creation on play.openvanilla.app (main realm): all 83 retail race/class pairs get
rem start data, their race's own starting zone (Death Knights: Acherus) and starting gear, and Death Knights
rem need no level-55 character. Backs up the changed tables first; "Rollback character fix.bat" undoes it.
rem One upload and one SSH login (the server pauses SSH after many quick logins).
rem Needs next to this file: charfix_world.sql, charfix.sh, charfix_rollback.sh.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "OPTS=-i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30"
for %%f in (charfix_world.sql charfix.sh charfix_rollback.sh) do if not exist "%%f" (echo %%f is missing next to this file. & pause & exit /b 1)
if not exist "%KEY%" (echo SSH key %KEY% not found. & pause & exit /b 1)
set "T=%TEMP%\wu-charfix.tgz"
if exist "%T%" del /q "%T%"
tar -czf "%T%" charfix_world.sql charfix.sh charfix_rollback.sh || (echo Packing failed. & pause & exit /b 1)

echo [1/2] Uploading the fix...
scp %OPTS% "%T%" %HOST%:/tmp/wu-charfix.tgz || (echo Upload failed. If it says "timed out", wait 2 minutes and run this again. & pause & exit /b 1)

echo [2/2] Applying it on the server (backup, database, settings, world server restart: 2-10 minutes)...
rem Runs on the server by itself (charfix.log), so a dropped connection can't stop it halfway.
ssh %OPTS% %HOST% "mkdir -p /srv/wrath/charfix && tar -xzf /tmp/wu-charfix.tgz -C /srv/wrath/charfix && rm -f /tmp/wu-charfix.tgz && cd /srv/wrath/charfix && sed -i 's/\r$//' charfix.sh charfix_rollback.sh charfix_world.sql && (setsid nohup bash charfix.sh > charfix.log 2>&1 < /dev/null & echo $! > charfix.pid) && sleep 1 && tail -n +1 -f --pid=$(cat charfix.pid) charfix.log; grep -q '^CHARFIX OK' charfix.log"
if errorlevel 1 (
  echo.
  echo The fix did not report success. If the connection dropped it may still be running:
  echo   ssh in and run: tail -f /srv/wrath/charfix/charfix.log
  echo "Rollback character fix.bat" puts the tables back from the backup.
  del /q "%T%" 2>nul
  pause
  exit /b 1
)
del /q "%T%" 2>nul
echo.
echo Done. Make a new character with a new pair (for example a Tauren Paladin or a Human Hunter): it starts
echo in its race's zone with its starting gear, and the main realm's pop-up offers the boost to 80.
pause
exit /b 0
