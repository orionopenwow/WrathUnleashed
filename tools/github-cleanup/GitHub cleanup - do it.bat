@echo off
setlocal
title GitHub cleanup - do it
cd /d "%~dp0..\.."
py -3 tools\github-cleanup\gh_cleanup.py --go
exit /b %ERRORLEVEL%
