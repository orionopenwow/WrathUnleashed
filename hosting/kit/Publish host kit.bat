@echo off
setlocal
title Publish the host kit (public download)
rem Owner tool (Autopilot step "hostkit"): builds WrathUnleashed-host-kit.zip from this kit folder and ..\..\realm
rem (presets, modules.env, Lua, profile SQL, the build recipe), checks it with the Leyline export's safety rules
rem (no game data, secrets, logs or brand words; nothing is uploaded if anything is flagged), and puts it on
rem the public release https://github.com/orionopenwow/Leyline/releases/tag/host-kit with your own gh sign-in.
rem No questions, safe to run again (the file is replaced). Never changes this folder.
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & exit /b 1)
where gh >nul 2>&1 || (echo The GitHub CLI is needed: winget install GitHub.cli   then: gh auth login & exit /b 1)
if not exist "..\..\tools\leyline-repo\hostkit.py" (echo Run this from the WrathUnleashed folder's hosting\kit. & exit /b 1)
%PY% "..\..\tools\leyline-repo\hostkit.py" --kit "%~dp0." --upload || exit /b 1
rem The same kit as the Leyline Host pack (versioned zip + torrent + hostpack.json on the "host-pack" release), and
rem stream\hostpack.json for the site (deploy it with the sign-in step, "signin").
%PY% "..\pack\make-hostpack.py" --upload --write-site
exit /b %ERRORLEVEL%
