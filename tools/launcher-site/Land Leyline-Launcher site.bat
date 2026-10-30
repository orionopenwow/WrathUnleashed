@echo off
setlocal
title Put the openvanilla.app changes on GitHub (orionopenwow/Leyline-Launcher)
rem Autopilot step "ovsite". Takes the branch feat-ov-focus from leyline-launcher-site.bundle next to this file
rem (Claude drops it here; never committed) and fast-forwards main in the workspace's .repos\leyline-launcher clone,
rem then pushes main. GitHub Pages then puts www/ live: openvanilla.app's home sends visitors to the Leyline front page,
rem and the repo cleanup (1.12 tools in labs/) lands with it. Fast-forward only: it stops, changing nothing, if the
rem clone isn't a clean checkout of main or GitHub moved on. Never force-pushes, makes no commits.
rem Uses the landing code kept in labs\done\ov-rename\leyline_rename.py (gh signed in as orionopenwow).
set "WU=%~dp0..\.."
for %%I in ("%WU%") do set "WU=%%~fI"
set GIT_TERMINAL_PROMPT=0
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & exit /b 1)
where git >nul 2>&1 || (echo Git is not installed: https://git-scm.com/download/win & exit /b 1)
where gh >nul 2>&1 || (echo The GitHub CLI is not installed: winget install GitHub.cli  ^(then: gh auth login^) & exit /b 1)
if not exist "%~dp0leyline-launcher-site.bundle" (echo leyline-launcher-site.bundle is not next to this file. Ask Claude for it. & exit /b 1)
%PY% "%WU%\labs\done\ov-rename\leyline_rename.py" --find-clone --wu "%WU%" --land "%~dp0leyline-launcher-site.bundle" --branch feat-ov-focus %*
if errorlevel 1 (echo OVSITE FAILED & exit /b 1)
echo OVSITE OK: openvanilla.app updates from GitHub Pages in a few minutes
exit /b 0
