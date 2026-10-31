# Leyline HQ (the Admin Console)

**Leyline HQ** is the one place to run Leyline: **https://play.openvanilla.app/wrath/admin**. Status, what needs
you, what shipped, notes from Claude and to Claude, the people, the realms, the game, the content and the system,
in plain words, on a phone too. Server-rendered by the Wrath portal (`stream/hq.py` for HQ, `stream/admin.py` for
the console underneath, hooked into `stream/wrath_portal.py`), in the Leyline look, with a little plain script
(the typed confirm). Only the owner and staff can open it.

HQ is the main place now. The older tools stay: the GM console (`gmconsole/`, 127.0.0.1:8099 over the SSH tunnel)
for restarts and logs, and Leyline Control on the owner's PC as the deploy runner (it has an **Open HQ** button).

## Home: ten seconds

| Part | What it says | Where it comes from |
|---|---|---|
| **Status strip** | Website up (and when its files changed), Wrath Unleashed online and players, the relay and how many realms it lists, browser play on/off, the last server check, disk and memory | `status.json` (SOAP `server info`), the relay listing, the game data switch, `hq/changes.json` from the PC, `statvfs` and `/proc/meminfo` |
| **Needs you** | every open item, reports first (newest first), then the queues, each with its buttons | `.bug` reports, message reports, forum reports, link reports, realm reports, the Workshop queue, the index queue, theme packs waiting |
| **From Claude** | Claude's latest plain-language note (title, date, a few points) | `hq/claude-notes.json` from the PC |
| **Note to Claude** (owner) | a box; notes show waiting, on Claude's PC, seen, closed. "Claude reads these next time it checks in; for a live chat use the Claude app." | `hq/owner-notes.jsonl` (append-only) |
| **Releases** | launcher version, channel or hold, the newest GitHub build runs, the addon pack version, the host pack version, when the website's files changed | GitHub's public API (no token, cached 10 minutes), `addonpack.json` on the `leyline-addons` release, `hostpack.json` |
| **Recent changes** | the last deploys: done, failed or waiting | `hq/changes.json` from the PC |

The menu: **Home · Needs you · Players · Realms · Releases · Content · Game · System**. Content opens Catalog,
Workshop, Index, Themes, Forum, Profiles and All reports; System opens Health, Numbers (the old dashboard), Flags,
Staff and Audit.

## Roles

owner > admin > mod. Every action names the least role it needs; buttons a role can't use are not shown, and the
server checks again.

| Role | Who | Can |
|---|---|---|
| **mod** | staff granted as mod; `WU_MODS_ADMINS`; a game account with GM level `WU_ADMIN_GM_LEVEL` or more | reports (resolve, dismiss, notes), hide links, realms and forum posts, pin/lock threads, profile resets, re-run checks, kick, mute, unmute, send to Dalaran |
| **admin** | staff granted as admin (an old staff entry without a role is an admin); `WU_ADMIN_STAFF` | everything a mod does, plus approvals and rejections, featured and edits, the index, realm official/featured/verified, relay blocks, News, game bans and unbans, announcements, site-wide sanctions, signing out launchers, forum merges |
| **owner** | `WU_ADMIN_OWNERS` | everything, plus flags, staff, the stable/beta channel and hold, notes to Claude |

## Players

Find someone by name, Name#1234, game account or character. Their page shows the profile, characters and whether
they are in the game, sanctions (in force and past), reports about them, what they made (Workshop items, links,
realms they host), launcher sign-ins (sign one or all out) and the staff history for them. Actions:

- **In the game** (one character box): Kick, Send to Dalaran, Mute (minutes + reason), Unmute.
- **The game account**: Ban (hours, 0 = permanent; reason; type the account) and Unban.
- **On Leyline (site-wide)**: Mute (no forum posts, no messages or friend requests), No new submissions (Workshop
  links, + Your server), Suspend (all of that, plus Hero Key sign-in to community realms, profile changes and
  reports; a suspended staff member loses the console). Hours (0 = until lifted), a reason the player reads, the
  account typed to confirm. Keyed by game account and/or website account id. **Lift** ends it at once; nothing is
  deleted (`admin/sanctions.json` keeps it, marked lifted).

