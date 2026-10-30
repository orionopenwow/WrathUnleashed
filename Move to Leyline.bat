@echo off
setlocal EnableDelayedExpansion
title Move to Leyline (one time)
rem One double-click, once, by the owner (never by Autopilot). Makes ONE folder, Desktop\Leyline:
rem   Desktop\WrathUnleashed  -> Desktop\Leyline                          (this workspace: Autopilot, every step)
rem   Desktop\Leyline         -> Desktop\Leyline\.repos\leyline-public    (the public repo's copy, "leyline" step)
rem   Desktop\OpenVanilla     -> Desktop\Leyline\.repos\leyline-launcher  (the Leyline-Launcher clone, ovland/ovrename)
rem and renames the private GitHub repo WrathUnleashed to leyline-workspace (the old address redirects).
rem First a dry run that changes nothing and shows the plan; then type YES. It refuses while steps are waiting
rem or running, or when the GitHub CLI is not signed in as orionopenwow. If a folder is in use it tries again,
rem and if it still can't, it puts back what it moved (log: %TEMP%\leyline-move.log).
rem How: tools\workspace-move\move_to_leyline.py, run from a copy in %TEMP% (a folder can't be renamed while this
rem window stands in it).
if /i "%~1"=="--staged" goto :staged

set "WS=%~dp0"
set "WS=%WS:~0,-1%"
set "STAGE=%TEMP%\leyline-move"
if not exist "%WS%\tools\workspace-move\move_to_leyline.py" (echo tools\workspace-move\move_to_leyline.py is missing. Ask Claude. & pause & exit /b 1)
if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%" || (echo Could not make %STAGE%. & pause & exit /b 1)
copy /y "%~f0" "%STAGE%\Move to Leyline.bat" >nul || (echo Could not copy this file to %STAGE%. & pause & exit /b 1)
copy /y "%WS%\tools\workspace-move\move_to_leyline.py" "%STAGE%\" >nul || (echo Could not copy the helper. & pause & exit /b 1)
cd /d "%USERPROFILE%"
rem No "call": the copy takes over, and this file is never read again (its folder is about to move).
"%STAGE%\Move to Leyline.bat" --staged "%WS%"

:staged
set "WS=%~2"
cd /d "%USERPROFILE%"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (echo Python 3 is needed: https://www.python.org/downloads/ & pause & exit /b 1)
if exist "%~dp0new-root.txt" del "%~dp0new-root.txt"

echo ===== The plan (dry run: nothing changes) =====
%PY% "%~dp0move_to_leyline.py" --root "%WS%"
if errorlevel 1 (echo. & echo Nothing was changed. & pause & exit /b 1)
echo.
set "OK="
set /p OK=Type YES to do it (anything else cancels):
if not "!OK!"=="YES" (echo Cancelled. Nothing was changed. & pause & exit /b 0)

echo.
echo ===== Moving =====
%PY% "%~dp0move_to_leyline.py" --root "%WS%" --go
if errorlevel 1 (echo. & echo Stopped: see above and %TEMP%\leyline-move.log. & pause & exit /b 1)

set "NEW="
if exist "%~dp0new-root.txt" set /p NEW=<"%~dp0new-root.txt"
if not defined NEW (echo Done, but the new folder is unknown: open Desktop\Leyline and double-click "Leyline Control.bat". & pause & exit /b 0)
echo.
echo Starting the control window from !NEW! ...
cd /d "!NEW!"
start "Leyline Control" /min cmd /c ""!NEW!\Leyline Control.bat""
start "" explorer "!NEW!"
echo.
echo Next, in the Claude desktop app: add the folder !NEW! (and remove the old WrathUnleashed one),
echo then tell Claude "moved to Leyline".
pause
exit /b 0
