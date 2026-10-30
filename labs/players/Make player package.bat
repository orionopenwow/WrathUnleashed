@echo off
rem Builds labs\players\WrathUnleashed-Player.zip: the browser client, the page host, the player
rem launcher and our own addons. No game data goes in it. Share the zip with your testers.
rem In labs\players\ since 2026-10-30 (superseded by the Leyline launcher); it works from the workspace folder.
cd /d "%~dp0..\.."
if not exist "play\dist\wenilla_bg.wasm" (echo Run "play\Play locally (one click).bat" once first, so the client build is put together. & pause & exit /b 1)
set "OUT=%TEMP%\WrathUnleashed-Player"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%\dist" "%OUT%\addons"
xcopy /e /i /y /q "play\dist\*" "%OUT%\dist\" >nul
del /q "%OUT%\dist\wasm.part.*" "%OUT%\dist\wenilla.js.new" 2>nul
copy /y "play\wenilla-host.exe" "%OUT%\" >nul
if exist "play\wenilla-host.new.exe" copy /y "play\wenilla-host.new.exe" "%OUT%\wenilla-host.exe" >nul
copy /y "labs\players\Play WrathUnleashed.bat" "%OUT%\" >nul
copy /y "labs\players\README.txt" "%OUT%\" >nul
xcopy /e /i /y /q "addons\OVArmory" "%OUT%\addons\OVArmory\" >nul
xcopy /e /i /y /q "addons\OVQoL" "%OUT%\addons\OVQoL\" >nul
del /q "%OUT%\addons\OVQoL\README.md" 2>nul
powershell -NoProfile -Command "Compress-Archive -Force -Path '%OUT%\*' -DestinationPath '%~dp0WrathUnleashed-Player.zip'" || (echo Zipping failed. & pause & exit /b 1)
rmdir /s /q "%OUT%"
echo Done: labs\players\WrathUnleashed-Player.zip
pause
