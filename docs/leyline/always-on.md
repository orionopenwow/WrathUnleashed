# Always-on realms

Two ways to give the Leyline realm list a realm that stays up for good, in as few steps as we could make it. A realm someone leaves running is one fewer that we have to run, and players get more places to go.

- **A. Start a new always-on realm**, for example a Vanilla+ realm, on a spare PC or a small Linux server you rent. Five steps.
- **B. Already run a server?** Put it on the list without changing it. Four questions.

Either way the realm talks out to the Leyline relay over one connection. You open no ports, nobody sees your address, and it is listed within a minute.

## A. A new always-on realm

### What you need

- A machine that stays on. A spare PC works, or a small Linux server (a "VPS") with 4 GB of memory, 2 cores and about 30 GB of disk.
- Your own copy of the game, of the client the realm is for. The kit reads the map data it needs from your game folder once, on that machine. **We never send game files and the kit never downloads them.** On a rented server, copy your own game folder there first.

### Five steps

1. **Install Docker.** Windows or macOS: [Docker Desktop](https://www.docker.com/products/docker-desktop/). Linux: `curl -fsSL https://get.docker.com | sh`.
2. **Get the host kit.** Download [the host kit zip](https://github.com/orionopenwow/Leyline/releases/download/host-kit/WrathUnleashed-host-kit.zip) and unzip it. On a Linux server:

```
curl -fsSLO https://github.com/orionopenwow/Leyline/releases/download/host-kit/WrathUnleashed-host-kit.zip
unzip WrathUnleashed-host-kit.zip && cd "Leyline host"
```

3. **Tell it where your game folder is** (only if it doesn't find it by itself): `export WU_WOW_DIR=/path/to/your/game`.
4. **Start it, always on:**

```
bash leyline host --ruleset vanillaplus --public --always-on
```

It asks for the realm's name and your GM account name; everything else comes from the line above. On Windows, double-click `Host a Leyline realm.bat`, type `vanillaplus` for the profile and `public`.

5. **Make your GM account** on your own join link (the command prints it; `leyline status` shows it again), with a password only your browser sees.

That's it. The first start takes 5 to 20 minutes (the databases). Your realm is on the list within a minute of starting, and `--always-on` makes it come back by itself after a reboot.

### The rulesets for an always-on realm

| Ruleset | What it is | Players use |
|---|---|---|
| `vanillaplus` | **Vanilla+**: the original world only, level 60, 1.5x experience, the later races and classes closed. Made to stay up. | the Wrath client, the browser and the launcher |
| `progression` | 1x from level 1, each character moves through the three eras at their own pace. | the Wrath client, the browser and the launcher |
| `main` | The full world from level 1 at 3x, with an optional boost. | the Wrath client, the browser and the launcher |
| `cmangos-1.12.1` | **True Vanilla**: a plain realm on the CMaNGOS core, for the Vanilla client itself. The kit builds it from source on your machine. | their own Vanilla client |

Vanilla+ plays on the Wrath client, so anyone with the launcher or a browser can join. True Vanilla needs players to have the Vanilla client.

### Always on, in plain words

- Every container of the realm restarts by itself if it stops.
- `--always-on` makes Docker start when the machine boots (on Linux; it asks for root once if needed). With Docker Desktop, turn on Settings > General > "Start Docker Desktop when you sign in", and keep the PC from sleeping.
- After a reboot, `leyline status` tells you it's back.
- Updates: run the same command again. It keeps the realm, characters and links.

## B. Put a server you already run on the list

For a server you already run on any core (AzerothCore, TrinityCore, CMaNGOS, VMaNGOS and the rest), on this PC, a server or your own network. Only a small helper runs next to it. It lists your server and passes the relay's players on to your login server. **It never changes your server**: not its realm list, accounts, GM rights or files. It has no database login at all.

1. **Install Docker** and **get the host kit** (steps 1 and 2 above).
2. **Run the link command.** Linux or macOS: `bash leyline link`. Windows: double-click `Link my server.bat`.
3. **Answer four questions:**
   1. its name on the realm list;
   2. its login server, as this machine reaches it (default `127.0.0.1:3724`);
   3. its world server (default `127.0.0.1:8085`);
   4. the client it's for: `vanilla`, `tbc` or `wrath`.
4. **Turn off your login server's wrong-password IP ban.** Every relay player arrives from the helper's address, so one player's typos would lock everyone out. Set `WrongPass.MaxCount = 0` in your login server's config (`authserver.conf` or `realmd.conf`). The relay limits wrong passwords per player instead.

That's it: it's on the list within a minute. Players still make accounts the way your server already does, and the realm address your server hands out must already work for players (it's the one they use today).

Later: `leyline link status`, `leyline link stop` (offline at once, off the list after 6 hours), `leyline link remove`. Running `leyline link` again keeps the same realm id. Add `--always-on` to make it come back after a reboot.

## Claim it for your account

A listed realm shows as "Unclaimed" until you claim it with your Hero Key. The site gives you a one-time token; you run `leyline claim TOKEN` (Windows: `Realm tools.bat claim TOKEN`). Only the machine that holds the realm's key can claim it. The site's "Claim a realm" page is coming (see [Hero Key](hero-key.md)).

## If something's wrong

| What you see | What to do |
|---|---|
| "Docker is installed but not running" | Start Docker (Linux: `systemctl start docker`), then run the command again. |
| Not on the list after a few minutes | `leyline status` (or `leyline link status`). "Not connected": the machine can't reach the internet on port 443. |
| Players can't get past the login | The realm list needs your login server to answer the helper: check the addresses with `leyline link status`. On Linux the helper shares the machine's network, so `127.0.0.1` is the machine itself. |
| Players log in but can't enter the world | (Linked servers) the realm address your server hands out doesn't reach players. Set it to the public address players use today. |
| Everyone gets "too many wrong passwords" | (Linked servers) step 4: turn off the login server's wrong-password IP ban. |
| It didn't come back after a reboot | Linux: `sudo systemctl enable docker`. Docker Desktop: start it when you sign in. |

More: the [Hosting](hosting.md) guide covers every command and preset.