The hooks are one call each, `admin.blocked(activity, acct=, site=)`, which never raises and returns the text to
refuse with: `stream/forum.py` (posting), `stream/social.py` (send, request, accept: messages; profile; herokey;
report only when suspended; reading, declining, removing and blocking always work), `stream/workshop.py` (the link
form, by website id; the portal sets `workshop.blocked`), `stream/hostflow.py` (+ Your server) and
`wrath_portal.herokey_issue` / `herokey_issue_api`. The hub's index submissions are anonymous, so no hook there.

## Game

Announce and on-screen notice (admins), the character tools, the account tools (the account typed twice), GM
tickets (read-only, SOAP `ticket list`) and who is online (`account onlinelist`, bots left out). Every console
command is built in `stream/hq.py build()` from checked parts (the GM console's rules: characters 2-12 letters,
accounts letters/digits/`_ . -`, no bot accounts, reasons and messages one line without chat codes or brand names),
must start with an allow-listed word, and is audited. The GM console port: kick, mute, unmute, teleport to Dalaran,
announce, notify, ban, unban, tickets; mail, restarts, the streaming switch and logs stay in the GM console.

## Realms

The official realm's state, the community realms (hide, flag, official, featured, verified, reports), and
**Block at the relay** (admins; reason; type the realm id). Blocks go to `admin/relay-block.json` and the public feed
`/wrath/leyline/relay-block.json`: `{"format": 1, "updated_at", "blocked": [{"id", "at"}], "sig"}` (ids and times
only). With `WU_RELAY_FEED_KEY` set on the portal, `sig` is HMAC-SHA256 over the sorted, compact JSON without `sig`.

The relay (`hosting/relay/wurelay/relay.py`) polls it every minute when `RELAY_BLOCK_FEED` is set:

| Relay setting | What |
|---|---|
| `RELAY_BLOCK_FEED` | `https://play.openvanilla.app/wrath/leyline/relay-block.json` (empty: off, the default) |
| `RELAY_BLOCK_FEED_KEY` | the same key as `WU_RELAY_FEED_KEY`; set, an unsigned or wrongly signed feed is ignored |
| `RELAY_BLOCK_FEED_MAX_NEW` | new ids taken per update (default 10; the rest on the next updates); 500 in all |

Removals take effect at once; a feed that does not answer keeps the last list; the ids are cached next to the
relay's state (`block-feed.json`) for restarts. `RELAY_BLOCK_FILE` still blocks its own ids, and its
`allow <realm id>` lines win over the feed.

## The JSON API

For a later launcher admin mode (no launcher UI yet). Cookie sign-in plus the CSRF token from `api/me`, sent as
`X-Leyline-CSRF` (or the field `csrf`); a POST must also pass the same-site check. JSON answers, never redirects.

```
GET  /wrath/admin/api/me                {account, name, role, csrf, can: [actions]}
GET  /wrath/admin/api/inbox             {items: [{kind, id, label, title, text, sub, at, where, person, actions}], problems}
GET  /wrath/admin/api/search?q=         {people: [{acct, name, tag, main, sanctions}]}
GET  /wrath/admin/api/person?acct=&site= {person: {...}}
GET  /wrath/admin/api/realm?id=         {realm, overrides, relay_blocked, reports}
GET  /wrath/admin/api/audit?n=&action=  {audit: [...]}
GET  /wrath/admin/api/stats             {status, needs_you, needs_you_by_kind, releases, changes}
GET  /wrath/admin/api/notes             {from_claude, to_claude (owner only)}
POST /wrath/admin/api/act               {action, target, ...fields, confirm}  ->  {ok, message}
```

TODO: Bearer tokens with an admin scope for the launcher (the social device tokens plus a staff check), so the
launcher needs no website cookie.

## What the owner's PC sends (and fetches)

The PC knows the deploys and Claude writes its notes there; HQ only receives small JSON files. One bat,
`tools/hq/HQ sync.bat` (`tools/hq/hq_sync.py`), three Autopilot step names:

| Step | Does |
|---|---|
| `hq-sync` | builds and uploads `changes.json` (the last 30 steps from UPDATES-PENDING/DONE and `control/last-run.json`: id, step, title, note, ok, time; never a log line) and `claude-notes.json` (from `control/hq-notes.json`), then downloads the owner's open notes to `control/notes-from-owner.json` |
| `hqnote` | the same (the name for "publish Claude's notes") |
| `hq-inbox` | the same (the name for "fetch the owner's notes") |

