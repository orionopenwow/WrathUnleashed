@echo off
rem Builds players\WrathUnleashed-Player.zip: the browser client, the page host, the player
rem launcher and our own addons. No game data goes in it. Share the zip with your testers.
cd /d "%~dp0"
if not exist "play\dist\wenilla_bg.wasm" (echo Run "Play WotLK (one click).bat" once first, so the client build is put together. & pause & exit /b 1)
set "OUT=%TEMP%\WrathUnleashed-Player"
if exist "%OUT%" rmdir /s /q "%OUT%"
mkdir "%OUT%\dist" "%OUT%\addons"
xcopy /e /i /y /q "play\dist\*" "%OUT%\dist\" >nul
del /q "%OUT%\dist\wasm.part.*" "%OUT%\dist\wenilla.js.new" 2>nul
copy /y "play\wenilla-host.exe" "%OUT%\" >nul
if exist "play\wenilla-host.new.exe" copy /y "play\wenilla-host.new.exe" "%OUT%\wenilla-host.exe" >nul
copy /y "players\Play WrathUnleashed.bat" "%OUT%\" >nul
copy /y "players\README.txt" "%OUT%\" >nul
xcopy /e /i /y /q "addons\OVArmory" "%OUT%\addons\OVArmory\" >nul
xcopy /e /i /y /q "addons\OVQoL" "%OUT%\addons\OVQoL\" >nul
del /q "%OUT%\addons\OVQoL\README.md" 2>nul
powershell -NoProfile -Command "Compress-Archive -Force -Path '%OUT%\*' -DestinationPath '%~dp0players\WrathUnleashed-Player.zip'" || (echo Zipping failed. & pause & exit /b 1)
rmdir /s /q "%OUT%"
echo Done: players\WrathUnleashed-Player.zip
pause
