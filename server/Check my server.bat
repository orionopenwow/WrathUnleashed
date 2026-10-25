@echo off
rem Read-only look at your Hetzner server (play.openvanilla.app) so Claude can plan the Wrath move.
rem Changes nothing on the server. Writes server-report.txt next to this file.
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=root@play.openvanilla.app"
echo Reading the server (read only)...
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 %HOST% "echo ==== host; hostname; uptime; echo; echo ==== memory; free -h; echo; echo ==== disk; df -h / /opt 2>/dev/null; echo; echo ==== cpu; nproc; lscpu | grep -E 'Model name|^CPU\(s\)'; echo; echo ==== os; . /etc/os-release; echo \$PRETTY_NAME; echo; echo ==== docker; docker --version; docker compose version; echo; echo ==== containers; docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}\t{{.Ports}}'; echo; echo ==== compose projects; docker compose ls; echo; echo ==== listening; ss -ltnp | grep -E ':(22|80|443|3724|8085|8090|3306|7878)\b'; echo; echo ==== opt; ls -la /opt; echo; echo ==== caddy; systemctl is-active caddy 2>/dev/null; ls /etc/caddy 2>/dev/null; docker ps --filter name=caddy --format '{{.Names}}'; echo; echo ==== backups; ls -la /opt/*/backups 2>/dev/null | tail -5; crontab -l 2>/dev/null; echo; echo ==== images; docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}' | head -30" > server-report.txt 2>&1
if errorlevel 1 (echo The SSH check failed; server-report.txt has the message.) else (echo Done: server-report.txt)
pause
