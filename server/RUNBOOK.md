# WrathUnleashed launch runbook

From "Hetzner says the AX42 is ready" to "players are in the world". Every step is done by
you, the owner: each one is marked **[OWNER]**. Nothing in this kit contacts the server on
its own.

Placeholders used below. Replace them everywhere:

| Placeholder | Meaning |
|---|---|
| `203.0.113.10` | the box's public IPv4 (Hetzner Robot shows it) |
| `example.com` | your domain; the site and realm run on `play.example.com` |
| `YOURNAME` | your own GM login name |

Commands marked **PC** run in Windows PowerShell on your PC. Commands marked **box** run
over SSH on the server. Run box commands from `/srv/wrath` unless a step says otherwise.

## Time plan

| Step | What | Time |
|---|---|---|
| 0 | Prepare the uploads on your PC (can be done before the box arrives) | 15-30 min |
| 1 | DNS record | 5 min (+ propagation) |
| 2 | OS check, upload the kit, run `bootstrap.sh` | 15-20 min |
| 3 | Turn on the website (Caddy) | 5 min |
| 4 | Upload client data and realm settings | 10-40 min (your upload speed) |
| 5 | Load (or build) the realm image | 5 min (build: 30-60 min) |
| 6 | First start | 10-20 min |
| 7 | World customizations (Brawl SQL) | 5 min |
| 8 | Realm address | 2 min |
| 9 | SOAP service account and GM account | 10 min |
| 10 | Sign-up page live, end-to-end test | 10 min |
| 11 | Open to players | 5 min |
| 12 | Backups | 10 min |
| 13 | Monitoring (Uptime Kuma) | 15 min |
| | **Total, without vmaps/mmaps** | **about 2-3 hours** |

Steps 14-16 (updates, rollback, day-to-day) are for after launch.

---

## 0. Prepare the uploads on your PC (before the box arrives) **[OWNER]**  (15-30 min)

All of this uses the realm that already runs locally. Make one folder for everything:

**PC**
```powershell
$UP = "$env:USERPROFILE\Desktop\wu-upload"
New-Item -ItemType Directory -Force $UP | Out-Null
cd C:\Users\campw\Desktop\WrathUnleashed\realm
```

**0a. Client data** (dbc, maps, Cameras; vmaps/mmaps if you ran `3-extract-pathing.bat`).
These files came from your own client install. They go to the server's disk only: no web
page ever serves them. If you ran "Build custom realm.bat", the volume already holds the
mod-arac all-races DBCs, so the export includes them.
```powershell
docker run --rm -v ov-client-data:/d:ro -v "${UP}:/out" alpine:3.20 sh -c "tar -C /d -czf /out/client-data.tgz . && ls -lh /out/client-data.tgz"
```
Expect about 1-2 GB without vmaps/mmaps, about 4-6 GB with them.

