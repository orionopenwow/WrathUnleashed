# Forever UI in the streamed browser client

The streamed client at `wrath.openvanilla.app` (the gated "mini" slice) now gets Forever UI, the same
way your own install does, and its files are in the fast-load prefetch. **You don't need a new
wenilla-host build.**

## What you run

1. Copy everything in this folder into `WrathUnleashed\stream\`, merging `server\`. This replaces
   `server\slice-install.sh` and `server\patch-index.sh`. Each one gets a small hook, so that
   **Make mini slice.bat** and **Update browser client.bat** put Forever UI back after every new
   slice or client upload.
2. Run **`Add Forever UI to the stream.bat`**. It takes Forever UI from the first place it finds:
   - a folder or zip you pass to it;
   - your WoW folder (`foreverui-installed.txt` / `wow-folder.txt`), which **Install Forever UI.bat**
     already filled;
   - `fui-src.tgz`;
   - the GitHub zip.

   It packs only Forever UI's files: `Interface\AddOns\ForeverUI`, `Interface\ForeverUI` and
   `Interface\GlueXML\ForeverUI*`. That is about 330 MB, 803 files. It sends them with the server
   scripts as **one tar on stdin over one SSH**. It is safe to run again: a second run replaces the
   first.
3. Deploy the portal change, `wrath_portal.py`. Copy it over the fastloop copy and run
   **Update sign-in and warm-up.bat**, or let the stream kit carry it, as before. The diff is in
   `wrath_portal.diff`.
4. To undo, run **`Remove Forever UI from the stream.bat`** (one SSH). It puts the slice, its tier
   lists, `GlueXML.toc` and the client's boot list back exactly as they were uploaded.

Players who want the stock look add `?foreverui=0` to the page address. To give everyone the stock
look without removing the files, set `WU_FOREVERUI=0` in `portal.env`.

## How it works (server: `/srv/wrath/stream`)

- **The overlay** is in `overlays/foreverui/`, in game-path layout: the one real copy. `fui-overlay.py`
  hard-links into `slices/mini` the files that the slice does not have, so they take no extra disk
  space. Files the slice already has are left alone. At home the archive copy beats loose files too.
  The stray `Interface\Minimap` arrow is not taken for the same reason.
  - **GlueXML.toc** is the one exception. It is rebuilt from the slice's own stock copy with
    `ForeverUIGlue.xml` added before `GlueLocalizationPost.xml`, and the stock copy is kept.
  - Everything the script does is recorded in `slices/mini/.overlay-foreverui/`. wenilla-host
    neither lists nor serves dot folders. That record makes removing it exact and re-applying it
    idempotent.
- **Why merge into the slice instead of a second layer:** wenilla-host has a single `--patch`
  folder. With `--only-listed` (wu-play), only that folder is served: the loose `Interface` layer is
  off, and there is no second patch flag.
  - Docker nested bind mounts can't add files into an existing read-only folder such as `GlueXML`.
  - Merging needs no host change. A separate patch layer would need `--patch` to accept several
    folders, both in `read_layered`/`patch_file` and in the `__index` walk.
- **`/data/__index`** is built by wu-play from the slice folder and cached until restart.
  `fui-install.sh` restarts wu-play and checks through wu-portal that the index lists
  `Interface\AddOns\ForeverUI\ForeverUI.toc`. The client's web addon scan (`discover_web`) finds the
  addon from that index.
- **Backups:** scripts that get replaced are saved to `overlays/backup/<name>.<date>`. The first
  untouched `boot-manifest.json` is saved there too. The stock toc and tier lists are kept in the
  slice's own record.
- **Disk:** before unpacking, the server checks that it has room for the upload plus 2 GB, the same
  margin as `slice-install.sh`.

## Fast load: the prefetch

The client (`boot.js`) has two kept prefetches.

- **The boot list** (`www/boot-manifest.json`) is fetched beside the wasm, before the first screen.
- **The interface prefetch** runs at the first glue screen, from `/data/__tier/0.txt`. If there is
  no tier list it falls back to `__index`. It takes, by prefix: FrameXML, GlueXML and
  `AddOns\Blizzard_*` text, then the interface `.blp` files minus the big folders, up to 160 MB.

Left alone, Forever UI would be missed in three ways:

- The glue files load before the interface prefetch starts.
- `AddOns\ForeverUI\*.lua` matches no prefix.
- None of its files would be in `0.txt`.

Renaming the folders is not an option: the addon must be called `ForeverUI`. So the server edits
the lists:

- **`boot-manifest.json` (+246 names, about 10.7 MB):** all 141 Forever UI text files (the glue
  ones and the addon's) plus up to 8 MB of the login art the glue code names (smallest first,
  credits excluded). Each of those would otherwise be one blocking round trip of about 185 ms; the
  141 text files alone come to about 26 s. The names are under a `foreverui_overlay` key, so they
  come out exactly.
- **`.tiers/0.txt` + `index.json`** list all 803 files, in two marked blocks:
  - the first block goes **ahead of** the stock entries: the text, then 48 MB of the art the code
    names. This way Forever UI's own frames win the 160 MB art budget over the stock art they
    replace;
  - the rest goes after the stock entries.

  "Download this section" therefore covers all of Forever UI, and the header and index counts are
  kept right. The size of the first block can be changed with `FUI_TIER0_FIRST_MB`.

I tested against the 18:18 `boot.js` (copy in `tests/client-ref/`). The tier-0 interface prefetch
queued Forever UI art first, and `?foreverui=0` still turned it off.

**Warning:** in the current `bw/web/boot.js` (18:30) and `pcdist-release/boot.js` (18:38), the
interface-prefetch block is gone. `prefetchUi`, `UI_BOOST` and `UI_PREFETCH_CONCURRENCY` are still
called but no longer defined, which looks like an unfinished merge. If it ships like that, only the
boot-list part of this change helps.

## Portal (`wrath_portal.py`)

`env_js` adds `foreverui: "1"`. In the client the env object outranks the query string, so
`/__env.js` also copies `?foreverui=` from the page URL into the env. Without that, `?foreverui=0`
could not turn it off. In the stream the env value also outranks `/console foreverUI 0`; use
`?foreverui=0` instead.

## Tests

- `bash tests/test_fui_stream.sh <mod-forever-ui checkout> [stream2 kit] [wenilla-host]`: 41/41
  pass (log in `tests/test_fui_stream.log`). It uses a fake docker, and the **real Linux
  wenilla-host** serving `--only-listed` as wu-play does, with the server command taken from the .bat
  and the tar on stdin. It checks that:
  - every Forever UI file is listed in `__index` and served byte-exact, and the patched
    `GlueXML.toc` is exactly the stock one plus one line;
  - the tier 0 list and the boot list are filled as described above;
  - a second install gives the same result;
  - a slice re-upload and a client re-upload get Forever UI back;
  - removing it restores everything byte-for-byte, and a bad upload is refused without changing
    anything;
  - the page env gives `foreverui=1`, and `?foreverui=0` turns it off.
- `tests/test_stream.py`: the portal tests plus two env checks. All pass.
- The stream kit's `tests/test_server_scripts.sh` still passes 44/44 with the hooked scripts.

## Licence

Forever UI is © Adrestie, GPL-2.0 (github.com/Adrestie/mod-forever-ui). In repo mode the .bat
includes its `LICENSE` as `Interface\AddOns\ForeverUI\LICENSE-GPL-2.0.txt`. The addon is
shipped as its own Lua/XML source.

Its art comes from the modern WoW client. Like the slice built from your own files, it is served
only behind sign-in, in the gated stream: wu-play behind Caddy's `forward_auth` and the `wu_play`
cookie. It is never published anywhere public; keep it that way.

One exception: `boot-manifest.json` is on the ungated client-file list, so it is readable without
signing in. It carries only file names, which are the same as in the public repo. No art or code is
served there.
