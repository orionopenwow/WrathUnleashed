@echo off
rem Read only: shows which step of the newest wu-images / launcher build failed, and its last log lines.
rem Also kept in logs\github-builds.log.
setlocal
cd /d "%~dp0..\.."
set PY=py -3
where py >nul 2>&1 || set PY=python
%PY% "tools\github-builds\github_builds.py" --why
exit /b %errorlevel%
