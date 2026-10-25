@echo off
title WrathUnleashed Control
rem Opens the control window (http://127.0.0.1:8098 on this PC only). Close this window to stop it.
rem Any older copy still holding the port is closed first, so the newest version always runs.
cd /d "%~dp0"
for /f "tokens=5" %%p in ('netstat -ano ^| findstr /r /c:"127.0.0.1:8098 .*LISTENING"') do taskkill /f /pid %%p >nul 2>&1
where py >nul 2>&1 && (py -3 tools\control\control.py & goto :eof)
where python >nul 2>&1 && (python tools\control\control.py & goto :eof)
echo Python 3 is needed: https://www.python.org/downloads/
pause
