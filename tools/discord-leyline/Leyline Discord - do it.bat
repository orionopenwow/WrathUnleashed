@echo off
setlocal
chcp 65001 >nul
title Leyline Discord - do it
rem Rebrands and resets your Discord server to Leyline. It shows the plan first and asks you to type YES.
rem Before any change it backs up the server to your Desktop (Leyline-discord-backup-...).
rem Old channels are NOT deleted: they move into a hidden, read-only ARCHIVE category.
rem It never posts as the bot: your #welcome message is a draft text file for you to post yourself.
rem
rem You need a throwaway bot first (5 minutes, once):
rem   1. Open https://discord.com/developers/applications and click "New Application". Name it "Leyline setup",
rem      tick the box, click Create.
rem   2. Left menu: "Bot". Click "Reset Token", confirm, then "Copy". Keep it to yourself.
rem      (Paste it when this window asks, or save it in a file named token.txt next to this .bat.)
rem   3. Left menu: "OAuth2". Under "OAuth2 URL Generator" tick "bot", then under "Bot Permissions" tick
rem      "Administrator". Copy the URL at the bottom, open it, pick your server, click Authorize.
rem   4. In Discord: Server Settings, Roles, drag the "Leyline setup" role to the top of the list.
rem   5. Run "Leyline Discord - preview.bat" first, then this.
rem   6. Afterwards: kick the bot (Server Settings, Integrations, Leyline setup, Kick) and in the Developer Portal
rem      click Reset Token again (or delete the app), so the token is dead.
rem
rem Extra options (add them after the .bat name in a command prompt, or edit the last python line):
rem   --delete-archived    also delete the archived channels after the backup (asks you to type the server name)
rem   --delete-old-roles   also delete roles that aren't Moderator/Helper/Creator/Member (asks you to type DELETE ROLES)
rem   --backup-messages N  messages to back up per channel (default 1000)
rem   --plain              channel names without the little symbols in front
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
echo  Leyline Discord - DO IT. You'll see the plan first, then type YES to go ahead.
echo  Need a bot token first? Open README.md next to this file, or read the top of this .bat (right-click, Edit).
echo.
%PY% discord_leyline.py --apply %*
echo.
pause
