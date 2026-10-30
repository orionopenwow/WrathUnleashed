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
rem The boost and start-kit script rides along (same backup and live reload).
if exist "custom\lua_scripts\ov_main.lua" copy /y "custom\lua_scripts\ov_main.lua" "%T%\" >nul
rem Quality of life (instant spell learn on level up, .learnall, .respec, .xp, .hearth, .summon) rides along too.
if exist "custom\lua_scripts\ov_qol.lua" copy /y "custom\lua_scripts\ov_qol.lua" "%T%\" >nul
rem The Leyline realm list for the in-game Leyline window (WULY addon messages) rides along too.
if exist "custom\lua_scripts\ov_leyline.lua" copy /y "custom\lua_scripts\ov_leyline.lua" "%T%\" >nul
rem Companions (.recruit, .buddy, .dismiss) ride along too.
if exist "custom\lua_scripts\ov_companions.lua" copy /y "custom\lua_scripts\ov_companions.lua" "%T%\" >nul
rem The Goldshire Inn guest pass (inert until the website hands out passes) and the Discord World chat bridge
rem (inert until the bridge daemon is switched on) ride along too.
if exist "custom\lua_scripts\ov_demo.lua" copy /y "custom\lua_scripts\ov_demo.lua" "%T%\" >nul
if exist "custom\lua_scripts\ov_discord.lua" copy /y "custom\lua_scripts\ov_discord.lua" "%T%\" >nul
rem Leyline friends and messages (.lm, .lr, .lf; the portal polls it over SOAP) rides along too.
if exist "custom\lua_scripts\ov_social.lua" copy /y "custom\lua_scripts\ov_social.lua" "%T%\" >nul
rem Go anywhere from the website (the Modes hub: ovgo set, .go) rides along too.
if exist "custom\lua_scripts\ov_go.lua" copy /y "custom\lua_scripts\ov_go.lua" "%T%\" >nul
rem The Builder (.build: props in build areas, saved builds and share codes) rides along too.
if exist "custom\lua_scripts\ov_build.lua" copy /y "custom\lua_scripts\ov_build.lua" "%T%\" >nul
rem The OVMOD addon channel the Builder window talks over (ov_build.lua works without it, dot commands only).
if exist "custom\lua_scripts\ov_modapi.lua" copy /y "custom\lua_scripts\ov_modapi.lua" "%T%\" >nul
rem The Builder's link to mod-sandbox-core (moves in place); does nothing on an image without the module.
if exist "custom\lua_scripts\ov_sandbox_core.lua" copy /y "custom\lua_scripts\ov_sandbox_core.lua" "%T%\" >nul
rem Leyline minigolf (/golf): the referee for sessions, turns and published courses; needs ov_modapi.lua.
if exist "custom\lua_scripts\ov_golf.lua" copy /y "custom\lua_scripts\ov_golf.lua" "%T%\" >nul
rem Leyline Modes (/modes): sessions and the relay for scripted minigames; needs ov_modapi.lua.
if exist "custom\lua_scripts\ov_modes.lua" copy /y "custom\lua_scripts\ov_modes.lua" "%T%\" >nul
if exist "custom\lua_scripts\ov_playmode.lua" copy /y "custom\lua_scripts\ov_playmode.lua" "%T%\" >nul
rem The Leyline Workshop (Esc > Mods & Workshop > Workshop, /wrath/workshop): player-made courses, modes and builds,
rem GM review and one-click Play; needs ov_modapi.lua. workshop-export.py fills the web page (step 1c).
if exist "custom\lua_scripts\ov_workshop.lua" copy /y "custom\lua_scripts\ov_workshop.lua" "%T%\" >nul
if exist "custom\workshop-export.py" copy /y "custom\workshop-export.py" "%T%\" >nul
rem The Admin Console's realm half (console/SOAP "ovadmin": Workshop review, .bug reports, GM level) for
rem play.openvanilla.app/wrath/admin (stream/admin.py).
if exist "custom\lua_scripts\ov_admin.lua" copy /y "custom\lua_scripts\ov_admin.lua" "%T%\" >nul
if exist "custom\leyline-fetch.py" copy /y "custom\leyline-fetch.py" "%T%\" >nul
rem The web armory rides along too: .armory off / .armory on (ov_armory.lua), and armory-export.py, which
rem serverpass.sh installs with its 5-minute cron (step 1b) to fill play.openvanilla.app/wrath/armory.
if exist "custom\lua_scripts\ov_armory.lua" copy /y "custom\lua_scripts\ov_armory.lua" "%T%\" >nul
if exist "custom\armory-export.py" copy /y "custom\armory-export.py" "%T%\" >nul
copy /y serverpass.sh "%T%\serverpass.sh.txt" >nul
tar -cf "%TEMP%\wu-serverpass.tar" -C "%T%" . || (echo Packing failed. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "T=$(mktemp -d) && tar -x -C $T -f - && sed 's/\r$//' $T/serverpass.sh.txt > $T/sp.sh && rm -f $T/serverpass.sh.txt && (cd $T && tar -cf - *.lua $(ls leyline-fetch.py armory-export.py workshop-export.py 2>/dev/null)) | SERVERPASS_WARN_MIN=%WARN% bash $T/sp.sh 2>&1 | tee /tmp/wu-serverpass.log; rm -rf $T; grep -q '^SERVERPASS OK' /tmp/wu-serverpass.log" < "%TEMP%\wu-serverpass.tar"
if errorlevel 1 (echo. & echo It did not report success; see above. & del /q "%TEMP%\wu-serverpass.tar" & rmdir /s /q "%T%" & pause & exit /b 1)
del /q "%TEMP%\wu-serverpass.tar" & rmdir /s /q "%T%"
echo.
echo Done: Dungeon Finder from 10, .bug, .stuck and .wu are live.
pause
exit /b 0
