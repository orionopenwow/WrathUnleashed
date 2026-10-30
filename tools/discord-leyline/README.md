# Leyline Discord: rebrand and reset (you run it, once)

This turns your Discord server into the simple Leyline community server: new name and icon, four categories and ten
channels, four roles, and every old channel tucked away in a hidden archive. You run it from your own PC. Claude never
connects to Discord and never posts anything.

## Why a bot

Discord only lets a program change a server through a **bot token**. Running it as your own account is against
Discord's terms and can get your account banned. So you make a throwaway bot, use it for five minutes, then kick it.

## The 5 steps

1. **Make the bot.** Open <https://discord.com/developers/applications> → **New Application** → name it
   `Leyline setup`, tick the box, **Create**. Left menu → **Bot** → **Reset Token** → confirm → **Copy**.
   That token is the bot's password: don't share it. Either keep it on the clipboard (the script asks for it and
   hides what you paste) or save it in a file named `token.txt` next to the script (it is git-ignored).
2. **Invite it.** Left menu → **OAuth2** → **OAuth2 URL Generator** → tick **bot** → under **Bot Permissions** tick
   **Administrator** → copy the URL at the bottom, open it, pick your server, **Authorize**. Then in Discord:
   **Server Settings → Roles**, drag the `Leyline setup` role to the **top** of the list.
3. **Preview.** Double-click **`Leyline Discord - preview.bat`**. It prints the whole plan and changes nothing.
4. **Do it.** Double-click **`Leyline Discord - do it.bat`**. It shows the plan again; type `YES`. It backs up the
   server to your Desktop first (`Leyline-discord-backup-<date>`), then makes the changes.
5. **Finish by hand.** Post your welcome (below), do the "by hand" list it prints, then **kick the bot**
   (Server Settings → Integrations → Leyline setup → Kick) and in the Developer Portal click **Reset Token** again or
   delete the app, so the token is dead. Delete `token.txt` if you made one.

## What it does

| | |
|---|---|
| Server | name `Leyline`, the crystal icon; the banner and invite background too if your server has the boosts for them; system messages go to #welcome; AFK channel off; on a Community server #welcome becomes the rules channel. |
| **START** | `✦︱welcome`, `✦︱announcements` (both read-only for everyone; Moderators can post) |
| **PLAY** | `◆︱general`, `◆︱help` (10 s slowmode), `◆︱looking-for-group`, and the `◆︱Hangout` voice channel |
| **CREATE** | `⟡︱mods-and-workshop`, `⟡︱host-a-beacon`, `⟡︱showcase` |
| **FEEDBACK** | `·︱bug-reports`, `·︱ideas` (10 s slowmode) |
| Roles | Moderator (violet, can manage messages and time people out), Helper (blue, @-mentionable), Creator (light violet), Member (light blue). The first three show apart in the member list. |
| Old channels | moved into a hidden **ARCHIVE** category: nobody sees it except Moderators (and you), and nobody can post there. Nothing is deleted. Empty old categories are hidden. |

- **History is kept** where it can be: an existing `#general`, `#announcements`, `#help`, `#lfg`, `#suggestions`
  and so on is renamed and moved instead of replaced (the full list of names it reuses is `ALIASES` in the script).
- **Never touched:** the @everyone role (only per-channel permissions), roles that belong to bots or integrations,
  roles above the bot, roles you have yourself, and your members.
- **Safe to run again.** A second run changes nothing. If it stops halfway (a network blip, the bot's role not at the
  top), fix that and run it again: it carries on.
- The little symbols are one table at the top of the script (`GLYPHS`). Want none? Run with `--plain`.

## Your welcome message

The bot never posts: the welcome should come from you. After the run, the backup folder holds:

- `welcome-message.txt` (also on your clipboard): what Leyline is, the three links, the three rules, with
  `TODO(owner)` lines for your own words. Paste it into #welcome, then hover it → **…** → **Pin Message**.
- `help-getting-in.txt`: a short "Getting in" note for #help. Paste and pin it the same way.

## Options

Add these after the .bat name in a command prompt (`"Leyline Discord - do it.bat" --delete-old-roles`):

| Option | |
|---|---|
| `--delete-archived` | after the backup, delete the archived channels and the empty old categories. You type the server's name to confirm. The backup only has the last N messages of each channel. |
| `--delete-old-roles` | delete roles that aren't Moderator, Helper, Creator, Member or Owner (same never-touch rules). You type `DELETE ROLES` to confirm. |
| `--backup-messages N` | messages to back up per channel (default 1000; `0` skips messages). |
| `--plain` | channel names without the symbols. |
| `--guild <id>` | which server, if the bot is in more than one (otherwise it asks). |

## The backup

`Desktop\Leyline-discord-backup-<date>\`: `guild.json` (server settings), `roles.json`, `channels.json` (with every
channel's permissions), `messages\<channel>-<id>.json` (author, time, content, attachment links; Discord's attachment
links stop working after a while, so save any file you care about), `what-changed.txt`, and the two drafts.

## Things it can't do (it prints them with the exact menu path)

Rules screening and onboarding (Community servers only), the server description, the `discord.gg/leyline` vanity
link (boost level 3), the banner without boost level 2, the GitHub release feed webhook, and handing out the Member
role automatically.

## For developers

`python3 tools/discord-leyline/test_discord_leyline.py` runs the tests against a fake Discord on localhost
(`LEYLINE_DISCORD_API` points the script at it). Standard library only.
