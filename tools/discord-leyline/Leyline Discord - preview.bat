@echo off
setlocal
chcp 65001 >nul
title Leyline Discord - preview (changes nothing)
rem Shows exactly what the Leyline rebrand would do to your Discord server. It changes NOTHING.
rem
rem Discord only lets a program change a server through a bot, so first make a throwaway one (5 minutes, once):
rem   1. Open https://discord.com/developers/applications and click "New Application". Name it "Leyline setup",
rem      tick the box, click Create.
rem   2. Left menu: "Bot". Click "Reset Token", confirm, then "Copy". That is the bot's password: keep it to yourself.
rem      (Paste it when this window asks, or save it in a file named token.txt next to this .bat.)
rem   3. Left menu: "OAuth2". Under "OAuth2 URL Generator" tick "bot", then under "Bot Permissions" tick
rem      "Administrator". Copy the URL at the bottom, open it, pick your server, click Authorize.
rem   4. In Discord: Server Settings, Roles, drag the "Leyline setup" role to the top of the list.
rem   5. Run this preview. When it looks right, run "Leyline Discord - do it.bat".
rem   6. Afterwards: kick the bot (Server Settings, Integrations, Leyline setup, Kick) and in the Developer Portal
rem      click Reset Token again (or delete the app), so the token is dead.
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PY="
where py >nul 2>&1 && set "PY=py -3"
if not defined PY where python >nul 2>&1 && set "PY=python"
if not defined PY (
  echo Python 3 is needed: https://www.python.org/downloads/  ^(tick "Add python.exe to PATH"^)
  pause & exit /b 1
)
echo.
echo  Leyline Discord - PREVIEW. This changes nothing.
echo  Need a bot token first? Open README.md next to this file, or read the top of this .bat (right-click, Edit).
echo.
%PY% discord_leyline.py %*
echo.
pause
