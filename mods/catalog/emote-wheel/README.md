# Emote Wheel

A ring of eight emotes at your cursor. Type `/wheel` (or set a key: Key Bindings > WrathUnleashed > Emote wheel), then click one. Esc or a right-click closes it.

- Default ring, clockwise from the top: Wave, Cheer, Dance, Laugh, Bow, Thank, Point, Roar.
- `/wheel set 3 kiss` puts `/kiss` in slot 3 (slots 1-8, clockwise from the top). Saved per character.
- `/wheel reset` brings back the default eight.

UI only: nothing runs on the realm. Test, from this folder:

```
lua5.1 tests/test_ui.lua ui/WUEmoteWheel/WUEmoteWheel.lua
```
