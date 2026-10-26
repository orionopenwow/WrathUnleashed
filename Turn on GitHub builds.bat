@echo off
setlocal
title Turn on GitHub builds (one time)
rem The owner's one double-click for GitHub's side of hosting and the launcher. Safe to run again.
rem What it does (tools\github-builds\github_builds.py, standard library Python, your own gh sign-in):
rem   1. asks GitHub for the permissions the builds need (workflow, write:packages, admin:org): a browser page
rem      opens, you click Authorize. No token is shown or saved anywhere new.
rem   2. turns on Actions for the org and both repos where GitHub's API allows it;
rem   3. copies the workflow files from tools\github-workflows\ into .github\workflows\ and pushes them
rem      (WrathUnleashed: wu-images, wu-hosting [+ realm-scripts once its deploy secret exists];
rem       the public Leyline repo: leyline-launcher). Only those files are committed.
rem   4. starts the image build (ghcr.io/orionopenwow/...) and pushes the launcher tag launcher-v<version>;
rem   5. shows progress, then opens the pages GitHub has no API for (package visibility: Public) and prints
rem      the checklist. You can close the window while the images build (1-3 hours) and run it again later.
rem Never run by Autopilot: step 1 needs you in the browser.
cd /d "%~dp0"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & pause & exit /b 1)
where gh >nul 2>&1 || (echo The GitHub CLI is needed: winget install GitHub.cli   then: gh auth login & pause & exit /b 1)
where git >nul 2>&1 || (echo Git is needed: https://git-scm.com/download/win & pause & exit /b 1)
%PY% "%~dp0tools\github-builds\github_builds.py" %*
set "RC=%ERRORLEVEL%"
echo.
pause
exit /b %RC%
