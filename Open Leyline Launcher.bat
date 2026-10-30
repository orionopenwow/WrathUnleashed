@echo off
setlocal EnableExtensions
title Leyline launcher
rem One double-click opens the Leyline launcher from this folder. It uses the first of these that it finds:
rem   1. the installed launcher (the installer's per-user folder, then Program Files)
rem   2. the copy built from this folder (launcher\src-tauri\target\release\leyline.exe)
rem   3. the newest launcher release on GitHub (orionopenwow/Leyline, a launcher-v* tag): downloads its Windows
rem      installer to your Temp folder, runs it, then opens the launcher
rem   4. builds it from this folder (first time 5-15 minutes; needs Node.js and Rust, it says how to get them if
rem      they're missing), then opens it. Later double-clicks open the built copy at once.
rem "Open Leyline Launcher.bat" rebuild    builds again from this folder (after launcher changes), then opens it
rem Nothing here changes the game, the server or the website.
set "WU=%~dp0"
set "WU=%WU:~0,-1%"
set "BUILT=%WU%\launcher\src-tauri\target\release\leyline.exe"
if /i "%~1"=="rebuild" goto build
rem The launcher's version in this folder: a copy older than it (an old install, an old build) is never opened;
rem this folder's launcher is built instead (so the look and the realm are always the current ones).
set "SRCVER="
for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "(Get-Content -Raw '%WU%\launcher\src-tauri\tauri.conf.json' | ConvertFrom-Json).version" 2^>nul`) do set "SRCVER=%%V"

for %%P in ("%LOCALAPPDATA%\Leyline\leyline.exe" "%LOCALAPPDATA%\Leyline\Leyline.exe" "%LOCALAPPDATA%\Programs\Leyline\Leyline.exe" ^
            "%ProgramFiles%\Leyline\Leyline.exe" "%ProgramFiles%\Leyline\leyline.exe" "%BUILT%") do (
  if exist "%%~P" call :current "%%~P" && (
    echo Opening the Leyline launcher: %%~P
    start "" "%%~P"
    exit /b 0
  )
)
if exist "%BUILT%" goto build

rem --- 3. a released installer on GitHub
where gh >nul 2>&1 || goto build
set "TAG="
for /f "usebackq delims=" %%T in (`gh release list --repo orionopenwow/Leyline --limit 30 --json tagName --jq ".[].tagName | select(startswith(\"launcher-v\"))" 2^>nul`) do (
  if not defined TAG set "TAG=%%T"
)
if not defined TAG (
  echo No Leyline launcher release on GitHub yet: building it from this folder instead.
  goto build
)
set "DL=%TEMP%\leyline-launcher-%TAG%"
if not exist "%DL%" mkdir "%DL%"
echo Downloading the Leyline launcher installer (%TAG%)...
gh release download "%TAG%" --repo orionopenwow/Leyline --dir "%DL%" --pattern "*-setup.exe" --clobber || gh release download "%TAG%" --repo orionopenwow/Leyline --dir "%DL%" --pattern "*.msi" --clobber || goto build
for %%F in ("%DL%\*-setup.exe" "%DL%\*.msi") do (
  echo Running the installer: %%~nxF
  start /wait "" "%%~F"
  goto installed
)
goto build
:installed
for %%P in ("%LOCALAPPDATA%\Leyline\leyline.exe" "%LOCALAPPDATA%\Leyline\Leyline.exe" "%ProgramFiles%\Leyline\Leyline.exe") do (
  if exist "%%~P" ( start "" "%%~P" & exit /b 0 )
)
echo The installer finished. Open Leyline from the Start menu.
pause
exit /b 0

rem --- 4. build it from this folder
:build
where npm >nul 2>&1
if errorlevel 1 (
  echo.
  echo Node.js is needed to build the launcher the first time. Install it with:
  echo     winget install OpenJS.NodeJS.LTS
  echo then double-click this file again.
  pause
  exit /b 1
)
where cargo >nul 2>&1
if errorlevel 1 (
  echo.
  echo Rust is needed to build the launcher the first time. Install it with:
  echo     winget install Rustlang.Rustup
  echo and the C++ build tools ^(once^):
  echo     winget install Microsoft.VisualStudio.2022.BuildTools --override "--quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
  echo then double-click this file again.
  pause
  exit /b 1
)
pushd "%WU%\launcher" || (echo The launcher folder is missing: %WU%\launcher & pause & exit /b 1)
if not exist node_modules (
  echo Getting the build tools for the launcher ^(once^)...
  call npm install --no-audit --no-fund || (popd & echo npm install failed. & pause & exit /b 1)
)
echo Building the Leyline launcher ^(the first time takes 5-15 minutes; later builds are quick^)...
call npx --no-install tauri build --no-bundle || (popd & echo The build failed: the lines above say why. & pause & exit /b 1)
popd
if not exist "%BUILT%" (echo The build finished but %BUILT% is missing. & pause & exit /b 1)
echo Opening the Leyline launcher.
start "" "%BUILT%"
exit /b 0

rem :current EXE  -> exit 0 when EXE's version is at least this folder's launcher version (or either is unknown)
:current
if not defined SRCVER exit /b 0
set "EXEVER="
for /f "usebackq delims=" %%V in (`powershell -NoProfile -Command "(Get-Item -LiteralPath '%~1').VersionInfo.ProductVersion" 2^>nul`) do set "EXEVER=%%V"
if not defined EXEVER exit /b 0
powershell -NoProfile -Command "if ([version]('%EXEVER%' -replace '[^0-9.].*$','') -ge [version]'%SRCVER%') { exit 0 } else { exit 1 }" >nul 2>&1
if errorlevel 1 (
  echo %~1 is version %EXEVER%, older than this folder's %SRCVER%: building the current one instead.
  exit /b 1
)
exit /b 0
