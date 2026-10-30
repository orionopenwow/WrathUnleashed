# Making a WrathUnleashed mod

A WrathUnleashed mod is a folder with a `mod.json`, plus a normal 3.3.5a addon (`ui/`), some server Lua (`realm/`), or both. You need Python 3. `lua5.1` is optional but useful for running tests.

## 1. Start from the template

```
python3 wu-mod.py new my-mod
```

This copies the example mod, Dalaran Dice, into `my-mod/` with your id filled in. Dalaran Dice adds a `.dice` command that rolls dice in Dalaran and shows the result to everyone within 30 yards, plus an addon that keeps the last five rolls on screen.

## 2. Fill in mod.json

```json
{
  "id": "my-mod",
  "name": "My Mod",
  "version": "0.1.0",
  "author": "Your Name",
  "licence": "MIT",
  "kind": "both",
  "category": "sandbox",
  "wu": "1.0",
  "description": "One or two sentences on what it does.",
  "permissions": ["commands", "chat", "db"]
}
```

`kind` is `ui`, `realm` or `both`. `permissions` lists what your realm code does: `commands`, `gossip`, `spawns`, `events`, `chat`, `db`, `timers`. Players see this list, so keep it short. [SPEC.md](SPEC.md) says which functions need which permission.

`category` (optional) is the shelf your mod sits on in the Workshop at `/wrath/mods`. Leave it out and it follows the kind: `ui` and `both` go under `addons`, `realm` under `realm-scripts`. Pick one of:

| `category` | Shelf | What goes there |
|---|---|---|
| `addons` | Addons and UI | Interfaces, unit frames, nameplates, meters, quest helpers, bag and chat mods, UI skins. |
| `graphics` | Shaders and graphics | Lighting, sky, water, post effects, colour grades, graphics presets for our engines. |
| `sandbox` | Sandbox and game modes | Garry's Mod-style kits such as Prop Hunt, hide and seek, races, murder mystery, tower defense, jump maps. |
| `maps` | Custom maps | New zones, arenas, dungeons and housing plots. |
| `builds` | Builds | Saved Builder creations shared as codes. |
| `encounters` | Boss fights and encounters | Community bosses, encounter scripts, raid replays. |
| `models` | Models and props | Original creatures, mounts, props and buildings. |
| `realm-scripts` | Realm scripts | Server-side features such as QoL, events, economies, professions and companions. |
| `presets` | Server presets | Ready realm recipes such as a Dalaran hangout, duels-only, raid night, RP and hardcore. |
| `audio` | Sounds and music | Original ambience, music packs and UI sounds. |
| `tools` | Tools | Developer HUD plugins, map viewers, log analysers and OBS overlays. |
| `conversions` | Total conversions | Whole new games built from the categories above. |
| `themes` | Launcher themes | Theme packs for the Leyline launcher. These are not mods: see [docs/THEMES.md](../docs/THEMES.md). |

The list lives in [categories.json](categories.json); `wu-mod.py check` rejects anything else. An empty shelf on the site says "Publish the first one" and links here, so yours can be the first.

## 3. Write the realm part (mod-ale Lua)

A dot command:

```lua
local function onCommand(event, player, command)
    if not player or command ~= "hello" then return end   -- not ours: let other scripts see it
    player:SendBroadcastMessage("Hello, " .. player:GetName() .. "!")
    return false                                          -- handled
end
RegisterPlayerEvent(42, onCommand)                        -- needs "commands"
```

Your own table (always named `mod_<your id with underscores>_something`):

```lua
CharDBExecute("CREATE TABLE IF NOT EXISTS mod_my_mod_visits (guid INT UNSIGNED PRIMARY KEY, n INT UNSIGNED NOT NULL)")
CharDBExecute(string.format(
    "INSERT INTO mod_my_mod_visits (guid, n) VALUES (%d, 1) ON DUPLICATE KEY UPDATE n = n + 1",
    player:GetGUIDLow()))                                  -- needs "db"
```

A `can` hook must **always** return `true` or `false`. If it returns nothing, mod-ale blocks the action for everyone:

```lua
local function canJoinQueue(event, player)
    if player:GetLevel() < 15 then return false end
    return true                                           -- don't forget this line
end
RegisterPlayerEvent(50, canJoinQueue)                     -- needs "events"
```

To send data to your addon, use the realm's `OVMod` table. Don't `require` it:

```lua
if OVMod then OVMod.Send(player, "my-mod", "hello", "some,data") end   -- needs "chat"
```

Not allowed in realm code: `io`, most of `os`, `require`, `dofile`, `loadstring`, `debug` and a few others. Run `check` and it will tell you.

## 4. Write the UI part (a normal addon)

Put it in `ui/MyMod/` with `MyMod.toc` starting `## Interface: 30300`. Addon messages from your realm code arrive as `CHAT_MSG_ADDON` with prefix `OVMOD` and the text `my-mod<TAB>hello<TAB>1/1<TAB>some,data`. `ui/DalaranDice/DalaranDice.lua` in the template shows how to read them.

## 5. Art and sound

Only use files you made or are allowed to share, and list each one in `assets/CREDITS.txt`:

```
dice.tga - Your Name - CC-BY-4.0 - drawn for this mod
roll.ogg - Someone Else - CC0-1.0 - https://example.org/their-page
```

Files taken from the game (`.mpq`, `.blp`, `.m2`, `.wmo`, `.adt`, `.dbc` and similar) are rejected, even if renamed.

## 6. Check, test, pack

```
python3 wu-mod.py check my-mod
cd my-mod && lua5.1 tests/test_my_mod.lua realm/my_mod.lua && cd ..
python3 wu-mod.py pack my-mod -o dist
```

`check` prints each problem with a `fix:` line and exits with an error until they are fixed. Warnings don't block. `pack` writes `dist/my-mod-0.1.0.zip` and a `.sha256` file; packing the same files again gives the same zip.

The template's tests show the fake-ALE style: stub the few mod-ale functions your script calls, load it with `dofile`, then call its event handlers with fake players.

## Try it in the browser before you submit

Drop your addon's zip (or its folder) anywhere on the Wrath game page: it is checked with the same UI
rules as `wu-mod.py check` (`.toc` with `## Interface: 30300`, files the TOC lists, addon file types only,
no game data, size limits) and kept in your browser only, never uploaded. It loads the next time the page
loads; the page menu's "Your addons" turns it off or removes it. A packed mod zip works too: only its `ui/`
half is installed (the realm half needs the realm).

## What happens next

Send the zip and its sha256 to the WrathUnleashed team. Realm mods get a human review first. An approved mod goes into
`mods/catalog/<your id>/`; the next `mods` step puts it on the realm and in the streamed client, and it shows up on the
Workshop at https://play.openvanilla.app/wrath/mods with its own page, download and share link (`/wrath/m/<your id>`).
In the game, Esc > Mods & Workshop > Workshop lists it, with an on/off switch for its addon.

`mods/catalog/` has three examples: Dalaran Dice (this template), Pings (a realm half and an addon talking over OVMOD)
and Emote Wheel (addon only). Planned for later: a `wu-mod test` command that runs your mod on a local test realm, and
signed packages.
