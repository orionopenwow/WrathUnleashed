# Leyline Admin Console

Staff pages for running Leyline and its launcher, at **https://play.openvanilla.app/wrath/admin**. They are
server-rendered by the Wrath portal (`stream/admin.py`, hooked into `stream/wrath_portal.py`), use the Leyline look,
and need only a little plain script (the typed confirm). Only the owner and staff can open them.

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
**Staff**, type that id (and a name for the list) and press **Grant staff**. **Revoke** asks you to type the id.
These people are staff too, without a grant:

| Who | Set where |
|---|---|
| ids in `WU_ADMIN_STAFF` | `portal.env`, comma separated |
| ids in `WU_MODS_ADMINS` (the Workshop's own admins, `stream/projects.py`) | `portal.env` |
| a game account with GM level `WU_ADMIN_GM_LEVEL` or more on the realm (default **3**; `0` turns this off) | `.account set gmlevel` on the realm; asked over SOAP (`ovadmin gm`), cached 5 minutes |

## Sections

| Section | What staff can do |
|---|---|
| **Dashboard** | Realm (online, players, bots, login queue) and relay (community realms); queues (Workshop items waiting, index submissions, theme packs waiting); open reports; catalog counts; launchers in the wild (see below). |
| **Catalog** | Packaged mods: approve, reject, unpublish, feature, edit name, description and category, re-run the checker (`mods/wu-mod.py`) and read its findings. Community links: hide, unhide, feature, edit, dismiss reports. |
| **Workshop** | What players made (`characters.mod_workshop_items`): approve, reject, unpublish (back to waiting), feature, edit title and description, re-run the checks (the word filter and reference checks). |
| **Index** | The community index: the submissions queue (approve, or reject with a reason), delist or list again, re-scan one entry or all. |
| **Realms** | Community realms from the Beacons relay, with their heartbeats: hide, unhide, flag (a staff note), mark official. |
| **Releases** | The launcher's GitHub releases (read-only); which version is **stable** and **beta**, and **hold** (owner only); the launcher's News posts. |
| **Flags** | The P2P/torrent feature flags (owner only to change). |
| **Themes** | Theme packs (the Workshop category `themes`): approve, reject, feature. |
| **Reports** | `.bug` reports (seen, resolve, won't fix), message reports (done, dismiss, reopen), reported community links; notes on any of them. |
| **Health** | What the server can see: SOAP, `ov_admin.lua`, the relay listing, the Workshop export's age, the mods catalog, writable folders, the checker, GitHub. |
| **Audit** | Every action: who, what, when, before and after, and refusals. |

Owner only: grant or revoke staff, change a feature flag, set the stable or beta channel, hold or release updates.

## Safety

- **Sign-in:** the website's own session (`/api/me`), like every other page. No new accounts or passwords.
- **CSRF:** every POST carries a token bound to the session and the account (HMAC with a key in
  `admin/secret.key`, or `WU_ADMIN_SECRET`); a POST from another site (an `Origin` that isn't ours) is refused.
- **Typed confirm:** destructive actions (reject, unpublish, hide, delist, mark official, revoke, flags, stable,
  hold) need the target typed (a mod id, a realm id, `HOLD`, ...). The button stays off until it matches, and the
  server checks it again.
- **Audit log:** `admin/audit.jsonl`, one line per action and per refusal: `{at, who, name, role, action, target,
  before, after, ok, note}`. Append-only.
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
To refuse a realm at the relay itself (no logins, off the relay's own list), add its id to the relay's
`RELAY_BLOCK_FILE` on the relay box.

### Message reports (`stream/social.py`)

The console uses the social module's store: `Social.reports(status, limit)` and
`Social.resolve_report(id, by, outcome, status)` (`open`, `done`, `dismissed`). It shows the reported player's name,
the reporter's name, the reason and note, and only the reported message.

### Theme packs (`docs/THEMES.md`)

Theme packs are Workshop entries in the category `themes` (packaged `mod:<id>` or community `link:<pid>`), so the
console uses the catalog's actions on them. They are listed at once like any Workshop entry; set
`WU_THEMES_REVIEW=1` to keep new packs off the site and `all.json` until staff approve them.

### Health and Autopilot

Autopilot runs on the owner's PC (`control/last-run.json` there) and its check logs stay there, so the server cannot
see them: the Health page says so. If a step ever uploads a copy of `last-run.json`, point `WU_AUTOPILOT_STATUS` at
it and the page shows the last run.

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

## Deploy and test

- `signin` step ("Update sign-in and warm-up.bat"): ships `stream/admin.py` (and `mods/wu-mod.py` for the checker)
  with the portal changes.
- `scripts` step: ships `realm/custom/lua_scripts/ov_admin.lua` and the `ov_workshop.lua` change (live reload).

Tests:

```
python3 -I stream/tests/test_admin.py stream/wrath_portal.py
lua5.1 stream/tests/test_ov_admin.lua realm/custom/lua_scripts
```
