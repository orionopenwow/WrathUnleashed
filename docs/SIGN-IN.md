# Sign-in and profiles (website and launcher)

Owner, 2026-10-30: "Allow manage account within launcher, bio profile pic etc basic stuff, smooth out the login process,
incorporate hero key gmail and discord signin in sign in phases on site and launcher".

## Who does what

```
 browser / launcher                our portal (stream/, Python)                 the website (Rust, /opt/wenilla-realm)
 ------------------                ----------------------------                 --------------------------------------
 /wrath/signin  ───────────────▶   the chooser: Hero Key, Google, Discord
                                   (a button shows only when the website's
                                   own /login page offers that way)
 /wrath/signin/go/<way> ───────▶   sets ly_next (ours, Path=/wrath) and
                                   wr_next=/wrath/signin/welcome (the website's
                                   own "come back to" cookie), then  ─────────▶ /key, /auth/google/start, /auth/discord/start
                                                                                signs in, makes the account the first time,
                                                                                sets wr_session, lands on wr_next
 /wrath/signin/welcome ◀────────────────────────────────────────────────────────
                                   first time only: name, picture, bio (Skip works)
 back to where they came from
```

- Sign-in itself (sessions, accounts, Google, Discord, Hero Keys) stays in the Rust site. Nothing in Python sees a
  password, makes an account or reads its database; the portal learns who is signed in through `GET /api/me` and
  `GET /api/play`, as before. No Rust change and no new image were needed.
- `wr_next` is the Rust site's own cookie (`auth/oauth.rs` `next_cookie`, `landing`): it only ever sends a browser to a
  path on this site (`safe_next`). We set it to `/wrath/signin/welcome`, nothing else.
- Which ways show: `stream/profiles.py` `ways()` reads the website's `/login` (no cookie) every 5 minutes and looks for
  `/auth/google/start` and `/auth/discord/start`. The Hero Key is always there. If `/login` can't be read: Hero Key and
  Google, no Discord.

## The launcher

The launcher's sign-in is the device code flow it always had (`stream/social.py`, `/wrath/link`), with three buttons:
each opens `/wrath/link?code=XXXX-XXXX&via=herokey|google|discord`, which goes straight to that way's sign-in (or the
chooser when the way isn't offered), then back to the code to approve. The launcher polls and continues by itself; the
first time, it opens its own Manage account page for the profile step.

## Profiles

- Name and `#tag`: stream/social.py's (one name everywhere). Refused: the game and company names, also hidden behind
  separators (`profiles.name_problem`).
- Bio: plain text, up to 300 characters, the word filter's words starred out, game and company names replaced.
- Picture: one of 12 original preset shapes (`profiles.PRESETS`) or the initial. Served at `/wrath/avatar/p/<id>.svg`
  (a week) and `/wrath/avatar/u/<public id>.svg?v=<n>` (a day; `v` changes when the picture or name does).
- The admin console's Profiles tab resets a picture, bio or name. Every change, the player's own too, is kept in
  `profile_history` (profiles.sqlite3) and staff resets are in the audit log. Nothing is deleted.

### Not built, and what each would need

- Uploading a picture: the portal runs on the stock `python:3.12-alpine` image, which has no image library to decode and
  re-encode an upload safely (strip metadata, 256 px WebP). Needs a portal image with Pillow (e.g. a two-line Dockerfile
  `FROM python:3.12-alpine` + `RUN pip install --no-cache-dir Pillow==<pinned>`, used by stream-lib.sh and
  fastloop.sh), then an upload endpoint in profiles.py. TODO(owner): say if you want this.
- The Google or Discord picture: the Rust site asks Google for `openid profile` and Discord for `identify`, but keeps
  only the display name; `/api/me` answers `{username, display_name, role}`. Needs, in the Rust site: store the
  provider's picture URL on the identity (`identities.avatar_url`), and add `"avatar_url"` to `/api/me`. The portal
  would then offer "Use my Google/Discord picture" and proxy it (never hotlink).
- Showing which ways are linked, and unlinking: `/api/me` doesn't say. Needs `"providers": ["google", ...]` in
  `/api/me`; unlinking needs a POST on the Rust site (it has none). Today the profile page links to `/account/key`
  (the Hero Key page) and to `/auth/<way>/start?link=1` (the Rust site's own "link this way to my account").

## Owner checklist

Nothing below types a password or makes an account on another service for you.

- [ ] Google: already on (the website has offered it for months). Nothing to do.
- [ ] Discord sign-in (TODO(owner)): the website has Discord sign-in built in; it was switched off on 2026-10-22
      ("discord is only a join button now"). The Discord application it used still exists (its id and secret are in
      `/opt/wenilla-realm/.env`). To turn sign-in back on WITHOUT the Herald bot (we never post on the Discord):
      1. On the server, in `/opt/wenilla-realm/.env`: `DISCORD_SIGNIN=on` (or delete the line), and check
         `DISCORD_CLIENT_ID` and `DISCORD_CLIENT_SECRET` are set.
      2. In `/opt/wenilla-realm/compose.override.yaml`, the realm service's `DISCORD_CLIENT_ID:` and
         `DISCORD_CLIENT_SECRET:` lines back to `${DISCORD_CLIENT_ID:-}` and `${DISCORD_CLIENT_SECRET:-}` (discord_off.sh
         blanked them), and `DISCORD_GUILD_ID:`, `DISCORD_BOT_TOKEN:`, `DISCORD_REQUIRE_ROLE_IDS:` and
         `DISCORD_GRANT_ROLE_ID:` blank (`""`): then sign-in asks Discord only for `identify` (name and id), never adds
         anyone to the server and has no wave gate.
      3. `cd /opt/wenilla-realm && docker compose up -d realm`, and keep `/etc/openvanilla-discord-off` so the Herald
         bot stays off. (`bash discord_off.sh on` would also start the bot: don't use it for this.)
      4. In the Discord developer portal, the application's OAuth2 redirect must list
         `https://play.openvanilla.app/auth/discord/callback` (it did when Discord sign-in was on).
      Within 5 minutes the Discord button appears on /wrath/signin and in the launcher. To hide it again:
      `DISCORD_SIGNIN=off` and restart the realm service.
- [ ] Read the sign-in and welcome words (TODO(owner) in stream/profiles.py).

No new environment variables or secrets on our portal. `WU_PROFILES=0` turns profiles and /wrath/signin off.
