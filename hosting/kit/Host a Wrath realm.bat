@echo off
setlocal enabledelayedexpansion
title Leyline - host a realm
rem Host a Leyline (3.3.5a) realm from this PC. Needs Docker Desktop, nothing else.
rem No port forwarding: the realm talks out to the relay, players connect to the relay, and nobody
rem sees your home IP address. Safe to run again: it keeps your realm, characters and invite link.
rem
rem It asks three things the first time: the realm's name, its profile, private or public.
rem Answers can also come from the environment: WU_NAME, WU_PROFILE (main, brawl, progression, dalaran, vanillaplus, den, or a
rem profile for another client in profiles\: cmangos-1.12.1, cmangos-2.4.3; WU_CLIENT_DIR is its game folder),
rem WU_VISIBILITY, WU_WOW_DIR, WU_BUILD (1: build the realm images here if they are not published, 0: stock).
cd /d "%~dp0"

rem ---- images (the prebuilt ones are published by Leyline's CI; the local build is the fallback)
if not defined WU_IMAGE set "WU_IMAGE=ghcr.io/orionopenwow/wu-ac-wotlk"
if not defined WU_TAG set "WU_TAG=stable"
if not defined WU_LOCAL_IMAGE set "WU_LOCAL_IMAGE=ov/ac-wotlk"
if not defined WU_LOCAL_TAG set "WU_LOCAL_TAG=custom"
if not defined WU_TOOLS_PREBUILT set "WU_TOOLS_PREBUILT=ghcr.io/orionopenwow/wu-host-tools:1"
set "WU_TOOLS_IMAGE=wu-host-tools:1"
if not defined WU_RELAY set "WU_RELAY=relay.openvanilla.app"
set "ARAC_REPO=https://github.com/heyitsbench/mod-arac"
set "ARAC_COMMIT=3f605e09c656eb3b620ef2d70c7ef61808c1cfb0"
set COMPOSE=docker compose -f "%~dp0docker-compose.host.yml" --project-directory "%~dp0."

docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it ^(or install it from docker.com^), then run this again. & pause & exit /b 1)

echo.
echo == Helper image
docker pull -q "%WU_TOOLS_PREBUILT%" >nul 2>&1 && docker tag "%WU_TOOLS_PREBUILT%" "%WU_TOOLS_IMAGE%"
docker image inspect "%WU_TOOLS_IMAGE%" >nul 2>&1 || (
  echo   Building the small helper image ^(once, about a minute^)...
  docker build -q -t "%WU_TOOLS_IMAGE%" "%~dp0tools" >nul || (echo Building the helper image failed. Is this PC online? & pause & exit /b 1)
)

