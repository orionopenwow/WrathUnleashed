# Dalaran Dice

A small example mod for WrathUnleashed. Type `.dice` in Dalaran to roll 2d6, or `.dice 3d20` for other dice. Everyone within 30 yards sees the roll. Players with the DalaranDice addon also see the last five rolls in a small box (`/dicelog` shows or hides it).

- `realm/dalaran_dice.lua`: the `.dice` command (mod-ale). Rolls are stored in `mod_dalaran_dice_rolls`.
- `ui/DalaranDice/`: the addon. It reads OVMOD addon messages from the realm.
- `tests/`: fake-ALE tests. Run them from this folder:

```
lua5.1 tests/test_dalaran_dice.lua realm/dalaran_dice.lua
lua5.1 tests/test_ui.lua ui/DalaranDice/DalaranDice.lua
```
