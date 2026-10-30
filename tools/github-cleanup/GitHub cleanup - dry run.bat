@echo off
setlocal
title GitHub cleanup - dry run
cd /d "%~dp0..\.."
py -3 tools\github-cleanup\gh_cleanup.py
exit /b %ERRORLEVEL%
