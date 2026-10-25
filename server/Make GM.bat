@echo off
rem Gives an existing account GM level 3 on play.openvanilla.app (your own account only).
rem Usage: Make GM.bat ACCOUNTNAME
cd /d "%~dp0"
set "U=%1"
if "%U%"=="" set /p U=Account name: 
echo %U%| findstr /r "^[A-Za-z0-9][A-Za-z0-9]*$" >nul || (echo Letters and digits only. & pause & exit /b 1)
echo REPLACE INTO account_access (id, gmlevel, RealmID) SELECT id, 3, -1 FROM account WHERE username = UPPER('%U%'); SELECT a.username, x.gmlevel FROM account a JOIN account_access x ON x.id = a.id WHERE a.username = UPPER('%U%');| ssh -i "%USERPROFILE%\.ssh\openwow" root@play.openvanilla.app "docker exec -i ov-ac-database sh -c 'MYSQL_PWD=$MYSQL_ROOT_PASSWORD exec mysql -uroot acore_auth'"
pause
