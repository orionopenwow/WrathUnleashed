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
| Weekly refresh | `tools/github-workflows/hub-index.yml` → `.github/workflows/hub-index.yml` |
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
   listed the week it gets one. Non-commercial or no-derivatives terms: left out.
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
* Sorted by (category, name, id). `hub_index.py check` validates it.

`tools/hub-index/holding.json`: `{format: 1, needs_licence: [{repo, name, builds, reason}], review: [{repo,
reason}], excluded: [{repo, reason}]}`, each sorted by repo. The PR shows what changed in it.

## Inputs

* `seeds.json`: `{"seeds": [{repo, builds (default ["3.3.5a"]), category, type, name, description, needs,
  author, skip}]}`. `skip` is a policy decision with its reason; skips about a licence, game-format files or patch
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
  weekly workflow reads it from the live site.

**On GitHub:** the "Submit a mod" issue form in the public Leyline repo (labels `mod-submission`). A
maintainer adds the label `approved`; the next weekly run picks it up (issues with both labels). Closing or
removing the label takes it back out.

## The weekly refresh

`.github/workflows/hub-index.yml` in WrathUnleashed: Mondays 07:17 UTC and on manual dispatch. It runs
`discover`, `build`, `check` and the tests, and when the index, the pool or the holding list changed it pushes
the branch `hub-index/refresh` and opens (or updates) a pull request with the report. It never pushes to main and
never merges: a person reviews the new entries and the review list, then merges. It uses only the built-in
`GITHUB_TOKEN` (repo search 30 a minute, code search where the token allows it, issues read from the public
Leyline repo). The repo setting "Allow GitHub Actions to create and approve pull requests" must be on: "Turn on
GitHub builds.bat" sets it, or puts it on its checklist.

Once merged, the "signin" step ships the new `stream/hub/` to the portal.

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
