@echo off
rem Test build with the nameplate API for addons (C_NamePlate, nameplateN, NAME_PLATE_UNIT_ADDED/REMOVED):
rem same page and Data, served from dist-nameplates instead of dist. Close the regular
rem "Play 3.3.5a in browser" window first (same port).
cd /d "%~dp0"
if not exist "dist-nameplates.tgz" copy /b "dist-nameplates.tgz.part00"+"dist-nameplates.tgz.part01" "dist-nameplates.tgz" >nul
if not exist "dist-nameplates\wenilla_bg.wasm" (
  echo Unpacking the test build...
  tar -xzf dist-nameplates.tgz || (echo Unpacking failed. & pause & exit /b 1)
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8090/"
wenilla-host.exe --www dist-nameplates --data "C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
pause