echo.
echo == Your realm
rem Earlier answers (running this again keeps them as the defaults)
for /f "usebackq delims=" %%L in (`docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup get`) do set "%%L"
if not defined WU_NAME (
  set "D=My Wrath Realm"
  if defined WU_OLD_NAME set "D=!WU_OLD_NAME!"
  set "WU_NAME=!D!"
  set /p "WU_NAME=Realm name [!D!]: "
)
rem The newest client build offered (tools\wuhost\cores.py MAX_OFFERED_BUILD). Hidden by the owner on 2026-10-30:
rem the 4.3.4 profile keeps its files but is not offered. Set this back to 18414 (or LEYLINE_ALL_CLIENTS=1) to offer it again.
if not defined LL_MAX_OFFERED_BUILD set "LL_MAX_OFFERED_BUILD=12340"
:askprofile
if not defined WU_PROFILE (
  set "D=main"
  if defined WU_OLD_PROFILE set "D=!WU_OLD_PROFILE!"
  echo   main         normal Wrath from level 1, or a one-time boost to 80
  echo   brawl        everyone starts at 80 in Dalaran, everything unlocked
  echo   progression  blizzlike, Vanilla then TBC then Wrath per character
  echo   dalaran      a light Dalaran hangout: no bots, boost to 80 straight to Dalaran, your own rules
  echo   vanillaplus  Vanilla+: the original world only, level 60, 1.5x XP, made to stay up for good
  echo   den          My Den: a private room to build in with friends ^(no bots, invite link only^)
  for /d %%P in ("%~dp0profiles\*") do if exist "%%P\profile.lock" (
    set "PB=99999"
    for /f "usebackq tokens=2 delims==" %%B in (`findstr /b "LL_BUILD=" "%%P\profile.lock"`) do set "PB=%%B"
    if "%LEYLINE_ALL_CLIENTS%"=="1" set "PB=0"
    if !PB! LEQ %LL_MAX_OFFERED_BUILD% echo   %%~nxP   a realm for another client ^(profiles\%%~nxP\NOTICE.md^)
  )
  set "WU_PROFILE=!D!"
  set /p "WU_PROFILE=Profile [!D!]: "
)
set "OTHER=0"
if exist "%~dp0profiles\%WU_PROFILE%\profile.lock" set "OTHER=1"
if "%OTHER%"=="0" if /i not "%WU_PROFILE%"=="main" if /i not "%WU_PROFILE%"=="brawl" if /i not "%WU_PROFILE%"=="progression" if /i not "%WU_PROFILE%"=="dalaran" if /i not "%WU_PROFILE%"=="vanillaplus" if /i not "%WU_PROFILE%"=="den" (echo Please type main, brawl, progression, dalaran, vanillaplus, den or one of the profiles listed. & set "WU_PROFILE=" & goto askprofile)
:askvis
if not defined WU_VISIBILITY (
  set "D=private"
  if defined WU_OLD_VIS if /i not "%WU_PROFILE%"=="den" set "D=!WU_OLD_VIS!"
  echo   private  only friends with your invite link can join
  echo   public   listed in Beacons on openvanilla.app for everyone
  set "WU_VISIBILITY=!D!"
  set /p "WU_VISIBILITY=Private or public [!D!]: "
)
if /i not "%WU_VISIBILITY%"=="private" if /i not "%WU_VISIBILITY%"=="public" (echo Please type private or public. & set "WU_VISIBILITY=" & goto askvis)
rem A realm for another client: its own build and start (profiles\Host a profile realm.bat).
if "%OTHER%"=="1" (
  call "%~dp0profiles\Host a profile realm.bat"
  exit /b !ERRORLEVEL!
)
if not exist "realm-files\profiles\main.env" (echo This kit is missing its realm-files folder. Download the full kit again. & pause & exit /b 1)

echo.
echo == Realm images
set "IMG=" & set "TAG="
set "PULLERR=%TEMP%\wu-host-pull.txt"
docker pull -q "%WU_IMAGE%-worldserver:%WU_TAG%" >nul 2>"%PULLERR%" && docker pull -q "%WU_IMAGE%-authserver:%WU_TAG%" >nul 2>>"%PULLERR%" && docker pull -q "%WU_IMAGE%-db-import:%WU_TAG%" >nul 2>>"%PULLERR%" && (set "IMG=%WU_IMAGE%" & set "TAG=%WU_TAG%" & echo   Using the prebuilt WrathUnleashed images.)
if not defined IMG docker image inspect "%WU_LOCAL_IMAGE%-worldserver:%WU_LOCAL_TAG%" >nul 2>&1 && (set "IMG=%WU_LOCAL_IMAGE%" & set "TAG=%WU_LOCAL_TAG%" & echo   Using the images built on this PC.)
if not defined IMG call :noimages || (pause & exit /b 1)
docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup init --name "%WU_NAME%" --profile %WU_PROFILE% --visibility %WU_VISIBILITY% --image %IMG% --tag %TAG% --tools-image %WU_TOOLS_IMAGE% --relay %WU_RELAY% >nul || (echo Setup failed ^(see above^). & pause & exit /b 1)

echo.
echo == Game data for the server ^(from your own 3.3.5a install; nothing is downloaded or shared^)
docker volume create ov-client-data >nul
docker run --rm -v ov-client-data:/d alpine:3.20 test -d /d/dbc -a -d /d/maps >nul 2>&1 && (echo   Already extracted.) || call :extract || (pause & exit /b 1)
if not "%IMG%"=="acore/ac-wotlk" (
  docker run --rm -v ov-client-data:/d alpine:3.20 test -d /d/dbc-stock >nul 2>&1 || call :arac
)

