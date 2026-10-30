@echo off
setlocal EnableDelayedExpansion
title WrathUnleashed - how much server disk every part of the game needs
rem Measures, from YOUR 3.3.5a Data folder, how much disk each part of the game would take on the
rem stream server: the base (login, UI, player and item models), every tier of slices\mini.json
rem (Dalaran, the capitals, the starter areas...) and EVERY instance in the game's Map.dbc: all
rem classic, TBC and Wrath dungeons and raids, battlegrounds and arenas. Nothing is exported or
rem uploaded: it walks the files and adds up their sizes, lite (item textures cut down, as the
rem slice ships them) and full.
rem
rem Every place is counted beyond the base (what it adds on top of it, alone). Places share files
rem with each other too, so the report also gives the total of everything together.
rem
rem   1 asks the server which creatures and objects are spawned on every instance map (one SSH
rem     connection; without it, creature and object models are not counted and it says so)
rem   2 wenilla-host --size-report walks and measures (a few minutes)
rem   3 writes "size report\size-report.md" (a sorted table) and "size-report.json", and opens the table
rem
rem   "Size report.bat"                        your Data folder below
rem   "Size report.bat" "D:\WoW 3.3.5a\Data"   another Data folder
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "SSH=ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 -o ConnectTimeout=20 %HOST%"
set "DATA=%~1"
if "%DATA%"=="" set "DATA=C:\Users\campw\Downloads\World of Warcraft 3.3.5a\Data"
set "HOSTEXE=%~dp0bin\wenilla-host.exe"
set "W=%~dp0work"
set "OUT=%~dp0size report"

if not exist "%DATA%\common.MPQ" if not exist "%DATA%\common-2.MPQ" (echo "%DATA%" is not a 3.3.5a Data folder. & pause & exit /b 1)
if not exist "%HOSTEXE%" (echo bin\wenilla-host.exe is missing. & pause & exit /b 1)
if not exist "%W%" mkdir "%W%"
echo Data folder: %DATA%

echo [1/3] Asking the server what is spawned on every instance map (one SSH connection)...
if exist "%W%\sr" rmdir /s /q "%W%\sr"
mkdir "%W%\sr"
copy /y server\displays.py "%W%\sr\" >nul
copy /y slices\mini.json "%W%\sr\" >nul
set "DISPLAYS="
tar -cf - -C "%W%\sr" displays.py mini.json | %SSH% "d=$(mktemp -d) && tar -xf - -C $d && python3 -I $d/displays.py $d/mini.json --instances; rc=$?; rm -rf $d; exit $rc" > "%W%\displays-all.tsv"
if errorlevel 1 (
  echo        The server did not answer: creature and object models are NOT counted this time.
) else (
  set "DISPLAYS=--displays "%W%\displays-all.tsv""
  for /f %%n in ('find /c /v "" ^< "%W%\displays-all.tsv"') do echo        %%n creature and object displays
)

echo [2/3] Measuring (wenilla-host --size-report, a few minutes)...
set "BOOT="
for %%m in (boot-manifest.json world-manifest.json) do if exist "slices\%%m" set "BOOT=!BOOT! --boot "slices\%%m""
"%HOSTEXE%" --data "%DATA%" --size-report slices\mini.json !DISPLAYS! !BOOT! --out "%OUT%" > "%W%\size-report.log" || (type "%W%\size-report.log" & goto fail)

echo [3/3] Done.
echo        %OUT%\size-report.md   (the table, biggest first)
echo        %OUT%\size-report.json (the same numbers for scripts)
start "" notepad "%OUT%\size-report.md"
pause
exit /b 0
:fail
echo.
echo The measurement failed (see above). Nothing was changed anywhere.
pause
exit /b 1
