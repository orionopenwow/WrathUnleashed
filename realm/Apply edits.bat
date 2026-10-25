@echo off
rem Apply your realm edits without rebuilding anything.
rem   edits\world\*.sql       world database (NPCs, items, quests, vendors, spawns, start spells)
rem   edits\characters\*.sql  character database
rem   edits\auth\*.sql        account database
rem   profiles\*.env, modules.env   settings
rem   custom\lua_scripts\*.lua      server Lua (mod-ale, custom image)
rem Each .sql runs in name order, so prefix them 010-, 020-...; write them so they are safe to run
rem twice (DELETE ... then INSERT, or INSERT IGNORE / REPLACE). Then the world server restarts to
rem pick everything up (about a minute). Only C++ module changes need "Build custom realm.bat".
setlocal enabledelayedexpansion
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
set ok=1
for %%D in (world characters auth) do (
  if exist "edits\%%D\*.sql" (
    for /f "delims=" %%F in ('dir /b /on "edits\%%D\*.sql"') do (
      echo   acore_%%D  ^<  %%F
      docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_%%D < "edits\%%D\%%F" || set ok=0
    )
  )
)
if "!ok!"=="0" (echo. & echo One or more edits failed; the messages above say which. & pause & exit /b 1)
echo Restarting the world server with the edits and settings...
docker compose up -d ac-worldserver
docker compose restart ac-worldserver
echo.
echo Done. Lua-only change? In game, a GM can type .reload ale instead of restarting.
pause