Leyline Control also runs it by itself after every run and after the 3-hourly server check (output in
`logs/hq-sync-auto.log`; a failure never fails the run). The upload goes to `/srv/wrath/portal-data/hq` (the portal's
`/data/hq`), one atomic rename per file; the time of the download goes to `picked-up-at`.

**How Claude adds a note:** write `control/hq-notes.json` on the PC:

```json
{"format": 1,
 "notes": [{"id": "n20261031a", "date": "2026-10-31", "title": "Leyline HQ is live",
            "items": ["Home shows what is up and what needs you", "Leave me notes there"]}],
 "ack": ["o20261031120000ab12"]}
```

newest first (50 at most, 8 points each; no brand names: the step refuses them and uploads nothing), then queue
`<id> hqnote <what>` in UPDATES-PENDING.txt. **How Claude reads the owner's notes:** `control/notes-from-owner.json`
(open notes, newest first, `status` new or seen); put the ids it has read in `ack` and they show as seen on HQ.
Both files are git-ignored.


## Open it

1. Sign in on the website as usual (Google or a Hero Key), then go to `/wrath/admin`.
2. The first time, you are not on any list, so the page says **Staff only** and shows **your account id**.
3. Put that id in `/srv/wrath/portal.env` on the server and restart the portal (the `signin` step does that):

   ```
   WU_ADMIN_OWNERS=<your account id>
   ```

   Several owners: separate the ids with commas. Owners can do everything; staff can do everything except the
   owner-only actions below.

## Grant staff

Ask the person to open `/wrath/admin` once: the Staff only page shows their account id. Then, as the owner, open
**System > Staff**, type that id (and a name for the list), pick **mod** or **admin** and press **Grant**.
**Revoke** asks you to type the id. These people are staff too, without a grant:

