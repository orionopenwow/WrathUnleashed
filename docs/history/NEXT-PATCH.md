# Next big patch (WrathUnleashed + Open Vanilla site/launcher)

Everything below goes out together. Claude runs the live smoke test after it is applied.

## In the patch
**Browser client (new build, being packaged)**
- Keyboard and clicks in the world: WASD, Enter for chat, the action-bar keys, gossip options (Instant 80).
- UI scale: the interface sized correctly on big windows (login, character select, in game); `?uiscale=` override.
- Forever UI fidelity: tiling, rotation, highlight glows, word wrap; overlap fixes from the live screenshots.
- Faster load: the wasm is fetched first, a 14 MB brotli copy is served, and the loading cover lifts once the ground is in.

- Keyboard root cause found live: `WTF\DefaultBindings.wtf` was missing from the streamed files, so every key shipped unbound. Fix: the client gets built-in default key bindings, and the slice now includes the file (`stream\slices\mini.json`, `boot-manifest.json`).
- Memory: with auto sign-in, the login screen (its model, music and art) is never loaded, and pre-game scenes are freed once you're in the world.

**Streamed slice (`stream\Make mini slice.bat`, after the new client)**
- Adds the key-bindings file, Ulduar, Eye of Eternity, Onyxia and Ruby Sanctum (all raids), and dungeon content from level 10.

**Realm (no client needed)**
- Instant 80: the PvE set equipped and spell bars filled for all 27 specs (`Update realm scripts.bat`).
- New characters: Apprentice Riding and their race's mount from level 1.
- Levelling rates: 3x XP, 2x rested, reputation and skill-ups (`Set levelling rates.bat`).
- Stop slow-load kicks (10-minute idle limit).

**Site and launcher (OpenVanilla repo, already placed in the folder)**
- The launcher shows WrathUnleashed only, with live players/bots from status.json. PLAY > Browser opens /wrath, and PLAY > Online uses your own 3.3.5a folder (realmlist set automatically).
- Duels and Boss Fights are marked closed; game.html and portal.html forward to the Wrath page.
- Guards so the old 1.12 hotpatch and realm scripts can't touch the Wrath server.
- The hero line is hidden behind a TODO for you to write (preview: `index.html?preview=1`).

## Order to run
1. `stream\Update browser client.bat` (the new build, once it's on the Desktop)
2. `stream\Make mini slice.bat` (clears the old slice first)
3. `realm\Update realm scripts.bat`
4. `realm\Set levelling rates.bat` (announces a 5-minute restart)
5. `OpenVanilla\dev\Ship.bat`, then `dev\Release.bat` with the next version (1.56.0)
6. `Ship WrathUnleashed.bat`

Steps 3–4 are already live (you ran them on 24 October); re-run them only if they change again.

Until step 5's Release is out: don't run `dev\Server.bat 1`, `Ship_Release.bat` or the hotpatch workflow by hand.

## Still yours to write
- The home page hero line and the link-preview text (still "Vanilla Remastered").
- A WrathUnleashed news card for the launcher (`www/downloads/live.src.json`).
- The realm tagline, summary and rules (`www/realms/wrathunleashed.json`).