echo.
echo == Starting the realm ^(the first start imports the databases: 5-20 minutes^)
for /f %%T in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')"') do set "T0=%%T"
%COMPOSE% up -d || (echo The realm did not start. Run "Realm tools.bat" and pick "logs". & pause & exit /b 1)
call :waitready || (pause & exit /b 1)
call :profilesql
if "!RESTART!"=="1" (
  for /f %%T in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')"') do set "T0=%%T"
  %COMPOSE% restart ac-worldserver
  call :waitready || (pause & exit /b 1)
)

echo.
echo == Connecting to the relay
for /l %%i in (1,1,24) do (
  findstr /c:"\"realmlist_ok\": true" "state\relay-state.json" >nul 2>&1 && goto connected
  timeout /t 5 >nul
)
echo   Not connected yet; it keeps trying by itself. Run "Check my realm.bat" in a minute.
goto done
:connected
echo   Connected. Your home address stays hidden behind %WU_RELAY%.
:done
echo.
echo == Done
docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup show
echo.
echo Send your friends the invite link above. They open it once, make an account there, then play with
echo   set realmlist %WU_RELAY%
echo "Check my realm.bat" tests everything the way a player would.
echo Your realm's rules: state\rules.txt ^(then "Realm tools.bat rules"^).
if exist "state\host-login.txt" (echo Your GM login: state\host-login.txt) else (echo Your GM account: make it yourself on your own link in state\host-link.txt ^(keep that link to yourself^).)
pause
exit /b 0

rem ------------------------------------------------------------------ helpers
:noimages
rem The registry answered "denied / not found": the images aren't published yet. Anything else: offline.
findstr /i /c:"denied" /c:"unauthorized" /c:"not found" /c:"manifest unknown" /c:"does not exist" "%PULLERR%" >nul 2>&1 && (echo   The ready-made realm images are not published yet.) || (echo   Could not download the ready-made realm images ^(is this PC online?^).)
echo     build   build them on this PC now: 1-2 hours, about 15 GB of disk, only once ^(bots, boost, transmog...^)
echo     stock   start now with a plain server, without those extras ^(run this again later to switch^)
set "HOW=%WU_BUILD%"
if "%HOW%"=="1" set "HOW=build"
if "%HOW%"=="0" set "HOW=stock"
:askhow
if not defined HOW (set "HOW=build" & set /p "HOW=Build or stock [build]: ")
if /i not "%HOW%"=="build" if /i not "%HOW%"=="stock" (echo   Please type build or stock. & set "HOW=" & goto askhow)
if /i "%HOW%"=="stock" (
  set "IMG=acore/ac-wotlk" & set "TAG=master"
  echo   Using AzerothCore's stock images: the realm runs without Leyline's modules.
  exit /b 0
)
if not exist "realm-files\build\sources.lock" (echo This kit has no realm-files\build folder. Download the full kit again. & exit /b 1)
echo   Building the realm images on this PC: 1-2 hours and about 15 GB of disk, only once.
set "B=%~dp0cache\build"
if not exist "%B%" mkdir "%B%"
copy /y "realm-files\build\sources.lock" "%B%\" >nul
copy /y "realm-files\build\fetch.sh" "%B%\" >nul
if exist "%B%\patches" rmdir /s /q "%B%\patches"
xcopy /e /i /q /y "realm-files\build\patches" "%B%\patches" >nul
echo   [1/2] Sources at the pinned commits ^(about 1 GB^)...
docker run --rm --entrypoint sh -v "%B%:/w" alpine/git:latest /w/fetch.sh || (echo Getting the sources failed ^(is this PC online?^). Run this again: it carries on where it stopped. & exit /b 1)
echo   [2/2] Compiling ^(the long part^)...
for %%T in (worldserver authserver db-import) do (
  docker build --target %%T --build-arg CTOOLS_BUILD=db-only --build-arg CWITH_WARNINGS=OFF --build-arg CTYPE=Release -f "%B%\acore\apps\docker\Dockerfile" -t "%WU_LOCAL_IMAGE%-%%T:%WU_LOCAL_TAG%" "%B%\acore" || (echo The build failed: see the first "error:" above. Run this again: finished parts are kept. & exit /b 1)
)
set "IMG=%WU_LOCAL_IMAGE%" & set "TAG=%WU_LOCAL_TAG%"
echo   Built.
exit /b 0

