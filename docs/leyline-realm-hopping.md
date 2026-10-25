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
   `WULY H:<id>` to itself. `ov_leyline.lua` echoes it.
2. The page (`wrath-page.js` `watchHops`) sees the echo (CHAT_MSG_ADDON through the bridge), or finds the global
   on its 2 s in-world poll (a realm that doesn't echo), takes and clears the global with `wenilla.lua`, and
   goes to `https://play.openvanilla.app/wrath?go=r:<id>` (own game files: `/wrath/play?mode=own&go=r:<id>`).
   The global is the authority: someone else's whisper can't make a page hop.
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
7. "Back to Wrath": the page bar's button, or the window's (it hops to `wrath`), goes to `/wrath`, a fresh
   session with no hop.

### Known limits

- The streamed slice only has its own part of the world. On a Beacon, the full world needs "Play with my own
  game files" (that mode is kept across a hop).
- A hop goes through the Wrath sign-in, so Wrath's realm must be answering.
- Private Beacons aren't listed, so they can't be hopped to yet (the bridge takes `?invite=`).
- The kept password is in this browser's localStorage, readable by script on the game's origin.
  "Use another account" on the bar forgets it.

## Next step (design only): Hero Key single sign-on for Beacons

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
