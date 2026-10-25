# Launcher

The Leyline Launcher is planned. It is being built now. Nothing on this page is released yet.

## What you can use today

Until the launcher ships, these do its jobs:

| Job | Today |
|---|---|
| Play Wrath | the browser at [play.openvanilla.app/wrath](https://play.openvanilla.app/wrath), or your own client (see [Play](play.md)) |
| Play Wrath from your own 3.3.5a folder in the browser | the player package's `Play WrathUnleashed.bat` |
| Find mods | the [Workshop](https://play.openvanilla.app/wrath/mods) and the in-game Workshop tab |
| Host a realm | the host kit and `leyline host` (see [Hosting](hosting.md)) |
| See realms | [play.openvanilla.app/wrath/realms](https://play.openvanilla.app/wrath/realms) and `/leyline` in the game |

## The plan

A desktop app named "Leyline", built with Tauri. It will:

- **Pick your clients.** Select 3.3.5a and 1.12 clients from your own folders. It reads your own files and ships no game data.
- **Manage mods.** Install, turn on and off, and update mods in the [mod format](mods.md).
- **Publish from GitHub.** Publish a mod from a GitHub repository.
- **Host realms.** Start and stop a realm, like `leyline host` does today.
- **Show a peer-to-peer realm list.** A list of realms that does not depend on one central server.

Decided for the first versions:

- All mods are allowed.
- No review queue yet.
- No code signing yet.

Because there is no review or signing yet, nobody but you decides whether a mod is safe. Only install mods you trust. Whether the launcher runs `wu-mod.py check` and the [mod rules](mods.md#realm-rules) before installing is to confirm.

## The phases

The order below follows the plan. There are no dates.

1. **Clients.** Find and select 3.3.5a and 1.12 client folders. Launch the chosen client with the right realm list.
2. **Mods.** Install and manage mods from the Workshop catalog and from GitHub.
3. **Publishing.** Publish your own mod from a GitHub repository.
4. **Hosting.** Host a realm from the app, using the same host kit and relay as today.
5. **Realm list.** A peer-to-peer realm list next to the relay's listing.

The exact phase split is to confirm: the `launcher/` folder is not in this copy of the repo yet.
