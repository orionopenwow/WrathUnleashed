@echo off
setlocal EnableDelayedExpansion
title Leyline - play locally (private test)
rem One click: Docker, your own game data, the local AzerothCore realm, your login, the page.
rem Everything stays on this PC (127.0.0.1). Close the "Open Vanilla host" window to stop the page;
rem realm\stop-realm.bat stops the server.
rem In play\ since 2026-10-30 (was "Play WotLK (one click).bat" at the top): R is the workspace folder one level up.
for %%I in ("%~dp0..") do set "R=%%~fI\"
cd /d "%R%"
set "WOW=C:\Users\campw\Downloads\World of Warcraft 3.3.5a"
set "COMPOSE=docker compose -f "%R%realm\docker-compose.yml""
set "DB=docker exec ov-ac-database mysql -uroot -pov-local-test -N -s"

echo [1/6] Docker
docker version >nul 2>&1 && goto docker_ok
if exist "%ProgramFiles%\Docker\Docker\Docker Desktop.exe" (
  echo       starting Docker Desktop...
  start "" "%ProgramFiles%\Docker\Docker\Docker Desktop.exe"
) else (
  echo       Docker Desktop is not installed: https://www.docker.com/products/docker-desktop/
  goto fail
)
for /l %%i in (1,1,60) do (
  timeout /t 3 >nul
  docker version >nul 2>&1 && goto docker_ok
)
echo       Docker did not come up.
goto fail
:docker_ok

echo [2/6] Game data for the server (your own install, first run only)
if not exist "%WOW%\Data\common.MPQ" (
  echo       No 3.3.5a install at "%WOW%". Edit WOW= at the top of this file.
  goto fail
)
docker volume create ov-client-data >nul
docker run --rm -v ov-client-data:/d acore/ac-wotlk-tools:master test -d /d/dbc >nul 2>&1
if errorlevel 1 (
  echo       extracting dbc + maps, a few minutes...
  docker run --rm --user root -v "%WOW%:/wow:ro" -v ov-client-data:/out -w /out acore/ac-wotlk-tools:master /azerothcore/env/dist/bin/map_extractor -i /wow -o /out >"%R%realm\extract.log" 2>&1
  docker run --rm -v ov-client-data:/d acore/ac-wotlk-tools:master test -d /d/dbc >nul 2>&1 || (echo       extraction failed, see realm\extract.log & goto fail)
)

echo [3/6] Realm (first start imports the databases, several minutes)
%COMPOSE% up -d >"%R%realm\up.log" 2>&1 || (echo       the realm did not start, see realm\up.log & goto logs)
set /a waited=0
:wait_world
docker logs ov-ac-worldserver 2>&1 | findstr /c:"ready..." >nul && goto world_ok
for /f %%s in ('docker inspect -f "{{.State.Status}}" ov-ac-worldserver 2^>nul') do set state=%%s
if /i "!state!"=="exited" (echo       the world server stopped & goto logs)
if !waited! geq 900 (echo       the world server is still not ready after 15 minutes & goto logs)
timeout /t 5 >nul
set /a waited+=5
set /a mod=waited %% 30
if !mod!==0 echo       still starting... !waited!s
goto wait_world
:world_ok
echo       ready.

echo [4/6] Your login
set count=0
for /f %%c in ('%DB% -e "SELECT COUNT(*) FROM acore_auth.account" 2^>nul') do set count=%%c
if "!count!"=="0" (
  echo       No account yet: choose a name and password for this test realm.
  set /p U=      Account name: 
  set /p P=      Password: 
  docker run --rm -v "%R%realm:/w:ro" python:3.12-alpine python /w/make_account.py "!U!" "!P!" > "%TEMP%\ov-account.sql" || goto fail
  docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_auth < "%TEMP%\ov-account.sql" 2>nul && echo       account !U! created.
  del "%TEMP%\ov-account.sql"
) else (
  echo       !count! account^(s^) already; realm\add-account.bat makes more.
)

echo [5/6] Local page host
rem A new client build arrives as wasm.part.* pieces (and wenilla.js.new); put it together.
if exist "%R%play\dist\wasm.part.00" (
  echo       installing the new client build...
  powershell -NoProfile -Command "$d='%R%play\dist'; $ms=New-Object IO.MemoryStream; foreach($p in (Get-ChildItem (Join-Path $d 'wasm.part.*') | Sort-Object Name)){ $b=[IO.File]::ReadAllBytes($p.FullName); $ms.Write($b,0,$b.Length) }; $ms.Position=0; $o=[IO.File]::Create((Join-Path $d 'wenilla_bg.wasm.new')); $gz=New-Object IO.Compression.GZipStream($ms,[IO.Compression.CompressionMode]::Decompress); $gz.CopyTo($o); $o.Close(); Move-Item -Force (Join-Path $d 'wenilla_bg.wasm.new') (Join-Path $d 'wenilla_bg.wasm'); New-Item -ItemType Directory -Force (Join-Path $d '..\..\_unused') | Out-Null; Move-Item -Force (Join-Path $d 'wasm.part.*') (Join-Path $d '..\..\_unused')"
)
if exist "%R%play\dist\wenilla.js.new" move /y "%R%play\dist\wenilla.js.new" "%R%play\dist\wenilla.js" >nul
rem Restart the host each time so a new build (play\wenilla-host.new.exe) is picked up.
taskkill /im wenilla-host.exe /f >nul 2>&1
timeout /t 1 >nul
if exist "%R%play\wenilla-host.new.exe" move /y "%R%play\wenilla-host.new.exe" "%R%play\wenilla-host.exe" >nul
start "Open Vanilla host" /min "%R%play\wenilla-host.exe" --www "%R%play\dist" --data "%WOW%\Data"
timeout /t 3 >nul

echo [6/6] Opening the browser
rem Best graphics: max view distance, 16x filtering, 4x AA, full ground detail and weather.
start "" "http://127.0.0.1:8090/?farclip=777&anisotropic=16&trilinear=1&gxmultisample=4&worlddetail=2&weatherdensity=3"
echo.
echo Done. Log in with your account. This window can be closed.
timeout /t 15
exit /b 0

:logs
call "%R%realm\collect-logs.bat" >nul
echo       logs written to realm\logs.txt
:fail
echo.
echo Stopped. Send realm\logs.txt (or a screenshot of this window).
pause
exit /b 1
