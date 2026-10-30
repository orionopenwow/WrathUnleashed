@echo off
setlocal enabledelayedexpansion
rem Host any client, on Windows: a realm for another client's build (profiles\<id>\, listed in
rem tools\wuhost\cores.py). Called by "Host a Wrath realm.bat" when WU_PROFILE names a folder here (WU_NAME,
rem WU_VISIBILITY, WU_TOOLS_IMAGE, WU_RELAY come from it); the launcher's Host page reaches it the same way.
rem The same steps as host-profile.sh: build the server here from its authors' source at the commits in
rem profile.lock, write the config, make the server data from YOUR OWN client of that build (read-only), start it.
rem Environment: WU_CLIENT_DIR (your game folder of that build), LL_THREADS, LL_MMAPS (0 skips the monster paths),
rem LL_JOBS, LL_REBUILD=1.
set "PD=%~dp0%WU_PROFILE%\"
for %%I in ("%~dp0..") do set "KIT=%%~fI"
cd /d "%KIT%"
if not defined WU_TOOLS_IMAGE set "WU_TOOLS_IMAGE=wu-host-tools:1"
if not defined WU_RELAY set "WU_RELAY=relay.openvanilla.app"
if not defined WU_VISIBILITY set "WU_VISIBILITY=private"
if not defined WU_NAME set "WU_NAME=My Leyline Realm"
if not exist "%PD%profile.lock" (echo This kit has no profiles\%WU_PROFILE% folder. Download the full kit again. & pause & exit /b 1)

rem ---- the pinned sources (KEY=VALUE lines only; nothing in the file is run)
for %%K in (LL_PROFILE LL_CORE_COMMIT LL_DB_COMMIT LL_DB_SHA256 LL_DB_REPO LL_DB_URL LL_DB_FILES LL_EXPANSION) do set "%%K="
for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%PD%profile.lock") do (
  set "K=%%A"
  if "!K:~0,3!"=="LL_" set "%%A=%%B"
)
if not "%LL_PROFILE%"=="%WU_PROFILE%" (echo profiles\%WU_PROFILE%\profile.lock is damaged. Download the full kit again. & pause & exit /b 1)
if not defined LL_CORE_COMMIT (echo profiles\%WU_PROFILE%\profile.lock is damaged. Download the full kit again. & pause & exit /b 1)
if not defined LL_DB_COMMIT (
  echo %LL_DB_SHA256%| findstr /r "^[0-9a-f][0-9a-f]*$" >nul || (echo The %LL_VERSION% profile is not ready yet: its database file has no pinned checksum. Pick another profile. & pause & exit /b 1)
)
set "LL_TAG=%LL_VERSION%-%LL_CORE_COMMIT:~0,12%"
set "ARGS=--build-arg LL_PROFILE=%LL_PROFILE% --build-arg LL_BUILD=%LL_BUILD% --build-arg LL_CORE_REPO=%LL_CORE_REPO% --build-arg LL_CORE_COMMIT=%LL_CORE_COMMIT%"
if defined LL_EXPANSION set "ARGS=%ARGS% --build-arg LL_EXPANSION=%LL_EXPANSION%"
if defined LL_DB_COMMIT set "ARGS=%ARGS% --build-arg LL_DB_REPO=%LL_DB_REPO% --build-arg LL_DB_COMMIT=%LL_DB_COMMIT%"
if defined LL_DB_URL set "ARGS=%ARGS% --build-arg LL_DB_URL=%LL_DB_URL% --build-arg LL_DB_SHA256=%LL_DB_SHA256% --build-arg LL_DB_FILES=%LL_DB_FILES%"
set "VOL=leyline-%LL_IMAGE:leyline-=%-client-data"
set PCOMPOSE=docker compose -f "%PD%%LL_COMPOSE%" --project-directory "%KIT%"

docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it ^(or install it from docker.com^), then run this again. & pause & exit /b 1)

echo.
echo == The %LL_VERSION% server: building it on this PC from its authors' source
echo   Server: %LL_CORE_REPO% at %LL_CORE_COMMIT:~0,12% ^(credits and licences: profiles\%LL_PROFILE%\NOTICE.md^).
if not defined LL_JOBS call :jobs
set "BUILT=1"
for %%T in (server extractors db-import) do (
  set "NEED=%LL_REBUILD%"
  docker image inspect "%LL_IMAGE%-%%T:%LL_TAG%" >nul 2>&1 || set "NEED=1"
  if "!NEED!"=="1" (
    if "!BUILT!"=="1" echo   The first build takes %LL_BUILD_TIME%, only once. Finished parts are kept.
    set "BUILT=0"
    echo   [%%T]
    docker build --target %%T --build-arg JOBS=!LL_JOBS! %ARGS% -f "%PD%Dockerfile" -t "%LL_IMAGE%-%%T:%LL_TAG%" "%PD%." || (echo The build failed: see the first "error" above. Run this again: finished parts are kept. & pause & exit /b 1)
  )
)
if "%BUILT%"=="1" (echo   Already built.) else (echo   Built.)

