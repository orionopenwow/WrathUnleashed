@echo off
setlocal
title WrathUnleashed - server pass (Dungeon Finder at 10, bug reports, QoL)
rem Dungeon Finder from level 10 (Ragefire, Wailing Caverns, Deadmines, Shadowfang), .bug reports, .stuck, .wu,
rem and grouping across factions. Backs everything up first. Announces a 5-minute restart in game, then
rem restarts the world server (2-10 min). One SSH login.
rem   "Server pass - finder 10 and bug reports.bat" now     restart without the 5-minute warning
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "WARN=5"
if /i "%~1"=="now" set "WARN=0"
if not exist serverpass.sh (echo serverpass.sh is missing next to this file. & pause & exit /b 1)
if not exist "custom\lua_scripts\ov_reports.lua" (echo custom\lua_scripts\ov_reports.lua is missing. & pause & exit /b 1)
if not exist "..\stream\lua\ov_slices.lua" (echo ..\stream\lua\ov_slices.lua is missing. & pause & exit /b 1)
set "T=%TEMP%\wu-serverpass"
if exist "%T%" rmdir /s /q "%T%"
mkdir "%T%"
copy /y "custom\lua_scripts\ov_reports.lua" "%T%\" >nul
copy /y "..\stream\lua\ov_slices.lua" "%T%\" >nul
copy /y serverpass.sh "%T%\serverpass.sh.txt" >nul
tar -cf "%TEMP%\wu-serverpass.tar" -C "%T%" . || (echo Packing failed. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -x -C $T -f - && sed 's/\r$//' $T/serverpass.sh.txt > $T/sp.sh && rm -f $T/serverpass.sh.txt && (cd $T && tar -cf - *.lua) | SERVERPASS_WARN_MIN=%WARN% bash $T/sp.sh 2>&1 | tee /tmp/wu-serverpass.log; rm -rf $T; grep -q '^SERVERPASS OK' /tmp/wu-serverpass.log" < "%TEMP%\wu-serverpass.tar"
if errorlevel 1 (echo. & echo It did not report success; see above. & del /q "%TEMP%\wu-serverpass.tar" & rmdir /s /q "%T%" & pause & exit /b 1)
del /q "%TEMP%\wu-serverpass.tar" & rmdir /s /q "%T%"
echo.
echo Done: Dungeon Finder from 10, .bug, .stuck and .wu are live.
pause
exit /b 0
