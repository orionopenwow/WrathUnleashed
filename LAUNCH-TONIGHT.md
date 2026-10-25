# Tonight: WrathUnleashed Brawl for the first 20 testers

The server is play.openvanilla.app (the Hetzner box that ran vanilla). The realm is Brawl, Warden is off. Sign-in is the website's own: Google or a Hero Key at https://play.openvanilla.app/wrath. The old play page there now sends people to /wrath.

**Website (openvanilla.app):** Duels and Boss Fights are hidden, WrathUnleashed is first in the realm list and selected, and Vanilla Remastered shows as offline. That goes live when you run `dev\Ship.bat` in OpenVanilla (after the deploy, so the link works).

| # | Step | Where | Time |
|---|---|---|---|
| 1 | Let "Build custom realm.bat" finish ("Done. The custom realm is up.") | PC | build running |
| 2 | Optional, 5 min: make a level 80 on your local realm, check `.ov`, `.armory`, `/armory`, `.qol` | PC | 5 min |
| 3 | `server\Deploy Wrath to my server.bat`, then type YES. It backs up vanilla, stops it, uploads your build and game data, and starts Brawl | PC → server | 30-60 min (mostly upload) |
| 4 | Check that both ports answer: `Test-NetConnection play.openvanilla.app -Port 3724` and `-Port 8085`. If either fails, open TCP 3724 and 8085 in the Hetzner Cloud Console firewall | PC | 5 min |
| 5 | Open https://play.openvanilla.app/wrath (the deploy opens it), sign in with Google or your Hero Key: it shows your Wrath account (WR0000…) and password | browser | 1 min |
| 6 | `server\Make GM.bat` with that account name | PC → server | 1 min |
| 7 | `Make player package.bat` builds players\WrathUnleashed-Player.zip (browser client plus host, no game data) | PC | 2 min |
| 8 | Send testers the zip and players\README.txt (rewrite it in your words). Each tester gets their own login at /wrath with Google or a Hero Key; nobody needs an account from you | you | — |
| 9 | Play: normal client with `set realmlist play.openvanilla.app`, or the browser via the zip | everyone | — |

**If something goes wrong:** run `server\Rollback to vanilla.bat` to bring vanilla back. Vanilla's databases are saved in `/root/vanilla-backups` on the server.

**Watch while people play:**
- `ssh ... "docker stats --no-stream"` for CPU and memory;
- `docker logs --tail 50 ov-ac-worldserver` for errors.

The box has 8 GB of memory: vanilla used 6 GB, and Wrath with 60 bots should need about 3-4 GB.

**Not done tonight (on the plan):**
- backups on a timer (`server\backup.sh` is ready);
- the website's wording about Wrath (your copy; only the realm list entry changed);
- re-running `openvanilla_realm_up.sh` rewrites the site's Caddyfile and drops the /wrath route, so don't run it while Wrath is live (or ask Claude to put the route back).
