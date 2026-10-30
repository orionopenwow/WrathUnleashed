# Hub rankings: Hot, Rising, Top rated, Most installed, New, Recently updated

How the Leyline hub and the launcher's Discover page order mods, addons, game modes and themes; what is counted,
what is kept, and how the community index refreshes every day.

| Piece | Where |
| --- | --- |
| Counts, ratings, the formulas, `mods.json` | `stream/hub_rank.py` (loaded by `stream/wrath_portal.py`) |
| Hub pages: sort tabs, kind filter, ratings, Install with Leyline | `stream/hub.py` (still behind the hidden hub: `/wrath/leyline-preview`) |
| Launcher: Discover's tabs, the install count, ratings | `launcher/src-tauri/src/rankings.rs`, `launcher/ui/app.js` |
| `leyline://install/<id>` | `launcher/src-tauri/src/deeplink.rs`, `tauri.conf.json` |
| The daily index and its review gate | `tools/hub-index/hub_index.py` (`build`, `gate`), `tools/github-workflows/hub-index.yml` |
| Tests | `stream/tests/test_hub_rank.py`, `tools/hub-index/test_hub_index.py`, `cargo test --no-default-features` (rankings, deeplink), `launcher/tests/mods.browser.test.cjs` |

## What is counted

**Installs.** After a Workshop install succeeds, the launcher posts once to `POST /wrath/api/hub/install`:
`{id, iid, build, via: "launcher"}`. `iid` is a random id made for that one install (24 url-safe characters,
new every time: not a player id, not a machine id). Settings › "Count my installs" turns it off.
The server:

* counts an `(id, day, iid)` once: a retry is not a second install;
* counts at most **2 installs of one mod a day from one address**, and takes at most **30 pings an hour** from one
  address (429 after); at most 50,000 counted installs a day in all;
* wants `Content-Type: application/json`, so another website can't post the count with a plain form;
* keeps the mod, the UTC day, the build and `hmac(server key, iid)` (for the dedupe, deleted after 3 days), and
  after that only per-mod per-day counts. **No IP address is stored**: for the limits it is hashed with a salt that
  lives in memory only and is replaced every UTC day.

**Ratings.** 1 to 5 stars, one per account per mod, changeable, and 0 takes it back. Why stars and not up/down:
the owner asked for "top rated", and a 1–5 scale gives the Bayesian average something to average (a mod can be
"good but not great"), while it still folds into a thumbs-style signal for Hot (stars above 3 push up, below 3
push down). Who may rate: someone signed in with the website's sign-in (cookie + the `X-Leyline-CSRF` token from
`GET /wrath/api/hub/me`, same-site only), or the launcher signed in through Friends (the same sign-in, as a
Bearer token; no CSRF needed for a token). No new accounts. The account is stored only as
`hmac(server key, account)`. Limits: 30 rating changes an hour per account, 60 an hour per address.

**Index signals.** From the daily index (`stream/hub/community-index.json`): forge stars, the last commit
(`updated`) and the latest release (`release: {tag, date, url}`).

## The formulas

Constants are at the top of `stream/hub_rank.py`; `compute()` is the one implementation (the launcher's
`rankings.rs` only sorts by the numbers it gets).

**Outlier damping** (applied to every count first). For each mod and day, let `med` be the median of that mod's
installs over the 28 days before (zeros included) and `cap = max(25, 4 × med)`. A day's count `n` counts as `n`
up to `cap`, and as `cap + √(n − cap)` above it. A one-day flood of 1,000 fake installs on a quiet mod counts as
about 56; a mod that really takes off raises its own median within days and is counted in full.

**Hot** (the default):

    heat = Σ over the last 30 days of  installs(d) × 2^(−age(d) / 3)
         + Σ over ratings changed in the last 30 days of  2 × (stars − 3) × 2^(−age / 7)
    hot  = sign(heat) × log10(1 + |heat|)  +  0.5 × 2^(−days since the last update / 7)  +  0.1 × log10(1 + forge stars)

An install loses half its weight every 3 days (Reddit/HN style decay); a 5-star rating today counts like 4
installs today, a 1-star like −4. The log keeps one big mod from drowning the page. A fresh release or commit gives
up to +0.5, fading over weeks; forge stars only break ties.

**Rising.** `last7` = installs in the last 7 days, `prev7` = the 7 before. Rising needs `last7 ≥ 5` and
`last7 > prev7`; then `rising = log2((last7 + 5) / (prev7 + 5))`. The `+5` stops "1 install after 0" from topping
the list. Mods that aren't rising come after, by `last7`.

**Top rated** (Bayesian average). With `n` ratings summing to `S`,
`score = (5 × prior + S) / (5 + n)`, where `prior` is the site-wide mean rating, itself started at 3.5 and blended
in over 10 ratings: `prior = (all stars + 3.5 × 10) / (all ratings + 10)`. One 5-star rating scores close to the
prior; twenty ratings averaging 4.5 beat it. Unrated mods come last.

**Most installed**: the damped all-time total; **Most installed (30 days)** (`installs30`, "This month" in the
launcher): the last 30 days. Ties by Hot.

**New**: the first day the hub saw the item (kept in `hub_first_seen`; the first deploy marks everything listed
then with that day, so the order there falls back to the last update). Ties by the last update.