:extract
set "WOW="
if defined WU_GAME_DIR set "WU_WOW_DIR=%WU_GAME_DIR%"
for %%D in ("%WU_WOW_DIR%" "%USERPROFILE%\Downloads\World of Warcraft 3.3.5a" "%USERPROFILE%\Desktop\World of Warcraft 3.3.5a" "C:\World of Warcraft 3.3.5a" "C:\Games\World of Warcraft 3.3.5a" "D:\World of Warcraft 3.3.5a" "C:\Program Files (x86)\World of Warcraft") do (
  if not defined WOW if exist "%%~D\Data\lichking.MPQ" set "WOW=%%~D"
)
if not defined WOW (
  set /p "WOW=Where is your 3.3.5a game folder (the one with Data in it)? "
)
if not exist "%WOW%\Data\lichking.MPQ" (echo No 3.3.5a game files in "%WOW%". & exit /b 1)
echo   Extracting dbc + maps from "%WOW%" ^(a few minutes^)...
docker run --rm --user root -v "%WOW%:/wow:ro" -v ov-client-data:/out -w /out acore/ac-wotlk-tools:master /azerothcore/env/dist/bin/map_extractor -i /wow -o /out || (echo Extracting the game data failed. & exit /b 1)
exit /b 0

:arac
echo   All-races-all-classes data ^(mod-arac, pinned commit^)...
if not exist "%~dp0cache" mkdir "%~dp0cache"
docker run --rm --entrypoint sh -v "%~dp0cache:/w" alpine/git:latest -c "set -e; d=/w/mod-arac; [ -d $d/.git ] || git init -q $d; cd $d; git remote add origin %ARAC_REPO% 2>/dev/null || true; git fetch -q --depth 1 origin %ARAC_COMMIT%; git checkout -q --force FETCH_HEAD" >nul 2>&1 || (echo   Skipped ^(offline?^): new characters can still use the classic race/class pairs. & exit /b 0)
docker run --rm -v ov-client-data:/d -v "%~dp0cache\mod-arac\patch-contents\DBFilesContent:/s:ro" alpine:3.20 sh -c "mkdir -p /d/dbc-stock && for f in /s/*.dbc; do b=$(basename $f); [ -f /d/dbc-stock/$b ] || cp /d/dbc/$b /d/dbc-stock/$b; cp $f /d/dbc/$b; done"
exit /b 0

:waitready
set /a N=0
:waitloop
timeout /t 10 >nul
docker logs --since %T0% wu-host-worldserver 2>&1 | findstr /c:"ready..." >nul && exit /b 0
set /a N+=1
set /a M=N %% 6
if !M!==0 echo   still starting...
if !N! GEQ 180 (echo The world server did not get ready in 30 minutes. Run "Realm tools.bat" and pick "logs". & exit /b 1)
goto waitloop

:profilesql
set "RESTART=0"
if exist "state\applied-%WU_PROFILE%" exit /b 0
set "FILES=modern_combos.sql"
if /i "%WU_PROFILE%"=="brawl" set "FILES=brawl_world.sql brawl_world_2.sql modern_combos.sql"
if /i "%WU_PROFILE%"=="main" set "FILES=main_unbrawl.sql main_world.sql modern_combos.sql"
if /i "%WU_PROFILE%"=="dalaran" set "FILES=main_unbrawl.sql main_world.sql modern_combos.sql"
echo.
echo == World changes for the %WU_PROFILE% profile ^(once^)
for %%F in (%FILES%) do (
  if exist "realm-files\sql\%%F" (
    docker exec -i wu-host-database sh -c "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql -uroot acore_world" < "realm-files\sql\%%F" && echo   applied %%F
  ) else (echo   %%F is not in this kit, skipped)
)
echo done> "state\applied-%WU_PROFILE%"
set "RESTART=1"
exit /b 0
