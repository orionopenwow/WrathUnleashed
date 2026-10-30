@echo off
rem Replaces the repo history with one Leyline commit (backup bundle on the Desktop first).
rem See tools\fresh-history\fresh_history.py for every step. Stops at the first problem.
setlocal
cd /d "%~dp0..\.."
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed. & exit /b 1)
%PY% "tools\fresh-history\fresh_history.py" --go
exit /b %errorlevel%
