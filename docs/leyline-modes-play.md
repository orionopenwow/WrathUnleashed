# Leyline Modes: every game mode one click away

The launcher's **Modes** page (after Realms) and the **Games** section at the top of
[/wrath/modes](https://play.openvanilla.app/wrath/modes) list the same game modes, from one catalog.

## The catalog

`stream/playmodes.json`, checked by `python3 -I stream/playmodes.py --check` (and by `stream/tests/test_playmodes.py`).
The site serves it at `https://play.openvanilla.app/wrath/modes.json`. The launcher (`launcher/src-tauri/src/modes.rs`)
reads that, keeps the last good copy, and falls back to the copy built into Leyline (the same file, `include_str!`).

Each entry: `id`, `title`, `line` (one plain sentence), `kind`, `players` `{min, max or null}`, `status`
(`live` / `coming`), `start`, and `credit` `{by, license, source, note?, more?}` for anything that isn't ours.

| kind | runs where | start | PLAY |
|---|---|---|---|
| `realm` | our realm, through `ov_playmode.lua` | `{"go": "mode:<id>"}` | browser link or desktop handoff |
| `offline` | the browser client, no server (the player's own game folder) | `{"path": "/wrath/..."}` | opens that page |
| `realm-type` | its own server type, hosted with the Host pack | `{"host": "<preset>"}` | HOST IT (the Host page) |

`coming` entries show "Coming soon" and their source link, never a PLAY button.

To add a realm mode: add the entry, add the same id to `MODES` in `realm/custom/lua_scripts/ov_playmode.lua` (how it
starts: the mode's own OVMOD message), run the tests. The test fails if the two lists differ.

## One click in the browser: `?go=mode:<id>`

1. PLAY opens `https://play.openvanilla.app/wrath?go=mode:<id>`.
2. The portal signs the player in as usual. `remember_go` (stream/wrath_portal.py) sees `mode:`, checks the id
   against the catalog's live realm modes, and sends one SOAP console command for that game account:
   `ovplay go <ACCOUNT> <id>` (at most 20 a minute per account, the same as other go intents).
3. `ov_playmode.lua` keeps it in `ov_playmode_intents` (auth DB) for 10 minutes, checks the id against its own
   table again, and acts at once if a character is online, else 7 s after the account's first login after the click,
   but only if that login comes within 5 minutes of it. It is used once. Any other login (a reconnect after a
   disconnect, another character, an older click) never starts a round: it says "Waiting for you: ... type
   `.playmode <id>`", and `.playmode` starts it.
4. Starting goes through the mode's own script, exactly as its own window's button (`OVMod.Dispatch`):
   * Minigolf: `wugolf start` (first course). Alone it tees off at once; in a party the party nearby is invited and
     the Golf window opens for Tee off.
   * Bumper Balls, Coin Dash: alone `wumodes solo` (runs at once); in a party `wumodes host` (a lobby, window opened).
   * Community modes: opens the Leyline Modes window (Modes.lua `open`), where the GM-approved modes are.
   * In combat, dead, or in a battleground: says why and keeps the intent; `.playmode` tries again. A brand new
     character's first login is never interrupted.

Nothing in `/__gate` or `/__env.js` changed: like the Workshop's `?go=w:<id>` and the hub's `?go=q:`, the intent
lives on the realm, keyed by the signed-in game account, so the page never carries it and the client is never
trusted with it. `go_param` drops `mode:` values, so the game page sees no `go` for them.

## One click on the desktop: the LeylinePlay handoff

Simplest robust mechanism: a tiny addon the launcher writes into the player's own 3.3.5a client.

1. PLAY (Home's play setting is "online") calls `mode_prepare_desktop(client, id)`: only a live realm mode, only a
   3.3.5a client. It writes `Interface/AddOns/LeylinePlay/`:
   * `LeylinePlay.toc` (`## Interface: 30300`, `## SavedVariables: LeylinePlayDB`),
   * `Pending.lua`: `LEYLINE_PENDING = { mode = "<id>", nonce = "<16 hex>", made = <unix seconds> }`,
   * `LeylinePlay.lua` (source: `launcher/src-tauri/src/modes/LeylinePlay.lua`).
2. Then the page calls the existing `play` command on the official realm (realmlist written, game started).
3. After login the addon waits 8 s and sends one OVMOD whisper to itself: `wuplay\tgo\t1/1\t<id>`.
   `ov_playmode.lua` treats it exactly like a player typing `.playmode <id>`: id checked, one start every 5 s.
4. The addon never asks twice for the same nonce (saved variables), ignores a pick older than 15 minutes, and does
   nothing on a realm without `ov_playmode.lua` (an addon whisper to yourself).

Why not a server-side intent for the desktop too: the launcher has no game-account identity (the social sign-in is
optional and not tied to the game account), and it never handles passwords. The addon needs no network and no
account. The only thing the client "asks" for is to start a minigame, which any player may do by typing a command.

## Commands

* Players: `.playmode` (the list, or the waiting pick), `.playmode <id>`, `.playmode cancel`.
* Console / SOAP only: `ovplay go <ACCOUNT> <id>`, `ovplay clear <ACCOUNT>`.

## Live test

Deployed first: `scripts` (ov_playmode.lua, ov_golf/ov_modes unchanged), `foreverui` (Modes.lua, Golf.lua `open`),
`signin` (wrath_portal.py, modes.py, playmodes.py, playmodes.json).

```sh
curl -s https://play.openvanilla.app/wrath/modes.json | python3 -m json.tool | head -20     # schema 1, 7 modes
curl -s https://play.openvanilla.app/wrath/modes | grep -c 'id="mode-'                       # 7
```

In the owner's browser, signed in: open `https://play.openvanilla.app/wrath?go=mode:coin-dash`, pick a character,
enter the world. About 7 s later chat says `[Play] Starting Coin Dash.` and Coin Dash runs. On the realm console:
`ovplay go <ACCOUNT> minigolf` answers `ovplay ok: ... (10 min)`. In game: `.playmode` lists the modes.
