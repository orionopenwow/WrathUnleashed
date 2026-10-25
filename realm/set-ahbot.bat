@echo off
setlocal
rem Gives the auction house bot (mod-ah-bot-plus) a character to sell and buy as, and turns it on.
rem Make a character for it first (any account, not a playerbot), e.g. "Auctioneer", then:
rem   set-ahbot.bat Auctioneer
cd /d "%~dp0"
if "%~1"=="" (echo Usage: set-ahbot.bat CHARACTERNAME & pause & exit /b 1)
set GUID=
for /f %%g in ('docker exec ov-ac-database mysql -uroot -pov-local-test -N -s -e "SELECT guid FROM acore_characters.characters WHERE name='%~1'" 2^>nul') do set GUID=%%g
if "%GUID%"=="" (echo No character named %~1. Is the realm running? & pause & exit /b 1)
(
  echo # Written by set-ahbot.bat: the auction bot sells and buys as %~1.
  echo AC_AUCTION_HOUSE_BOT_GUIDS=%GUID%
  echo AC_AUCTION_HOUSE_BOT_ENABLE_SELLER=true
  echo AC_AUCTION_HOUSE_BOT_BUYER_ENABLED=true
) > ahbot.env
docker compose up -d ac-worldserver
echo The auction bot now uses %~1 (guid %GUID%). Delete ahbot.env and restart to turn it off.
pause
