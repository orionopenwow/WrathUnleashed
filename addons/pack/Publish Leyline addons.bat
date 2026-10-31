@echo off
setlocal
title Publish the Leyline addons (public download)
rem Owner tool (Autopilot step "addons"): builds leyline-addons-<version>.zip from our own addons (WrathUnleashedUI
rem from stream\fui-web, OVArmory and OVQoL from addons\, and the WUModCatalog list made from mods\catalog.json),
rem checks it (addon files only, no game data, secrets or brand words in the addon list; nothing is uploaded if
rem anything is flagged), and puts the zip and addonpack.json on the public release
rem https://github.com/orionopenwow/Leyline/releases/tag/leyline-addons with your own gh sign-in.
rem The Leyline launcher reads addonpack.json from there and installs or updates the addons in players' 3.3.5a
rem game folders (Clients, Mods > Our addons, and PLAY on the Dalaran Hangout). Never Forever UI, never game data.
rem No questions, safe to run again (a new version each run). Never changes this folder.
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & exit /b 1)
where gh >nul 2>&1 || (echo The GitHub CLI is needed: winget install GitHub.cli   then: gh auth login & exit /b 1)
if not exist "make-addonpack.py" (echo Run this from the WrathUnleashed folder's addons\pack. & exit /b 1)
%PY% "make-addonpack.py" --upload
exit /b %ERRORLEVEL%
