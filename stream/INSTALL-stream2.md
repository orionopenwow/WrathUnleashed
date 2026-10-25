# Installing stream2 over WrathUnleashed\stream

Copy these from `stream2\` into `C:\Users\campw\Desktop\WrathUnleashed\stream\` (same relative path).

**Replace**

| file | what changed |
|---|---|
| `Make mini slice.bat` | kit also carries `lua\tiers_lua.py`, `server\www-patch.py`, `www-files\`; the page edits run on every upload; the slice and its `mini.json` go up in one tar (3 SSH connections in all, was 5) |
| `Upload a mini slice.bat` | one SSH connection (was 4): `mini.json` travels in the tar |
| `README-stream.md` | tiers/order, level-1 rules, size report, own files, download sections |
| `wrath_portal.py` | `/wrath/play?mode=own`, both buttons, own-mode `/__auth` and `/__env.js` |
| `wenilla-host-stream.patch` | the whole Rust change against the tree's index (adds `size.rs`, tier lists, `/data/__tier`, order/box/tiles) |
| `bin\wenilla-host`, `bin\wenilla-host.exe` | `--size-report`, `order`, boxes, tier-tagged displays, `.tiers` lists, `/data/__tier` |
| `lua\ov_slices.lua` | data-driven tiers, level-1 rules, Ebon Hold, LFG by level, `.play` submenus |
| `lua\lfg_ids.py` | also writes `OV_STREAM_LFG_LEVEL` |
| `slices\mini.json` | `order` + keyed tiers (54) in the owner's priority: base, Dalaran, arenas, Violet Hold/ToC, Stormwind, Orgrimmar, Northshire, Valley of Trials, Ebon Hold, Naxx/OS/VoA, battlegrounds, heroics, classic dungeons by level, TBC, Wrath levelling, ICC last; `maxTier` = last tier (the budget decides). Reorder by moving keys (keep `base`, `dalaran` first) |
| `server\displays.py` | tier column, `--instances`, `order` |
| `server\stream-up.sh`, `stream-down.sh`, `stream-switch.sh`, `slice-install.sh`, `stream-lib.sh` | tier table + LFG levels (`realm_tables`), `WU_OWNFILES`, `mini.json` in the upload tar, www edits, SIGPIPE-safe checks |
| `tests\test_lua.py`, `tests\test_ov_slices.lua`, `tests\test_server_scripts.sh`, `tests\test_stream.py` | the new rules and modes |

**New**

`Size report.bat`, `lua\tiers_lua.py`, `server\www-patch.py`, `www-files\` (ownfiles.js, ownfiles-worker.js,
mpq.js, chain.js, sections.js, sections-worker.js, index.html and boot.js for reference, web.patch),
`tests\sections.browser.test.cjs`.

**Unchanged** (keep yours): `Record a capture.bat`, `server\patch-index.sh`, `sql\ov_stream_accounts.sql`,
`slices\boot-manifest.json`, `slices\world-manifest.json`, `www\` (your client build: `www-patch.py` edits
the uploaded copy on the server).

**Then**: run `Size report.bat` (optional, to see the costs), reorder `order` in `slices\mini.json` if you
like, run `Make mini slice.bat`, then on the server once `bash /srv/wrath/stream/stream-up.sh` (it
installs the new realm tables and sets `WU_OWNFILES=1`). `ov_main.lua` needs no change.
