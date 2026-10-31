@echo off
setlocal enabledelayedexpansion
title Leyline - link a server you already run
rem Put a server you ALREADY run (any core: on this PC, a VPS or your network) on the Leyline realm list.
rem Needs Docker Desktop. Only one small helper runs (container wu-link-agent): it talks out to the Leyline relay,
rem lists your server, and passes the relay's players on to your login server. It never changes your server:
rem not its realm list, accounts, GM rights or files (it has no database login). Safe to run again.
rem
rem   "Link my server.bat"           four questions, then it's listed within a minute
rem   "Link my server.bat" status    is it connected and listed?
rem   "Link my server.bat" stop      stop the helper (your server shows offline, then leaves the list)
rem   "Link my server.bat" remove    take the helper away (the realm id stays in state\ for next time)
rem
rem Answers can come from the environment: LEYLINE_LINK_NAME, LEYLINE_LINK_AUTH, LEYLINE_LINK_WORLD,
rem LEYLINE_LINK_CLIENT (vanilla, tbc or wrath), LEYLINE_LINK_TAGLINE, LEYLINE_LINK_CORE, LEYLINE_LINK_TAGS.
cd /d "%~dp0"
if not defined WU_TOOLS_PREBUILT set "WU_TOOLS_PREBUILT=ghcr.io/orionopenwow/wu-host-tools:1"
set "WU_TOOLS_IMAGE=wu-host-tools:1"
if not defined WU_RELAY set "WU_RELAY=relay.openvanilla.app"
set "LC=wu-link-agent"

docker version >nul 2>&1 || (echo Docker Desktop is not running. Start it ^(or install it from docker.com^), then run this again. & pause & exit /b 1)

if /i "%~1"=="status" goto status
if /i "%~1"=="stop" (
  docker stop %LC% >nul 2>&1
  echo Stopped. Your server shows as offline on the list at once and leaves it after 6 hours. Start again: run this file.
  exit /b 0
)
if /i "%~1"=="remove" (
  docker rm -f %LC% >nul 2>&1
  echo The helper is gone: your server leaves the realm list ^(offline at once, off the list within 6 hours^).
  echo The realm id is kept in state\ ^(realm.key^): run this file again to come back as the same realm.
  exit /b 0
)
if not "%~1"=="" (echo Usage: "Link my server.bat" [status ^| stop ^| remove] & exit /b 1)

if exist "state\host.json" (
  findstr /c:"\"linked\": true" "state\host.json" >nul || (
    echo This kit folder already hosts a realm. Unzip a fresh copy of the host kit to link a server you already run.
    pause & exit /b 1
  )
)

echo.
echo == Helper image
docker pull -q "%WU_TOOLS_PREBUILT%" >nul 2>&1 && docker tag "%WU_TOOLS_PREBUILT%" "%WU_TOOLS_IMAGE%"
docker image inspect "%WU_TOOLS_IMAGE%" >nul 2>&1 || (
  echo   Building the small helper image ^(once, about a minute^)...
  docker build -q -t "%WU_TOOLS_IMAGE%" "%~dp0tools" >nul || (echo Building the helper image failed. Is this PC online? & pause & exit /b 1)
)

echo.
echo == Link a server you already run
for /f "usebackq delims=" %%L in (`docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup get`) do set "%%L"
if not defined LEYLINE_LINK_NAME (
  set "D=My Realm"
  if defined WU_OLD_NAME set "D=!WU_OLD_NAME!"
  set "LEYLINE_LINK_NAME=!D!"
  set /p "LEYLINE_LINK_NAME=1. Its name on the realm list [!D!]: "
)
if not defined LEYLINE_LINK_AUTH (
  set "LEYLINE_LINK_AUTH=127.0.0.1:3724"
  set /p "LEYLINE_LINK_AUTH=2. Its login server, as this PC reaches it [127.0.0.1:3724]: "
)
if not defined LEYLINE_LINK_WORLD (
  set "LEYLINE_LINK_WORLD=127.0.0.1:8085"
  set /p "LEYLINE_LINK_WORLD=3. Its world server, as this PC reaches it [127.0.0.1:8085]: "
)
:askclient
if not defined LEYLINE_LINK_CLIENT (
  set "LEYLINE_LINK_CLIENT=wrath"
  set /p "LEYLINE_LINK_CLIENT=4. The client it's for: vanilla, tbc or wrath [wrath]: "
)
set "BUILD="
if /i "%LEYLINE_LINK_CLIENT%"=="vanilla" set "BUILD=5875"
if /i "%LEYLINE_LINK_CLIENT%"=="tbc" set "BUILD=8606"
if /i "%LEYLINE_LINK_CLIENT%"=="wrath" set "BUILD=12340"
if not defined BUILD (echo Please type vanilla, tbc or wrath. & set "LEYLINE_LINK_CLIENT=" & goto askclient)
if not exist "state\host.json" if not defined LEYLINE_LINK_TAGLINE set /p "LEYLINE_LINK_TAGLINE=One line for the realm list (optional): "

