@echo off
setlocal
title Turn on launcher updates (one time)
rem The owner's one double-click so Leyline can update itself. Safe to run again.
rem   1. makes the updater's signing key pair on this PC (Tauri CLI through npx, in a throwaway folder);
rem   2. stores the private key and its password as GitHub Actions secrets of orionopenwow/Leyline with gh
rem      (fed on stdin: never shown, never saved in the repo), then wipes the throwaway folder;
rem   3. writes only the PUBLIC key into launcher\src-tauri\tauri.conf.json for the next Ship.
rem Then: Ship to GitHub, then the Leyline step, then "setup\Turn on GitHub builds.bat" (it pushes the launcher-v tag).
rem ("Ship the Leyline launcher.bat" at the top of the workspace does all of that in one go.)
rem Running it again does not make a new key. Never run by Autopilot: gh may need you in the browser.
rem Every run writes to logs\launcher-updates.log (no keys in it).
rem In setup\ since 2026-10-30: everything below runs from the workspace folder one level up.
cd /d "%~dp0.."
set "ROOT=%CD%"
if not exist logs mkdir logs
set "LOG=%ROOT%\logs\launcher-updates.log"
>>"%LOG%" echo %date% %time% bat started
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  >>"%LOG%" echo %date% %time% STOPPED: Python 3 not found
  echo Python 3 is needed: https://www.python.org/downloads/
  pause & exit /b 1
)
where gh >nul 2>&1 || (
  >>"%LOG%" echo %date% %time% STOPPED: gh not found
  echo The GitHub CLI is needed: winget install GitHub.cli   then: gh auth login
  pause & exit /b 1
)
where npx >nul 2>&1 || (
  >>"%LOG%" echo %date% %time% STOPPED: npx not found
  echo Node.js is needed for the Tauri CLI: https://nodejs.org ^(LTS^)
  pause & exit /b 1
)
%PY% "%ROOT%\tools\launcher-updates\launcher_updates.py" %*
set "RC=%ERRORLEVEL%"
>>"%LOG%" echo %date% %time% finished with code %RC%
pause
exit /b %RC%
