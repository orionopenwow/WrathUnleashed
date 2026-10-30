@echo off
rem Open Vanilla private test: the 3.3.5a browser client (benilla-wotlk web port) on your own install.
rem Serves the page and your Data folder on this PC only (127.0.0.1). Close this window to stop.
cd /d "%~dp0"
start "" cmd /c "timeout /t 3 >nul & start http://127.0.0.1:8090/"
wenilla-host.exe --www dist --data "C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
pause
