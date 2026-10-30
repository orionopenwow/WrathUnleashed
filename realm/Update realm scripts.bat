@echo off
setlocal
title WrathUnleashed - update realm scripts (live)
rem Sends the realm Lua scripts listed below from custom\lua_scripts to the server and reloads them live:
rem no restart, nobody is disconnected. Backs up the old files; a refused reload puts them back. One SSH login.
rem   Update realm scripts.bat [file.lua ...]     (default: ov_main.lua)
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "FILES=%*"
if "%FILES%"=="" set "FILES=ov_main.lua"
if not exist luaup.sh (echo luaup.sh is missing next to this file. & pause & exit /b 1)
for %%f in (%FILES%) do if not exist "custom\lua_scripts\%%~f" (echo custom\lua_scripts\%%~f is missing. & pause & exit /b 1)
set "T=%TEMP%\wu-lua"
if exist "%T%" rmdir /s /q "%T%"
mkdir "%T%"
for %%f in (%FILES%) do copy /y "custom\lua_scripts\%%~f" "%T%\" >nul
copy /y luaup.sh "%T%\" >nul
tar -cf "%TEMP%\wu-lua.tar" -C "%T%" . || (echo Packing failed. & pause & exit /b 1)
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new root@play.openvanilla.app "T=$(mktemp -d) && tar -x -C $T -f - && sed -i 's/\r$//' $T/luaup.sh && rm -f $T/luaup.sh.lua && (cd $T && tar -cf - *.lua) | bash $T/luaup.sh 2>&1 | tee /tmp/wu-luaup.log; rm -rf $T; grep -q '^LUAUP OK' /tmp/wu-luaup.log" < "%TEMP%\wu-lua.tar"
if errorlevel 1 (echo. & echo It did not report success; see above. & del /q "%TEMP%\wu-lua.tar" & rmdir /s /q "%T%" & pause & exit /b 1)
del /q "%TEMP%\wu-lua.tar" & rmdir /s /q "%T%"
echo.
echo Done: the scripts are live.
pause
exit /b 0
