# Leyline friends and messages

One friends list and one set of messages across the game (the browser client and desktop clients on the
realm), the Leyline launcher and the website.

- **Who is who.** A Leyline account is the player's game account: one per website account (`WR000123`),
  handed out by the website's sign-in through `/api/play`. There are no new accounts, emails or passwords.
  Friends see a chosen name with a 4-digit tag (`Orion#4821`). The name defaults to the website's display
  name, or to the first character the realm saw. A main character can be shown too.
- **Where it lives.**
  - The portal (`stream/social.py`, loaded by `stream/wrath_portal.py`) keeps everything.
  - The realm (`realm/custom/lua_scripts/ov_social.lua`) reports presence and carries `.lm` and `.lf`.
  - The in-game panel is `stream/fui-web/Interface/AddOns/WrathUnleashedUI/Social.lua` (`/lfriends`).
  - The launcher has a Friends page (`launcher/ui/social.js`, `launcher/src-tauri/src/social.rs`).

```
 launcher (social.rs) ──Bearer token──┐
 website page (cookie + CSRF) ────────┤ HTTPS  /wrath/api/social/*   ┌───────────────────────────┐
                                      └─────────────────────────────▶│ wu-portal: social.py      │
                                                                     │ /data/social.sqlite3      │
 game client ──WUSO addon msgs / .lm .lf──▶ ov_social.lua ◀──SOAP────│ bridge thread: pull/flush │
                                            (worldserver)            └───────────────────────────┘
```

No new ports. The portal already talks to AzerothCore over SOAP to make accounts, and the bridge uses the
same console. The pattern is the same as the Discord bridge (`ov_discord.lua`):
- every 3 seconds the portal runs `ovsocial pull`;
- it runs `ovsocial msg`, `ovsocial tell` and `ovsocial fr` to send things back.

When nobody is in game or in the launcher, the poll slows to every 15 seconds.

## Privacy rules

- Presence is shown only between accepted friends. Both players must have said yes.
- "Appear offline" (`.lf offline`, the panel, or the launcher) shows you as offline to everyone. Messages
  still arrive.
- A block hides everything, both ways:
  - the friendship and any requests are removed;
  - no messages can be sent;
  - no presence is shown;
  - a friend request to the blocker gets the same answer as "no such player".
- Bots never appear. These accounts are ignored on the realm and in the portal:
  - `RNDBOT*` accounts;
  - players for whom `IsBot` or `IsPlayerbot` is true.
- The realm stamps the sender with the account of the character that typed the message, read from the auth
  DB. It never uses a name sent by the client. The panel accepts only addon messages that the realm whispers
  to the player.
- Message bodies are never written to logs. Names and texts cross SOAP hex-encoded.
- Only `sha256(token)` of a launcher session is stored. The token itself goes to the launcher once.
- Retention:
  - messages are kept for 30 days, and at most 500 per conversation;
  - handled reports are deleted after 180 days.

## Limits

| What | Limit |
|---|---|
| Messages | 20 a minute and 600 a day per account (`WU_SOCIAL_MSG_PER_MIN`, `WU_SOCIAL_MSG_PER_DAY`); 500 characters |
| In game | 8 `.lm`/`.lr`/`.lf` actions per character per 30 seconds; chat lines are 255 characters |
| Friend requests | 20 an hour, 100 waiting at once, 500 friends |
| Reports | 10 a day per account |
| API calls | 240 a minute per account |
| Launcher sign-ins | 10 code requests per address per 10 minutes, 10 linked launchers per account (the oldest makes room) |
| Long polls | at most 200 open at once (more answer at once) |

Names are 2 to 24 letters, digits, dots, dashes or underscores. They pass the realm's word filter (ported
from `ov_workshop.lua`) and may not contain the game's brand names. In messages, words that trip the filter
are starred out.

## The JSON API

Everything is under `/wrath/api/social/`. Caddy already sends `/wrath*` to wu-portal; `/api/*` on the site
belongs to the website's own service.

Sign-in, one of two kinds:
- **The website cookie** (`wr_session`), checked through `/api/me` and `/api/play` and cached for 60 seconds.
  POSTs must:
  - send `X-Leyline-CSRF: <csrf from GET me>`;
  - not be cross-site (`Sec-Fetch-Site`, `Origin`).
- **A launcher token**: `Authorization: Bearer <token>`. No CSRF is needed because nothing is sent
  automatically. Every call counts as "online in the launcher" for 75 seconds.