**0b. The custom realm images** (skip if you launch on AzerothCore's stock images).
One file, shared layers stored once:
```powershell
docker save -o "$UP\wu-images.tar" ov/ac-wotlk-db-import:custom ov/ac-wotlk-authserver:custom ov/ac-wotlk-worldserver:custom
```

**0c. Realm settings and SQL.**
```powershell
Copy-Item -Recurse profiles, modules.env, brawl_world.sql, brawl_world_2.sql, make_account.py, docker-compose.build.yml "$UP\"
New-Item -ItemType Directory -Force "$UP\custom" | Out-Null
Copy-Item -Recurse custom\lua_scripts, custom\fetch.sh, custom\sources.lock "$UP\custom\"
```
Do **not** copy `ahbot.env`: it names a character GUID from your local realm, which does not
exist on the new one (step 16 sets the auction bot up again).

**0d. This kit.** Put the `wu-server` folder next to it, e.g. `$UP\wu-server`.

> Line endings: if you open a `.sh` file in Notepad and save it, Windows may add CRLF line
> endings and bash will fail with `$'\r': command not found`. Fix on the box with
> `sudo sed -i 's/\r$//' /srv/wrath/*.sh`.

## 1. DNS **[OWNER]**  (5 min, then propagation)

At your DNS provider, add an **A record** `play.example.com` -> `203.0.113.10`, TTL 300.
Do it first: Caddy needs it to get a TLS certificate, and players' clients need it.
(Using the bare IP as the realm address also works; DNS lets you move boxes later.)

Check from the PC: `Resolve-DnsName play.example.com`

## 2. OS check, upload the kit, run bootstrap **[OWNER]**  (15-20 min)

**2a. OS.** If Hetzner delivered the box in the rescue system instead of with Ubuntu, log in
with the rescue password from the Robot e-mail, run `installimage`, pick
**Ubuntu 24.04**, keep software RAID 1 over both NVMe disks, save, let it reboot (10-15 min).
Make sure your SSH public key is installed for root (Robot: "Key management", or choose it
when ordering). `bootstrap.sh` copies root's keys to the `wow` user and refuses to turn
off password login if no key exists.

**2b. Upload the kit and run it.**

**PC**
```powershell
scp -r "$UP\wu-server" root@203.0.113.10:/root/
ssh root@203.0.113.10
```
**box (as root)**
```bash
cd /root/wu-server && bash bootstrap.sh
```
It prints numbered steps. When it says so, **open a second terminal and check you can log in
as `wow`** before closing the root session:

**PC (second window)**
```powershell
ssh wow@203.0.113.10
docker ps    # works without sudo (the wow user is in the docker group)
```
From now on, work as `wow` (`sudo` works without a password).

Re-running `bootstrap.sh` is safe: it keeps `.env`, `signup.env`, `site/` and every setting
you changed, and does not restart Docker if nothing changed.

## 3. Turn on the website **[OWNER]**  (5 min)

**box**
```bash
sudo sed -i 's/^DOMAIN=.*/DOMAIN=example.com/' /srv/wrath/caddy.env
sudo systemctl restart caddy
sudo journalctl -u caddy -n 30 --no-pager    # look for "certificate obtained successfully"
```
Open `https://play.example.com` in a browser: the placeholder page shows. Edit
`/srv/wrath/site/index.html` (the site text is yours). Never put game client files in
`site/`: the web server refuses `.mpq`, `.dbc`, map and model extensions anyway.

## 4. Upload client data and realm settings **[OWNER]**  (10-40 min)

**PC**
```powershell
scp "$UP\client-data.tgz" "$UP\wu-images.tar" wow@203.0.113.10:/srv/wrath/upload/
scp -r "$UP\profiles" "$UP\modules.env" "$UP\custom" wow@203.0.113.10:/srv/wrath/
scp "$UP\brawl_world.sql" "$UP\brawl_world_2.sql" wow@203.0.113.10:/srv/wrath/sql/
scp "$UP\make_account.py" "$UP\docker-compose.build.yml" wow@203.0.113.10:/srv/wrath/
```
Time: 2 GB at 50 Mbit/s upload is about 6 minutes. If the connection drops on a big file,
resume with rsync from WSL instead of starting over:
`rsync -avP --partial /mnt/c/Users/campw/Desktop/wu-upload/client-data.tgz wow@203.0.113.10:/srv/wrath/upload/`

**box:** make the `ov-client-data` volume a bind to `/srv/wrath/client-data`, then unpack:
```bash
docker volume inspect ov-client-data >/dev/null 2>&1 || \
  docker volume create --driver local --opt type=none --opt o=bind \
    --opt device=/srv/wrath/client-data ov-client-data
sudo tar -C /srv/wrath/client-data -xzf /srv/wrath/upload/client-data.tgz
ls /srv/wrath/client-data          # expect: dbc  maps  Cameras  (and vmaps mmaps if exported)
du -sh /srv/wrath/client-data
```
Because the volume is a bind, later data changes are a plain `rsync` into
`/srv/wrath/client-data/` (for example adding vmaps/mmaps later).

If you uploaded vmaps **and** mmaps, turn line-of-sight and pathing on:
```bash
sed -i 's/^OV_PATHING=.*/OV_PATHING=1/' /srv/wrath/.env
```

Pick the rules (default `brawl`; also `progression`, `casual`):
```bash
sed -i 's/^OV_PROFILE=.*/OV_PROFILE=brawl/' /srv/wrath/.env
```

## 5. Realm image **[OWNER]**  (5 min; building: 30-60 min)

**Option A (recommended): load the images you saved in step 0b.**
```bash
docker load -i /srv/wrath/upload/wu-images.tar
docker image ls 'ov/ac-wotlk-*'     # three images, tag "custom"
```

**Option B: build on the box** (the AX42 compiles faster than most PCs). Needs
`custom/fetch.sh`, `custom/sources.lock` and `docker-compose.build.yml` from step 4.
```bash
cd /srv/wrath
docker run --rm --entrypoint sh -v /srv/wrath/custom:/w alpine/git:latest /w/fetch.sh
docker compose -f docker-compose.prod.yml -f docker-compose.build.yml build
```
If the client data you exported was extracted **before** "Build custom realm.bat" ever ran
(no mod-arac DBCs), copy them in once, as the build script does on the PC:
```bash
docker run --rm -v ov-client-data:/d \
  -v /srv/wrath/custom/acore/modules/mod-arac/patch-contents/DBFilesContent:/s:ro alpine:3.20 \
  sh -c 'mkdir -p /d/dbc-stock && for f in /s/*.dbc; do b=$(basename "$f"); [ -f /d/dbc-stock/$b ] || cp /d/dbc/$b /d/dbc-stock/$b; cp "$f" /d/dbc/$b; done'
```

**Option C: stock AzerothCore (no modules).**
```bash
sed -i 's#^OV_IMAGE=.*#OV_IMAGE=acore/ac-wotlk#; s#^OV_TAG=.*#OV_TAG=master#' /srv/wrath/.env
cd /srv/wrath && docker compose pull
```

## 6. First start **[OWNER]**  (10-20 min)

```bash
cd /srv/wrath
docker compose up -d
docker compose logs -f ac-db-import      # creates and fills the databases; ends with "exited with code 0"
docker logs -f ov-ac-worldserver         # wait for the line containing "ready..."  (Ctrl-C only stops following the log)
docker compose ps                        # database, authserver, worldserver: "healthy" after a while
```
The first start imports every database and, with playerbots, creates the bot accounts and
characters, so it is the slowest. Later starts take 1-3 minutes.

Check the ports from your PC: `Test-NetConnection 203.0.113.10 -Port 3724` and `-Port 8085`
(`TcpTestSucceeded : True`). Port 7878 (SOAP) must **fail** from the PC: it is bound to the
box's 127.0.0.1 only.

## 7. World customizations **[OWNER]**  (5 min)

The Brawl profile needs its world SQL, as "Make it Brawl.bat" does on the PC. Skip for
`progression` / `casual`. Both files are safe to run again.
```bash
cd /srv/wrath
for f in sql/brawl_world.sql sql/brawl_world_2.sql; do
  docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_world' < "$f" && echo "applied $f"
done
docker compose restart ac-worldserver
```

## 8. Realm address **[OWNER]**  (2 min)

```bash
sudo /srv/wrath/set-realm-address.sh play.example.com "WrathUnleashed"
```
This writes `address`, `localAddress` and `name` in `acore_auth.realmlist`. The
authserver picks it up within about 20 seconds; no restart needed.

## 9. SOAP service account and your GM account **[OWNER]**  (10 min)

The sign-up page and `soap-cmd.sh` log in to the worldserver's SOAP port as the GM account
`SOAPSVC`. Its password was generated into `/srv/wrath/signup.env` by bootstrap. SOAP only
accepts accounts with GM level 3.

**9a. Create SOAPSVC.** Pick one way.

*Through the console* (the way you know). Show the password first:
```bash
sudo grep '^SOAP_PASS=' /srv/wrath/signup.env
docker attach ov-ac-worldserver
```
Type, at the `AC>` prompt (press Enter once if no prompt shows):
```
account create SOAPSVC <the SOAP_PASS value>
account set gmlevel SOAPSVC 3 -1
```
Then **detach with Ctrl-P followed by Ctrl-Q**. **Never press Ctrl-C in the attached console:
that shuts the world server down.**
Note: the console echoes what you type, so it ends up in `docker logs ov-ac-worldserver`
(readable by root and the docker group only; rotated at 5 x 50 MB).

*Without typing the password anywhere* (uses the `make_account.py` you uploaded; same SRP6
SQL `add-account.bat` uses on the PC; it also sets GM level 3):
```bash
sudo bash -c 'set -a; . /srv/wrath/signup.env; python3 /srv/wrath/make_account.py "$SOAP_USER" "$SOAP_PASS"' \
  | docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth'
```

**9b. Test SOAP.**
```bash
sudo /srv/wrath/soap-cmd.sh "server info"
```
You should see the core revision, players online and uptime.

**9c. Optional hardening: stop SOAPSVC from logging into the game.** The authserver
refuses a locked account from any IP other than `last_ip`; SOAP does not check the lock.
```bash
docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_auth' \
  <<<"UPDATE account SET locked = 1, last_ip = '127.0.0.1' WHERE username = 'SOAPSVC';"
sudo /srv/wrath/soap-cmd.sh "server info"     # must still work
```

**9d. Your own GM account**, through SOAP (nothing lands in the console log). The leading
`read -rs` keeps the password out of your shell history:
```bash
read -rs -p "GM password (6-16 chars, no spaces): " P; echo
sudo /srv/wrath/soap-cmd.sh "account create YOURNAME $P"
sudo /srv/wrath/soap-cmd.sh "account set gmlevel YOURNAME 3 -1"
unset P
```
(The console works as well: `docker attach ov-ac-worldserver`, the same two commands,
Ctrl-P Ctrl-Q.)

## 10. Sign-up page live, end-to-end test **[OWNER]**  (10 min)

```bash
sudo systemctl start wu-signup
sudo journalctl -u wu-signup -n 20 --no-pager      # "listening on 127.0.0.1:8090 ..."
curl -s https://play.example.com/signup/healthz     # "ok"
```
Open `https://play.example.com/signup`, create a test account, then log in with a 3.3.5a
client (step 11) and enter the world.

Limits (in `/srv/wrath/signup.env`, then `sudo systemctl restart wu-signup`):
`SIGNUP_PER_IP_PER_HOUR=3` accounts per IP per hour, 30 form posts per IP per hour, 60
accounts per minute in total.

**Turnstile (recommended for a public launch).** In the Cloudflare dashboard create a
Turnstile widget for `play.example.com`, then put its keys in `signup.env`:
```bash
sudo nano /srv/wrath/signup.env      # TURNSTILE_SITEKEY=...  TURNSTILE_SECRET=...
sudo systemctl restart wu-signup
```
The check is on only while `TURNSTILE_SECRET` is set.

## 11. Open to players **[OWNER]**  (5 min)

**What players do.** They need a 3.3.5a (build 12340) client. In the client folder, open
`Data\enUS\realmlist.wtf` (or their locale: `enGB`, `deDE`, ...) and replace the contents with:
```
set realmlist play.example.com
```
Then start `Wow.exe` and log in with the account from the sign-up page. Account names and
passwords are not case-sensitive in this client.

**Warden** is on (AzerothCore's default) because players use stock clients. The browser
client from the PC setup has no Warden module, so it cannot use this realm.

**mod-arac (all races, all classes)** needs a client patch (`Patch-A.MPQ`) on each player's
PC. It is built from game data: link players to the module's own project page if you want
them to have it, and do not host the MPQ on `play.example.com`.

**Bots on a public box.** `modules.env` comes from the PC with
`AC_PLAYERBOTS_MIN_RANDOM_BOTS=60` / `AC_PLAYERBOTS_MAX_RANDOM_BOTS=60`
(mod-playerbots keys `Playerbots.MinRandomBots` / `MaxRandomBots`). Guidance for the AX42:
- Start around **150** (min = max keeps the count steady) for launch day. Bots fill
  battlegrounds, Dungeon Finder and the world while real numbers ramp up.
- Check the world update time under load: `sudo /srv/wrath/soap-cmd.sh "server info"`.
  If the update diff stays above ~100-150 ms at peak, lower the count; if it stays well
  below 50 ms, you can raise it in steps of 50-100.
- As real players arrive (200-300 online), consider lowering bots: players matter more
  than filler, and the CPU cost is per character in the world.
- Changing the count: edit `/srv/wrath/modules.env`, then `docker compose up -d ac-worldserver`.
  New bots need a few minutes to log in and spread out.
- Keep `AC_PLAYERBOTS_RANDOM_BOT_TALK=0` and broadcasts off (as shipped) on a public realm.

**Restart with a warning** (announces a countdown, then restarts; Docker brings it back):
```bash
sudo /srv/wrath/soap-cmd.sh "server restart 300"
```

## 12. Backups **[OWNER]**  (10 min)

The nightly timer was installed by bootstrap (04:30 UTC). Run it once now and check:
```bash
sudo systemctl start wu-backup && sudo journalctl -u wu-backup -n 20 --no-pager
sudo ls -l /srv/wrath/backups/
systemctl list-timers wu-backup.timer
```
Each night writes `/srv/wrath/backups/<date>_<time>/` with `acore_auth`, `acore_characters`,
`acore_world` (and `acore_playerbots`) dumps (`mysqldump --single-transaction`, gzipped),
`config.tar.gz` (settings and secrets) and `SHA256SUMS`. 14 days are kept.

**Off-site copy (recommended):** fill in `/srv/wrath/backup.env` (see `backup.env.example`).
Example with a Hetzner Storage Box (SFTP on port 23):
```bash
sudo ssh-keygen -t ed25519 -N '' -f /root/.ssh/storagebox
# add /root/.ssh/storagebox.pub to the Storage Box (Robot -> Storage Box -> SSH keys)
sudo tee -a /root/.ssh/config >/dev/null <<'EOF'
Host u123456.your-storagebox.de
  Port 23
  User u123456
  IdentityFile /root/.ssh/storagebox
EOF
sudo nano /srv/wrath/backup.env
#   RESTIC_REPOSITORY=sftp:u123456.your-storagebox.de:/wrath
#   RESTIC_PASSWORD=<long random string; store it in your password manager too>
sudo systemctl start wu-backup && sudo journalctl -u wu-backup -n 30 --no-pager
```
Restore: see step 15.

## 13. Monitoring with Uptime Kuma **[OWNER]**  (15 min)

Runs in Docker on the box's loopback only; you reach it through an SSH tunnel.
```bash
docker run -d --name uptime-kuma --restart unless-stopped \
  -p 127.0.0.1:3001:3001 --add-host=host.docker.internal:host-gateway \
  -v uptime-kuma:/app/data louislam/uptime-kuma:1
```
**PC**
```powershell
ssh -N -L 3001:127.0.0.1:3001 wow@203.0.113.10
```
Open `http://localhost:3001`, create the admin login, then add monitors:

| Monitor | Type | Target |
|---|---|---|
| Auth server | TCP port | `host.docker.internal` : `3724` |
| World server | TCP port | `host.docker.internal` : `8085` |
| Sign-up + SOAP | HTTP(s) - keyword | `https://play.example.com/signup/healthz`, keyword `ok` |
| Website | HTTP(s) | `https://play.example.com/` |

Add a notification (Discord webhook, e-mail, ...) and attach it to every monitor. A
monitor from outside the box (any free external uptime checker on ports 3724/8085) also
catches the case where the whole box is down.

Useful by hand:
```bash
docker compose ps                     # health of every service
docker stats --no-stream              # CPU / RAM per container
sudo /srv/wrath/soap-cmd.sh "server info"
tail -f /srv/wrath/logs/world/Server.log
```

---

## 14. Updating without rebuilding **[OWNER]**

| Change | How | Players notice |
|---|---|---|
| World data (SQL) | `docker exec -i ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot acore_world' < change.sql`, then a `reload ...` command for that table if one exists (`sudo ./soap-cmd.sh "reload all"`), otherwise a restart | nothing / a restart |
| Lua scripts (mod-ale) | copy into `/srv/wrath/custom/lua_scripts/`, then `sudo ./soap-cmd.sh "reload ale"` (or type `.reload ale` in game as GM). Check `logs/world/Server.log` for "Reloading ALE" and Lua errors. SOAP may answer with an error text even though the reload ran | nothing |
| Settings (`modules.env`, `profiles/*.env`, `OV_PROFILE`, `OV_PATHING` in `.env`) | edit, then `docker compose up -d ac-worldserver` (compose sees the change and recreates the container). Warn first: `sudo ./soap-cmd.sh "server restart 120"` | a 1-3 minute restart |
| Settings in `docker-compose.prod.yml` | edit, then `docker compose up -d` | restart of the changed service |
| Website | edit files in `/srv/wrath/site/` | nothing |
| Sign-up limits / Turnstile | edit `signup.env`, `sudo systemctl restart wu-signup` | nothing |

Before any SQL change: `sudo systemctl start wu-backup` (a dump takes a minute or two).

**New realm image** (C++ or module changes need a rebuild; on the PC, then upload):
```bash
# 1. keep the running images under a rollback tag
for s in db-import authserver worldserver; do docker tag ov/ac-wotlk-$s:custom ov/ac-wotlk-$s:rollback; done
# 2. fresh backup (the new db-import may change the schema)
sudo systemctl start wu-backup
# 3. load the new images (uploaded as in step 0b/4) and restart with a warning
docker load -i /srv/wrath/upload/wu-images.tar
sudo ./soap-cmd.sh "server restart 300"     # or: docker compose up -d
docker compose up -d
```

## 15. Rollback **[OWNER]**

Work from the smallest change outwards.

1. **A setting broke the world server** (it restarts in a loop: `docker compose ps`,
   `docker logs --tail 100 ov-ac-worldserver`): undo the edit, `docker compose up -d
   ac-worldserver`. Last night's settings are in the backup:
   `sudo tar -tzf /srv/wrath/backups/<date>/config.tar.gz` and extract the one file you need,
   e.g. `sudo tar -C /tmp -xzf /srv/wrath/backups/<date>/config.tar.gz modules.env`.
2. **A Lua script broke**: remove or fix it, `sudo ./soap-cmd.sh "reload ale"`.
3. **A new realm image is bad**:
   ```bash
   for s in db-import authserver worldserver; do docker tag ov/ac-wotlk-$s:rollback ov/ac-wotlk-$s:custom; done
   docker compose up -d
   ```
   If the new image's db-import already changed the database schema, also restore the
   backup you took just before the update (next item), since the old core may not run on
   the newer schema.
4. **Bad data in the database** (a broken SQL change, a griefing incident):
   ```bash
   sudo /srv/wrath/restore.sh                                   # lists backups
   sudo /srv/wrath/restore.sh 2026-10-30_043000 acore_world       # one database
   sudo /srv/wrath/restore.sh 2026-10-30_043000                   # everything in that backup
   ```
   It takes a safety backup first, stops auth + world, loads the dumps, starts them again.
   Restoring `acore_characters` rolls every player back to that time: announce it.
5. **From the off-site copy** (box lost or local backups gone):
   ```bash
   sudo bash -c 'set -a; . /srv/wrath/backup.env; restic snapshots; restic restore latest --target /srv/wrath/restic-restore'
   sudo /srv/wrath/restore.sh /srv/wrath/restic-restore/srv/wrath/backups/<date>
   ```
   On a brand-new box: steps 2-6 first, then restore, then step 8 if the address changed.

## 16. Day-to-day notes **[OWNER]**

- **Console:** `docker attach ov-ac-worldserver`; leave with **Ctrl-P Ctrl-Q**, never Ctrl-C.
  For one-off commands `sudo /srv/wrath/soap-cmd.sh "<command>"` is safer.
- **Auction house bot:** make a normal character for it (e.g. "Auctioneer") on any non-bot
  account, then:
  ```bash
  G=$(docker exec ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot -N -s -e "SELECT guid FROM acore_characters.characters WHERE name = '"'"'Auctioneer'"'"'"')
  printf 'AC_AUCTION_HOUSE_BOT_GUIDS=%s\nAC_AUCTION_HOUSE_BOT_ENABLE_SELLER=true\nAC_AUCTION_HOUSE_BOT_BUYER_ENABLED=true\n' "$G" > /srv/wrath/ahbot.env
  docker compose up -d ac-worldserver
  ```
- **Reboots for kernel updates** are not automatic. Pick a quiet hour:
  `sudo ./soap-cmd.sh "server shutdown 300"`, wait for it to stop, then `sudo reboot`.
  Everything (Docker services, Caddy, sign-up, backup timer) starts on boot.
- **Database shell:** `docker exec -it ov-ac-database sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" exec mysql -uroot'`
- **Secrets:** `/srv/wrath/.env` (owned by `wow`), `signup.env` and `backup.env` (owned by
  root) are mode 600; backups contain
  them too (backups/ is root-only). Do not paste them into chats or tickets.
- **Firewall:** Docker-published ports bypass ufw. Only 3724 and 8085 are published on all
  interfaces; keep every new admin service on `127.0.0.1:` like SOAP and Uptime Kuma.
