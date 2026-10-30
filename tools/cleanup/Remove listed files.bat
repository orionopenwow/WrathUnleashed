@echo off
rem Removes the files listed in tools\cleanup\REMOVE.txt (tracked repo files only), for the next ship to record.
setlocal
cd /d "%~dp0..\.."
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed. & exit /b 1)
%PY% "tools\cleanup\remove_listed.py"
exit /b %errorlevel%
