# Smarter Bots: Companions, Herald and what they share

Status: plan, 2026-10-29. Owner asks: "Compansions addon better looking more control added into their plan" and
"Smarter Bots / Herald / Companions Plan". Written from the pinned sources: mod-playerbots e88cc40 (Companions,
3.3.5a), mod-ale 84b85cc, the Herald patches 0020 and 0055 (cmangos playerbots, 1.12), and what was seen live
on 2026-10-26. Ordered by what players feel first. Owner decisions are marked **Decision** and listed at the end.

## Where we are (today's branch)

| Done | What players get |
|---|---|
| The Bots window (`/comp`, minimap button) | roster with role, class colour, live health and mana, spec, item level, status; orders; per-bot spec, role, gear; fill, usual party, dismiss. No chat lines. |
| Orders through the bot's own AI | `PlayerbotAI:HandleCommand` and `ChangeStrategy` (mod-ale): no "To <bot>: maintenance" spam |
| Bots come back after a crash | adopt: bots in your group whose master is you are yours again; a look 15 s after login says so |
| Achievement spam hidden | the window's addon hides achievement lines from your own bots |
| Talent specs from env, dismiss without RemoveMember, loot always pass | shipped 1062-1064 |

## Principles

1. **Bots are always labelled bots.** In chat, in the window, in docs. Never passed off as players.
2. **Measure, then tune.** Every threshold below gets a number from fight logs before it becomes a default.
3. **The realm decides.** The client asks; the realm checks owner, combat, cooldowns, caps.
4. **Bots never take loot from players.** Owner decision, final.
5. **No LLM chat at launch, no "AGI" claims.** See "What we will not do".

## Companions (this realm: 3.3.5a, mod-playerbots e88cc40)

### P1: what a player notices in the first dungeon

