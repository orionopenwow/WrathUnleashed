# The Leyline Workshop: for creators

The Workshop is one list of what players made on the realm: **minigolf courses**, **modes** and **builds**. Anyone can find your work there and play it in one click, in game or from the web.

- **In game:** Esc > Mods & Workshop > **Workshop** (or `/workshop`).
- **On the web:** <https://play.openvanilla.app/wrath/workshop>. Every item has its own page and a share link (`/wrath/w/<id>`).

## Publish

| What | How | Review |
|---|---|---|
| Minigolf course | Build it in the course editor (`/golf edit`, see [GOLF-COURSES.md](GOLF-COURSES.md)) and press **Publish**. | Live at once. A title the word filter flags waits for a GM. |
| Mode | Write it in the mode editor (`/modes edit`, see [MODES.md](MODES.md)) and press **Publish**. | A GM looks at it first: a mode is code. |
| Build | Save it (`.build save <name>`), get its code (`.build share <name>`), then `.workshop publish <code> [title]`, or use **Publish a build** in the Workshop tab. | A GM looks at it first. |

Publishing the same course or mode again (same title) makes a **new version** of the same item. Plays and votes stay.

Limits: 5 courses, 5 modes and 10 builds per character. Titles are 40 characters at most, letters, digits and plain punctuation.

## Your items

- `.workshop mine` lists your items, their number, version, state, plays and votes. The **Mine** button in the Workshop tab shows the same.
- `.workshop describe <id> <text>` sets the short description (140 characters).
- States: **waiting for a GM**, **approved** (everyone sees it), **not approved**.

## Play

- **Play** on a course starts it where you stand and invites your party nearby.
- **Play** on a mode hosts it where you stand. Your party nearby is invited.
- **Play** on a build pastes it where you stand. You need the builder role and a build area (`.build where`).
- On the web, **Play** opens the game in your browser (sign in first) and starts the item once you are in the world.
- `.workshop play <id>` does the same from chat.

Each player can give an item one thumbs up or down per account. You can't rate your own.

## Rules

- Only your own work, in open formats. Workshop items are text (course files, mode scripts) and builds made from the realm's prop catalog. They point at the game's own props by number; they never contain game files.
- No game data in any mod or package. Files that are game archives, models, textures or map tiles are refused by their content, whatever their name.
- Keep titles and descriptions friendly. A word filter catches the worst; GMs take down the rest.
- Nothing is for sale.

## For GMs

- `.workshop pending` lists what waits, oldest first, with flagged titles marked.
- `.workshop approve <id>`, `.workshop reject <id>`, `.workshop unpublish <id>` (takes it down everywhere, a course out of `/golf` too).
- `.modes approve <key>` and `.workshop approve <id>` are the same thing for modes.

## How it works

- Realm: `realm/custom/lua_scripts/ov_workshop.lua` keeps the list (`mod_workshop_items`, `mod_workshop_votes`). Play hands the item to its own script (`ov_golf.lua`, `ov_modes.lua`, `ov_build.lua`), which checks role, area, budget and rate as usual. A mode's code runs only in the host's client sandbox, never on the realm.
- In game: `WrathUnleashedUI/Workshop.lua`, over the OVMOD channel (mod `wuws`).
- Web: `stream/creations.py`, from a file `realm/custom/workshop-export.py` writes every 5 minutes (approved items only). Play is `/wrath?go=w:<id>`.