docker run --rm -v "%KIT%:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup init --name "%WU_NAME%" --profile %LL_PROFILE% --visibility %WU_VISIBILITY% --image %LL_IMAGE% --tag %LL_TAG% --tools-image %WU_TOOLS_IMAGE% --relay %WU_RELAY% >nul || (echo Setup failed ^(see above^). & pause & exit /b 1)

echo.
echo == Server data from your own %LL_VERSION% client ^(nothing is downloaded or shared^)
docker volume create %VOL% >nul
set "MADE=0"
docker run --rm -v %VOL%:/d alpine:3.20 test -f /d/.ready >nul 2>&1 && set "MADE=1"
if "%MADE%"=="1" (echo   Already made.) else (call :extract || (pause & exit /b 1))

echo.
echo == Starting the %LL_VERSION% realm ^(the first start loads the world database: 5-20 minutes^)
for /f %%T in ('powershell -NoProfile -Command "(Get-Date).ToUniversalTime().ToString('yyyy-MM-ddTHH:mm:ss')"') do set "T0=%%T"
rem --remove-orphans: this kit folder's other realm containers stop if it hosted another profile before (data stays)
%PCOMPOSE% up -d --remove-orphans || (echo The realm did not start. Run "Realm tools.bat" and pick "logs". & pause & exit /b 1)
call :waitready || (pause & exit /b 1)

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
docker run --rm -v "%KIT%:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup show
echo.
echo Players need their own %LL_VERSION% client. They open your invite link once, make an account there,
echo   then play with: set realmlist %WU_RELAY%   ^(the join page says where this client keeps that line^)
echo "Check my realm.bat" tests everything the way a player would. Credits: profiles\%LL_PROFILE%\NOTICE.md
pause
exit /b 0

rem ------------------------------------------------------------------ helpers
:jobs
rem One compile job per CPU, at most one per 2 GB of the memory Docker Desktop has.
set "LL_MEM="
for /f %%M in ('docker info --format {{.MemTotal}}') do set "LL_MEM=%%M"
if not defined LL_MEM set "LL_MEM=4294967296"
for /f %%J in ('powershell -NoProfile -Command "[math]::Max(1,[math]::Min([int]$env:NUMBER_OF_PROCESSORS,[math]::Floor([int64]$env:LL_MEM/2GB)))"') do set "LL_JOBS=%%J"
if not defined LL_JOBS set "LL_JOBS=2"
exit /b 0

:extract
set "CLIENT="
for %%D in ("%WU_CLIENT_DIR%" "C:\Games\%LL_VERSION%" "D:\Games\%LL_VERSION%" "%USERPROFILE%\Games\%LL_VERSION%" "%USERPROFILE%\Desktop\%LL_VERSION%" "C:\%LL_VERSION%") do (
  if not defined CLIENT if exist "%%~D\Data" call :isclient "%%~D" && set "CLIENT=%%~D"
)
if not defined CLIENT set /p "CLIENT=Where is your %LL_VERSION% game folder (the one with Data in it)? "
call :isclient "%CLIENT%" || (echo No %LL_VERSION% game files in "%CLIENT%". & exit /b 1)
echo   Reading "%CLIENT%" ^(read-only^). This takes %LL_EXTRACT_TIME% ^(set LL_MMAPS=0 to skip the monster paths^).
docker run --rm -v "%CLIENT%:/client:ro" -v %VOL%:/data -e LL_THREADS -e LL_MMAPS -e "LL_CLIENT_FILES=%LL_CLIENT_FILES%" %LL_IMAGE%-extractors:%LL_TAG% || (echo Making the server data failed ^(see above^). Run this again: finished parts are kept. & exit /b 1)
exit /b 0

:isclient
rem %1 = a folder: it has every file profile.lock names (Windows paths ignore case)
for %%F in (%LL_CLIENT_FILES:,= %) do (
  set "F=%%F"
  if not exist "%~1\!F:/=\!" exit /b 1
)
exit /b 0

:waitready
set /a N=0
:waitloop
timeout /t 10 >nul
docker logs --since %T0% wu-host-realm-world 2>&1 | findstr /c:"%LL_READY%" >nul && exit /b 0
set /a N+=1
set /a M=N %% 6
if !M!==0 echo   still starting...
if !N! GEQ 180 (echo The world server did not get ready in 30 minutes. Run "Realm tools.bat" and pick "logs". & exit /b 1)
goto waitloop
