# Leyline launcher: changes

Each `## <version>` section is the text of that GitHub release (`launcher-v<version>`); the release workflow
copies it.

## 0.3.0 (2026-10-29)

- **Every client you have.** Leyline reads the build from your own client's executable: 1.12.1 (5875),
  2.4.3 (8606), 3.3.5a (12340), 4.3.4 (15595) and 5.4.8 (18414). Any other build is listed as "other": it can
  play realms, but gets no mods. Leyline never downloads a client.
- **The realm address, per build.** 1.12: `realmlist.wtf` next to the game. 2.4.3 and 3.3.5a:
  `Data/<locale>/realmlist.wtf` (and the `realmList` line in `WTF/Config.wtf` when there is one). 4.3.4 and
  5.4.8: `SET realmlist` in `WTF/Config.wtf`. Your original is always kept as a backup, and MY OWN REALMLIST
  puts it back.
- **Mods by build.** Addons need the client's own Interface number (11200, 20400, 30300, 40300, 50400). Discover
  and My Mods only offer what fits the client. Client patches (.MPQ) are for 1.12, 2.4.3 and 3.3.5a.
- **Every server type.** Realms show their server (AzerothCore, TrinityCore, CMaNGOS, vMaNGOS, MaNGOS or other)
  and their build. PLAY picks one of your clients that fits, or says which client is missing. "Only realms my
  clients can play" hides the rest.
- **My Mods.** One click to install, update and remove. A title-bar pill counts Workshop updates across all your
  clients, with UPDATE ALL. Native mods (.dll, .asi) need a one-time OK per mod. Removing a mod leaves files you
  changed.
- **Themes.** Settings › Themes: Leyline Classic, Dark Rounded, Light Rounded, and Rounded Auto (follows your
  system's light or dark mode). Install theme packs from Discover › Themes or a zip. Packs are colours,
  fonts and pictures only, checked before use. Ctrl+Shift+Backspace always goes back to Leyline Classic. The rounded themes show a small violet crystal next to the
  Leyline name.
- **Host pack.** Host → GET THE HOST PACK downloads the realm tools into Leyline (checked before install), finds
  Docker, and gives you START, STOP, LOGS, COPY INVITE LINK and NEW INVITE LINK. Updates keep your realm, its
  invite and its logins. The old "choose the kit folder" way still works.
- **Peer-to-peer, ready but off.** Direct connections to hosted realms and torrent downloads (mods, themes, the
  Host pack and launcher updates only, never game files) are built in and switched off. Settings › Advanced
  shows them.
- **Leyline updates itself.** It checks at start and every 6 hours, downloads in the background, checks the
  signature, and shows "Update ready, restart" in the title bar. It never restarts on its own and never while a
  game it started is open. Settings has a Stable or Beta channel.
- **Windows, macOS and Linux builds** from one tag: setup .exe and .msi; a universal .dmg; .AppImage and .deb.

## 0.2.0

- Mods: install, update, turn off and remove Workshop mods per client, or drop your own zip, folder or patch.
- Realms: the official realm and the community Beacons, invite links for private realms, BACK TO WRATH.
- Host: start your own realm with the host kit.

## 0.1.0

- Pick your own 3.3.5a or 1.12.1 client, set its realmlist (with a backup) and start it; or play in the browser.
