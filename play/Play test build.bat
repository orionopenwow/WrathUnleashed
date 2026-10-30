@echo off
rem Newest test build (20261029a): quick key taps send their start/stop, frames keep coming in a visible but unpainted pane, AllowAttributeChanges, partyBackgroundOpacity, a warning for WMOs with missing group files.
rem Same page and Data, served from dist-test. Close the regular "Play 3.3.5a in browser" window first.
cd /d "%~dp0"
if exist "dist-test" if not exist "dist-test.stamp-20261029a" rmdir /s /q dist-test
if exist "dist-test.tgz" if not exist "dist-test.stamp-20261029a" del dist-test.tgz
if not exist "dist-test.tgz" copy /b "dist-test.tgz.part00"+"dist-test.tgz.part01"+"dist-test.tgz.part02" "dist-test.tgz" >nul
if not exist "dist-test\wenilla_bg.wasm" (
  echo Unpacking the test build...
  tar -xzf dist-test.tgz || (echo Unpacking failed. & pause & exit /b 1)
  echo.> dist-test.stamp-20261029a
)
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8090/"
wenilla-host.exe --www dist-test --data "C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
pause
