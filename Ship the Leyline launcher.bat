@echo off
setlocal
title Ship the Leyline launcher
rem The owner's one double-click to release the Leyline launcher (installers for Windows, macOS, Linux, and
rem the self-update feed). It runs, in order, and stops at the first failure:
rem   1. Turn on launcher updates.bat  - the update signing key (made once, kept in GitHub secrets, never shown;
rem                                     later runs keep the same key)
rem   2. Ship WrathUnleashed.bat       - saves the launcher (with the public key) to GitHub, hands-free
rem   3. Update Leyline repo.bat       - copies the launcher into the public orionopenwow/Leyline repo
rem   4. Turn on GitHub builds.bat     - installs the workflows and pushes the launcher-v<version> tag, which
rem                                     builds the installers and the release on GitHub (about 20-40 minutes)
rem Each step's window text stays visible; press a key when a step says "Press any key".
cd /d "%~dp0"
if not exist logs mkdir logs
set "LOG=%~dp0logs\ship-launcher.log"
>>"%LOG%" echo %date% %time% started

echo [1/4] Launcher update key
call "%~dp0Turn on launcher updates.bat"
if errorlevel 1 goto fail

echo [2/4] Saving to GitHub
set "WU_SHIP_AUTO=1"
set "WU_SHIP_MSG=Leyline launcher release: update key and the latest launcher"
call "%~dp0Ship WrathUnleashed.bat"
set "R=%ERRORLEVEL%"
set "WU_SHIP_AUTO="
if "%R%"=="1" goto fail

echo [3/4] Public Leyline repo
call "%~dp0tools\leyline-repo\Update Leyline repo.bat"
if errorlevel 1 goto fail

echo [4/4] GitHub builds and the launcher release tag
call "%~dp0Turn on GitHub builds.bat"
if errorlevel 1 goto fail

>>"%LOG%" echo %date% %time% done
echo.
echo DONE. The release builds on GitHub now: https://github.com/orionopenwow/Leyline/actions
echo When it is green, the installers are on https://github.com/orionopenwow/Leyline/releases
pause
exit /b 0

:fail
>>"%LOG%" echo %date% %time% STOPPED at a failed step
echo.
echo Stopped: a step above failed. Nothing after it ran. Tell Claude (logs\ship-launcher.log).
pause
exit /b 1
