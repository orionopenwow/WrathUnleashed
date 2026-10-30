# Client addons (3.3.5a)

Third-party addons, kept here under `_local/` only; never copy them into the MIT repo or publish
them (several ship Blizzard-derived icons and sounds).

Install: double-click `install-gm-addons.bat` (or pass your client folder as the first argument).
It always installs the GM window, then asks about the addon pack and the all-races patch.
Log in with an account made by `realm\add-account.bat` (GM level 3) for the GM tools.

## GM window (always)
| Addon | What it is | Command | Source |
|---|---|---|---|
| AzerothAdmin v24 + QoL | Full GM panel: GM/char/NPC/game object/teleport/ticket/server tabs, item, spell, quest, creature and object lookups with one-click add, model viewer, sliders | `/aa` | github.com/superstyro/AzerothAdmin, with github.com/Dandenas/coa-azerothadmin (movable windows, 50-150% scale slider, color presets) |
| AzerothAdmin_Models | Model data for the game object viewer, loads on demand | (auto) | same |
| MiniGM 1.2.0 | GM HUD: fly/speed/god toggles, 1,306 teleport spots, playerbot controls | `/mgm` | github.com/ntorres38/MiniGM |

## Addon pack (asks; fetched at the commits in `addons.lock`, Docker must be running)
| Addon | Why | Source |
|---|---|---|
| Questie-335 | Quest helper with a WotLK database; live data from the realm's mod-questie-bridge | github.com/Aldori15/Questie (branch 335) |
| Deadly Boss Mods | Boss timers and warnings, Classic to Wrath raids | github.com/Zidras/DBM-Warmane |
| Details! | Damage and healing meter | github.com/Bunny67/Details-WotLK |
| AtlasLoot | Loot tables for every dungeon and raid | github.com/Gescht/AtlasLoot3.3.5a |
| AdiBags | One-window bags sorted by category | github.com/Sattva-108/AdiBags-WoTLK-3.3.5 |
| MultiBot | Point-and-click control of your playerbots; talks to the realm's mod-multibot-bridge | github.com/Wishmaster117/MultiBot-Chatless |

## All races, all classes (asks)
Copies `Patch-A.MPQ` from mod-arac (fetched by `realm\Build custom realm.bat`) into your client's
`Data` folder, so character creation offers every race/class pair. Delete it to undo.

`_src/` holds the clones the addons are copied from; `_pack/` is the staged pack.
