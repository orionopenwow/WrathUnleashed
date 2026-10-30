@echo off
rem Turn the local test realm into the WrathUnleashed MAIN realm: a normal game from level 1, and every new
rem character may take a one-time boost to 80 with a spec kit (custom\lua_scripts\ov_main.lua). Puts back the
rem stock world rows Brawl changed (main_unbrawl.sql; nothing happens if this database never ran Brawl), adds
rem the boost menu's texts (main_world.sql), keeps the modern race/class pairs, and switches the profile to main.
rem Characters made before this keep what they have. Safe to run again. Needs the custom realm image (mod-ale).
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_world < main_unbrawl.sql || (echo The SQL did not apply. Is the realm running? & pause & exit /b 1)
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_world < main_world.sql || (echo main_world.sql did not apply. & pause & exit /b 1)
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_world < modern_combos.sql
powershell -NoProfile -ExecutionPolicy Bypass -File custom\setenv.ps1 OV_PROFILE main
echo World database updated. Restarting the world server with the main settings...
docker compose up -d ac-worldserver
echo.
echo Done. Make a new character: on its first login it asks "level 1" or "boost to 80".
pause
