@echo off
setlocal
title Put the Leyline Launcher changes on GitHub (orionopenwow/Leyline-Launcher)
rem Was Autopilot step "ovland" (done; the step is gone). Run after "ovrename". Takes the branch feat-leyline-launcher-rename from
rem feat-leyline-launcher-rename.bundle next to this file, fast-forwards the PC's OpenVanilla clone's main to it
rem and pushes main (gh signed in as orionopenwow; refuses Chumpton). Fast-forward only: it stops, changing
rem nothing, if the clone isn't a clean checkout of main or GitHub moved on. Never force-pushes, makes no commits.
rem The release itself stays the owner's: dev\Release.bat 1.57.0 in that clone.
rem Done for good (2026-10-29); in labs\done\ov-rename\ since 2026-10-30, so the workspace is three folders up.
set "WU=%~dp0..\..\.."
for %%I in ("%WU%") do set "WU=%%~fI"
set GIT_TERMINAL_PROMPT=0
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & exit /b 1)
where git >nul 2>&1 || (echo Git is not installed: https://git-scm.com/download/win & exit /b 1)
where gh >nul 2>&1 || (echo The GitHub CLI is not installed: winget install GitHub.cli  ^(then: gh auth login^) & exit /b 1)
if not exist "%~dp0feat-leyline-launcher-rename.bundle" (echo feat-leyline-launcher-rename.bundle is not next to this file. Ask Claude for it. & exit /b 1)
%PY% "%~dp0leyline_rename.py" --find-clone --wu "%WU%" --land "%~dp0feat-leyline-launcher-rename.bundle" --branch feat-leyline-launcher-rename %*
exit /b %ERRORLEVEL%
