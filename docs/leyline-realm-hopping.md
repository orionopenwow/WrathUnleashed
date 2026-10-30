# Leyline realm hopping (MVP) and the next step: Hero Key sign-on for Beacons

## What the MVP does

Join in the in-game Leyline window reloads the browser game on that community realm (a Beacon), in the same
tab. "Back to Wrath" is one click in the window and on the page.

### The bridge (hosting/relay/wurelay/relay.py)

- `wss://<relay>/ws/<realm id>/auth` and `/ws/<realm id>/world`: a WebSocket per game connection, turned into a
  stream on the Beacon's existing multiplexed tunnel (service 3724 or 8085 on the host's agent). The older
  `/r/<id>/ws/<port>` path stays.
- Framing is wu-play's: binary messages, one TCP read per message, the bytes reassembled as a stream; either
  side's close closes the other. `?host=` is ignored.
- It only reaches a realm whose agent is connected and signed in (Ed25519 realm key). The relay never dials a
  host; nothing in the request names one.
- Limits: the realm's own caps (streams, KB/s, GB/day, per-IP streams and connection rate), plus WebSocket
  upgrades per IP per minute (`RELAY_WS_PER_MIN_PER_IP`, 30), browser streams in total (`RELAY_MAX_WS_TOTAL`,
  1024), all streams in total (`RELAY_MAX_STREAMS_TOTAL`, 4096), and an Origin allow-list
  (`RELAY_PLAY_ORIGINS` + `RELAY_SITE_ORIGINS`; no Origin = a native tool, allowed like raw TCP).

### The hop, step by step

1. Join on a live community realm: `Leyline.lua` sets the Lua global `WUUI_LEYLINE_HOP = <id>` and whispers
   `WULY H:<id>` to itself (`ov_leyline.lua` echoes it; that only matters to the addon itself, see below).
2. The page (`wrath-page.js` `watchHops`) polls the global every second while the bridge is up
   (`wenilla.lua`: take it and clear it), and goes to `https://play.openvanilla.app/wrath?go=r:<id>` (own game
   files: `/wrath/play?mode=own&go=r:<id>`). The poll is the trigger: the web client gives CHAT_MSG_ADDON to the
   addons but not to the page bridge (see "What the real client does"). The global is the authority: someone
   else's whisper can't make a page hop. Leyline.lua clears an untaken global after 8 s (the desktop client).
3. The portal signs the player in as usual and carries `go` to the gate. `/__gate` checks the id against the
   relay listing (live realms only) and marks the session as a hop. Anything else lands on Wrath.
4. `/__env.js` for a hop session: `hop`, `hop_name`, `hop_ws`, `hop_join`, `host` (the relay), `home`, and no
   Wrath login.
5. `wrath-early.js` (before the client starts) wraps `WebSocket`: the client's own `/ws/3724` becomes
   `<hop_ws>/auth`, any other port `<hop_ws>/world`. It fills in the login this browser keeps for that realm
   (`localStorage["wu.leyline.login.<id>"]`).
6. No login kept yet: the page frames the realm's join page (`/join/<id>?hop=1&from=<origin>`, served with COEP,
   CORP and `frame-ancestors` for the play origins only). The player makes an account there (SRP verifier made
   in the browser, as before) or types one they have. The join page hands the login to the game page only
   (postMessage to an allowed origin). The page keeps it and reloads. The login is never sent to our servers;
   the game proves it to the Beacon with SRP.
7. "Back to Wrath": the page bar's button, or the window's (it hops to `wrath`), goes to `/wrath?go=h:dalaran`, a
   fresh session with no hop that lands in Dalaran (the go intent, `ov_go.lua`; a brand-new character's first
   login is never moved, and where level-1 characters start is unchanged).

### Known limits

- The streamed slice only has its own part of the world. On a Beacon, the full world needs "Play with my own
  game files" (that mode is kept across a hop).
