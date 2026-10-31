# Security hardening (2026-10-31)

What a read-only security audit found, what is now fixed in the code, how to roll it out, and what only the owner
can do (it needs your Cloudflare, GitHub and server accounts). Plain steps, in order.

## 1. Fixed in the code

| Finding | What changed | Where |
|---|---|---|
| H1 rate limits never forgot anyone; a flood could reset them | One shared limiter, `stream/ratelimit.py`: old entries are swept by time (every minute), memory is capped (oldest dropped first), global caps (say "all installs today") live apart and survive any flood or reset, and IPv6 counts per /64 (one home can't dodge a limit by changing its last digits). The portal, `social.py`, `hub_rank.py` and `profiles.py` use it; `admin.py` and `hub.py` are switched by their owners. | `stream/ratelimit.py`, tests `stream/tests/test_ratelimit.py` |
| H2 the portal could be tied up by slow or many callers | A caller idle on its connection for 30 s is dropped; at most 512 requests at once, the next one gets "503 busy" straight away; a SOAP call waits at most 8 s for its turn and 8 s for an answer. The stream site refuses request bodies over 2 MB. | `stream/wrath_portal.py`, `stream/server/stream-up.sh`; tests `stream/tests/test_portal_hardening.py` |
| L1 two missing `return`s after the Admin Console | Added. | `stream/wrath_portal.py` |
| L2 the SOAP bridge checked only the login name | It also checks a password when `BRIDGE_PASS` is set (constant-time). See 3.5. | `stream/wrath_portal.py` |
| L4 the launcher's sign-in link could be used for phishing | `/wrath/link?code=...` no longer offers a one-click Approve. The code in the link is shown only as something to compare, with a warning; the player types the code their launcher shows, and only then sees Approve. The launcher keeps opening the same link. | `stream/social.py`, test `stream/tests/test_social.py` |
| M1 `.playerbots bot add/addclass` skipped every bot limit | Those commands from a non-GM now go through the same per-player, per-realm, group-size and cooldown checks as `.recruit` (or get a friendly pointer to `.recruit`). `list`, `remove`, `logout` still work. Live reload safe. | `realm/custom/lua_scripts/ov_companions.lua`, test `stream/tests/test_ov_companions.lua` |
| M2 no chat anti-spam settings | Flood: 6 messages a second mutes for 30 s. `/say` from level 1, public channels and whispers from level 5. Chat links must be well formed. **Needs a realm restart** (see 2). | `realm/profiles/main.env`, `realm/serverpass.sh` |
| M4 no connection-flood limits on the game ports | `tools/security/firewall.sh`: per-address limits in Docker's own firewall chain (which ufw never sees) for 3724, 8085, the relay ports and the web; a fail2ban jail for repeated wrong passwords. Dry run unless you say `--apply`. | `tools/security/firewall.sh` and its two .bat files |
| H3 GitHub's deploy key was a full root shell | The key can now do one thing: hand realm scripts the realm already runs to `/srv/wrath/luaup-ci.sh`, which checks them and reloads them live. No shell, no new scripts (those need a restart). | `server/luaup-ci.sh`, `tools/github-workflows/realm-scripts.yml`, `setup/Set up automatic deploys.bat`, `tools/security/ci-key-migrate.sh` |
| M6 a native-code mod (DLL) was trusted forever after one OK | The OK is now for those exact files: an update that changes the DLL (or its settings) asks again. | `launcher/src-tauri/src/mods.rs` |
| M6 GitHub Actions pinned by tag | Every action is pinned by commit, the tag kept in a comment. | `tools/github-workflows/*.yml`, `.github/workflows/*.yml` |
| Caddy has no server timeouts | Read-only `Caddy check.bat` copies the live Caddyfile and compose files (secrets removed) to `tools\security\live\` for review. `caddy-apply.sh` (a draft) adds read timeouts and a 2 MB body cap under `/wrath`. | `tools/security/` |

## 2. Rolling it out (order)

1. **signin** (`stream/Update sign-in and warm-up.bat`): the portal, `ratelimit.py`, `social.py`, `profiles.py`,
   `hub_rank.py`. Players in game are not affected. Check: `/wrath` loads, the launcher's "Sign in" link asks you to
   type the code, the forum and profiles work.
2. **scripts** (`realm/Server pass ...bat`): `ov_companions.lua` reloads live. **But** the same run now also sets
   the chat settings, so its first run **restarts the realm with the 5-minute warning**. Pick a quiet time.
   After it: `.playerbots bot addclass mage` as a normal player answers like `.recruit`.
3. **Firewall**: `tools\security\Firewall limits - dry run.bat`, read it, then `Firewall limits - apply.bat`.
   Undo: `bash /usr/local/sbin/wu-firewall.sh --remove` on the server.
4. **CI key** (once): `tools\security\CI key - restrict (draft).bat` (dry run), then with `--apply`. It keeps the same
   key, so the GitHub secret stays. Then **ship** (`Ship to GitHub.bat`) so the new `realm-scripts.yml` is used,
   and push a small script change: the Actions run must end in `LUAUP OK`. (Or re-run
   `setup\Set up automatic deploys.bat`, which makes a fresh restricted key and removes the old line.)
5. **ship**: the launcher (`mods.rs`) and the pinned workflows go out with the next launcher release.
6. **Caddy**: `tools\security\Caddy check.bat`; read the file it saves. Then, from an SSH session on the server,
   `bash caddy-apply.sh` (dry run, shows the diff) and `bash caddy-apply.sh --apply`. It needs Caddy 2.7 or newer
   and puts the old Caddyfile back if Caddy refuses it. Then play 3+ minutes in the browser client to be sure
   WebSockets stay open.

New settings (all optional, in `/srv/wrath/portal.env`): `BRIDGE_PASS`, `WU_MAX_CONN` (512),
`WU_HANDLER_TIMEOUT` (30), `SOAP_TIMEOUT` (8). The firewall: `WU_FW_WEB=0` to leave 80/443 alone.

## 3. What only you can do

### 3.1 Cloudflare in front of the websites

The game ports (3724, 8085, the relay's 40000-40999) can't go through Cloudflare's free proxy; the websites can.

1. Cloudflare dashboard -> your domain -> **DNS**: `play`, `wrath` and `relay` (only its HTTP name, not a game
   port name) -> the cloud icon **orange** (Proxied). Leave any name players type as a realmlist **grey**.
2. **SSL/TLS** -> Overview -> **Full (strict)** (Caddy already has real certificates).
3. **Security -> WAF -> Rate limiting rules** -> Create rule (the free plan has one rule: make the first; Pro
   and up can add the second):
   - "Sign-in and forms": URI path starts with `/wrath/signin` or `/wrath/link` or `/login`, 20 requests per
     10 seconds per IP -> Block for 1 minute.
   - "Everything else": hostname is `play.openvanilla.app`, 300 requests per 10 seconds per IP -> Managed Challenge.
4. **Caching -> Cache Rules**: `/wrath/art/*` and `wrath.openvanilla.app` files ending `.wasm`, `.js` -> Eligible
   for cache, Edge TTL 1 day. Never cache `/wrath/api/*`, `/__env.js`, `/__gate`, `/data/__*`.
5. WebSockets: **Network -> WebSockets** on.
6. Then: `WU_FW_WEB=0 bash /usr/local/sbin/wu-firewall.sh --apply` (every visitor now comes from a Cloudflare
   address, so the server's own per-address web limits would hurt). Caddy must read the real visitor address from
   `CF-Connecting-IP`: in the Caddyfile's global options, `servers { trusted_proxies static <Cloudflare ranges> }`
   and `client_ip_headers CF-Connecting-IP` (Caddy 2.7+). Do this before step 1 goes orange, or every limit treats
   all visitors as one.

### 3.2 Turnstile (a bot check on sign-up)

1. Cloudflare -> **Turnstile** -> Add site -> `play.openvanilla.app`, Managed. You get a **site key** and a
   **secret key**.
2. On the server, in `/srv/wrath/signup.env` (mode 600): `TURNSTILE_SITEKEY=<site key>` and
   `TURNSTILE_SECRET=<secret key>`. The check turns on by itself when the secret is set.
3. Restart the signup service (`docker restart` its container, or `systemctl restart` it if it runs as a service).
4. Open the sign-up page in a private window: the widget shows; a sign-up still works.

### 3.3 Guest accounts (the Rust site, wenilla-realm)

Guest accounts are cheap to make. In the realm service's environment (the `.env` its compose file reads; the
Caddy check lists the files): `OPENVANILLA_GUEST_DAILY_MAX=300` (the realm-wide cap per day; the default is
100000). The per-address caps (20 an hour, 50 a day) are fixed in the code (`auth/guest.rs`); lowering them to
5 an hour and 10 a day is a small change in that repository. `OPENVANILLA_GUESTS=0` turns guests off.

### 3.4 GitHub: protect `main`

GitHub -> the repository -> **Settings -> Branches -> Add branch protection rule** (or Rulesets):
- Branch name pattern `main`.
- **Require status checks to pass**: `realm scripts / test` (and the launcher's tests).
- **Do not allow force pushes**, **do not allow deletions**.
- Settings -> **Actions -> General**: "Read repository contents" for the default token; untick "Allow GitHub
  Actions to create and approve pull requests".
- Settings -> **Secrets**: only `WU_DEPLOY_SSH_KEY`, `WU_KNOWN_HOSTS` and the release secrets you know.

### 3.5 The SOAP bridge password

The realm service calls the portal's bridge with its SOAP login. Find its password in the realm service's
settings (`SOAP_PASS` or the SOAP URL there) and put it in `/srv/wrath/portal.env` as `BRIDGE_PASS=<it>`; then
run **signin** again. From then on the bridge checks it. Test: make a new account on the site; it must be able to
log in to the game.

### 3.6 Database: one login per service, not root

Today the login and world servers use MySQL's root. Make them their own login (on the server):

```
docker exec -it ov-ac-database mysql -uroot -p
CREATE USER 'acore'@'%' IDENTIFIED BY '<a new long password>';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, CREATE TEMPORARY TABLES, LOCK TABLES
  ON acore_auth.* TO 'acore'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, CREATE TEMPORARY TABLES, LOCK TABLES
  ON acore_world.* TO 'acore'@'%';
GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, ALTER, INDEX, DROP, CREATE TEMPORARY TABLES, LOCK TABLES
  ON acore_characters.* TO 'acore'@'%';
-- the bots' database too, if there is one (SHOW DATABASES; look for acore_playerbots):
GRANT ALL ON acore_playerbots.* TO 'acore'@'%';
```

Then in the compose file, the three `AC_*_DATABASE_INFO` lines: `root;${DB_ROOT_PASSWORD}` ->
`acore;${DB_ACORE_PASSWORD}`, and `DB_ACORE_PASSWORD=<it>` in `/srv/wrath/.env`. Restart with the 5-minute
warning. Keep root for backups and `docker exec` only. (The server's update steps use root inside the database
container; that stays.)

### 3.7 SOAP accounts

AzerothCore's SOAP needs a GM level 3 account, and that account may run any console command. So:
- one SOAP account per user of it (the portal, the signup service, the Discord bridge), each with its own long
  password, so one leak can be shut off alone (`account set password`, or `account delete`);
- SOAP stays on the server only (`127.0.0.1:7878` and the internal network; never published);
- the portal only sends its own fixed commands, and the bridge only lets the realm service run the list in
  `BRIDGE_ALLOW` (account create/password/delete, kick, ban, announce...).

## 4. Monthly checklist (10 minutes)

1. `tools\security\Caddy check.bat`: read the saved file. Anything published that shouldn't be? Any new site
   block without the body cap?
2. `fail2ban-client status wrath-auth` and `sshd` on the server: a sudden jump means someone is trying.
3. `iptables -S WU-LIMIT` still there (after Docker updates).
4. GitHub: Settings -> Deploy keys and Secrets: nothing you don't know. Actions: no failed `realm scripts` deploys.
5. `/root/.ssh/authorized_keys`: your key, and the deploy key **with** `command="/srv/wrath/luaup-ci.sh"`. Nothing else.
6. Update the server: `apt update && apt upgrade`, then reboot in a quiet hour (the firewall comes back by itself).
7. Images: the realm runs `:master` images. Note the image IDs (`docker images`) before an update so you can go
   back; pinning to a dated tag or digest is better once the realm is stable.
8. Rotate one secret a month (SOAP passwords, `BRIDGE_PASS`, the deploy key via the setup .bat).
9. The Admin Console's audit log: staff actions you don't recognise.
10. Backups: restore last week's dump into a scratch database once a quarter.
