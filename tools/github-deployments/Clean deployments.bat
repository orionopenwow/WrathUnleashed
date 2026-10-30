@echo off
setlocal
title Clean the GitHub deployment history
rem Run this yourself (never by Autopilot). First it lists how many deployment records each Leyline repo has
rem (Leyline-Launcher, WrathUnleashed, Leyline). Then, if you agree, it deletes them: type YES when asked.
rem Records are only history: sites, releases and packages are not touched.
rem   Clean deployments.bat               list only
rem   Clean deployments.bat delete        delete all of them (asks YES first)
rem   Clean deployments.bat keep          delete all but the newest of each kind (asks YES first)
cd /d "%~dp0..\.."
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & pause & exit /b 1)
where gh >nul 2>&1 || (echo The GitHub CLI is needed: winget install GitHub.cli ^(then: gh auth login^) & pause & exit /b 1)
set "ARGS="
if /i "%~1"=="delete" set "ARGS=--delete"
if /i "%~1"=="keep" set "ARGS=--delete --keep-latest"
if not "%~1"=="" goto run
%PY% "tools\github-deployments\clean_deployments.py"
echo.
set "GO="
set /p "GO=Delete ALL of these records now? Type YES to continue, anything else to stop: "
if not "%GO%"=="YES" (echo Nothing deleted. & pause & exit /b 0)
set "ARGS=--delete --yes"
:run
%PY% "tools\github-deployments\clean_deployments.py" %ARGS%
pause
