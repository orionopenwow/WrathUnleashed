# Leyline launcher themes

A theme changes how the Leyline launcher looks: colours, corners, fonts and art. It never changes what the
launcher does. Players pick one under **Settings › Themes**, and find more under **Discover › Themes**.

## Built-in themes

| Theme | Look |
|---|---|
| **Leyline Classic** | stone, parchment and gold: the Leyline art (the default) |
| **Dark Rounded** | flat dark surfaces, 12 px corners, Inter or the system font, no art |
| **Light Rounded** | the same shape in light |
| **Rounded Auto** | Dark or Light Rounded, following the system's light or dark setting |

The choice is saved in the app-data folder (`themes/active.json`) and applies at once.
**Ctrl+Shift+Backspace** always goes back to Leyline Classic.

## Make a theme pack

A theme pack is a folder (or a .zip of one) with:

```
my-theme/
  theme.json        what it is
  theme.css         the one stylesheet
  preview.png       optional: shown on the theme's card (png or webp, up to 1 MB)
  images/…          optional: png, webp, svg
  fonts/…           optional: woff2
  LICENSE.txt       optional: README, LICENSE, LICENCE, CREDITS or OFL (.txt or .md)
```

Nothing else. **No JavaScript, ever**, and no HTML. The whole pack is at most **5 MB** and 64 files, and
files sit at most two folders down.

### theme.json

```json
{
  "id": "night-owl",
  "name": "Night Owl",
  "author": "TODO(owner)",
  "version": "1.0.0",
  "licence": "MIT",
  "preview": "preview.png",
  "kind": "rounded-dark",
  "description": "Deep blue, soft corners."
}
```

| Field | Needed | Rule |
|---|---|---|
| `id` | yes | 3–32 lower-case letters, digits and single dashes, starting with a letter; not a built-in's id. A Workshop pack's id is its Workshop id (`mod:<id>`). |
| `name`, `author`, `version`, `licence` | yes | text (`licence`: an SPDX id such as `MIT` or `CC-BY-4.0`) |
| `kind` | yes | what the pack builds on: `rounded-dark`, `rounded-light` or `classic` |
| `preview` | no | a png or webp in the pack |
| `description` | no | up to 300 characters |

### theme.css

`kind` picks the starting look; your CSS goes on top of it.

**`rounded-dark` / `rounded-light`.** The flat look reads every colour, corner, font and border from
`--t-*` custom properties. Most packs only set these:

```css
:root {
  --t-bg: #0b1020;            /* the window */
  --t-bg-image: none;         /* or url("images/bg.webp") */
  --t-surface: #121933;       /* panels, cards, title bar, side bar, play bar */
  --t-surface-2: #182143;     /* inputs, cards inside panels */
  --t-raised: #202b55;        /* buttons, hover */
  --t-border: #283563;
  --t-border-strong: #3a4a85;
  --t-border-w: 1px;
  --t-text: #eef1ff;
  --t-text-2: #cdd4f2;        /* body copy */
  --t-muted: #a4acd0;         /* hints, labels */
  --t-accent: #8ab4ff;        /* PLAY, the picked tab, links */
  --t-accent-strong: #a9c7ff; /* hover on the accent */
  --t-on-accent: #0b1020;     /* text on the accent */
  --t-accent-soft: rgba(138, 180, 255, 0.15);
  --t-ok: #5ad58a;  --t-warn: #f2c14e;  --t-bad: #ff8a80;  --t-danger: #e5484d;
  --t-radius: 12px;  --t-radius-sm: 10px;  --t-radius-xs: 6px;
  --t-font: "Owl Sans", Inter, system-ui, sans-serif;
  --t-font-display: var(--t-font);   /* headings */
  --t-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
}
@font-face { font-family: "Owl Sans"; src: url("fonts/owl-sans.woff2") format("woff2"); }
```

Keep text readable: aim for a contrast of at least 4.5:1 for `--t-text`, `--t-text-2` and `--t-muted` on
`--t-surface`, and for `--t-on-accent` on `--t-accent`.