| Call | Body or query | Answer |
|---|---|---|
| `GET me` | | `{me: {pid, name, tag, main, offline}, csrf?}` |
| `GET state` | | `{v, me, friends: [{pid, name, tag, main, status: game\|launcher\|offline, realm, char, unread}], incoming, outgoing, blocked}` |
| `GET events?since=<v>` | | waits up to 25 seconds for a change, then returns the state; `{v, same: true}` when nothing changed |
| `GET thread?with=<pid>[&before=<id>]` | | `{messages: [{id, mine, text, at, via: game\|launcher\|web}]}`, 50 at a time |
| `POST profile` | `{name?, main?, show_main?, offline?}` | `{ok, me}` |
| `POST request` | `{to: "Name#1234" \| a unique name \| a character name}` | `{ok, text}` (a request back from them makes you friends at once) |
| `POST accept` / `decline` / `remove` / `unblock` | `{pid}` | `{ok, text}` |
| `POST block` | `{pid}` or `{to}` | `{ok, text}` |
| `POST send` | `{to: pid, text}` | `{ok, message}` |
| `POST read` | `{with: pid}` | `{ok}` |
| `POST report` | `{pid, reason: spam\|harassment\|hate\|cheating\|other, note?}` | `{ok, text}` |
| `POST device/start` | (no sign-in) | `{device_code, user_code, verify_url, interval, expires_in}` |
| `POST device/poll` | `{device_code}` | `{status: pending\|slow_down\|denied\|expired\|ok, token?}` |
| `POST token/revoke` | (Bearer) | `{ok}` |

Errors come back as `{error: "plain words"}` with 400, 401 (signed out), 403, 404, 409 or 429.
A `pid` is a random 10-character public id. Website account ids and game account names never leave the
server.

### The launcher's sign-in (device code)

1. The launcher calls `POST device/start`. It opens `verify_url`
   (`https://play.openvanilla.app/wrath/link?code=BCDF-GHJK`) in the system browser.
2. `/wrath/link`:
   - signed out, it goes to the website's sign-in (`/login?next=...`) and comes back;
   - signed in, it shows the code with **Approve** and **Not me**. The form carries an HMAC token tied to
     the session and the action, and cross-site posts are refused;
   - it also lists the linked launchers, each with a **Revoke** button.
3. The launcher polls `POST device/poll` every 4 seconds. On approval it receives the token once. It saves
   the token in `<app data>/Leyline/social-session.json` (0600 on Mac and Linux) and never stores a
   password. **Sign out** in the launcher revokes the token on the server too.

## The realm bridge (SOAP, `ov_social.lua`)

From the portal to the realm, as console commands. These are answered only for the console; players can't
run them.

| Command | Answer |
|---|---|
| `ovsocial pull <after-seq> <boot> <0\|1>` | `ovsocial ok <boot> <last-seq> <events>`, then one line per event (listed below). With `1`, the answer also has a `P <ACCOUNT> <hex char> <guid>` line for every player online (bots excepted). |
| `ovsocial msg <ACCOUNT> <id> <hex from> <hex text>` | `ovsocial ok shown <id>`, or `ovsocial none` when that account isn't online. The message is then counted as read. |
| `ovsocial tell <ACCOUNT> <hex text>` | `ovsocial ok told` / `ovsocial none` |
| `ovsocial fr <ACCOUNT> <part> <of> <hex chunk\|->` | the friends list for `.lf` and the panel, in parts of up to 960 hex characters. The lines are `name\ttag\tg\|l\|o\|q\|p\twhere\tunread`. |
| `ovsocial status` | `active=… queued=… seq=… boot=…` |

The event lines in a pull answer:
- `I <seq> <ACCOUNT> <hex char>`: a login;
- `O <seq> <ACCOUNT> <hex char>`: a logout;
- `M <seq> <ACCOUNT> <hex char> <hex to> <hex text>`: a `.lm`;
- `F <seq> <ACCOUNT> <hex char> <hex verb> <hex arg>`: a `.lf` action.

Delivery is at least once:
- The realm keeps events until a pull asks after them.
- A new boot time (a restart or `.reload ale`) sends everything again, and the portal takes a full snapshot.
- Every 2 minutes the portal takes another full snapshot, so presence settles by itself.
- After 3 failed pulls, the portal counts nobody as in game.
- Nothing is queued unless the portal pulled in the last 60 seconds.