**1. Pull and threat discipline.** The commonest complaint about bot groups: damage bots open before the tank
has threat, so the tank chases loose mobs and the healer dies.
- Already in the pinned module: the `wait for attack` strategy and the `wait for attack time <seconds>` command
  (damage waits after the tank engages), the `threat` strategy (damage stops when close to the tank's threat),
  `pull` / `pull rti` commands, `mark rti` (tanks mark their target), `dps assist` vs `dps aoe` (focus vs spread).
- Plan: a "Tank pulls" switch in the window (on by default inside dungeons and raids) that gives damage bots
  `+wait for attack,+threat` and a 2-3 s wait, and tank bots `+mark rti`. Inside the open world it stays off.
- Measure: from the fight log (below), "pulls where a non-tank had aggro in the first 5 s". Target: under 10%.

**2. Healer triage.** Healers spread heals evenly and lose the tank on big pulls.
- Pinned knobs: `CriticalHealth 25`, `LowHealth 45`, `MediumHealth 65`, `AlmostFullHealth 85`, `HealDistance 38.5`,
  and the `focus heal targets` strategy with the `focus heal <name>` command.
- Plan: (a) in the window, "Heal the tank first" on each healer (focus heal on the group's tank);
  (b) per-instance thresholds tuned from logs (heavy raid damage wants healers to start earlier: 70-75 for the
  tank); (c) mana discipline: `save mana` strategy below 30% mana outside boss fights.
- Measure: tank deaths per hour, healer out-of-mana wipes, overheal share.

**3. Boss strategy coverage gaps.** The pinned module ships tactics for: MC, BWL, Onyxia, AQ20, Karazhan, Gruul,
Magtheridon, SSC, TK, Hyjal, BT, ZA, Naxxramas, OS, EoE, VoA, Ulduar, ICC, RS, and 21 dungeons (list in
docs/COMPANIONS.md). Missing, in order of how often a level-80 group of 10 meets them here:

| Gap | Why first | Bosses that wipe bots without tactics |
|---|---|---|
| **Trial of the Crusader (10)** | the 3.3.5a gear catch-up raid; a short raid with 5 fights | Northrend Beasts (Acidmaw/Dreadscale swap, Icehowl charge), Jaraxxus (Legion Flame, Incinerate Flesh, interrupts), Faction Champions (CC, kill order), Twin Val'kyr (orb colours, essences), Anub'arak (frost patches, phase 3 burn) |
| **Halls of Reflection** | the last 5-man of the ICC set; the gauntlet wipes groups | waves, Falric and Marwyn, the final escape (run, break the walls) |
| Trial of the Champion (dungeon) | covered (TOC folder); check the jousting stage live | - |
| Sunwell Plateau, Zul'Gurub, AQ40 | old content on a level-80 realm: bots overgear it | low priority |
| TBC and vanilla 5-mans | levelling with a buddy or a party | mostly trash and simple bosses; generic play copes |

- How: strategies in mod-playerbots' own style (`src/Ai/Raid/<Raid>/`: triggers, actions, multipliers), in our
  fork, compiled by GitHub CI, and offered upstream (the module is GPL-2). ToC10 is about the
  size of the existing Onyxia + OS work together.
- **Decision:** ToC10 first, then Halls of Reflection?

**4. Per-raid guides.** One short card per instance: "Bots know these fights / you do these things" (who
interrupts, where to stand, what the bots don't do). In the Bots window (an "Here" line when you are inside an
instance) and on the docs site. Text from the coverage table; no game data.

**5. Loot: always pass.** Done, global keys (need, greed, disenchant, recipes off; no looting under free-for-all).
The one hole: items under the loot threshold go round-robin.
- **Decision:** when `.recruit party/raid` creates or fills a group the player leads, set the loot method to
  free-for-all (bots never loot under it), and tell the player once? Or leave group loot and the round-robin
  greys/whites as now?

### P2: raid nights that work

**6. Smarter raid play.**
- Formation per fight: the window's formation picker exists now; next, per-boss defaults (spread for chain
  damage, stack for shared hits) set by the raid strategy itself.
- Interrupt rotation: mod-playerbots interrupts per bot; assign one interrupter per caster mob by `rti`.
- Ready check and buffs before a pull: "Prepare for raid" now does maintenance, autogear, rebuff; add a ready
  check (`ready` command) so the window shows who is missing mana or health.
- Raid size: 10 now; 25 stays behind `OV_COMPANIONS_RAID25` until the load numbers below say yes.

**7. Measured server-load caps.** Today's caps (9 per player, 60 per realm) are sensible guesses, not
measurements. Plan:
- Turn on `Playerbots.PerfMonEnabled` (env `AC_PLAYERBOTS_PERF_MON_ENABLED=1`) on a test realm; GMs read it with
  `.playerbots pmon` (and reset it), plus the core's `.server info` (world update time).
- Load test on the real host (2 CPUs): 1, 3, 6 owners with 9 bots each in a raid instance, in combat, for 10
  minutes; record median and p95 world update time and CPU.
- Rule: the realm cap is the largest load with p95 update under 100 ms and no player-visible lag; keep 25 % headroom.
  `OV_COMPANIONS_REALM_MAX` follows the number. Re-measure after each module bump.
- Knobs that help: `BotActiveAlone` and its smart scale (idle bots far from players think less),
  `IterationsPerTick`, `ReactDelay` / `DynamicReactDelay`.

**8. A bot-quality regression test.** So a module bump never quietly makes bots worse.
- A fixed scenario on a test realm, run by Autopilot after each image build: a GM character recruits a fixed
  10-player raid (fixed classes and specs), teleports to a fixed target (a training dummy area for rotation
  output; one simple boss, e.g. Patchwerk in Naxxramas 10, for tank, heal and threat), fights 3 times.
- Scorecard from the fight log: damage per bot vs its spec's baseline, deaths, wipes, time to kill, non-tank
  aggro in the first 5 s, overheal, bots that idled more than 5 s in combat.
- Pass if no figure is worse than the last good build by more than 10 %. The scorecard goes to the watchdog
  report; a fail blocks the image from going live.

### P3: polish

**9. Rotations from wowsims APLs.** wowsims/wotlk is MIT-licensed (copyright 2022 wowsims team). Its action
priority lists are good, tested statements of "what to press next" per spec. We may port the *priorities*
(the order and conditions) into mod-playerbots' action priorities for specs where bots are weakest, with credit
in the source and the docs. We never copy wowsims' item, spell or talent databases: those are derived from the
game's own data. **Decision:** OK to port priorities under MIT with credit?

**10. Window, next steps.** Per-bot "heal the tank first", "tank pulls" switch, a ready-check column, the
per-instance card, keybinds for Follow/Stay/Attack, and a compact mode (just bars) for raids.

## Herald (Open Vanilla 1.12: the self-bot, cmangos playerbots)

Herald is the bot AI playing a real player's own character on the 1.12 realm. From the patches on disk:
- **0020 Herald's brain** (on cmangos playerbots 31e0f32): a fight predictor with a risk budget decides each
  pull; stuck recovery in steps after 25 / 70 / 150 s; grouping with another Herald for a shared quest (invite,
  accept, leave queued as the client's own packets); gray-only selling and repairs; memory of where and to what
  he died (an hour); a fight log and a stuck log in the database (a scorecard reads them); one line per choice for
  the Herald panel, sent only to his own client (`OVH:` lines kept out of chat); eleven upstream fixes.
- **0055 straight questing**: no side trips (trainers, cities, auction house) since spells are learned on
  level-up there and every character has a mount; rides when travelling.
- The project's "Herald never dies" plan (claude/herald-never-die-plan.md) holds the current status and targets.
  TODO(owner): confirm what is live on Open Vanilla now; this plan only carries ideas across.

**What carries over to Companions**
- The fight log and the scorecard (Herald has them; Companions needs them for P1 and P2 above).
- The risk budget, as a pull gate for the "Tank pulls" switch: the tank bot won't pull a pack the group's
  health, mana and gear can't take (Herald's predictor, with group numbers instead of one character's).
- Stuck recovery in steps (bots that fall behind in instances: summon, then teleport, then report).
- The panel line: one short "why" per choice ("Waiting: tank has no threat yet") shown in the Bots window,
  never in chat; same channel idea as `OVH:` and `wucomp`.

**What carries over to Herald**
- The chatless window pattern (addon channel, realm-side checks) and the chatter filter.
- Ownership recovery after a crash, if Herald sessions can come back without their state.

## Shared ideas

- **Fight logs.** One row per fight: realm, instance, boss or trash, group (classes, specs, item levels), duration,
  deaths, wipes, damage and healing per bot, who had aggro when, threat leader changes, the bots' last 10
  actions before each death. Tables `mod_companions_fight` (3.3.5a) and Herald's `openvanilla_herald_fight`
  (1.12), same columns where they can be.
- **A risk budget.** Each choice (pull, chain-pull, stand in a ground effect to finish a cast) spends risk; a
  group has a budget that refills out of combat. Herald's predictor shows it works for one character.
- **Data-tuned thresholds.** Heal thresholds, wait-for-attack seconds, AoE avoid radius, mana save points: set
  from the fight logs per instance, re-tuned monthly; every change logged with the numbers that drove it.
- **wowsims APL rotations** (MIT, credited; never their game-derived data). See P3.

## What we will NOT do

- **No LLM chat at launch.** Bots don't hold conversations; they answer orders. An LLM would cost money per
  message, invent things, and blur "bot" and "player". Revisit only as an opt-in, clearly labelled, after launch.
  **Decision** if ever.
- **No "AGI" or "human-like" claims** in any text players or visitors see. They are scripted bots that follow
  priorities, tuned with data.
- No bots that pretend to be players, join random players' groups unasked, or take loot.
- Nothing decompiled or derived from wowdecomp/Waystone, and no game data shipped.

## Order of work

| # | Item | Impact | Where | Steps to ship |
|---|---|---|---|---|
| 1 | Bots window, crash recovery, chatter filter | high | Lua, addon | done on this branch: scripts, foreverui |
| 2 | Fight log (Companions) | enables 3-8 | Lua (`ON_ENTER/LEAVE_COMBAT`, deaths), table | scripts |
| 3 | Tank pulls switch, heal-the-tank | high | Lua + addon (strategies exist) | scripts, foreverui |
| 4 | Load test, real caps | high (stability) | ops, env | realm |
| 5 | ToC10 strategies | high for raiders | C++ in our module fork, CI | image build, realm |
| 6 | Regression scorecard | protects all of the above | Autopilot, test realm | - |
| 7 | Halls of Reflection | medium | C++, CI | image build, realm |
| 8 | Per-instance guide card | medium | addon + docs | foreverui, client |
| 9 | APL ports for weak specs | medium | C++, CI | image build, realm |
| 10 | Core patch: no achievement chat for bots | low (the filter covers our players) | C++ core fork, CI | image build, realm |

## Owner decisions

1. ToC10 first, then Halls of Reflection? (recommended)
2. Loot: free-for-all set automatically when a fill makes or fills your group, or leave group loot as now?
3. wowsims APL priorities ported under MIT with credit, never their data: OK?
4. The one-line core patch so bots never announce achievements to anyone (not just our addon users): OK to
   carry in our core fork?
5. 25-player raids stay off until the load test says the host can carry them: agreed?
6. LLM chat: confirm "not at launch".