**`classic`.** Starts from Leyline Classic. Set its variables (`--text`, `--muted`, `--gold`, `--gold-hi`,
`--bronze`, `--bronze-hi`, `--ink`, `--ink-soft`, `--ok`, `--warn`, `--bad`) and replace art with plain rules,
for example `.side { background: url("images/my-panel.webp") center / 100% 100%; }`.

Plain rules may target any element of the launcher (`.titlebar`, `.side`, `.nav.on`, `.panel`, `.btn`,
`.card`, `.playbar`, `.play`, and so on: see `launcher/ui/index.html`). `html[data-theme="<your id>"]` is
set while your pack is on.

### What the checker allows

Leyline parses `theme.css` and rebuilds it from an allowlist. Anything outside it refuses the whole pack,
with the reason shown:

- **Rules:** plain rules, `@media`, `@supports`, `@font-face`, `@keyframes`. No `@import`, `@namespace`,
  `@charset` or any other at-rule, and no nesting.
- **Properties:** any custom property (`--anything`), plus colours, backgrounds, borders, corners, shadows,
  filters, fonts and text styling, padding, margin, gap, sizes, transforms, transitions, animations, masks
  and scrollbar colours. Not allowed: `display`, `position`, `visibility`, `z-index`, `pointer-events`,
  `top`/`left`/`inset`, and `content` other than `""`, `none` or `normal` (a theme cannot add words).
- **`url()`** only names a png, webp, svg or woff2 file inside the pack (`url("images/bg.webp")`). No
  `http:`, `https:`, `//`, `data:`, `file:` or `..`. `@font-face` `src` must be a woff2 in the pack.
- **Never:** `expression`, `javascript:`, `behavior`, `-moz-binding`, `image-set`, `attr()`, backslash
  escapes, `<`, or HTML comments.
- **Files:** checked by their first bytes as well as their names. An svg may not have scripts, `on…=`
  handlers, `<foreignObject>`, entities or any link outside itself.

The pack is checked when it is installed and again every time it loads. The launcher's window only loads
scripts that ship with the app and images and fonts from itself or `data:`, so a theme can't load
anything from the internet.

### Try it

Settings › Themes › **INSTALL FROM A FOLDER…** and pick your folder (or **INSTALL FROM A ZIP…**). Press
**PREVIEW** to try it (KEEP or UNDO), or **USE**. Install it again after each change. If a rule is refused,
the message says which one and why.

## Publish a theme pack

Theme packs are the Workshop category `themes` (`mods/categories.json`), in the same `/wrath/mods/all.json`
as mods (`mods/all-json.md`):

- **A community link** (`link:<12 hex>`, category `themes`): your repo or page. Players get the zip there
  and use INSTALL FROM A ZIP.
- **A packaged theme** (`mod:<id>`, category `themes`, `source: "packaged"`): the zip is on the Workshop's
  own site with its `sha256`. Leyline downloads it only from that site, at most 5 MB, and installs it only if
  the sha256 matches the catalog and the pack's `id` matches the Workshop id.
  TODO(owner): `wu-mod.py` packs `mod.json` mods only; packaged themes need a `theme.json` step in the
  mods pipeline before the first one is published.

Theme packs are open content (CSS, images, fonts): no game files and no game art. Use only art and fonts
you made or may share, and say their licence.

## Where things live

| Path | What |
|---|---|
| `launcher/ui/themes.js` | applies the theme before the window paints; Settings › Themes and Discover › Themes |
| `launcher/ui/themes/rounded.css` | the Rounded looks and the `--t-*` tokens |
| `launcher/ui/themes/themes.css` | the theme cards, tabs and the preview bar |
| `launcher/src-tauri/src/themes.rs` | the pack format, the checker, install, list, apply, remove (`cargo test --no-default-features themes`) |
| `<app data>/themes/<id>/` | installed packs; `installed.json` says where each came from, `active.json` which is on |