`OV_SOCIAL=0` in the worldserver's environment turns the script off.

### In game

- `.lm <friend> <text>`: a Leyline message. The friend can be named by name, `Name#1234`, main or current
  character. The line shows at once as `[Leyline] To [Friend]: text`.
- Incoming messages show as `[Leyline] [Name] whispers: text`, in whisper pink.
- `.lr <text>`: reply to the last Leyline message.
- `.lf`: your list, with presence and unread counts.
- `.lf add|accept|decline|remove|block|unblock <name>`: manage friends.
- `.lf offline|online`: appear offline, or be seen again.
- `.lf report <friend> <reason>`: report a friend.
- When a player logs in, they get the latest 5 unread messages and a count of waiting requests. Their
  friends in game see "Name is now in game".
- `/lfriends` (or `/leylinefriends`) opens the panel. The panel is also reached from the **Leyline** button
  on the Friends window and from **Friends** in the Leyline window (`/leyline`).
- The panel talks to the realm over addon messages with the prefix `WUSO`; `Social.lua` describes them.

## Storage

SQLite in `$WU_PORTAL_DATA/social.sqlite3`. That is `/data` in wu-portal, and
`/srv/wrath/portal-data/social.sqlite3` on the host (WAL mode, 0600).

| Table | What |
|---|---|
| `social_accounts` | `acct` (game account), `pid`, `name`, `tag`, `main`, `show_main`, `offline`, `created` |
| `social_chars` | characters seen on the realm: `name_lc`, `realm`, `acct`, `name`, `seen` |
| `social_rel` | `a`, `b`, `state` (`req` = a asked b; `ok` = friends, one row each way), `label` (what the asker typed), `at` |
| `social_blocks` | `a` blocked `b` |
| `social_messages` | `id`, `lo`/`hi` (the two accounts, sorted), `sender`, `body`, `at`, `via`, `seen` |
| `social_tokens` | `hash` (sha256 of the launcher token), `acct`, `label`, `created`, `used` |
| `social_reports` | the report queue (below) |

### The report queue (for the admin console)

```sql
CREATE TABLE social_reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, at INTEGER,         -- unix time
  reporter TEXT, target TEXT,                                -- game account names
  reason TEXT,                                               -- spam | harassment | hate | cheating | other
  note TEXT,                                                 -- up to 300 characters from the reporter
  context TEXT,                                              -- JSON: the last 20 messages between them [{from, text, at, via}]
  via TEXT,                                                  -- web | launcher | game
  status TEXT DEFAULT 'open',                                -- open | done | dismissed
  handled_by TEXT, handled_at INTEGER, outcome TEXT);
```

The admin console reads it in Python, inside wu-portal:
- `social.store.reports(status="open", limit=100)` returns a list of dicts, with `reporter_name` and
  `target_name` added;
- `social.store.resolve_report(id, by, outcome, status="done")` closes a report.

A report is the one place a message body is kept beyond its conversation, so that moderators can see what
happened. The panel tells the reporter that the last messages go with the report.

## Settings (wu-portal's `portal.env`)

| Setting | Effect |
|---|---|
| `WU_SOCIAL=0` | turns friends and messages off; the API answers 404 |
| `WU_SOCIAL_POLL` | seconds between bridge polls (default 3) |
| `WU_SOCIAL_KEEP_DAYS` | how long messages are kept (default 30) |
| `WU_SOCIAL_THREAD_MAX` | messages kept per conversation (default 500) |
| `WU_SOCIAL_MSG_PER_MIN`, `WU_SOCIAL_MSG_PER_DAY` | message rate limits (defaults 20 and 600) |
| `WU_FORM_SECRET` | keeps CSRF and form tokens valid across restarts (otherwise a random key per start) |

## Tests

```
python3 -I stream/tests/test_social.py stream/wrath_portal.py    # the API against the real ov_social.lua (lua5.1)
lua5.1 stream/tests/test_ov_social.lua                           # the realm script
lua5.1 stream/tests/test_wuui_social.lua                         # the in-game panel with ov_social.lua
CARGO_TARGET_DIR=/home/claude/.leyline-target cargo test -j1 --no-default-features --manifest-path launcher/src-tauri/Cargo.toml social
NODE_PATH=$(npm root -g) node --test launcher/tests/social.browser.test.cjs   # the launcher's Friends page (Playwright)
```
