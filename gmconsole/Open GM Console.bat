@echo off
setlocal
title WrathUnleashed - GM console (keep this window open)
rem Opens the GM console in your browser through ONE ssh connection to play.openvanilla.app:
rem   ssh -L 8099:127.0.0.1:8099 ...   the console only listens on the server's 127.0.0.1, so this tunnel
rem                                    is the only way in. Closing this window closes the console.
rem The same connection reads the login token from /srv/wrath/gmconsole.env. It is kept in memory only:
rem never written to disk here and never shown, only handed to your browser in the login link.
if not exist "%USERPROFILE%\.ssh\openwow" (echo SSH key %USERPROFILE%\.ssh\openwow not found. & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText('%~f0'); iex ($s.Substring($s.IndexOf('#'+'PS1')))"
echo.
echo The GM console is closed.
pause
exit /b 0

#PS1 (PowerShell: everything below runs inside the one ssh connection's lifetime)
$port = 8099
$key = Join-Path $env:USERPROFILE '.ssh\openwow'
function PortOpen { try { $c = New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', $port); $c.Close(); return $true } catch { return $false } }
if (PortOpen) { Write-Host "Port $port is already in use on this PC: another GM console window is open (use that one, or close it)."; return }
$remote = "grep -m1 '^GM_TOKEN=' /srv/wrath/gmconsole.env 2>/dev/null || echo GMC_NO_TOKEN; docker ps --format '{{.Names}}' | grep -qx wu-gmconsole && echo GMC_RUNNING || echo GMC_NOT_RUNNING; exec sleep infinity"
$psi = New-Object Diagnostics.ProcessStartInfo
$psi.FileName = 'ssh'
$psi.Arguments = "-i `"$key`" -o StrictHostKeyChecking=accept-new -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -L ${port}:127.0.0.1:${port} root@play.openvanilla.app `"$remote`""
$psi.UseShellExecute = $false
$psi.RedirectStandardOutput = $true
Write-Host 'Connecting to play.openvanilla.app...'
$p = [Diagnostics.Process]::Start($psi)
$tok = $null; $state = $null
while ($true) {
  $line = $p.StandardOutput.ReadLine()
  if ($null -eq $line) { break }
  if ($line -match '^GM_TOKEN=([A-Za-z0-9_-]{32,})$') { $tok = $Matches[1]; $Matches.Clear(); continue }
  if ($line -eq 'GMC_NO_TOKEN') { $state = 'notoken'; continue }
  if ($line -eq 'GMC_RUNNING') { $state = 'ok'; break }
  if ($line -eq 'GMC_NOT_RUNNING') { $state = 'down'; break }
  Write-Host $line
}
if ($null -eq $state) {
  Write-Host 'The SSH connection ended (see above). If it says "Connection timed out", the server is pausing SSH after many quick logins: wait 2 minutes and try again.'
  return
}
if ($state -eq 'down' -or $null -eq $tok) {
  if ($state -eq 'down') { Write-Host 'The GM console is not running on the server: run Install GM Console.bat.' }
  else { Write-Host 'No login token on the server (/srv/wrath/gmconsole.env): run Install GM Console.bat.' }
  try { $p.Kill() } catch {}
  return
}
$ok = $false
for ($i = 0; $i -lt 40 -and -not $ok; $i++) { if (PortOpen) { $ok = $true } else { Start-Sleep -Milliseconds 250 } }
if (-not $ok) { Write-Host "The tunnel on 127.0.0.1:$port did not open."; try { $p.Kill() } catch {}; $tok = $null; return }
Start-Process ('http://127.0.0.1:' + $port + '/login?t=' + $tok)
$tok = $null
Write-Host ''
Write-Host "GM console: http://127.0.0.1:$port  (opened in your browser)"
Write-Host 'Keep this window open while you use it. Close it (or press Ctrl+C) to close the console.'
$p.WaitForExit()
