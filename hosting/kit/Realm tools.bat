@echo off
setlocal
title Leyline - realm tools
rem Small jobs for a hosted realm. "Realm tools.bat friend NAME [PASSWORD]" etc. also work without the menu.
cd /d "%~dp0"
docker version >nul 2>&1 || (echo Docker Desktop is not running. & pause & exit /b 1)
if not exist "state\host.json" (echo Run "Host a Wrath realm.bat" first. & pause & exit /b 1)
set "T=docker run --rm -v "%~dp0.:/kit" -e WU_KIT=/kit wu-host-tools:1 python -m wuhost.setup"
set "C=%~1"
if not "%C%"=="" goto %C% 2>nul || (echo Unknown command %C%. & exit /b 1)
echo   1  show       invite link, your login, relay status
echo   2  friend     make a game account for a friend
echo   3  newinvite  make a new invite link (the old one stops working)
echo   4  public     list the realm in Beacons
echo   5  private    friends with the link only
echo   6  claim      link the realm to your Hero Key account (token from openvanilla.app)
echo   7  signup     who may make accounts on the join page (invite / open / off)
echo   8  logs       the last lines of every server's log
echo   9  rules      after editing state\rules.txt or state\beacon.json: update the realm list text
echo  10  browser    browser players on / off (on = Warden off, so the browser client can join)
echo  11  maxplayers the most players at once (the server's cap and the realm list's)
set /p "N=Pick 1-11: "
for %%P in ("1 show" "2 friend" "3 newinvite" "4 public" "5 private" "6 claim" "7 signup" "8 logs" "9 rules" "10 browser" "11 maxplayers") do for /f "tokens=1,2" %%A in (%%P) do if "%N%"=="%%A" goto %%B
echo Nothing picked. & pause & exit /b 0

:show
%T% show
pause & exit /b 0
:friend
set "U=%~2" & set "P=%~3"
if "%U%"=="" set /p "U=Your friend's account name (letters/digits): "
%T% friend %U% %P% | docker exec -i wu-host-database sh -c "MYSQL_PWD=\"$MYSQL_ROOT_PASSWORD\" exec mysql -uroot acore_auth" && echo Done. Your friend opens your invite link once, then logs in with that account.
pause & exit /b 0
:newinvite
%T% new-invite
echo That is your new invite link. The old one no longer lets anyone new in.
pause & exit /b 0
:public
%T% visibility public
echo Now public: on the realm list within a minute.
pause & exit /b 0
:private
%T% visibility private
pause & exit /b 0
:claim
set "K=%~2"
if "%K%"=="" set /p "K=Claim token from openvanilla.app: "
%T% claim %K% && echo Done. The site sees the token on your realm's status page within a minute.
pause & exit /b 0
:signup
set "M=%~2"
if "%M%"=="" set /p "M=invite / open / off: "
%T% signup %M%
pause & exit /b 0
:browser
set "M=%~2"
if "%M%"=="" set /p "M=Browser players on / off: "
%T% browser %M%
pause & exit /b 0
:maxplayers
set "M=%~2"
if "%M%"=="" set /p "M=Most players at once (0 = the ruleset's own): "
%T% listing --max-players %M%
pause & exit /b 0
:rules
%T% rules && echo Done. The realm list and your join page show it within a minute ^(public realms^).
pause & exit /b 0
:logs
call "%~dp0profiles\pick-compose.bat"
docker compose -f "%CF%" --project-directory "%~dp0." logs --tail 80
pause & exit /b 0
