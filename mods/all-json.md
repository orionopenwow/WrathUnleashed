# /wrath/mods/all.json

One list of every Workshop project: our packaged mods and the community links, in one schema. The
Leyline Launcher (`launcher/`) and the in-game window read it so they show the same list as
https://play.openvanilla.app/wrath/mods. It is public, `Access-Control-Allow-Origin: *`, no sign-in.

```json
{
  "format": 1,
  "generated_at": "2026-10-25T12:00:00Z",
  "categories": [{"id": "addons", "name": "Addons and UI", "line": "...", "icon": "interface"}],
  "builds": ["3.3.5a", "1.12", "any"],
  "projects": [
    {
      "id": "mod:pings",
      "source": "packaged",
      "name": "Pings",
      "description": "Alt-click the world map ...",
      "category": "addons",
      "builds": ["3.3.5a"],
      "author": "WrathUnleashed",
      "author_url": "",
      "licence": "MIT",
      "repo": "https://github.com/orionopenwow/WrathUnleashed/tree/main/mods/catalog/pings",
      "page": "https://play.openvanilla.app/wrath/mods/pings",
      "credits": "Pings by WrathUnleashed · MIT · github.com",
      "stars": null, "last_push": "",
      "submitted_by": "", "submitted_at": "", "last_checked": "",
      "version": "0.1.0", "kind": "both", "permissions": ["chat", "timers"], "on_wrath": true,
      "download": "https://play.openvanilla.app/wrath/mods/pings/download",
      "sha256": "..."
    },
    {
      "id": "link:3f9a0c12bd47",
      "source": "community",
      "name": "frame-kit",
      "description": "A tidy set of unit frames for raids.",
      "category": "addons",
      "builds": ["3.3.5a", "1.12"],
      "author": "alice", "author_url": "https://github.com/alice",
      "licence": "MIT",
      "repo": "https://github.com/alice/frame-kit",
      "page": "https://play.openvanilla.app/wrath/mods/p/3f9a0c12bd47",
      "credits": "frame-kit by alice · MIT · github.com",
      "stars": 42, "last_push": "2026-10-20T10:00:00Z",
      "submitted_by": "Alice", "submitted_at": "2026-10-25T11:58:00Z", "last_checked": "2026-10-25T11:58:00Z",
      "version": null, "kind": null, "permissions": null, "on_wrath": null, "download": null, "sha256": null
    }
  ]
}
```

| field | meaning |
| --- | --- |
| `id` | stable: `mod:<mod id>` or `link:<12 hex>` |
| `source` | `packaged` (our catalog, with a zip) or `community` (a link only: nothing is hosted) |
| `category` | one of the 12 `categories` ids (`mods/categories.json`) |
| `builds` | `3.3.5a`, `1.12`, or `any`; a project for both lists both |
| `author`, `author_url`, `licence`, `repo` | the credit. `licence` is `""` when the repo states none: show "licence not stated" |
| `credits` | the credit line exactly as the site prints it under each card |
| `stars`, `last_push`, `last_checked` | from the forge's public API (GitHub, GitLab, Codeberg); `null` / `""` when unknown |
| `version` … `sha256` | packaged mods only; `null` for community links |

Sorted by name. Hidden links are left out. New fields may appear in format 1: ignore what you don't know.
Show the text as text (never as HTML) and open `repo` / `page` in the browser.
