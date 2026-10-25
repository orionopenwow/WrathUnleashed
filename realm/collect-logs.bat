@echo off
rem Collect the realm containers' logs into logs.txt (for debugging).
cd /d "%~dp0"
(docker compose ps -a & echo ===== database & docker logs --tail 80 ov-ac-database & echo ===== db-import & docker compose logs --tail 120 ac-db-import & echo ===== worldserver & docker logs --tail 60 ov-ac-worldserver & echo ===== authserver & docker logs --tail 30 ov-ac-authserver) > logs.txt 2>&1
echo Wrote logs.txt
