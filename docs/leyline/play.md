# Play

There are three ways to play Wrath: streamed in the browser, in the browser with your own game folder, or in your own 3.3.5a client. They all use the same realm, the same account and the same characters.

## Sign in

1. Open [play.openvanilla.app/wrath](https://play.openvanilla.app/wrath).
2. Sign in with Google or your [Hero Key](hero-key.md).
3. The site makes your game account for you. There are no separate Wrath accounts to ask for.

A Hero Key saved in your browser signs you in by itself the next time. If that fails, you get the normal sign-in page.

## In the browser

**Play now** takes you straight into the game in a browser tab. You need a browser with WebGPU, such as a recent Chrome or Edge.

- The browser streams a small part of the world: Dalaran, arenas, dungeons and raids. Your character stays inside that part while you play this way.
- No game files are needed for this.
- The browser client downloads in the background while you read the realm page, so the game starts faster.
- **End my browser pass** on the account page ends the session. Do this before you play the same account with your own files.

A new character picks once: start at level 1, or take a one-time boost to 80 with a spec kit, professions and a trip to Dalaran.

## In the browser with your own game folder

This option is built but sits behind a switch on the server (`WU_OWNFILES=1`). When it is on, the account page shows **Play in the browser with my game folder**.

- The page reads your own 3.3.5a `Data` folder on your computer. Nothing is uploaded.
- The server sends no game data. You get the whole world, not only the streamed part.

## With your own client

You need your own 3.3.5a install (build 12340). We don't provide game files.

1. Sign in at [play.openvanilla.app/wrath](https://play.openvanilla.app/wrath).
2. Open **Play with the desktop client or the player package**. It shows your account name and password. Sign in again any time to see them.
3. Open `Data\enUS\realmlist.wtf` (or `Data\enGB\...`) in a text editor and change the line to `set realmlist play.openvanilla.app`.
4. Delete the `Cache` folder next to the game, start it, and log in.

The player package has a `Play WrathUnleashed.bat` that asks for your 3.3.5a folder once and opens the game in your browser. It only reads your own files, on your PC.

The 1.12 client plays on the sibling Open Vanilla realm, not on Wrath. The planned [Leyline Launcher](launcher.md) will pick a 3.3.5a or a 1.12 client from your own folders.

## Community realms

Players host their own realms on Leyline. See them at [play.openvanilla.app/wrath/realms](https://play.openvanilla.app/wrath/realms), with their rules and player counts.

To join one:

1. Open its **Join** link. It looks like `https://relay.openvanilla.app/join/<realm id>`.
2. Make an account on that page. Your password is turned into a login key in your browser. The relay and the host never see it.
3. For a stock client, set the realm list to the line the join page shows. That is `set realmlist relay.openvanilla.app`, or the same with the realm's own port, such as `relay.openvanilla.app:40000`.

For a private realm, open the invite link on the same PC and internet connection you play from. The invite lasts 24 hours for that address.

## Share links

Short links open a page with a preview card and a button into the game. After sign-in, the game takes you there.

| Link | What it shares |
|---|---|
| `/wrath/r/<realm>` | a realm |
| `/wrath/h/<hangout>` | a Dalaran hangout |
| `/wrath/q/<dungeon or queue>` | a Dungeon Finder queue, for example `/wrath/q/258` |
| `/wrath/b/<raid or wing>` | a boss fight |
| `/wrath/m/<mod id>` | a mod on the Workshop |
| `/wrath/u/<character>` | a player's armory page |

The [Modes hub](https://play.openvanilla.app/wrath/modes) lists every duel spot, raid, dungeon and hangout as one link each. If you can't go yet (in combat, too low a level), the realm keeps the trip for 30 minutes. Type `.go` when you are ready. See [Commands](commands.md#getting-around).

The [web armory](https://play.openvanilla.app/wrath/armory) shows character sheets. It never shows bots or characters whose player typed `.armory off`.

## Guest pass

A "Try Leyline in the Goldshire Inn" guest pass is built but off by default. When an operator turns it on, a visitor gets a one-time guest character for 20 minutes, with no sign-up. Guests stay in the inn and can only use say and emotes.
