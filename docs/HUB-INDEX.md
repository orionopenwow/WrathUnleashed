# The Leyline hub and its community index

The hub is one catalog of everything modding-related for the game's classic clients: our Workshop (packages the
launcher installs), a credited **link-out index** of open community projects, and launcher theme packs. It covers
every client build the launcher supports: **1.12.1, 2.4.3, 3.3.5a, 4.3.4 and 5.4.8**, each entry tagged by build.

It is **hidden** for now (the owner, 2026-10-26: "hide the full leyline front page thing but build it out for
now"): served at `/wrath/leyline-preview`, `noindex` in a meta tag and an `X-Robots-Tag` header, linked from no
other page. One switch makes it the front door later (below).

| Piece | Where |
| --- | --- |
| Index pipeline | `tools/hub-index/hub_index.py` (tests: `tools/hub-index/test_hub_index.py`) |
| Curated seeds, discovered pool, blocklist | `tools/hub-index/seeds.json`, `candidates.json`, `blocklist.json` |
| The index (output) | `stream/hub/community-index.json` |
| Holding list (output) | `tools/hub-index/holding.json`: `needs_licence`, `review`, `excluded` |
| Hub pages, submissions, launcher feed | `stream/hub.py` (tests: `stream/tests/test_hub.py`) |
| Daily refresh | `tools/github-workflows/hub-index.yml` → `.github/workflows/hub-index.yml` |
| Preview thumbnails | `hub_index.py thumbs`, `stream/www-files/art/hub-thumbs/`, `tools/hub-index/Refresh hub thumbnails.bat` |
| The scout (daily digest of new finds) | `tools/hub-index/scout.py` (tests: `test_scout.py`), `.github/workflows/scout.yml`, `docs/scout/` |
| Issue form | `tools/github-workflows/ISSUE_TEMPLATE/submit-mod.yml` → Leyline's `.github/ISSUE_TEMPLATE/` |

## The rules

A repo is listed only when all of these hold. The pipeline applies them; `validate_index` in `stream/hub.py`
checks the output again, and the tests check every checked-in entry.

1. **No game data.** Any game-format file in the repo (MPQ, M2, MDX, BLP, ADT, WMO, WDT, WDL, DBC, DB2, SKIN,
   ANIM, vmaps, mmaps and the like) leaves it out, and so does anything that calls itself a repack, a client
   patch or a client download. This is strict on purpose: many interface addons ship BLP textures, and we
   can't tell the author's own art from the game's, so they are left out (they show in `holding.json` with
   the file that tripped the rule).
2. **Source only.** Executables and archives committed to the repo (exe, dll, scr, msi, zip, rar, 7z, cab, apk,
   dmg, pkg) leave it out, except inside a dependency folder (`dep/`, `deps/`, `contrib/`, `third_party/`,
   `vendor/`, `external/`, `packages/`, `win32/`...), where server cores keep their build libraries. Look-alike
   repos from fake-star campaigns usually trip this rule; the blocklist names the ones seen so far.
3. **Nothing paid.** A name, description or topic about shops, VIP, donations, payments, premium or battle
   passes leaves it out; a README that offers a paid or paywalled version leaves it out; a README that only
   mentions Patreon, a subscription or "premium" puts a discovered repo on the review list.
4. **No Chumpton.** Nothing from or mentioning that account, anywhere in the repo's name, description or README.
5. **Nothing decompiled.** wowdecomp shut down after a cease-and-desist on 2026-10-29. Anything naming
   wowdecomp or Waystone, or calling itself decompiled, or with decompiler databases in the tree, is left out. A
   README that mentions decompiler tools (Ghidra, IDA, Hex-Rays) goes to review.
6. **No bots or cheats** for other people's realms: unlockers, injectors, memory editing, client bots, speed
   hacks, packet editors, multiboxing tools. Server-side playerbots are fine (they run on your own realm).