- A hop goes through the Wrath sign-in, so Wrath's realm must be answering.
- Private Beacons aren't listed, so they can't be hopped to yet (the bridge takes `?invite=`).
- The kept password is in this browser's localStorage, readable by script on the game's origin.
  "Use another account" on the bar forgets it.

## The Dalaran Hangout (the owner's realm as a Beacon)

The owner hosts it; nothing runs anywhere but on the realm's own box. `hosting/hangout/hangout-up.sh` (the
`hangout` step; `hangout-off` takes it off Leyline, keeping its key) runs two containers next to the realm:

- `wu-hangout-agent`: the host kit's own agent with `setup.py official`'s host.json: public, `signup: off`,
  `official: true` (the agent never touches `acore_auth.realmlist`, accounts or GM rights), players and bots
  from `http://wu-portal:8091/wrath/status.json`. Its key is made on the box (`state/realm.key`, 0600). It
  tunnels to the relay's web side on the same box (`ws://<RELAY_HTTP_BIND>/agent`) and is listed as
  "Dalaran Hangout".
- `wu-hangout-auth`: a second login server for relay players: the realm's own authserver image and settings
  (copied from `ov-ac-authserver`), the same database, no published port, but `AC_WRONG_PASS_MAX_COUNT=0`.
  Every relay player reaches a realm from the agent's address; the realm's own IP ban (10 wrong passwords,
  10 minutes) would lock every hopper out at once. The relay counts wrong passwords per player IP instead
  (`RELAY_AUTH_FAILS_PER_IP`, 10 in `RELAY_AUTH_FAIL_WINDOW_SECS`, 600): it reads only the authserver's
  logon answers. That protects every Beacon the same way.

Accounts: the hangout IS Wrath, so a hop into it uses the player's own Wrath login. `/__env.js` for that hop
session carries `hop_home: "1"` with the session's own `user`/`pass` (the same account the portal already made;
the relay and the agent carry only SRP, never the password), and `wrath-early.js` keeps it (any other Beacon:
dropped, as before). No join page, no second account, nothing typed. The relay refuses signups for it.

Dalaran: `/__gate` hops to it only while it's live on the listing; the portal turns `go=r:<hangout id>` into
the `h:dalaran` go intent, so hop arrivals land in Dalaran; "Back to Wrath" lands there too. The hangout is
first on `/wrath/realms` (with "Play in Dalaran" straight to `/wrath?go=h:dalaran`, no relay needed) and in the
in-game list (`leyline-fetch.py` reads `/srv/wrath/hangout-realm.id`). Limits: through the relay it shares the
per-realm caps (`RELAY_MAX_STREAMS` 128 = 64 players at once, `RELAY_KBPS`); the site's button and "Back to
Wrath" go direct.

## The Leyline Sample Hangout (temporary, 2026-10-29)

Community-hosted realms are the main Leyline network; the official realm becomes a temporary, lighter **Leyline
Sample Hangout** to try the game. It is the main realm with an overlay (`realm/profiles/sampler.env`), switched by
`realm/sampler.sh` (Autopilot `sampler-check`, `sampler`, `sampler-off`):

- **Streamed browser sessions** (marked by the sign-in gate) get Dalaran, their starting area (Northshire Valley,
  the Valley of Trials, Ebon Hold for Death Knights) and every streamed dungeon, raid, arena and battleground. The
  capitals close (`OV_SAMPLER_CITIES=1` opens them). Elsewhere `ov_slices.lua` brings them home with "Add your own
  3.3.5a game folder to explore the whole world ... Or join a community realm from Leyline."
- **Own files** (a desktop client, or "Use my game folder" in the browser, which clears the mark) keep the whole
  world, as on the main realm. With streaming switched off, every session is an own-files session.
- The Dungeon Finder, raids, Companions, the boost, minigolf, Modes, the Workshop, friends and the admin console
  are unchanged. A build area opens on Krasus' Landing (`OV_BUILD_DALARAN=1`).
