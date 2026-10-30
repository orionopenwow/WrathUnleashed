@echo off
setlocal EnableDelayedExpansion
title WrathUnleashed - browser client
rem Plays WrathUnleashed in your browser with YOUR OWN WoW 3.3.5a game files. Nothing is
rem downloaded: this window serves the game page and your own files to your browser on this PC
rem only (127.0.0.1), and connects you to the realm. Close this window to stop.
cd /d "%~dp0"
set "REALM=play.openvanilla.app"

if exist wow-folder.txt set /p WOW=<wow-folder.txt
if not exist "!WOW!\Data\common.MPQ" (
  echo Where is your 3.3.5a game folder? ^(the one with Wow.exe and Data^)
  set /p WOW=Folder: 
  set "WOW=!WOW:"=!"
  if not exist "!WOW!\Data\common.MPQ" (echo That folder has no Data\common.MPQ. & pause & exit /b 1)
  >wow-folder.txt echo !WOW!
)

rem Our own addons (Armory window, QoL), installed once into your AddOns folder.
if exist addons\ (
  if not exist "!WOW!\Interface\AddOns" mkdir "!WOW!\Interface\AddOns"
  xcopy /e /i /y /q addons\* "!WOW!\Interface\AddOns\" >nul
)

set "URL=http://127.0.0.1:8090/?farclip=777&anisotropic=16&trilinear=1&gxmultisample=4&worlddetail=2&moderncombos=1"
echo Starting the page host (keep this window open)...
rem Opens Chrome (or Edge) after the host is up; WebGPU is needed.
start "" powershell -NoProfile -WindowStyle Hidden -Command "Start-Sleep 3; try { Start-Process chrome '%URL%' -ErrorAction Stop } catch { try { Start-Process msedge '%URL%' -ErrorAction Stop } catch { Start-Process '%URL%' } }"
wenilla-host.exe --www dist --data "!WOW!\Data" --upstream %REALM%
pause
