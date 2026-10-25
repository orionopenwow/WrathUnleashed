@echo off
rem Make a login (GM level 3) on the local test realm. Usage: add-account.bat NAME PASSWORD
cd /d "%~dp0"
set U=%1
set P=%2
if "%U%"=="" set /p U=Account name: 
if "%P%"=="" set /p P=Password: 
docker run --rm -v "%~dp0:/w:ro" python:3.12-alpine python /w/make_account.py %U% %P% > "%TEMP%\ov-account.sql" || (pause & exit /b 1)
docker exec -i ov-ac-database mysql -uroot -pov-local-test acore_auth < "%TEMP%\ov-account.sql" && echo Account %U% created.
del "%TEMP%\ov-account.sql"
pause