- 12 random bots, all level 80, living around Dalaran's bankers (`AC_PLAYERBOTS_*` in the overlay); idle grids
  unload after a minute; open-world visibility 75 yards.
- Labels: the realm list name, the play page, `/wrath/realms` and `/wrath/leyline` say "Leyline Sample Hangout"
  and "temporary" (`WU_SAMPLER=1` in portal.env); everyone gets a one-line welcome in game.
- The browser slice `stream/slices/sampler.json` is `mini.json` less the capitals and the Goldshire inn; the
  `slice-sampler` step builds it and `stream/server/slice-serve.sh sampler` serves it beside mini
  (`slice-serve.sh mini` switches back; `sampler.sh off` does it too).

## Website realms: the key is made on the host's PC

`/wrath/host` makes a page id, invite/host secrets and a claim token, never a key. The download (seed v2)
carries those; `setup.py init --seed` makes the key on the PC. The agent's hello carries
`pair_sha256 = sha256("leyline-pair-v1\n" + claim token)`; the website asks `GET /api/pair/<hash>` (rate
limited, first realm to show a hash keeps it, kept in the relay's state file) and from then on shows that realm
id's links and status. Why: keys.py's rule (the key never leaves the host's PC) held for every realm except
website ones, whose key sat in `/srv/wrath/hosted` (and its backups) until the first connect, and in the
downloaded .bat forever. Same steps for the player; the only visible change is that the share and invite
links appear on the page once the PC connects (the realm id comes from the PC's key). Older records (seed v1)
keep working.

## What the real client does (answered from the source, 2026-10-25)

- **WebSocket.** The wasm glue (`wenilla.js`, wasm-bindgen) does `new WebSocket(url)` on the main thread at the
  moment of connecting, against the global, and the URL is `{wss://page host}/ws/{port}?host=...`
  (`benilla-protocol/src/transport/web.rs` `connect_url`; `set_ws_base` is never called). So `wrath-early.js`'s
  wrapper, installed before the module script, is what the client calls, and the returned object is a real
  WebSocket (binaryType and handlers work).
- **CHAT_MSG_ADDON.** It reaches the UI's addons (`benilla-ui/src/script/addon_message.rs`
  `deliver_addon_message`), so the Leyline window's list works. It does NOT reach the page: that function
  calls `fire_event_values` directly, past `fire_event_into`, which is where the bridge's event tap copies
  events. So `wenilla.on('CHAT_MSG_ADDON')` never fires today; the 1 s poll of the global is the trigger. (A
  one-line client fix would be to deliver it through `fire_event_into`; the page needs nothing more.)
- **Self-whisper echo on AzerothCore.** Stock AzerothCore does deliver an addon whisper to yourself
  (`ChatHandler` finds the receiver by name, the level rule skips `receiver == sender`, `Player::Whisper` sends
  CHAT_MSG_WHISPER with LANG_ADDON to the target; `AddonChannel` must be on, the default). With `ov_leyline.lua`
  the original is swallowed and the script answers itself. Either way the page doesn't depend on it now.
- **The framed join page under COOP/COEP.** The game page is `COOP: same-origin` + `COEP: require-corp`
  (wu-play). The relay serves `/join/<id>` with `COEP: require-corp`, `CORP: cross-origin` and
  `frame-ancestors <play origins>`, which is exactly what a require-corp page needs to frame it; tested in
  headless Chromium (`stream/tests/hop-frame.browser.test.cjs`): the frame loads in hop mode, the login comes
  back by postMessage, the page stays `crossOriginIsolated`; without those two headers the frame is blocked;
  an unlisted origin can't frame it. A popup can't work (COOP severs `window.opener`), and a credentialless
  iframe isn't needed. Keep Caddy from stripping the headers (it doesn't today).

## Live test: Wrath's Dalaran -> the Dalaran Hangout through the relay -> Back to Wrath

Run in the owner's browser pane, signed in to play.openvanilla.app. Deployed first: `relay`, `hangout` (its last
lines print the hangout's realm id, below `RID`), `signin`, `client`, `scripts`. Nothing here makes an account
or types a password: every login is the player's own, filled in by the page.

1. **The hangout is live.** On any play.openvanilla.app page:
   ```js
   const L = await (await fetch('https://relay.openvanilla.app/api/listing/realms.json')).json();
   const H = L.realms.find((r) => r.name === 'Dalaran Hangout');
   const RID = H.community.realmId;
   [H.state, RID, H.community.lastHeartbeat]          // 'live', the id, {online: true, players: N, bots: N}
   (await (await fetch(`https://relay.openvanilla.app/r/${RID}/status.json`)).json())   // online: true
   ```
   `https://play.openvanilla.app/wrath/realms` shows Dalaran Hangout first among community realms, with
   "Play in Dalaran".
2. **On Wrath, in the world.** Open `https://play.openvanilla.app/wrath`, pick a character, enter the world. On the
   game tab (wrath.openvanilla.app):
   ```js
   wenilla.state.session.state                         // 'inworld'
   window.__wuHop.status()                             // hop: null, sockets: [], watch.polls > 0 (the 1 s poll runs)
   ```
3. **The in-game list.** Open the Leyline window and read the list (or Esc > Mods & Workshop > Leyline realms):
   ```js
   await wenilla.lua('WrathUnleashedUI.ToggleLeyline()');
   await new Promise((r) => setTimeout(r, 3000));
   await wenilla.lua(`local t = {} for i, r in ipairs(WrathUnleashedUI.Leyline.realms) do
     t[i] = r.id .. '|' .. r.name .. '|' .. tostring(r.live) end return table.concat(t, '\n')`)
   // 'this|WrathUnleashed|true' first, then '<RID>|Dalaran Hangout|true'
   ```
4. **Hop to the hangout** (the window's own Join; clicking Join on that row is the same):
   ```js
   await wenilla.lua(`for _, r in ipairs(WrathUnleashedUI.Leyline.realms) do
     if r.name == 'Dalaran Hangout' then WrathUnleashedUI.Leyline.Join(r) return r.id end end`)
   ```
   Within about a second the tab goes to `play.openvanilla.app/wrath?go=r:<RID>` and comes back to the game at
   `wrath.openvanilla.app/?go=r:<RID>`. If it doesn't: `window.__wuHop.status().watch` shows `polls`, `taken`
   and `error`.
5. **On the hangout.** After the reload:
   ```js
   const s = window.__wuHop.status(); s.hop      // {id: RID, name: 'Dalaran Hangout', base: 'wss://relay.openvanilla.app/ws/<RID>', login: true, home: true}
   s.signedIn                                    // true: the Wrath login, no join page
   !!document.querySelector('#wu-hop-join')      // false
   document.querySelector('#wu-hop-bar').textContent   // 'On Dalaran Hangout · Leyline' + 'Back to Wrath' (no 'Use another account')
   ```
   The character list comes up by itself (same account, same characters). Enter the world, then:
   ```js
   window.__wuHop.status().sockets   // [{from: 'wss://wrath.openvanilla.app/ws/3724', to: '.../ws/<RID>/auth'},
                                     //  {from: 'wss://wrath.openvanilla.app/ws/<port>', to: '.../ws/<RID>/world'}]
   await new Promise((r) => setTimeout(r, 7000));       // the go intent fires 5 s after login
   [wenilla.state.map.id, wenilla.state.zone?.name]     // [571, 'Dalaran'] (or 'Crystalsong Forest', the zone under
                                                        // the city); chat says "[Go] Taking you to Dalaran."
   (await (await fetch(`https://relay.openvanilla.app/r/${RID}/status.json`)).json()).players   // counts you
   ```
6. **Play.** Walk, talk, open a menu: `wenilla.chat('/say hello from the Leyline hangout')`, `wenilla.chat('/who')`.
   A 15-minute idle is fine (the client pings).
7. **Back to Wrath** (the bar's button; the window's own Back says "You're on Wrath now" here, since the hangout
   is Wrath):
   ```js
   document.querySelector('#wu-hop-bar button.home').click();
   ```
   The tab goes to `play.openvanilla.app/wrath?go=h:dalaran`, then the game. Then:
   ```js
   window.__wuHop.status()          // hop: null, sockets: [] (straight to Wrath, not through the relay)
   // in the world, after ~7 s:
   [wenilla.state.map.id, wenilla.state.zone?.name]     // [571, 'Dalaran']
   ```
   The same through the poll, from the hangout: `await wenilla.lua('WUUI_LEYLINE_HOP = "wrath"')`.
8. **Checks that should fail.** `(await fetch('https://relay.openvanilla.app/api/pair/' + '0'.repeat(64))).status`
   is 404. A login with a wrong password through the relay counts against your IP for that realm only
   (10 in 10 minutes, then a 429 for 10 minutes): don't try it on the owner's IP.

A player-hosted Beacon (when one is live) tests the framed join page: Join it in step 4; the realm's join page
opens over the game; the player makes an account there (their own password, typed by them) or signs in; the page
reloads signed in to that realm (`status().hop.login: true`, the login in `localStorage` under
`wu.leyline.login.<id>`). Its world beyond the streamed slice needs "Play with my own game files".

## Next step (design only): Hero Key single sign-on for Beacons

**Built (2026-10-30), behind the `herokey_sso` flag, off by default: see [HERO-KEY-SSO.md](HERO-KEY-SSO.md).** The
build differs from the sketch below in one way: the website signs a per-realm assertion (Ed25519, site key pinned in
the host kit) carrying the per-realm pseudonym and the SRP verifier of a one-time password, instead of the browser
deriving a per-realm key from the Hero Key secret. The rest (per-realm ids, one-time SRP login, the relay passing an
opaque blob, a realm opt-in, bans per pseudonym) is as sketched. The original design, kept for the record:

The goal: hop with no account step and no password kept in the browser. A player's Hero Key identity is their
login on every Beacon that opts in.

- **Identity.** Each Hero Key holder has a key pair already (the website's sign-in). For Leyline, they derive a
  separate per-realm key, so Beacons can't link one player across realms unless the player wants that:
  `k_realm = HKDF(hero_secret, "leyline-realm" || realm_id)`.
- **Account on first hop.** The page asks the relay for a challenge from the Beacon. The page signs it with
  `k_realm` and sends `{realm_id, pubkey, sig, display name}`. The Beacon's agent checks the signature and makes
  (or finds) an account bound to that pubkey. The name is derived (for example `HK` + 10 base32 characters of
  the key's hash). No password is involved.
- **Login.** The 3.3.5a client can only do SRP. So the agent sets a fresh random SRP password on that account
  for this login only (a one-time verifier, valid 2 minutes, one use). It returns the password to the page,
  sealed to the page's ephemeral key so the relay can't read it. The page puts it in the env and the client
  logs in as now. The agent rotates the verifier after use.
- **Trust.** The relay only forwards the sealed blobs. The Beacon host sees a pubkey and a derived name, never
  the Hero Key identity, unless the player shares it.
- **Opt-in.** A Beacon setting: `signup: "herokey"` next to `invite`, `open` and `off`. Old Beacons keep the
  join page flow from the MVP.
- **Revocation.** A player can forget a realm (the page drops it). A Beacon can ban a pubkey.
- **To build:** an agent control op (`herokey_login`), a relay route that passes it through
  (`POST /api/realms/<id>/herokey`, rate-limited like accounts), a page call from `wrath-page.js` before
  `wrath-early.js` needs the login (an extra boot step), and tests with the fake Beacon.