| Who | Role | Set where |
|---|---|---|
| ids in `WU_ADMIN_STAFF` | admin | `portal.env`, comma separated |
| ids in `WU_MODS_ADMINS` (the Workshop's own admins, `stream/projects.py`) | mod | `portal.env` |
| a game account with GM level `WU_ADMIN_GM_LEVEL` or more on the realm (default **3**; `0` turns this off) | mod | `.account set gmlevel` on the realm; asked over SOAP (`ovadmin gm`), cached 5 minutes |

## Sections

| Section | What staff can do |
|---|---|
| **Dashboard** | Realm (online, players, bots, login queue) and relay (community realms); queues (Workshop items waiting, index submissions, theme packs waiting); open reports; catalog counts; launchers in the wild (see below); the read-only line "Game data streaming: on/off since …" (docs/GAME-DATA-ON-OUR-SERVER.md: the switch is the owner's bat or the Autopilot step `gamedata-off` / `gamedata-on`, never a button here). |
| **Catalog** | Packaged mods: approve, reject, unpublish, feature, edit name, description and category, re-run the checker (`mods/wu-mod.py`) and read its findings. Community links: hide, unhide, feature, edit, dismiss reports. |
| **Workshop** | What players made (`characters.mod_workshop_items`): approve, reject, unpublish (back to waiting), feature, edit title and description, re-run the checks (the word filter and reference checks). |
| **Index** | The community index: the submissions queue (approve, or reject with a reason), delist or list again, re-scan one entry or all. |
| **Realms** | Community realms from the Beacons relay, with their heartbeats: hide, unhide, flag (a staff note), mark official. |
| **Releases** | The launcher's GitHub releases (read-only); which version is **stable** and **beta**, and **hold** (owner only); the launcher's News posts. |
| **Flags** | The P2P/torrent feature flags (owner only to change). |
| **Themes** | Theme packs (the Workshop category `themes`): approve, reject, feature. |
| **Reports** | `.bug` reports (seen, resolve, won't fix), message reports (done, dismiss, reopen), reported community links; notes on any of them. |
| **Profiles** | Player profiles (`stream/profiles.py`, docs/SIGN-IN.md): find by name, Name#1234 or game account; reset the picture, the bio, or the name (to Player, typed confirm). The old value stays in the profile history shown there; nothing is deleted. |
| **Health** | What the server can see: SOAP, `ov_admin.lua`, the relay listing, the Workshop export's age, the mods catalog, writable folders, the checker, GitHub, and game data streaming on/off (read-only). |
| **Audit** | Every action: who, what, when, before and after, and refusals. |

Owner only: grant or revoke staff, change a feature flag, set the stable or beta channel, hold or release updates,
notes to Claude. See **Roles** above for mods and admins.

## Safety

- **Sign-in:** the website's own session (`/api/me`), like every other page. No new accounts or passwords.
- **CSRF:** every POST carries a token bound to the session and the account (HMAC with a key in
  `admin/secret.key`, or `WU_ADMIN_SECRET`). A POST must also come from our own pages: `Sec-Fetch-Site`, when the
  browser sends it, must be `same-origin` (`cross-site` and `same-site`, a sibling subdomain, are refused), and the
  `Origin` (or, without one, the `Referer`) must be this site; `Origin: null` passes only with `same-origin`.
- **Typed confirm:** destructive actions (reject, unpublish, hide, delist, mark official, revoke, flags, stable,
  hold) need the target typed (a mod id, a realm id, `HOLD`, ...). The button stays off until it matches, and the
  server checks it again.
- **Audit log:** `admin/audit.jsonl`, one line per action and per refusal: `{at, who, name, role, action, target,
  before, after, ok, note, via}` (`via`: web or api). Append-only.
- **Rate limits:** 30 changes a minute per account, 240 pages a minute per account, 120 requests a minute per
  address before sign-in is known.
- **noindex:** `<meta name="robots" content="noindex,nofollow">` and `X-Robots-Tag` on every page, refusals too. No
  public page links here.
- **No secrets** on any page: no SOAP login, no game passwords, no keys.
- **Messages:** a message report shows only the reported message (the reported player's last message in that
  thread), never the rest of the conversation or the reporter's own messages.
- **Nothing deletes player data.** Unpublishing a mod or a Workshop item hides it; plays, votes, files and rows
  stay. Reports are resolved, never removed.

## Files

On the server, in `/srv/wrath/portal-data` (the portal's writable `/data`):

| File | What |
|---|---|
| `admin/staff.json` | `{"format": 1, "staff": {"<account id>": {"name", "by", "at"}}}` (mode 0640) |
| `admin/audit.jsonl` | the audit log |
| `admin/overrides.json` | `{"format": 1, "mods": {id: {...}}, "projects": {pid: {...}}, "workshop": {id: {...}}}`: `state` (`approved`, `rejected`, `unpublished`), `featured`, `name`, `description`, `category` |
| `admin/realm-overrides.json` | `{"format": 1, "realms": {"<realm id>": {"hidden", "official", "flag"}}}` |
| `admin/notes.json` | report notes: `{"bug:7": {"status", "notes": [{by, at, text}]}}` |
| `admin/checks/mod-<id>.json`, `admin/checks/ws-<id>.json` | the checker's last findings |
| `admin/launcher-versions.json` | optional: `{"versions": {"0.4.2": 12}}` (see below) |
| `admin/sanctions.json` | `{"format": 1, "sanctions": {"<id>": {type, acct, site, until, reason, by, at, lifted?}}}` (0640) |
| `admin/relay-block.json` | `{"format": 1, "blocked": {"<realm id>": {at, by, reason}}}` (0640); the feed carries ids and times only |
| `hq/changes.json`, `hq/claude-notes.json`, `hq/picked-up-at` | from the owner's PC (HQ sync) |
| `hq/owner-notes.jsonl` | the owner's notes to Claude: `{id, at, by, text}` and `{id, status, at, by}` lines |
| `leyline/flags.json`, `leyline/channel.json`, `leyline/news.json` | the public feeds |
| `hub/decisions.jsonl`, `hub/rescan.json` | for the index (see below) |

## Interfaces with the other parts

### The public feeds (for the launcher)

All CORS `*`, cached a minute, no sign-in:

- `GET /wrath/leyline/flags.json`: the host-pack/P2P format (`stream/leyline_net.py`, `docs/P2P-AND-TORRENT.md`):
  `{"format": 1, "updated_at", "flags": {...}, "limits", "stun", "sha256"}`. When `leyline_net.py` is in the portal it
  serves the file and the console writes through `leyline_net.write_flags`; without it, the console writes and
  serves the same format itself. A new flag is code: add it to `KNOWN` in `stream/leyline_net.py` and
  `launcher/src-tauri/src/p2p/flags.rs`.
- `GET /wrath/leyline/channel.json`:
  `{"format": 1, "updated_at", "stable": {"version", "tag", "url"} | null, "beta": {...} | null, "hold": false, "hold_note"}`
- `GET /wrath/leyline/news.json`: `{"format": 1, "updated_at", "posts": [{"id", "date", "tag", "title", "items": [...]}]}`,
  newest first, at most 20, hidden posts left out. The shape is the launcher's own `NEWS` entries (`launcher/ui/app.js`):
  the launcher can show these and fall back to its built-in list when the feed is empty or unreachable.
- `GET /wrath/leyline/realm-overrides.json`: `{"format": 1, "updated_at", "hidden": [realm ids], "official": [realm ids]}`
  (no staff notes).

### How the updater honours the channel

The launcher checks GitHub releases (`launcher/src-tauri/src/update.rs`; `latest.json` for the updater). Before it
offers anything:

1. Fetch `https://play.openvanilla.app/wrath/leyline/channel.json` (short timeout; cache it like the releases list).
2. If `hold` is `true`: offer no update at all (say nothing, or "Updates are paused for now").
3. Otherwise take the player's channel (`stable` by default; `beta` if they chose it in Settings). If that entry is
   set, the newest version to offer is its `version`: never offer a release newer than it, even when `latest.json`
   names one. A `beta` entry older than `stable` means "use stable".
4. Never offer a version older than the one installed (no downgrades from this file).
5. If the file is missing, unreachable or broken, behave exactly as today (the newest GitHub release).

So staff can ship a release on GitHub, test it as **beta**, and only then make it **stable**; and **hold** stops a bad
release reaching anyone without touching GitHub.

### Launchers in the wild

The launcher asks GitHub directly, so no server of ours sees its version and there is no telemetry. The dashboard
says "Not collected". If an update endpoint of ours ever logs the anonymous version string, write a summary
`{"versions": {"x.y.z": n}}` to `admin/launcher-versions.json` (or point `WU_LAUNCHER_VERSIONS` at it).

### The Workshop and the catalog (`stream/workshop.py`, `stream/creations.py`)

The portal sets `workshop.adjust` and `creations.adjust` to `admin.adjust_catalog(section, items, key)`: rejected
and unpublished items are left out, staff edits and `featured` are applied. `Workshop.load(raw=True)` gives the list
without them (the console uses it). `/wrath/mods/all.json` gains `"featured": true|false` (`mods/all-json.md`).
`/wrath/workshop` lists featured items first.

### Player creations on the realm (`ov_admin.lua`, `ov_workshop.lua`)

The portal has no database connection. It talks to the realm over SOAP, through `realm/custom/lua_scripts/ov_admin.lua`
(console/SOAP only; players never reach it):

```
ovadmin ping | gm <ACCOUNT>
ovadmin ws list <pending|approved|rejected|all> [n] | set <id> <approve|reject|pending> | edit <id> <title|descr> <text> | check <id>
ovadmin bugs list <new|seen|resolved|wontfix|open|all> [n] | set <id> <status> | count
```

`ov_workshop.lua` gained `OVWorkshop.Admin(id, action, text)` and `OVWorkshop.Check(item)`: review without dropping
anything (the in-game `.workshop unpublish` still drops; the console's "unpublish" puts the item back to waiting).
Text is cleaned twice: by the console (the characters `ov_workshop.lua` keeps) and by the realm.

### The community index (the hub, `stream/hub.py`, `tools/hub-index/`)

The console reads `hub/submissions.jsonl` and the index file (`stream/hub/community-index.json`, or
`WU_HUB_INDEX` / `WU_HUB_DIR`), and appends one line per decision to `hub/decisions.jsonl`, the file `stream/hub.py`
reads (the latest line per id wins):

```
{"id": "<12 hex>", "decision": "approve" | "reject" | "delist", "repo", "build", "category", "reason", "by", "at"}
```

"List again" is an `approve` line for a delisted entry. Re-scan requests go to `hub/rescan.json`:
`{"format": 1, "updated_at", "requests": {"<12 hex>" | "all": {"requested_at", "by"}}}`; the index build can read
them (for example through `approved.json`) and probe those repos first. The console never edits the index itself.

### Community realms (the Beacons relay listing)

The relay's listing is not changed. The portal applies `admin/realm-overrides.json` when it reads the list
(`community_realms()` in `stream/wrath_portal.py`): hidden realms are left out of `/wrath/realms` and the share
links, official ones get an **Official** tag. The launcher can do the same with `/wrath/leyline/realm-overrides.json`.
To refuse a realm at the relay itself (no logins, off the relay's own list), use **Block at the relay** on Realms
(the relay's block feed, above), or add its id to the relay's `RELAY_BLOCK_FILE` on the relay box.

### Message reports (`stream/social.py`)

The console uses the social module's store: `Social.reports(status, limit)` and
`Social.resolve_report(id, by, outcome, status)` (`open`, `done`, `dismissed`). It shows the reported player's name,
the reporter's name, the reason and note, and only the reported message.

### Theme packs (`docs/THEMES.md`)

Theme packs are Workshop entries in the category `themes` (packaged `mod:<id>` or community `link:<pid>`), so the
console uses the catalog's actions on them. They are listed at once like any Workshop entry; set
`WU_THEMES_REVIEW=1` to keep new packs off the site and `all.json` until staff approve them.

### Health and Autopilot

Autopilot runs on the owner's PC and its logs stay there. HQ sync sends the step names and outcomes and the last
server check (see above); Home shows them. `WU_AUTOPILOT_STATUS` (a copy of `last-run.json`) still works for the
Health page.

### Leyline Control (the owner's PC)

The deploy runner stays as it is, with: an **Open HQ** button; **Ask before deploys** (off by default: when on,
Autopilot runs only read-only steps such as `check`, the `*-check` dry runs and `hq-sync` by itself, and anything
that changes production waits for **Launch all**; stored as `"confirm"` in `control/autopilot.json`); every line a
step prints is scrubbed of passwords, tokens, keys and connection strings before it reaches `logs/` or the page;
the page's key is compared in constant time and also kept in an HttpOnly, SameSite=Strict cookie; and the last
server check is written to `control/last-check.json` for HQ.

## Settings (portal.env)

| Setting | Default | What |
|---|---|---|
| `WU_ADMIN_OWNERS` | none | owner account ids |
| `WU_ADMIN_STAFF` | none | extra staff account ids |
| `WU_ADMIN_GM_LEVEL` | `3` | game GM level that counts as staff; `0` = off |
| `WU_ADMIN_SECRET` | `admin/secret.key` | the CSRF key |
| `WU_ADMIN_DIR` | `$WU_PORTAL_DATA/admin` | the console's files |
| `WU_LEYLINE_DIR` | `$WU_PORTAL_DATA/leyline` | the public feeds |
| `WU_THEMES_REVIEW` | `0` | `1`: theme packs wait for approval |
| `WU_LEYLINE_RELEASES_API` | the GitHub API for `orionopenwow/Leyline` | releases (public API, no token) |
| `WU_MOD_TOOL` | `wu-mod.py` beside the portal | the checker |
| `WU_LAUNCHER_VERSIONS`, `WU_AUTOPILOT_STATUS`, `WU_HUB_INDEX`, `WU_HUB_DIR` | | see above |
| `WU_HQ_DIR` | `$WU_PORTAL_DATA/hq` | what the PC sends, the owner's notes |
| `WU_RELAY_FEED_KEY` | none | signs `/wrath/leyline/relay-block.json` (the relay's `RELAY_BLOCK_FEED_KEY`) |
| `WU_LEYLINE_RUNS_API` | the GitHub Actions runs API for `orionopenwow/Leyline` | build status on Home |
| `WU_ADDONPACK_URL` | `addonpack.json` on the `leyline-addons` release | the addon pack version |
| `WU_BOT_PREFIX` | `RNDBOT` | bot accounts the game tools refuse and the online list leaves out |

## Deploy and test

- `signin` step ("Update sign-in and warm-up.bat"): ships `stream/admin.py`, `stream/hq.py` (HQ; without it the
  classic console runs) and `mods/wu-mod.py` for the checker, with the portal changes.
- `relay` step: ships the relay with the block feed (off until `RELAY_BLOCK_FEED` is set on the relay box).
- `hq-sync` (or `hqnote`, `hq-inbox`): the PC's feeds, any time after `signin`.
- `scripts` step: ships `realm/custom/lua_scripts/ov_admin.lua` and the `ov_workshop.lua` change (live reload).

Tests:

```
python3 -I stream/tests/test_admin.py stream/wrath_portal.py
lua5.1 stream/tests/test_ov_admin.lua realm/custom/lua_scripts
(cd hosting/tests && python3 -m unittest test_relay_block_feed)
python3 -I tools/hq/test_hq_sync.py
python3 -I tools/control/test_control_hq.py
```
