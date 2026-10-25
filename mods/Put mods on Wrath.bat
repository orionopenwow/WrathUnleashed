@echo off
setlocal
title WrathUnleashed - put the mods catalog on Wrath
rem Every mod in mods\catalog goes live in one step:
rem   - checked and packed (wu-mod.py catalog): one bad mod and nothing changes,
rem   - the realm halves into the realm's lua_scripts\mods\<id>\ with a live "reload ale" (nobody is kicked;
rem     a refused reload or a Lua error puts the previous scripts back),
rem   - the addon halves into the streamed browser client (like Forever UI), with the in-game mod list
rem     (Esc ^> Mods ^& Workshop ^> Workshop),
rem   - catalog.json, the zips and screenshots onto the site: play.openvanilla.app/wrath/mods
rem Backs up first. ONE SSH connection (the server pauses SSH after many logins).
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
set "KIT=%~dp0..\stream\server"
if not exist "%~dp0catalog" (echo The catalog folder is missing next to this file. & goto fail)
if not exist "%~dp0wu-mod.py" (echo wu-mod.py is missing next to this file. & goto fail)
for %%f in (mods-install.sh mods-overlay.py) do if not exist "%KIT%\%%f" (echo ..\stream\server\%%f is missing. & goto fail)
if not exist "%KEY%" (echo SSH key %KEY% not found. & goto fail)

rem 1. A quick check here first when Python is installed (the server checks again before it changes anything).
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY where python >nul 2>nul && set "PY=python"
if defined PY (
  echo Checking the catalog...
  %PY% "%~dp0wu-mod.py" catalog "%~dp0catalog" -o "%TEMP%\wu-mods-catalog.json" --dist "%TEMP%\wu-mods-dist" || (echo A mod in the catalog does not pass the checks: see above. Nothing was sent. & goto fail)
)

rem 2. The catalog and the server scripts, as one tar on stdin.
set "STG=%TEMP%\wu-mods-up"
if exist "%STG%" rmdir /s /q "%STG%"
mkdir "%STG%\kit" "%STG%\catalog"
copy /y "%~dp0wu-mod.py" "%STG%\kit\" >nul || goto fail
copy /y "%KIT%\mods-install.sh" "%STG%\kit\" >nul || goto fail
copy /y "%KIT%\mods-overlay.py" "%STG%\kit\" >nul || goto fail
xcopy /e /i /y /q "%~dp0catalog" "%STG%\catalog\" >nul || goto fail
echo Uploading the catalog (one connection)...
tar -cf - -C "%STG%" kit catalog | ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 %HOST% "U=$(mktemp -d /tmp/wu-mods.XXXXXX) && tar -x -C $U -f - --no-same-owner && sed -i 's/\r$//' $U/kit/mods-install.sh && bash $U/kit/mods-install.sh install $U 2>&1 | tee /tmp/wu-mods.log; rm -rf $U; grep -q '^MODS OK' /tmp/wu-mods.log"
if errorlevel 1 (echo. & echo It did not report success; see above. Anything it changed was put back. & goto fail)
rmdir /s /q "%STG%"
echo.
echo Done: the mods are live. See them at https://play.openvanilla.app/wrath/mods
echo In the game: Esc ^> Mods ^& Workshop ^> Workshop (players reload the page to get new addons).
pause
exit /b 0

:fail
if exist "%TEMP%\wu-mods-up" rmdir /s /q "%TEMP%\wu-mods-up"
echo.
echo The mods were not put on Wrath. If it says "Connection timed out", the server is pausing SSH after
echo many quick logins: wait 2 minutes, then run this again.
pause
exit /b 1
