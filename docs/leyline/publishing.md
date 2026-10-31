# Publishing

How a mod gets from your folder to players. Read the [Mod format](mods.md) first.

## 1. Package your mod

From the `mods/` folder of the repo:

```
python3 wu-mod.py check my-mod
python3 wu-mod.py pack my-mod -o dist
```

`check` prints each problem with a `fix:` line. It exits with an error until every error is fixed. Warnings don't block.

`pack` writes `dist/my-mod-0.1.0.zip` and `dist/my-mod-0.1.0.zip.sha256`. Packing the same files again gives the same zip, byte for byte, so anyone can check that a zip matches its source.

## 2. Submit a link

Use one path: **Add your project** on the Workshop, at [/wrath/mods/submit](https://play.openvanilla.app/wrath/mods/submit). Sign in, paste your project's public repo link (GitHub, GitLab or Codeberg), pick a category and the client it works with, and write one line about it.

- Most links are listed straight away, credited to you and to the repo's author.
- A link goes to a person's review queue instead of the list when its repo has no open licence, when its text names the game or its publisher, or when it looks like decompiled, leaked, repack or cheat material. You hear nothing more until it is checked; nothing of yours is lost.
- Nothing is downloaded or hosted from a link: players install from your repo.

Want your mod in the packaged catalog (the one the mods step below puts on Wrath)? Put the zip and its `.sha256` in a release on your repo, add it with **Add your project**, and say so in the [Discord](https://discord.gg/hVeUxYwbkr). The team checks it with `wu-mod.py` and adds it to `mods/catalog/<your id>/` in the [repo](https://github.com/orionopenwow/WrathUnleashed/tree/main/mods). The modders' guide in the repo (`mods/README-modders.md`) says realm mods get a human look before they go on Wrath.

The [Leyline Launcher](launcher.md) installs mods from the same Workshop list.

## 3. The mods step

The team puts the whole catalog live with one step: `mods/Put mods on Wrath.bat`, or the Autopilot step `mods`. It uses one SSH connection and runs `stream/server/mods-install.sh` on the server. In order:

1. **Check and pack.** `wu-mod.py catalog` checks every mod. If one fails, nothing changes.
2. **Realm.** Each realm half goes into `lua_scripts/mods/<id>/`, then the realm runs a live `reload ale`. Nobody is kicked. A refused reload, or a Lua error from `mods/`, puts the old scripts back. Unchanged scripts mean no reload at all.
3. **Browser client.** The addon halves, and the generated `WUModCatalog` addon, are laid over the streamed client. A failure here puts the old addons and the old realm scripts back.
4. **Site.** `catalog.json`, `categories.json`, the zips and the screenshots go to the site, swapped in whole.

Backups are made first. The step ends with `MODS OK`.

## 4. Where players find it

- **The Workshop**: [play.openvanilla.app/wrath/mods](https://play.openvanilla.app/wrath/mods). It opens on a grid of the [categories](mods.md#categories) with a count for each, then the mods. Search with `?q=` (name, description, category). Filter by kind (`?kind=ui`, `realm` or `both`) or by permission (`?perm=chat`, or `?perm=none` for no realm permissions).
- **A category**: `/wrath/mods/c/<category id>`, for example `/wrath/mods/c/addons`. Your mod sits on the shelf its `category` names.
- **Its own page**: `/wrath/mods/<id>`, with what it does, its permissions in plain words, screenshots, the zip, and "Already on Wrath" when the realm runs it.
- **The zip**: `/wrath/mods/<id>/download`.
- **A share link**: `/wrath/m/<id>`, with a preview card.
- **For tools**: `/wrath/mods/catalog.json`, readable from any site.
- **In the game**: Esc, then Mods & Workshop, then Workshop. It lists every mod, with an on/off switch for its addon. `/mods` or `/workshop` opens the same panel.

## Versions

Raise `version` in `mod.json` for every change you send. The catalog keeps one version per mod: the one in `mods/catalog/<id>/`.
