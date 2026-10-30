@echo off
setlocal
title Rename the OpenVanilla GitHub repo to Leyline-Launcher
rem Was Autopilot step "ovrename" (done; the step is gone). Renames github.com/orionopenwow/OpenVanilla to orionopenwow/Leyline-Launcher with
rem this PC's GitHub CLI sign-in (orionopenwow only; refuses Chumpton), sets its description and homepage, and
rem points the PC's OpenVanilla clone at the new address. Safe to run again. Finds the clone by its origin
rem (OPENVANILLA_DIR, beside this folder, Desktop, Documents\GitHub, source\repos, the user folder).
rem leyline_rename.py here is a copy of tools\rename\leyline_rename.py in that repo.
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
%PY% "%~dp0leyline_rename.py" --find-clone --wu "%WU%" %*
exit /b %ERRORLEVEL%
