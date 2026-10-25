@echo off
setlocal EnableDelayedExpansion
title WrathUnleashed - UPDATE (everything Claude has ready)
rem The one thing to run. Claude writes what's ready into UPDATES-PENDING.txt (one step per line);
rem this runs them in order, skips the ones already done (UPDATES-DONE.txt), and stops at the first
rem failure with the step's own message. Safe to run again any time: nothing pending = nothing happens.
rem
rem   UPDATES-PENDING.txt line:   <id> <step> [note...]      e.g.   1024c client  new browser client
rem   steps:  client   stream\Update browser client.bat        (new browser game build)
rem           signin   stream\Update sign-in and warm-up.bat   (the Play page / sign-in)
rem           scripts  realm\Server pass - finder 10 and bug reports.bat   (realm Lua, reload, no restart)
rem           realm    realm\Server pass - finder 10 and bug reports.bat   (same, when settings changed: 5-min restart)
rem           foreverui stream\Add Forever UI to the stream.bat (menus, character select look)
rem           slice    stream\Make mini slice.bat              (streamed game files: 30-60 min)
rem           mods     mods\Put mods on Wrath.bat           (the mods catalog: realm, streamed addons, /wrath/mods)
rem           ship     Ship WrathUnleashed.bat                 (save everything to GitHub: asks you to type yes)
rem           leyline  tools\leyline-repo\Update Leyline repo.bat   (public Leyline copy; also runs after every ship)
cd /d "%~dp0"
set "PEND=UPDATES-PENDING.txt"
set "DONE=UPDATES-DONE.txt"
if not exist logs mkdir logs
if not exist "%PEND%" (echo Nothing is pending. You're up to date. & pause & exit /b 0)
if not exist "%DONE%" type nul > "%DONE%"

echo Ready to run:
set N=0
for /f "usebackq tokens=1,2,* eol=#" %%a in ("%PEND%") do (
  findstr /x /c:"%%a" "%DONE%" >nul 2>&1
  if errorlevel 1 (
    set /a N+=1
    echo   !N!. %%b  - %%c
  )
)
if "!N!"=="0" (echo   nothing new. You're up to date. & pause & exit /b 0)
echo.
echo Press any key to run them in this order (close the window to cancel).
pause >nul

for /f "usebackq tokens=1,2,* eol=#" %%a in ("%PEND%") do (
  findstr /x /c:"%%a" "%DONE%" >nul 2>&1
  if errorlevel 1 (
    call :run %%a %%b
    if errorlevel 1 goto :failed
  )
)
echo.
echo ===== ALL DONE. Tell Claude "updated" and it will test the live game. =====
pause
exit /b 0

:run
set "ID=%~1"
set "STEP=%~2"
echo.
echo ===== %STEP% (%ID%) =====
set "BAT="
set "ARGS="
set "INTERACTIVE="
if /i "%STEP%"=="client"  set "BAT=stream\Update browser client.bat"
if /i "%STEP%"=="signin"  set "BAT=stream\Update sign-in and warm-up.bat"
if /i "%STEP%"=="scripts" set "BAT=realm\Server pass - finder 10 and bug reports.bat"
if /i "%STEP%"=="realm"   set "BAT=realm\Server pass - finder 10 and bug reports.bat"
if /i "%STEP%"=="gm"      set "BAT=gmconsole\Install GM Console.bat"
if /i "%STEP%"=="lean"    set "BAT=realm\Lean server.bat"
if /i "%STEP%"=="relay"   set "BAT=hosting\relay\Deploy relay.bat"
if /i "%STEP%"=="hangout" set "BAT=hosting\hangout\Deploy Dalaran hangout.bat"
if /i "%STEP%"=="hangout-off" set "BAT=hosting\hangout\Take Dalaran hangout off Leyline.bat"
if /i "%STEP%"=="foreverui" set "BAT=stream\Add Forever UI to the stream.bat"
if /i "%STEP%"=="mods"    set "BAT=mods\Put mods on Wrath.bat"
if /i "%STEP%"=="leyline" set "BAT=tools\leyline-repo\Update Leyline repo.bat"
if /i "%STEP%"=="slice"   (set "BAT=stream\Make mini slice.bat" & set "INTERACTIVE=1")
if /i "%STEP%"=="ship"    (set "BAT=Ship WrathUnleashed.bat" & set "INTERACTIVE=1")
if not defined BAT (echo Unknown step "%STEP%" in %PEND%. Ask Claude. & exit /b 1)
if not exist "%BAT%" (echo %BAT% is missing. Ask Claude. & exit /b 1)
set "LOG=logs\%ID%-%STEP%.log"
if defined INTERACTIVE (
  call "%BAT%" %ARGS%
) else (
  rem Input from nul: the step's own "press any key" doesn't stop the run.
  call "%BAT%" %ARGS% < nul
)
if errorlevel 1 (echo. & echo STEP FAILED: %STEP%. Send Claude a screenshot of this window. & exit /b 1)
>> "%DONE%" echo %ID%
cd /d "%~dp0"
rem Every save to GitHub also refreshes the public Leyline copy (owner 2026-10-25).
if /i "%STEP%"=="ship" (
  echo.
  echo ===== leyline ^(after ship %ID%^) =====
  call "tools\leyline-repo\Update Leyline repo.bat" < nul > "logs\%ID%-leyline.log" 2>&1
  if errorlevel 1 (echo Leyline copy failed: see logs\%ID%-leyline.log. Send it to Claude. & exit /b 1)
  type "logs\%ID%-leyline.log" | findstr /b /c:"LEYLINE OK"
  cd /d "%~dp0"
)
exit /b 0

:failed
echo.
echo Stopped. Steps after the failed one did not run. Run UPDATE.bat again after it's fixed:
echo finished steps are skipped.
pause
exit /b 1
