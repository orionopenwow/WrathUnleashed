@echo off
setlocal EnableDelayedExpansion
rem Installs the client side of the WotLK realm into your 3.3.5a client:
rem   1. GM window: AzerothAdmin (/aa) and MiniGM (/mgm)            - always
rem   2. Addon pack: Questie-335, Deadly Boss Mods, Details!, AtlasLoot, AdiBags, MultiBot
rem      (fetched from GitHub at pinned commits; needs Docker running)  - asks
rem   3. All-races-all-classes client patch (Patch-A.MPQ, from mod-arac) - asks
rem Usage: install-gm-addons.bat ["C:\path\to\World of Warcraft 3.3.5a"]
set "WOW=%~1"
if "%WOW%"=="" set "WOW=C:\Users\campw\Downloads\World of Warcraft 3.3.5a"
if not exist "%WOW%\Wow.exe" (
  echo Could not find Wow.exe in "%WOW%".
  echo Run it again with your client folder:  install-gm-addons.bat "D:\Games\WoW 3.3.5a"
  pause & exit /b 1
)
set "DEST=%WOW%\Interface\AddOns"
if not exist "%DEST%" mkdir "%DEST%"

echo [1/3] GM window
for %%A in (AzerothAdmin AzerothAdmin_Models MiniGM) do (
  robocopy "%~dp0%%A" "%DEST%\%%A" /MIR /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 (echo Copy of %%A failed. & pause & exit /b 1)
)

echo [2/3] Addon pack
choice /c YN /m "Install Questie, Deadly Boss Mods, Details!, AtlasLoot, AdiBags and MultiBot"
if errorlevel 2 goto patch
docker version >nul 2>&1 || (echo Docker Desktop is not running; skipping the addon pack. & goto patch)
docker run --rm --entrypoint sh -v "%~dp0:/w" alpine/git:latest /w/fetch-addons.sh || (echo Fetching the addon pack failed. & goto patch)
for /d %%A in ("%~dp0_pack\*") do (
  robocopy "%%A" "%DEST%\%%~nxA" /MIR /NFL /NDL /NJH /NJS /NP >nul
  if errorlevel 8 echo Copy of %%~nxA failed.
)

:patch
echo [3/3] All races, all classes
choice /c YN /m "Add Patch-A.MPQ so any race can pick any class (needs the custom realm)"
if errorlevel 2 goto done
set "ARAC=%~dp0..\realm\custom\acore\modules\mod-arac\Patch-A.MPQ"
if not exist "%ARAC%" (echo Run realm\"Build custom realm.bat" first; it fetches the patch. & goto done)
copy /y "%ARAC%" "%WOW%\Data\Patch-A.MPQ" >nul && echo Patch-A.MPQ added to "%WOW%\Data".

:done
echo.
echo Done. Log in with a GM account from realm\add-account.bat, then:
echo   /aa   AzerothAdmin (full GM window)     /mgm   MiniGM (GM HUD + 1,300 teleports)
echo   .ov   free services (faction/race/appearance change; boost to 70 on the casual profile)
pause
