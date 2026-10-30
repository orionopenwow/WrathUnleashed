@echo off
setlocal
title Turn on GitHub builds (one time)
rem The owner's one double-click for GitHub's side of hosting and the launcher. Safe to run again.
rem Every step writes to logs\github-builds.log so Claude can see what happened.
rem   1. installs the GitHub CLI if it is missing (winget) and signs you in to GitHub in the browser if needed;
rem   2. asks GitHub for the permissions the builds need (workflow, write:packages, admin:org): click Authorize;
rem   3. turns on Actions, pushes the workflow files, starts the image build and the launcher tag;
rem   4. opens the pages GitHub has no API for (package visibility: Public) and prints the checklist.
rem Never run by Autopilot: the sign-in needs you in the browser.
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=%~dp0logs\github-builds.log"
>>"%LOG%" echo %date% %time% bat started
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  >>"%LOG%" echo %date% %time% STOPPED: Python 3 not found
  echo Python 3 is needed: https://www.python.org/downloads/
  pause & exit /b 1
)
where git >nul 2>&1 || (
  >>"%LOG%" echo %date% %time% STOPPED: git not found
  echo Git is needed: https://git-scm.com/download/win
  pause & exit /b 1
)
where gh >nul 2>&1 || (
  >>"%LOG%" echo %date% %time% gh missing: installing with winget
  echo Installing the GitHub CLI...
  winget install --id GitHub.cli -e --accept-source-agreements --accept-package-agreements >>"%LOG%" 2>&1
  set "PATH=%PATH%;%ProgramFiles%\GitHub CLI"
)
where gh >nul 2>&1 || if exist "%ProgramFiles%\GitHub CLI\gh.exe" set "PATH=%PATH%;%ProgramFiles%\GitHub CLI"
where gh >nul 2>&1 || (
  >>"%LOG%" echo %date% %time% STOPPED: gh still not found after winget
  echo The GitHub CLI didn't install. Install it from https://cli.github.com and run this again.
  pause & exit /b 1
)
gh auth status >nul 2>&1 || (
  >>"%LOG%" echo %date% %time% gh not signed in: opening the browser sign-in
  echo Sign in to GitHub in the browser window that opens ^(as orionopenwow^).
  gh auth login --web --git-protocol https --hostname github.com
)
gh auth status >>"%LOG%" 2>&1 || (
  >>"%LOG%" echo %date% %time% STOPPED: gh sign-in did not finish
  echo GitHub sign-in didn't finish. Run this again.
  pause & exit /b 1
)
>>"%LOG%" echo %date% %time% running github_builds.py
%PY% "%~dp0tools\github-builds\github_builds.py" %*
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo %date% %time% github_builds.py exited %RC%
echo.
pause
exit /b %RC%
