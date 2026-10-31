# Leyline launcher: changes

Each `## <version>` section is the text of that GitHub release (`launcher-v<version>`); the release workflow
copies it.

## Unreleased

- **A new look.** Leyline is flat and modern now: a navy Dark theme (the default) and a Light theme, rounded cards,
  a clean sans font and the Leyline mark up top. Pick one under Settings › Themes. The painted stone and parchment
  look is gone; if you had it (or a Rounded theme), Leyline moves you to Dark or Light on its own.
- **The same menu as the website.** Home, Realms, Mods, Host, Community and News. My Mods and Discover are one
  Mods page with the tabs Installed and Discover; Friends and the Community Hub are one Community page with the tabs
  Friends and Hub. Modes moved off the menu: open it from Home's featured mode or Realms › MODES.
- **Panels that stand out.** Pages and cards float on the website's backdrop picture as their own lighter layer,
  with a brighter edge, a soft shadow and a title strip. Turn the picture off under Settings › Background picture.
- **Realms like on the website.** Each realm is a card with its icon, the client version in gold, Official,
  Featured, Verified and New, its server, region, rules and uptime, and how many are playing on a small bar.
  Offline realms are dimmed. The Your realms list shows the icon and version too.
- **A console for your realm.** Once a realm runs on your PC, the Host page is its console: Online and listed at a
  glance, the database, login server, world server and relay agent, players online and uptime. Announce, set the
  message of the day, kick, ban or unban, keep an allow-list, or restart with five minutes' warning for everyone
  online (kick, ban and restart ask first). Run the health check, copy or renew your invite link, go public or
  private, choose who may sign up, read the server logs and edit your house rules. Before that: pick a ruleset
  (Vanilla+ starts always on) or link a server you already run. A short guide sits beside it.

## 0.3.1 (2026-10-29)

<!-- TODO(owner): the release's opening line -->
- **Community realms first.** The Realms page lists the realms players host first, in the network's fair order:
  featured realms, then the Leyline Sample Hangout (our own realm, for now), then every other realm by players
  online and uptime. Nothing can be bought or voted on. A line on top says how many realms and players are online.
- **Find a realm.** Filter by build, rules (Blizzlike, Boosted, Custom, PvP, RP, Hangout, Bots), region, language,
  or "Has players now". "Only realms my clients can play" still works with them.
- **Know a realm.** Each card shows its uptime over the last 7 days (or 24 hours), New, Featured and Verified host,
  its region (or the relay's estimate) and its player limit. REPORT sends a realm to Leyline staff, on the website.
- **Host your own.** A short how-to on the Realms page, and on the Host page an **ON THE REALM LIST** card: your
  realm's tags, region, language and player limit, saved into your kit and shown on the list within a minute.
- Direct connections stay off: a host can allow them, and they only show once the network turns them on.

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
