# Play

There are three ways to play Wrath: streamed in the browser, in the browser with your own game folder, or in your own 3.3.5a client. They all use the same realm, the same account and the same characters.

## Sign in

1. Open [play.openvanilla.app/wrath](https://play.openvanilla.app/wrath).
2. Sign in with Google or your [Hero Key](hero-key.md).
3. The site makes your game account for you. There are no separate Wrath accounts to ask for.

A Hero Key saved in your browser signs you in by itself the next time. If that fails, you get the normal sign-in page.

## In the browser

**Play now** takes you straight into the game in a browser tab. You need a browser with WebGPU, such as a recent Chrome or Edge.

- The browser streams a small part of the world: Dalaran, the capitals, the starting areas, arenas, dungeons and raids. Your character stays inside that part while you play this way.
- No game files are needed for this.
- Have a 3.3.5a game folder? Drop it on the game page to go anywhere. See [Use your own game folder to go anywhere](#use-your-own-game-folder-to-go-anywhere).
- The browser client downloads in the background while you read the realm page, so the game starts faster.
- **End my browser pass** on the account page ends the session. Do this before you play the same account with your own files.

A new character picks once: start at level 1, or take a one-time boost to 80 with a spec kit, professions and a trip to Dalaran.

## Use your own game folder to go anywhere

Streamed play keeps you in Dalaran, the capitals and the starting areas. With your own 3.3.5a game folder, the same browser tab plays the whole world, on the same realm and the same characters.

**Which folder.** The folder you start the 3.3.5a game from. It holds a `Data` folder with `common.MPQ`, `lichking.MPQ`, the `patch` files and a language folder such as `enUS`, `enGB` or `deDE`. You can give the game folder itself or just its `Data` folder. It must be build 12340: the page reads the build from the files, and a 1.12 or 2.4.3 folder is refused. If you don't know where it is, search your computer for `lichking.MPQ`; the folder two levels up is the game folder.

**How.**

1. Play in the browser as usual (**Play now**).
2. Drag the game folder onto the game page, at character select or in the world. Or open the page menu (the small **☰ menu** at the top) and press **Use my game folder**, or in the game open **Esc > Mods & Workshop > Leyline realms** and press **Use my game folder**.
3. The page checks the folder, then loads once more ("Opening the whole world…") and puts your character back where you were.

The Leyline window and the line under the Esc menu say **Whole world: your game folder** while it is on, or **Streamed: Dalaran, capitals, starting areas** without it.

**Chrome and Edge** remember the folder. The next time you play, it opens by itself, or after one click on **Use my game folder** when the browser asks again. **Firefox and Safari** cannot keep a folder between visits: they ask for it each time, and once more right after you pick it in the world (the page has to load once). If you don't answer, streamed play starts by itself after 20 seconds.

**Privacy.** Nothing is uploaded. The browser tab reads the archives straight from your disk, only the parts the game needs, and nothing else on your computer. **Forget my folder** in the folder window removes the page's access.

**What changes on the realm.** While your folder is in use, the realm lets your account go anywhere. When you play without it again (another visit, another browser, or the tab closed), streamed play's limit comes back by itself within 15 minutes, so you are never left somewhere the browser can't load. If you are outside the streamed places then, the realm sends you to Dalaran (or your capital or starting area).

**If something goes wrong.**

- *"No common.MPQ found"*: you gave a different folder. Give the game folder or its `Data` folder.
- *"This is a 1.12 game folder"* or *"This folder is build …"*: it is not a 3.3.5a (12340) folder. The 1.12 game plays on Open Vanilla.
- *"lichking.MPQ is missing"* or *"One archive is not enough"*: the folder is incomplete. Give the whole folder, not single files.
- *"Your browser asks once more"*: press **Use my game folder** and allow reading the folder. If you said no by mistake, press **Choose folder** and pick it again.
- *"Back to streamed play"*: the browser stopped reading the folder (it was moved, the game was patched while you played, or the permission was taken back). Reload the page to use it again.
- Two game tabs: only one tab plays at a time. The other tab offers **Play here**.
- Still stuck? Ask on our [Discord](https://discord.gg/hVeUxYwbkr).

## In the browser with your own game folder

This option is built but sits behind a switch on the server (`WU_OWNFILES=1`). When it is on, the account page shows **Play in the browser with my game folder**.

- The page reads your own 3.3.5a game folder (or its `Data` folder) on your computer. Nothing is uploaded.
- The server sends no game data. You get the whole world, not only the streamed part.
- The streamed page does the same when you drop your folder on it: see [Use your own game folder to go anywhere](#use-your-own-game-folder-to-go-anywhere).

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
