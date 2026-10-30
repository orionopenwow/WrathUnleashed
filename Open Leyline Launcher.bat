@echo off
setlocal EnableExtensions
title Leyline launcher
rem One double-click opens the Leyline launcher. No installer, nothing to set up:
rem   it keeps one file, .launcher\Leyline.exe in this folder, fresh from
rem   https://github.com/orionopenwow/Leyline/releases/download/launcher-latest/Leyline.exe
rem   (GitHub builds it from main after every launcher change), and opens it.
rem   A newer one is fetched only when there is one; with no internet the copy you have opens.
rem "Open Leyline Launcher.bat" rebuild    builds it from launcher\ on this PC instead (needs Node.js and Rust).
rem Nothing here changes the game, the server or the website.
set "WU=%~dp0"
set "WU=%WU:~0,-1%"
set "DIR=%WU%\.launcher"
set "EXE=%DIR%\Leyline.exe"
set "URL=https://github.com/orionopenwow/Leyline/releases/download/launcher-latest/Leyline.exe"
if /i "%~1"=="rebuild" goto build
if not exist "%DIR%" mkdir "%DIR%"

where curl >nul 2>&1 || goto open
if exist "%EXE%" (
  curl -fsSL --max-time 120 -z "%EXE%" -o "%EXE%.new" "%URL%" >nul 2>&1
) else (
  echo Getting the Leyline launcher ^(one file, about 15 MB^)...
  curl -fL --max-time 300 -o "%EXE%.new" "%URL%"
)
if exist "%EXE%.new" (
  for %%F in ("%EXE%.new") do if %%~zF GTR 1000000 (
    move /y "%EXE%.new" "%EXE%" >nul 2>&1 || echo Leyline is open, so the update waits for the next start.
  )
  if exist "%EXE%.new" del "%EXE%.new" >nul 2>&1
)

:open
if exist "%EXE%" (
  start "" "%EXE%"
  exit /b 0
)
echo The launcher isn't on GitHub yet ^(it appears after the next launcher build^): building it here instead.

rem --- build it on this PC (only needed before the first GitHub build, or with "rebuild")
:build
where npm >nul 2>&1 || (echo Building needs Node.js: winget install OpenJS.NodeJS.LTS & pause & exit /b 1)
where cargo >nul 2>&1 || (echo Building needs Rust: winget install Rustlang.Rustup ^(and the C++ build tools: winget install Microsoft.VisualStudio.2022.BuildTools --override "--quiet --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"^) & pause & exit /b 1)
pushd "%WU%\launcher" || (echo The launcher folder is missing: %WU%\launcher & pause & exit /b 1)
if not exist node_modules call npm install --no-audit --no-fund || (popd & echo npm install failed. & pause & exit /b 1)
echo Building the Leyline launcher ^(5-15 minutes the first time^)...
call npx --no-install tauri build --no-bundle || (popd & echo The build failed: the lines above say why. & pause & exit /b 1)
popd
if not exist "%DIR%" mkdir "%DIR%"
copy /y "%WU%\launcher\src-tauri\target\release\leyline.exe" "%EXE%" >nul || (echo Could not copy the built launcher. & pause & exit /b 1)
start "" "%EXE%"
exit /b 0
