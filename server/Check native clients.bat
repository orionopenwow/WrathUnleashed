@echo off
setlocal
title WrathUnleashed - why a 3.3.5a client can't connect (read only)
rem Read-only check for "it only works in the browser, not with my 3.3.5a client". Changes nothing.
rem The browser client reaches the realm through the website's relay; a real Wow.exe needs two game ports
rem open from the internet: 3724 (login) and 8085 (world), and the realm's address in acore_auth.realmlist.
rem Writes native-client-report.txt next to this file (no passwords in it).
cd /d "%~dp0"
set "KEY=%USERPROFILE%\.ssh\openwow"
set "HOST=play.openvanilla.app"
set "OUT=native-client-report.txt"
echo ==== from this PC (what a player's Wow.exe sees) > "%OUT%"
powershell -NoProfile -Command "foreach ($p in 3724,8085) { $c = New-Object Net.Sockets.TcpClient; $t = $c.BeginConnect('%HOST%', $p, $null, $null); if ($t.AsyncWaitHandle.WaitOne(5000) -and $c.Connected) { '{0} port {1}: OPEN' -f '%HOST%', $p } else { '{0} port {1}: BLOCKED (no answer in 5 s)' -f '%HOST%', $p }; $c.Close() }" >> "%OUT%"
echo.>> "%OUT%"
echo Reading the server (read only)...
ssh -i "%KEY%" -o StrictHostKeyChecking=accept-new -o ConnectTimeout=15 root@%HOST% "echo ==== containers; docker ps -a --format '{{.Names}}  {{.Status}}  {{.Ports}}' | grep -E 'ov-ac|wu-|caddy|realmd|mangosd'; echo; echo ==== listening on the game ports; ss -ltnp | grep -E ':(3724|8085|7878)\b' || echo 'nothing listens on 3724/8085'; echo; echo ==== ufw; ufw status 2>/dev/null | head -20; echo; echo ==== realm list; MYSQL_PWD=$(sed -n 's/^DB_ROOT_PASSWORD=//p' /srv/wrath/.env) docker exec -e MYSQL_PWD ov-ac-database mysql -uroot -h ac-database -t -e 'SELECT id,name,address,localAddress,port,gamebuild,flag FROM acore_auth.realmlist; SELECT username, last_ip, FROM_UNIXTIME(UNIX_TIMESTAMP(last_login)) AS last_login, failed_logins, os FROM acore_auth.account WHERE username NOT LIKE \"RNDBOT%%\" ORDER BY last_login DESC LIMIT 8' 2>&1; echo; echo ==== what the address resolves to; getent ahostsv4 play.openvanilla.app | head -2; echo this box: $(curl -s4 -m 5 https://ifconfig.me); echo; echo ==== settings; grep -E '^(WU_WARDEN|OV_PROFILE|WU_PLAYER_LIMIT)=' /srv/wrath/.env; echo; echo ==== last auth log lines; docker logs --tail 25 ov-ac-authserver 2>&1 | tail -25; echo; echo ==== last world log lines about logins; docker logs --since 2h ov-ac-worldserver 2>&1 | grep -iE 'warden|account|session|build|kick|disconnect' | tail -25" >> "%OUT%" 2>&1
if errorlevel 1 echo The SSH part failed; see %OUT%.
echo.
type "%OUT%"
echo.
echo Saved: %OUT%   (send it to Claude)
pause