**Recently updated**: the later of the last commit (`updated`) and the latest release's date.

Everything ties on the name. Results are computed once and reused for `WU_HUB_RANK_TTL` seconds (default 300);
a rating change clears the cache.

**Against gaming**, in one place: one count per install id and day; 2 counted installs per mod per address per
day; 30 pings an hour per address; JSON-only posts; damping of outlier days; one rating per account per mod,
30 rating changes an hour per account; the Bayesian prior; logs and decay so a burst fades. Nothing can be bought.

## The API

`GET /wrath/leyline/mods.json` (public, CORS `*`, `Cache-Control: max-age=60`):

    ?sort=hot|rising|top|installs|installs30|new|updated   (default hot; installs&window=30 = installs30)
    &client=<build>    1.12, 1.12.1, 5875, 2.4.3, 8606, 3.3.5a, 12340, 4.3.4, 15595, 5.4.8, 18414
    &kind=addon|mod|mode|theme      addon: a UI addon; mode: game modes and sandbox; theme: launcher themes; mod: the rest
    &q=<text>  &limit=1..1000 (50)  &offset=N

    {"format": 1, "sort": "hot", "client": "3.3.5a", "kind": null, "total": 180, "offset": 0, "limit": 50,
     "generated_at": "...", "formulas": "<this page>",
     "items": [{"id": "mod:pings", "name": "...", "author": "...", "summary": "...", "kind": "addon",
                "category": "addons", "builds": ["3.3.5a"], "source": "workshop|index|theme",
                "installable": true, "install": "leyline://install/mod:pings", "page": "<hub page>",
                "repo": "...", "licence": "MIT", "stars": 12, "version": "0.1.0", "release": null,
                "installs": {"all": 120, "d30": 40, "d7": 9, "prev7": 6},
                "rating": {"avg": 4.4, "n": 12, "score": 4.02},
                "hot": 1.83, "rising": 0.38, "new": "2026-10-30", "updated": "2026-10-28", "rank": 1}]}

`installable` is true only for what the launcher installs in one click: a Workshop package (zip on our site with
its sha256) or a theme pack with a download. Community index entries are link-outs (View source), as before.

`POST /wrath/api/hub/install`, `GET /wrath/api/hub/me?id=`, `POST /wrath/api/hub/rate`: above. The hub's item
page posts the rating as a plain form (`id`, `stars`, `t`: a per-session, per-item token) and is sent back to the
page; pages stay script-free.

Storage: `$WU_PORTAL_DATA/hub_rank.sqlite3` (tables `hub_installs`, `hub_install_seen`, `hub_ratings`,
`hub_first_seen`, `hub_meta` with the server key). `WU_HUB_RANK=0` turns it all off (the routes 404 and the hub
pages show their old sorts).

## The daily index

The workflow runs every day at 07:17 UTC (forge discovery only on Mondays and on demand). After `build`, the gate
compares the new index with the one on main (`hub_index.py gate --base`):

| Change | Goes |
| --- | --- |
| an entry on main: new stars, last change, archived flag, score, latest release | live: the `hub-index/daily` PR, merged by the workflow |
| an entry on main that now breaks a hard rule (game data, binaries, decompiled, paid, repack, cheats, not an open licence, the repo is gone, delisted, another client build) | taken off: the daily PR |
| a new entry | waits: the `hub-index/review` PR, and `holding.json` `pending_new` |
| any other change to a listed entry (name, summary, licence, builds, category, ...) | waits: the review PR (main keeps the old values) |
| an entry missing this run without breaking a rule | kept on main, listed in the review PR |

Robustness: a repo that doesn't answer (`could not read the repo: ...`) keeps its entry exactly as it was; once
GitHub says the API limit is used up, no more GitHub calls are made and last-known stars and releases are kept;
a 5xx or a dropped connection is retried once; a run that would drop more than 20% of the index writes nothing
(exit 3, the job fails with the report in its log; `build --allow-shrink` overrides). If branch rules stop the
workflow from merging its own PR, the daily PR stays open for a person.

## `leyline://install/<id>`

The hub's item page shows **Install with Leyline** (`leyline://install/<id>`) for installable items. The launcher
parses only `install/<catalog id>` (`mod:<id>`, `link:<12 hex>`, `theme:<id>`); anything else is ignored. A link
never installs by itself: Leyline opens Discover on that project, highlighted, and the player clicks INSTALL (a
web page can open a link, so the click is the consent).

What needs a launcher release (TODO(owner): ship it with the next launcher release):

* the scheme is registered in `tauri.conf.json` (`plugins.deep-link.desktop.schemes: ["leyline"]`), which the
  installers read: Windows (registry), Linux (`.desktop` MimeType). Until a release built with it is installed, the
  button does nothing on that PC;
* Windows and Linux hand the link to a newly started Leyline as an argument: that works now (`deeplink.rs`
  `from_args`, taken by the UI once with `deep_link_take`);
* not yet: a link while Leyline is **already open** (it starts a second window), and **macOS** (the link arrives as
  an Apple event, not an argument). Both need `tauri-plugin-deep-link` and `tauri-plugin-single-instance` in
  `Cargo.toml` and `lib.rs`/`app.rs` (a small change, but it adds crates; left for the launcher-core owner).
