# Realm edits

Drop `.sql` files here and run `realm\Apply edits.bat`. No rebuild.

| Folder | Database | Examples |
|---|---|---|
| `world/` | acore_world | vendors, NPC spawns, item stats, quests, start spells, loot |
| `characters/` | acore_characters | one-off fixes to characters |
| `auth/` | acore_auth | accounts, GM levels, realm list name |

- Files run in name order: `010-vendors.sql`, `020-loot.sql`, ...
- Make each file safe to run again: `DELETE` the rows you own, then `INSERT`, or use
  `INSERT IGNORE` / `REPLACE`.
- Settings live in `profiles\*.env` and `modules.env`; Lua in `custom\lua_scripts\`. The same
  bat restarts the world server so they apply. A GM can reload Lua live with `.reload ale`.
- Only changes to C++ modules (`custom\sources.lock`, `custom\patches`) need
  `Build custom realm.bat`.