7. **An open licence**, as SPDX: from the forge's API, or else from the licence file at the repo root. No licence,
   or one we don't recognise: the repo waits in `holding.json` → `needs_licence` (re-checked every run) and is
   listed the week it gets one. Non-commercial or no-derivatives terms: left out, and so is an open licence's text
   with a rider added on top (an "additional restriction" against commercial game use, the Commons Clause): a
   field-of-use limit makes it not an open licence, whatever the first paragraph says.
8. **A supported build.** For an addon the TOC's `## Interface:` decides (11200 = 1.12.1, 20400 = 2.4.3,
   30300 = 3.3.5a, 40300 = 4.3.4, 50400 = 5.4.8; anything else, such as current-game TOCs, is left out). For
   everything else: AzerothCore means 3.3.5a, vMaNGOS 1.12.1; then version numbers and build numbers in the
   name, description, topics and README; then names (vanilla, TBC, wrath, cata, pandaria) and the search that
   found it, which also need some sign the repo is about the game.
9. **Clean display text.** The game's brand words never appear in what a visitor sees. Names drop them (a repo
   called "<brand>-Spell-Editor" shows as "Spell-Editor"); descriptions are scrubbed (the brand used as an
   adjective is dropped, "An experimental <brand> emulator" → "An experimental emulator"; otherwise it becomes "the
   game", and the expansion's full title becomes "Wrath"); an author whose name carries one goes to review rather
   than being renamed. Repo links stay as they are and are never shown as text ("View source").
10. **A little signal** for discovered (not curated or submitted) projects: at least 3 stars.

**Curated waivers.** The file rules go by names alone, so a curated seed may waive named files that trip one by
their name and nothing else: `"waive": [{"file": "site/docs/index.mdx", "why": "an MDX docs page"}]`. A waiver needs
its reason, covers only the files it names, and only when every file the probe listed is named and the list is
complete (the probe keeps five): one more file, or a new one, trips the rule again. First used for Azeroth World
Editor (two MDX docs pages, and `decompile.ts`, which turns the realm database's SmartAI rows into readable steps).

Dedupe: one entry per canonical repo link (case, `.git`, `www.` and sub-paths folded), and one per display
name and build set (mirrors and re-uploads); the higher score wins and the other is listed as excluded.

Score (for ordering only): `10·log10(stars+1)`, +6/+3/+1 for a last commit within 1/3/6 years of the newest
commit in the run, +5 curated, +3 submitted, +1 with a description, −3 archived. No dates of the run itself are
used, so the same input gives the same bytes.

Descriptions: `summary` is ours, either the curated line from `seeds.json` or one the tool writes from facts ("A
realm module for AzerothCore (3.3.5a)."); `description` is the repo's own one-line description, scrubbed and cut
to 200 characters. Nothing else is copied from a repo.

## `stream/hub/community-index.json` (format 2)

```json
{"format": 2, "policy": "...", "builds": ["1.12", "2.4.3", "3.3.5a", "4.3.4", "5.4.8"], "categories": ["addons", "..."],
 "entries": [{
   "id": "link:3f9a0c12bd47", "name": "Improved Bank", "author": "silviu20092", "owner": "silviu20092",
   "repo": "https://github.com/silviu20092/mod-improved-bank", "forge": "github", "licence": "MIT",
   "category": "realm-scripts", "type": "module", "builds": ["3.3.5a"],
   "summary": "A realm module for AzerothCore (3.3.5a).", "description": "Improved bank module for AzerothCore.",
   "stars": 14, "updated": "2026-09-30", "archived": false, "needs": "AzerothCore", "source": "discovered", "score": 23.2}]}
```

* `id`: `link:` + the first 12 hex of sha256 of the lowercased canonical link, the same id
  `stream/projects.py` gives a Workshop community link to the same repo, so the two dedupe by id.
* `builds`: `1.12` (shown as 1.12.1), `2.4.3`, `3.3.5a`, `4.3.4`, `5.4.8`, or `any`; in that order.
* `category`: one of the 12 in `mods/categories.json`. `type`: addon, module, lua, core, tool, preset, other.
* `source`: `seed` (curated in `seeds.json`), `discovered`, `submitted`. `stars` is `null` when unknown.
* Sorted by (category, name, id). `hub_index.py check` validates it (the hub's rules, the thumbnail fields and files,
  and the `external` list).
* `thumb`, `thumb_credit` (optional, together): `"/wrath/art/hub-thumbs/<owner>__<repo>.webp"` for the entry's own
  GitHub repo and exactly `"Preview image from the project's GitHub page"`. Written by `hub_index.py thumbs` (below);
  `stream/hub.py` `validate_index` checks both (`thumb_problem`).
* `external` (top level, beside `entries`): the link-only external packs (below), and `external_policy` their
  one-line policy. `validate_index` only checks that it is a list; the hub checks each pack on its own
  (`external_problems`) and leaves a bad one out, so a bad pack never takes the entries down.

## Thumbnails

`python3 -I tools/hub-index/hub_index.py thumbs [--top 30] [--new] [--only owner/repo ...] [--refresh]` (also
`build --thumbs N`, which runs it after a good build for the top N, every new entry and the `--only` repos; a
thumbnail that can't be fetched never fails the build). `--new` adds every GitHub entry that has no thumb and was never
tried (the cache remembers a skip, so a repo without a usable image isn't asked again each run). For each picked
GitHub entry (and each external pack with a GitHub `repo`):

1. Read the repo's page on github.com and take its `og:image`: the social preview the owner set, or else the card
   GitHub draws for every repo.
2. Fetch it only from GitHub's own image hosts: `opengraph.githubassets.com`, `repository-images.githubusercontent.com`,
   `avatars.githubusercontent.com` (https only, checked again on every redirect). At most 2 MB is read; a bigger
   answer is dropped.
3. Keep it only when its first bytes say PNG, JPEG, GIF or WebP (never SVG, HTML or anything else), then make a
   640×320 WebP (centre crop, quality 80 stepping down until it is at most 60 KB) with Pillow, or ffmpeg when
   Pillow isn't installed.
4. Write `stream/www-files/art/hub-thumbs/<owner>__<repo>.webp` (lowercased; served at `/wrath/art/hub-thumbs/`)
   only when the bytes changed; a conditional request with the last ETag skips unchanged images
   (`tools/hub-index/.cache/thumbs.json`). An entry that already has its thumb is left alone without `--refresh`:
   GitHub's card changes with every star, and each change would be a review.

Why only the project's own GitHub preview: it is the picture the project chose to represent itself where it lives,
GitHub serves it for exactly this use (link previews), and it is credited as such on the page. Nothing from a README,
a release, a forum, Reddit or Discord is ever downloaded: those are other people's uploads (user content), and a post's
images are not the project's to give. GitHub's generated card prints the repo's name and description, so when they
carry a brand word or a client number (which the hub never shows) the card is skipped and the entry gets the
hub's generated tile. A custom preview can't be read that way: like any change to an entry beyond a refresh, a new or
changed thumb waits for a person in the daily review PR (`thumb` is not one of the gate's refresh fields).

**Where they run.** The daily workflow installs Pillow and runs `build --thumbs 30` before the gate: the gate holds
every new thumb back (entries and external packs alike), and the WebP files are committed only with the review PR,
never with the auto-merged daily one. On the owner's PC: `tools/hub-index/Refresh hub thumbnails.bat` (the Autopilot
step `thumbs`) installs Pillow for the user when it's missing, runs `thumbs --top 30 --new` and `check`; then Ship
(save to GitHub) and `signin` put them on the site.

**On the site** (`stream/hub.py`): a catalog card, an item page (with the credit under the picture), the Community
Spotlight, the Mod of the week and the gallery's mod tiles (the credit is in the tile's caption, which the lightbox
shows) use the thumb when its file is on the site; otherwise the tile drawn from the item's id. The portal serves
`/wrath/art/hub-thumbs/<owner>__<repo>.webp` from its art folder by pattern (lowercase, WebP magic bytes, 200 KB at
most, nothing else from that folder). `fastloop.sh` (the `signin` step) installs `www-files/art/hub-thumbs/` as a set.

## External packs (a policy exception)

The owner, 2026-10-30: "keep the ultraHD links for now and other similar". HD graphics packs (texture and model packs)
are client patch files, so under rule 1 they can never be index entries. They are listed apart, as link-only items in
the index's top-level `external` list, curated by hand in `tools/hub-index/external-packs.json`:

```json
{"id": "ext:994b561c9db9", "name": "UltraHD Graphics Modpack", "author": "", "url": "https://www.reddit.com/r/wowservers/comments/1xiqhdg/...",
 "category": "graphics", "type": "external-pack", "builds": ["3.3.5a"], "summary": "...", "external": true,
 "note": "External download, made and hosted by its authors; not checked or hosted by Leyline",
 "source_thread": "https://www.reddit.com/r/wowservers/comments/1xiqhdg/...", "added": "2026-10-30"}
```

* `url` is the pack's own page (its repo, official page or announcement thread), never a file, a release asset or a
  file host (zip/rar/7z/mpq/exe/apk, `/releases/download/`, Mega, MediaFire, Drive, Dropbox: refused).
* `external: true` and the `note` are fixed and shown with the item. Never mirrored, never installable: no Install,
  no `leyline://install`, nothing probed beyond the page.
* A thumbnail only from the pack's GitHub `repo` preview when it has one (as above); otherwise none (the hub's tile).
* Every other rule still holds: nothing decompiled or leaked, no whole-client downloads or repacks, no blocklisted
  repos or owners, nothing paid, no brand words or client numbers in the visible text.
* `id` is `ext:` + the first 12 hex of sha256 of the lowercased `url`. Sorted by (category, name, id).

**On the site:** the catalog shows them in their own group, "Graphics & external packs" (also the source filter
`?source=external`; category, build and search filters apply), each with the badge "External download, made and
hosted by its authors; not checked or hosted by Leyline" and a "Visit the authors' page" button (new tab,
`rel="noopener nofollow ugc"`). Each has its own page at `/wrath/leyline-preview/p/ext-<12 hex>` with the same badge,
the authors' page and (when it has one) its source repo. Never an Install or `leyline://install` link, never in the
launcher feed, never the Mod of the week or the Spotlight; in the gallery only when it has a GitHub-repo thumb.

Items using it: the UltraHD Graphics Modpack (r/wowservers 1xiqhdg), added 2026-10-30 from the thread alone (Reddit
could not be read from the build machine; a person should open the thread and check the pack's page is a page, free,
and not a whole client).

`tools/hub-index/holding.json`: `{format: 1, needs_licence: [{repo, name, builds, reason}], review: [{repo,
reason}], excluded: [{repo, reason}]}`, each sorted by repo. The PR shows what changed in it. A `build --only`
run replaces only the probed repos' places in it and keeps the rest.

## Inputs

* `seeds.json`: `{"seeds": [{repo, builds (default ["3.3.5a"]), category, type, name, description, needs,
  author, skip, waive, found}]}` (`found`: where we came across it, a thread permalink or a search; a note only). `skip` is a policy decision with its reason; skips about a licence, game-format files or patch
  files are re-checked every run, the others stay out.
* `candidates.json`: the discovered pool, `{"candidates": [{repo, via: [...], builds: [hints], stars, licence,
  description, topics, archived, pushed}]}`. `discover` adds to it and refreshes what the search says; a repo
  found once stays. Seeded on 2026-10-29 from GitHub's topic pages (stars as shown that day).
* `blocklist.json`: `owners`, `repos`, `patterns` (regex) are left out with their reason; `review` entries are
  held for a person.
* Approved submissions: the portal's `approved.json` (`--approved FILE|URL`, default `HUB_APPROVED_URL`) and
  approved issues (`--issues owner/repo`, default `HUB_ISSUES_REPO`). Approved ones are probed and judged like
  everything else; they skip the stars bar and their build and category are used unless the TOC disagrees
  (then review). Delisted repos are left out.

## Submissions

Two ways in, both reviewed by a person before anything is listed.

**On the site:** `GET/POST /wrath/leyline-preview/submit`. Repo link (GitHub, GitLab or Codeberg), build,
category, an optional note of up to 280 characters. No account, no email, nothing about the submitter is kept:
the IP is used only for an in-memory limit (5 an hour per address, 200 a day in all) and never written. A hidden
honeypot field drops bots. Already listed, already queued, Chumpton, or reviewed and refused: the form says so.

Queue, `$WU_PORTAL_DATA/hub/submissions.jsonl` (default `/data/hub/`, the portal's writable mount), one JSON
object per line, appended:

```json
{"id": "3f9a0c12bd47", "repo": "https://github.com/you/your-mod", "build": "3.3.5a", "category": "tools",
 "note": "What it does", "at": "2026-10-29T17:42:00Z", "via": "portal"}
```

`id` is the same 12-hex id as the index entry it would become. `stream/hub.py` `Store.pending()` returns the
submissions without a decision, oldest first, one per repo.

**Decisions** (written by the admin console, `feat-leyline-admin`): `$WU_PORTAL_DATA/hub/decisions.jsonl`, one
JSON object per line, appended; the last line for an id wins:

```json
{"id": "3f9a0c12bd47", "decision": "approve", "build": "3.3.5a", "category": "tools", "reason": "", "at": "2026-10-29T18:00:00Z", "by": "admin display name"}
{"id": "9b1c0e77aa01", "repo": "https://github.com/x/listed-thing", "decision": "delist", "reason": "author asked", "at": "..."}
```

* `decision`: `approve` (a submission), `reject` (a submission; it can't be submitted again), `delist` (any
  listed repo: gone from the hub and the feed at once, and from the index at the next refresh). `repo` is
  required for `delist` of something that was never submitted.
* `build` and `category` on an approve override the submitter's.
* `GET /wrath/leyline-preview/approved.json` publishes what the pipeline needs, and nothing else (no notes, no
  times, no names): `{"format": 1, "approved": [{id, repo, build, category}], "delisted": [{id, repo}]}`. The
  daily workflow reads it from the live site.

**On GitHub:** the "Submit a mod" issue form in the public Leyline repo (labels `mod-submission`). A
maintainer adds the label `approved`; the next daily run picks it up (into the review PR) (issues with both labels). Closing or
removing the label takes it back out.

## The daily refresh

`.github/workflows/hub-index.yml` in WrathUnleashed: every day at 07:17 UTC and on manual dispatch (`discover`
only on Mondays and on dispatch). It runs `build`, then `gate`, `check` and the tests, and splits the result in
two pull requests:

* `hub-index/daily`: refreshes of entries already on main (stars, last change, archived, score, latest release)
  and removals for a hard rule. The workflow merges this one itself (squash); when the repo's branch rules don't
  allow that, it stays open for a person.
* `hub-index/review`: new entries, other changes to listed entries, and entries that went missing without
  breaking a rule. Never merged automatically: a person reviews it, then merges.

A forge that doesn't answer (a timeout, GitHub's rate limit) never takes an entry off: the entry stays as it was,
with its last-known stars and release. A run that would drop more than 20% of the index at once writes nothing
and fails the job. The details and the gate's exact rules: `docs/HUB-RANKINGS.md`.

It uses only the built-in `GITHUB_TOKEN` (repo search 30 a minute, code search where the token allows it, one
repo and one latest-release call per GitHub entry, issues read from the public Leyline repo). The repo setting
"Allow GitHub Actions to create and approve pull requests" must be on: "setup\Turn on GitHub builds.bat" sets it, or
puts it on its checklist.

Once merged, the "signin" step ships the new `stream/hub/` (and `stream/www-files/art/hub-thumbs/`) to the portal.

## The scout

`tools/hub-index/scout.py run [--date YYYY-MM-DD] [--probe 40] [--max-pages 1] [--no-reddit] [--report FILE]`, daily
in `.github/workflows/scout.yml` (05:43 UTC and on dispatch). The owner, 2026-10-30: "a robust scanning system for
novel GitHubs and other things we can merge into this ultimate launcher". Where `discover` grows the pool with
everything that matches, the scout looks for what is *new or rising* and what it could add to Leyline.

**Sources** (read-only, rate-limit aware; without a token it still runs, with fewer results):

* GitHub search per area (launchers, server cores and modules, bots, addons and UI, tools and editors, web and
  mobile clients, graphics; `AREAS` in the script): repos created in the last 30 days, and repos pushed in the last
  14 days with 15+ stars (the risers). An anonymous run gets 10 searches a minute, the workflow's token 30; once GitHub
  says the limit is used up, no more GitHub calls that run and the digest says so.
* Codeberg and GitLab, newest first (the last 30 days), like `discover`.
* r/wowservers: only its two public feeds, `new/.rss` and `top/.json?t=week`, with a polite User-Agent
  (`leyline-scout/1.0 ...`). 403 or 429 means "not today". GitHub, GitLab and Codeberg links are taken from the posts;
  nothing else is fetched from Reddit, and never a post's image.

**Vetting**: the best `--probe` finds are cloned (`hub_index.probe`, cached by HEAD) and judged by the index's own
rules (`hub_index.judge`: licence, including the rider check — a licence file with a no-commercial-use rider is not
open even when the forge calls it MIT — game-format files, binaries, decompiled or wowdecomp-derived, paid, blocklist,
cheats). The rest are checked on their own words (name, description, topics). Then the lure checks:

* look-alike names: a repo from the last 60 days named like a project we know (the index, the seeds, the pool) by
  another owner, with no more stars than it (`azerothcore-wotlk-free`);
* star clusters: three or more new repos by different owners, made within a week, with exactly the same star count
  (5+) and a shared name word or the same description;
* release-only binaries: almost no files and no source, and a README that says to download it from Releases;
* README patterns alone: an archive password, "turn off your antivirus".

**Verdicts**: `index` (passes the index rules: the daily build will propose it), `watch` (fine, but not an entry: no
supported build, too few stars, no licence yet, or a person should look), `unprobed`, `rejected` (a hard rule, with the
reason), `lure`.

**Scores**: stars (log), stars a week (from `scout-state.json`'s history; the pool's last-known stars against the last
run; or stars over age for a repo made in the last 60 days), new to us, made in the window, merge tags, a Reddit
mention, archived. **Merge tags** (heuristic, no LLM): web client, realm hosting, launcher, mobile, mod format, bots,
editor, graphics, server core, addons/UI, tools, each with a one-line reason quoting the words that matched and where
(its description or its README).

**Output** (same input, same bytes; no clock but the date):

* `docs/scout/<date>.md`: top 15 new, top risers, Reddit mentions (permalinks, points, the verdict of each linked
  repo), merge candidates grouped by tag, rejected (counts by reason, then each), suspected lures (for a person to
  blocklist).
* `tools/hub-index/scout-state.json`: per repo its first-seen date, star history (12 points) and last verdict; Reddit
  posts seen (60 days). Safe to delete: velocity starts over.
* `tools/hub-index/candidates.json`: finds that are not rejected and not lures join the pool with `via: scout:...`, so
  the daily index build vets them and its review gate shows the new entries to a person.

**The workflow** opens or updates one PR, "Scout digest <date>", from the branch `scout/digest` (an unmerged branch's
earlier digests and star history are carried over). It never merges, never pushes to main and posts nowhere else.
It uses only the built-in `GITHUB_TOKEN`; the repo setting "Allow GitHub Actions to create and approve pull
requests" must be on (as for the hub index). Tests: `python3 -I tools/hub-index/test_scout.py` (fakes for GitHub,
Codeberg, GitLab, the Reddit feeds and the probe; no network).

## The launcher feed: `GET /wrath/leyline/catalog.json`

The merged catalog (Workshop, index, themes) in the shape of `/wrath/mods/all.json` (`mods/all-json.md`), so
`launcher/src-tauri/src/catalog.rs` reads it as it is. Public, CORS `*`. Extra fields (format 1 allows new ones):

| Field | Meaning |
| --- | --- |
| `hub` | `1`: this document is the hub feed |
| `categories` | the 12, then `themes` |
| `builds` | `1.12`, `2.4.3`, `3.3.5a`, `4.3.4`, `5.4.8`, `any` |
| project `source` | `packaged` and `community` as in all.json; index entries are `community`; themes are `theme` |
| `hub_source` | `index` or `theme` (Workshop projects keep their all.json record) |
| `link_out` | `true`: nothing to install. The launcher shows **View source** (`repo`) and **Open page** (`page`), never Install |
| `download`, `sha256` | always `null` for index entries. A release asset would only ever be offered after it passed our checker (`mods/wu-mod.py`'s rules: open formats, no game-format magic bytes); the pipeline doesn't do that yet, so there is no Install for index entries |
| `hub_page` | the item's hub page |
| `repo_description` | the repo's own one-line description (scrubbed) |
| `type`, `score`, `archived`, `needs`, `forge` | as in the index |

Ids are `mod:<id>`, `link:<12 hex>` and `theme:<id>`. For the launcher-core agent: today `catalog.rs` keeps only
`mod:`/`link:` ids and the builds `3.3.5a`, `1.12`, `1.12.1`, `any`; to show everything it should also accept
`theme:` ids and the builds `2.4.3`, `4.3.4`, `5.4.8` (a project whose builds all get filtered out currently
counts as "any").

## Themes: `stream/hub/themes.json`

Optional; none yet (the themes agent owns the packs). `{"format": 1, "themes": [{"id": "night-sky", "name",
"description", "author", "licence", "repo", "download", "sha256", "updated"}]}`. Ids are `[a-z][a-z0-9-]{1,31}`;
an entry with a brand word or a bad id is dropped. `download` must be https.

## Routes and switches

| Route | |
| --- | --- |
| `/wrath/leyline-preview` | front page: builds, categories, picks, creators, Host a Beacon |
| `/wrath/leyline-preview/catalog` | `?build=`, `?cat=` (12 + `themes`), `?source=workshop\|index\|theme`, `?q=`, `?sort=score\|name\|updated`, `?page=` |
| `/wrath/leyline-preview/p/<id>` | `link-<hex>`, `mod-<id>`, `theme-<id>` |
| `/wrath/leyline-preview/creators`, `/beacon`, `/submit` | |
| `/wrath/leyline-preview/approved.json` | for the pipeline |
| `/wrath/leyline/catalog.json` | the launcher feed |

* `WU_HUB_FRONT=1` (portal.env): the front door. `/wrath/leyline` serves the hub's front page and the preview
  pages drop `noindex`. Off by default.
* `WU_HUB=0`: the hub and the feed answer 404.
* No script on any page; everything works as plain links and forms.

The portal hooks (`stream/wrath_portal.py`): the module is loaded beside the others (`hub_mod`), `do_GET` hands
it the paths `hub.match()` owns before the `/wrath/leyline` route, and `do_POST` hands it its submit form.
