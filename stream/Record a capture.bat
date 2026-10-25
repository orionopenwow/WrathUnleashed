@echo off
setlocal
title WrathUnleashed - record what a place needs (accuracy check)
rem Runs the browser client locally from YOUR game files and writes down every game file it asks for
rem into record\names-<label>.txt, while you play on the live realm (play.openvanilla.app).
rem Visit the places of a tier (slices\mini.json has a capture list per tier), then close this window.
rem "Make mini slice.bat" adds every record\*.txt to the slice, so whatever the static walk missed
rem is included next time.
rem   "Record a capture.bat" dalaran
rem   "Record a capture.bat" naxx "D:\WoW 3.3.5a\Data"
rem Needs the browser client build in www\ (index.html, wenilla.js, wenilla_bg.wasm).
cd /d "%~dp0"
set "LABEL=%~1"
if "%LABEL%"=="" set "LABEL=capture"
set "DATA=%~2"
if "%DATA%"=="" set "DATA=C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
if not exist "www\index.html" (echo Put the browser client build in www\ first. & pause & exit /b 1)
if not exist record mkdir record
echo Recording into record\names-%LABEL%.txt. Your browser opens on http://127.0.0.1:8090/ :
echo log in with your Wrath account, go to the places, then close this window to stop.
start "" "http://127.0.0.1:8090/?host=play.openvanilla.app"
"%~dp0bin\wenilla-host.exe" --www www --data "%DATA%" --upstream play.openvanilla.app --record "record\names-%LABEL%.txt"
pause
