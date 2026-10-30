@echo off
rem Turn the local test realm into Wrath Brawl: level 80 starts in Dalaran with all class spells,
rem riding, exalted reputations, flight paths and gold; vendor items are free; every profession, free dual spec, bags, class kits, two mounts.
rem Characters made before this keep their level. Safe to run again.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_world < brawl_world.sql || (echo The SQL did not apply. Is the realm running? & pause & exit /b 1)
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_world < brawl_world_2.sql || (echo Round two did not apply. & pause & exit /b 1)
rem Modern race and class pairs: only does anything on the custom image (mod-arac adds the rest).
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_world < modern_combos.sql
echo World database updated. Restarting the world server with the Brawl settings...
docker compose up -d ac-worldserver
echo.
echo Done. Make a new character: it starts at 80 in Dalaran.
pause
