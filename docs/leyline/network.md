# How the Leyline network works

A plain guide for players: what happens when you pick a realm, and what we never do.

```
  You (launcher, game or browser)
            |
            v
   Leyline relay  ---- the realm list (every public realm)
            |
            v
  A host's PC, running their realm
```

1. **Realms are run by players.** A host runs a realm on their own PC. Leyline does not rent servers.
2. **The relay connects you.** You talk to the relay and the relay passes your game through to the host's PC. Nobody opens ports.
3. **Every realm has an id.** Sixteen letters and digits, made from the realm's own key on the host's PC. It never changes, so links keep working.
4. **Your address stays hidden.** Hosts never see players' internet addresses, and players never see the host's.
5. **Invite links open private realms.** The secret part of the link stays in your browser. A host can make a new link at any time, and the old one stops working.
6. **Public realms are listed.** A public realm shows on the realm list about a minute after the host's PC connects, and leaves it a few hours after the PC goes off.
7. **Claimed means a real account.** A host can claim their realm with a Hero Key account, so the list shows who runs it. Unclaimed realms say so.
8. **Official and community.** Wrath Unleashed is the official realm, run by Leyline. Every other realm is a community realm, run by its host under their own house rules.
9. **Dens are private rooms.** A Den is a small, invite-only realm to build in with friends. It is never on the public list.
10. **What we never do.** We never ship, upload or share game files: every host and player uses the game folder they already have. We never sell places on the list, and bots are always counted apart from players.

Want to run one? See [Hosting](hosting.md). Something wrong with a realm? Use **Report** on its card on the [realm list](https://play.openvanilla.app/wrath/realms).
