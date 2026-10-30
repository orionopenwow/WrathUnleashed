@echo off
rem Test build with the smooth-frames changes (..\SMOOTH-FRAMES.md): same page and Data, served from
rem dist-smooth instead of dist. Close the regular "Play 3.3.5a in browser" window first (same port).
cd /d "%~dp0"
if not exist "dist-smooth.tgz" if exist "dist-smooth.tgz.part00" copy /b "dist-smooth.tgz.part00"+"dist-smooth.tgz.part01" "dist-smooth.tgz" >nul
if not exist "dist-smooth\wenilla_bg.wasm" (
  echo Unpacking the test build...
  tar -xzf dist-smooth.tgz || (echo Unpacking failed. & pause & exit /b 1)
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8090/"
wenilla-host.exe --www dist-smooth --data "C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
pause
