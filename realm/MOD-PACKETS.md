# OVMOD mod packets (Open Mod API, M3 server half)

Server: `custom/lua_scripts/ov_modapi.lua` (transport + `OVMod` module) and
`custom/lua_scripts/ov_mod_pings.lua` (the first mod, "Pings & World Markers").
Client: `Mod.Packet` (built separately). Engine: mod-ale @ 84b85cc on AzerothCore 3.3.5a.

## Wire format

One addon message per part, prefix `OVMOD`, whispered to yourself (`SendAddonMessage("OVMOD", text, "WHISPER", UnitName("player"))`):

```
<modId>\t<name>\t<partIndex>/<partCount>\t<data>
```

- `modId`, `name`: 1-32 chars of `[A-Za-z0-9_.-]`.
- `partIndex` is **1-based**: `1/1` is a single-part message, `1/3 2/3 3/3` a three-part one.
- `data` is everything after the third tab, so it may contain tabs. Do not send NUL bytes.
- An empty payload is still one part: `pings\tmarker\t1/1\t`.

### Size limits (from the core, not negotiable)

| Direction | Limit | Where it comes from |
|---|---|---|
| client -> server | `"OVMOD\t" .. text` must be **at most 255 bytes**, so `text` <= 249 | `ChatHandler.cpp` drops any message whose `prefix\ttext` is over 255 bytes, without telling the client |
| server -> client | parts of **2000 data bytes** (`OVMod.SEND_CHUNK`) | ALE `Player:SendAddonMessage` has no cap; the 3.3.5a client handles ~3000 safely |

So a client part may carry `249 - #modId - #name - #"i/n" - 3` data bytes. With a flat 240-byte
part, any modId+name longer than ~3 characters overflows and the whole part is dropped by the
core. **The client should size parts from that formula** (or use a flat 200).

### Server-side limits (ov_modapi.lua)

| Limit | Value | Over the limit |
|---|---|---|
| parts per message | 64 | dropped |
| reassembled message | 16 KB | buffer dropped |
| unfinished messages per player | 8 | new message dropped |
| unfinished message idle time | 30 s | buffer dropped on the next part |
| parts per player per second | 40 | dropped (the core also mutes a player after 100 addon messages a second: `ChatFlood.AddonMessageCount`) |

Rules: a buffer starts only at part 1; a new part 1, or a different `partCount`, restarts it;
a duplicate part is ignored; parts can arrive in any order. Messages for a modId/name that no
script registered are dropped before buffering. Buffers are dropped at logout.

`OVMOD` messages are **swallowed** by the server (the ADDON_EVENT_ON_MESSAGE hook returns
false): the core does not echo them back to the sender or relay them to a party, guild or
whisper target. A client that whispers OVMOD to another player reaches only the server. Replies
always come from the server as a whisper whose sender is the player themself, so the client
should accept OVMOD only with `channel == "WHISPER"` and `sender == UnitName("player")`.

## Server API

```lua
local OVMod = require("ov_modapi")          -- ALE loads each file once; require is safe in any order
OVMod.On(modId, name, function(player, data) end)   -- one handler per modId/name; errors are caught and printed
OVMod.Off(modId, name)
OVMod.Send(player, modId, name, data)       -- chunks at 2000 bytes, whisper type 7 to the player
```

`.reload ale` rebuilds the Lua state: handlers are registered again by the reloaded scripts,
and all in-memory state (partial buffers, rate limits, markers) starts empty.

## Mod "pings"

| Direction | name | data |
|---|---|---|
| C -> S | `ping` | `x,y,z,mapId,kind` - kind `attack`, `onmyway`, `danger`, `assist` |
| C -> S | `marker` | `place,slot,x,y,z,mapId` (slot 1-8) |
| C -> S | `marker` | `clear,slot` (slot 1-8, `0` = all) |
| C -> S | `marker` | `sync` (send me my group's markers for this map) |
| S -> C | `ping` | `x,y,z,mapId,kind,senderGuidLow,senderName` |
| S -> C | `marker` | `set,slot,x,y,z,mapId,placerName` |
| S -> C | `marker` | `clear,slot` (`0` = all) |
| S -> C | `denied` | `rate`, `notleader`, `nogroup` or `bad` |

- Numbers are plain decimals (`-12.5`, `.5`); `1e3`, `0x10`, `inf`, `nan` are rejected. |coord| <= 20000.
- `mapId` must be the sender's current map. A point more than **100 yards** from the sender is
  pulled in to 100 yards along the same line (not rejected). Coordinates go out with 2 decimals.
- Relayed to group/raid members on the sender's map **and instance**, not back to the sender:
  the client draws its own ping/marker when it sends it.
- Rate limit: **5 messages per 5 seconds per player**, pings and marker changes together
  (`sync` counts too). Malformed messages are answered with `denied,bad` and not counted.
- Markers: the group leader or an assistant (in a party, the leader). 8 slots per group, kept in
  server memory. A member is sent `clear,0` and then every marker for their map/instance when they
  log in, change map, join the group, or send `sync`. Leaving the group sends `clear,0`;
  disbanding sends `clear,0` to everyone and forgets the markers.
- Playerbots receive the relays too; mod-playerbots ignores LANG_ADDON chat, so this is harmless.

## AIO compatibility (note only, no code)

Rochet2's AIO uses its own prefixes (server->client `SAIO`, client->server `CAIO`), its own part
header (message id + part number/count inside the payload, because it also fits the 255-byte
limit), Smallfolk-serialised payloads (optionally LZW-compressed) shaped as
`{ handlerName, functionName, args... }`, and on login it pushes addon *source code* to clients
that run the AIO client addon. To accept it in this dispatcher:

1. Register the extra prefixes in `onAddonMessage` and route them to a second, AIO-specific
   reassembler (its header is not `<modId>\t<name>\ti/n`), keeping the same per-player limits.
2. Ship Smallfolk (and LZW, if compression is on) server-side; deserialise with a size cap and
   with only plain data types allowed - never `loadstring` anything a client sent.
3. Map `AIO.AddHandlers(name, tbl)` onto `OVMod.On(name, fn)` and `AIO.Handle(player, name, fn, ...)`
   onto `OVMod.Send`, serialising args with Smallfolk and replying on `SAIO`.
4. Decide what to do about AIO's code push: the Open Mod API's sandbox model says mods are
   installed client-side and reviewed, so `AIO.AddAddon` should be refused (or limited to a
   signed allowlist) rather than letting the server send executable Lua to every client.
5. Same swallow rule: return false for `CAIO` so the core never relays it.

## Mod "pings" from the Workshop catalog

`mods/catalog/pings` (installed as `lua_scripts/mods/pings/pings.lua`) uses its own name, `map`, so it never
replaces this file's `ping` / `marker` handlers: C -> S `map` `kind,area,floor,x,y` (map-area coordinates 0-1, what an
addon can know), S -> C `map` `kind,area,floor,x,y,senderName`, and the same `denied` replies (`rate`, `nogroup`, `bad`).