rem Inside the helper's container, "this PC" is host.docker.internal (Docker Desktop).
set "A=%LEYLINE_LINK_AUTH:127.0.0.1:=host.docker.internal:%"
set "A=%A:localhost:=host.docker.internal:%"
set "W=%LEYLINE_LINK_WORLD:127.0.0.1:=host.docker.internal:%"
set "W=%W:localhost:=host.docker.internal:%"
set "EXTRA="
if defined LEYLINE_LINK_TAGLINE set EXTRA=!EXTRA! --tagline "%LEYLINE_LINK_TAGLINE%"
if defined LEYLINE_LINK_CORE set EXTRA=!EXTRA! --core %LEYLINE_LINK_CORE%
if defined LEYLINE_LINK_TAGS set EXTRA=!EXTRA! --tags %LEYLINE_LINK_TAGS%
if not exist state mkdir state
docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup link --name "%LEYLINE_LINK_NAME%" --auth-service %A% --world-service %W% --build %BUILD% --relay %WU_RELAY% !EXTRA! >nul || (echo The link settings were refused ^(see above^). & pause & exit /b 1)

echo.
echo == Starting the helper
docker rm -f %LC% >nul 2>&1
docker run -d --name %LC% --restart unless-stopped --read-only --cap-drop ALL --security-opt no-new-privileges --memory 96m --tmpfs /tmp --log-opt max-size=10m --log-opt max-file=3 --add-host host.docker.internal:host-gateway -v "%~dp0state:/state" %WU_TOOLS_IMAGE% python -m wuhost.agent --state /state >nul || (echo The helper did not start: docker logs %LC% & pause & exit /b 1)
set /a N=0
:wait
findstr /c:"\"connected\": true" "state\relay-state.json" >nul 2>&1 && goto connected
set /a N+=1
if !N! GEQ 30 (echo   Not connected yet: check this PC is online ^(docker logs %LC%^). & goto done)
timeout /t 2 /nobreak >nul
goto wait
:connected
echo   Connected to the Leyline relay.

:done
echo.
echo == Done
for /f "usebackq tokens=2 delims=:, " %%I in (`findstr /c:"\"realm_id\"" "state\host.json"`) do set "RID=%%~I"
echo   Your server shows on the Leyline realm list within a minute: https://play.openvanilla.app/wrath/r/!RID!
echo   Nothing on your server was changed. Two things to know:
echo   - Players arrive at your login server through the relay; the realm address your server hands out must
echo     already work for players ^(the one they use today^). Leyline leaves it alone.
echo   - Relay players all come from the helper's address, so turn off your login server's wrong-password IP ban
echo     ^(WrongPass.MaxCount = 0 in authserver.conf or realmd.conf^). The relay limits wrong passwords per player instead.
echo   It's listed as Unclaimed until you claim it for your Hero Key account: once the site gives you a claim token
echo   ^(its Claim a realm page^), run: "Realm tools.bat" claim TOKEN
echo   The helper restarts by itself whenever Docker Desktop runs. In Docker Desktop: Settings ^> General ^>
echo   "Start Docker Desktop when you sign in", so it comes back after a restart.
pause
exit /b 0

:status
if not exist "state\host.json" (echo Nothing linked yet: run this file. & exit /b 1)
docker ps -a --filter "name=^%LC%$" --format "Helper: {{.Status}}"
findstr /c:"\"connected\": true" "state\relay-state.json" >nul 2>&1 && (echo Relay:  connected) || (echo Relay:  not connected yet)
docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit %WU_TOOLS_IMAGE% python -m wuhost.setup show
exit /b 0
