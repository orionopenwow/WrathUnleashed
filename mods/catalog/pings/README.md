# Pings

Point at things for your group. Alt-click a spot on the world map, Alt-click in the world, or type `/ping`: everyone in your group on the same map sees a marker on their world map, an on-screen call ("Friend: Attack (29, 47)") and hears a ping.

- `/ping` pings where you stand. With an enemy targeted it calls **Attack**, with a friend **Help here**, otherwise **Look here**.
- `/ping attack`, `/ping danger`, `/ping assist` (or `help`), `/ping onmyway` (or `omw`), `/ping look`.
- Alt-click on the world map pings that exact spot. A plain click on the map still zooms as before.
- Alone, you see your own ping and nothing is sent.

How it works:

- `ui/WUPings/`: the addon. It sends `pings` / `map` messages over the realm's OVMOD channel and draws the pings it gets back.
- `realm/pings.lua`: checks each ping, keeps to 5 pings per 5 seconds per player, and passes it on to group members on the same map and instance. It never sends a ping back to its sender.
- Permissions: `chat` (OVMOD messages) and `timers` (it waits a second for the realm's OVMOD script if it loads first).

Tests, from this folder:

```
lua5.1 tests/test_pings.lua realm/pings.lua
lua5.1 tests/test_ui.lua ui/WUPings/WUPings.lua
```
