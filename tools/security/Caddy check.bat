@echo off
setlocal
title Leyline - Caddy and compose check (read-only)
rem Read-only: copies the LIVE Caddyfile, the compose files (secrets redacted on the server), the published ports,
rem the firewall and fail2ban state back to this PC, into tools\security\live\caddy-review-<date>.txt (not in git).
rem Runs caddy-check.sh with redact.py on the server: the same box and key as the other server steps
rem (root@play.openvanilla.app, %USERPROFILE%\.ssh\openwow). One SSH login. Changes nothing on the server.
cd /d "%~dp0"
for %%f in (caddy-check.sh redact.py) do if not exist "%%f" (echo %%f is missing next to this file. & pause & exit /b 1)
if not exist live mkdir live
for /f %%d in ('powershell -NoProfile -Command "Get-Date -Format yyyyMMdd-HHmm"') do set "D=%%d"
set "OUT=live\caddy-review-%D%.txt"
tar -cf - caddy-check.sh redact.py | ssh -i "%USERPROFILE%\.ssh\openwow" -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30 root@play.openvanilla.app "rm -rf /tmp/wu-sec && mkdir -p /tmp/wu-sec && tar -xf - -C /tmp/wu-sec && sed -i 's/\r$//' /tmp/wu-sec/*.sh /tmp/wu-sec/*.py && bash /tmp/wu-sec/caddy-check.sh; rm -rf /tmp/wu-sec" > "%OUT%"
findstr /b /c:"CADDY CHECK OK" "%OUT%" >nul || (echo It did not finish; see %OUT%. & pause & exit /b 1)
echo Saved %OUT%
exit /b 0
