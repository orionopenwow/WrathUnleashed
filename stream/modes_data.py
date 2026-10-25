#!/usr/bin/env python3
"""The Modes hub's data (stream/modes.py, GET /wrath/modes) and the go-anywhere allow-list of
realm/custom/lua_scripts/ov_go.lua, kept in this ONE file.

    python3 -I stream/modes_data.py --lua            print the Lua table ov_go.lua carries
    python3 -I stream/modes_data.py --write <ov_go>  rewrite that table inside ov_go.lua (between its
                                                     BEGIN/END GENERATED lines)

stream/tests/test_modes.py fails when ov_go.lua's copy and this file disagree, and when an ENTRANCES
number disagrees with stream/slices/mini.json.

Where the numbers come from:
  map ids      Map.dbc ids of 3.3.5a (build 12340), the same ids AzerothCore's world database uses
               (instance_template.map, areatrigger_teleport.target_map). The 5-player ids match
               ov_slices.lua's CLASSIC5 / BC5 / WRATH5 pools.
  ENTRANCES    (map -> x, y, z, orientation): copied from stream/slices/mini.json's "play" entries (the
               .play teleports, which are AzerothCore's areatrigger_teleport targets: the spot just inside
               the instance's door). A map without an entry here has none in mini.json: ov_go.lua then
               reads the first areatrigger_teleport row for that target_map from the world database at
               run time, and says "no entrance on file" if there is none.
  HANGOUTS     Dalaran: game_tele "Dalaran" (the same numbers as ov_slices.lua's HOME and ov_qol.lua's
               hub). Goldshire Inn: ov_demo.lua's INN (in front of the innkeeper's counter).
  levels       5-player dungeons: mini.json's "levels" (the realm's own Dungeon Finder range; the first four
               are lowered to 10 on this realm, see ov_slices.lua LFG_MIN_OVERRIDE) where it has them;
               otherwise the Dungeon Finder's usual 3.3.5a range, rounded. Raids: the level the raid is
               tuned for (60, 70, 80). The go check only uses the low end; the instance's own entry rules
               (AzerothCore dungeon_access_template) still apply at the door.
  random queues  LFGDungeons.dbc random ids, the ones ov_slices.lua's RANDOM_POOL knows.
  sizes        the raid sizes of 3.3.5a.
  bots         5-player dungeons and the random queues: the Dungeon Finder fills groups with labelled bots
               (ov_reports.lua .guide), and .recruit (ov_companions.lua) fills a 5-player party. Raids: no,
               .recruit stops at OV_COMPANIONS_GROUP_MAX (5 by default).

Standard library only; no game files are read or kept.
"""
from __future__ import annotations

import re
import sys

# map -> (x, y, z, o), from stream/slices/mini.json (see above)
ENTRANCES = {
    389: (3.81, -14.82, -17.84, 4.39), 43: (-163.49, 132.9, -73.66, 5.83), 36: (-16.4, -383.07, 61.78, 1.86),
    33: (-229.135, 2109.18, 76.8898, 1.267), 48: (-151.89, 106.96, -39.87, 4.53), 34: (54.23, 0.28, -18.34, 6.26),
    90: (-332.22, -2.28, -150.86, 2.77), 47: (1943, 1544.63, 82, 1.38), 189: (1688.99, 1053.48, 18.6775, 0.00117),
    129: (2592.55, 1107.5, 51.29, 4.74), 70: (-226.8, 49.09, -46.03, 1.39), 349: (1019.69, -458.31, -43.43, 0.31),
    209: (1213.52, 841.59, 8.93, 6.09), 109: (-319.24, 99.9, -131.85, 3.19), 230: (456.929, 34.0923, -68.0896, 4.71239),
    429: (44.4499, -154.822, -2.71201, 0), 229: (78.5083, -225.044, 49.839, 5.1), 289: (196.37, 127.05, 134.91, 6.09),
    329: (3593.15, -3646.56, 138.5, 5.33),
    543: (-1355.24, 1641.12, 68.2491, 0.6687), 542: (-3.9967, 14.6363, -44.8009, 4.88748),
    547: (120.101, -131.957, -0.801547, 1.47574), 546: (9.71391, -16.2008, -2.75334, 5.57082),
    557: (0.0191, 0.9478, -0.9543, 3.03164), 558: (-21.8975, 0.16, -0.1206, 0.0353412),
    560: (2741.87, 1315.25, 14.0423, 2.96016), 556: (-4.6811, -0.0930796, 0.0062, 0.0353424),
    269: (-1496.24, 7034.7, 32.5619, 1.75699), 545: (-13.8425, 6.7542, -4.2586, 0),
    555: (0.488033, -0.215935, -1.12788, 3.15888), 540: (-40.8716, -19.7538, -13.8065, 1.11133),
    553: (40.0395, -28.613, -1.1189, 2.35856), 554: (-28.906, 0.680314, -1.81282, 0.0345509),
    552: (-1.23165, 0.0143459, -0.204293, 0.0157123), 585: (7.09, -0.45, -2.8, 0.05),
    574: (153.789, -86.548, 12.551, 0.304), 601: (413.314, 795.968, 831.351, 5.5), 619: (333.351, -1109.94, 69.772, 0.553),
    600: (-517.343, -487.976, 11.01, 4.831), 604: (1891.84, 832.169, 176.669, 2.109), 578: (1055.93, 986.85, 361.07, 5.745),
    608: (1808.82, 803.93, 44.364, 6.282), 650: (805.227, 618.038, 412.393, 3.1456),
    575: (584.117, -327.974, 110.138, 3.122), 602: (1331.47, 259.619, 53.398, 4.772), 599: (1153.24, 806.164, 195.937, 4.715),
    576: (145.87, -10.554, -16.636, 1.528), 595: (1431.1, 556.92, 36.69, 5.16),
    632: (4922.86, 2175.63, 638.734, 2.00355), 658: (435.743, 212.413, 528.709, 6.25646), 668: (5239.01, 1932.64, 707.695, 0.800565),
    533: (3005.68, -3447.77, 293.93, 4.65), 615: (3228.58, 385.86, 65.549, 1.578), 624: (-505.96, -103.353, 157, 0),
    649: (563.61, 80.6815, 395.2, 1.59), 631: (76.8638, 2211.37, 30, 3.14965), 603: (-914.041, -148.98, 463.137, 6.28),
    616: (728.055, 1329.03, 267.235, 5.51524), 249: (29.1607, -71.3372, -8.18032, 4.58), 724: (3274, 533.531, 87.665, 3.16),
}

EXPANSIONS = [
    ("azeroth", "Azeroth", "Levels 10 to 60"),
    ("outland", "Outland", "Levels 60 to 70"),
    ("northrend", "Northrend", "Levels 70 to 80"),
]

# ---------------------------------------------------------------------------------------------
# Hangouts and duels (share kind "h")
# ---------------------------------------------------------------------------------------------
DALARAN = (571, 5807.98, 588.487, 660.94, 1.66594)     # game_tele "Dalaran"
GOLDSHIRE_INN = (0, -9460.3, 18.9, 57.0, 3.98)          # ov_demo.lua INN

HANGOUTS = [
    {"id": "dalaran", "name": "Dalaran", "pos": DALARAN, "min": 1, "tag": "Any level",
     "line": "The floating city: everyone meets here. Boost to 80 and land right in it."},
    {"id": "goldshire-inn", "name": "The Goldshire Inn", "pos": GOLDSHIRE_INN, "min": 1, "tag": "Any level",
     "line": "The Lion's Pride Inn in Elwynn Forest. With your own game files, or try it with no sign-up."},
]

# The duel spot: the Dalaran hangout's meeting point (duels work anywhere in the city).
DUEL = {"id": "duels", "name": "Duels in Dalaran", "pos": DALARAN, "min": 1, "tag": "Any level · 1 v 1",
        "line": "Meet in the city centre and challenge anyone who agrees.",
        "hint": "Duel: target a player and type /duel, or right-click their portrait. Either of you can say no."}

# ---------------------------------------------------------------------------------------------
# 5-player dungeons (share kind "q", by slug) and the random queues (kind "q", by LFG id)
# ---------------------------------------------------------------------------------------------
# (slug, name, map, (low, high))
_D = {
    "azeroth": [
        ("ragefire-chasm", "Ragefire Chasm", 389, (10, 21)), ("wailing-caverns", "Wailing Caverns", 43, (10, 25)),
        ("deadmines", "The Deadmines", 36, (10, 23)), ("shadowfang-keep", "Shadowfang Keep", 33, (10, 26)),
        ("blackfathom-deeps", "Blackfathom Deeps", 48, (20, 30)), ("stockade", "The Stockade", 34, (22, 30)),
        ("gnomeregan", "Gnomeregan", 90, (24, 34)), ("razorfen-kraul", "Razorfen Kraul", 47, (24, 34)),
        ("scarlet-monastery", "Scarlet Monastery", 189, (26, 45)), ("razorfen-downs", "Razorfen Downs", 129, (33, 43)),
        ("uldaman", "Uldaman", 70, (35, 45)), ("maraudon", "Maraudon", 349, (40, 52)),
        ("zulfarrak", "Zul'Farrak", 209, (42, 54)), ("sunken-temple", "The Temple of Atal'Hakkar", 109, (45, 55)),
        ("blackrock-depths", "Blackrock Depths", 230, (48, 60)), ("dire-maul", "Dire Maul", 429, (54, 60)),
        ("blackrock-spire", "Blackrock Spire (Lower and Upper)", 229, (55, 60)),
        ("scholomance", "Scholomance", 289, (56, 60)), ("stratholme", "Stratholme", 329, (56, 60)),
    ],
    "outland": [
        ("hellfire-ramparts", "Hellfire Ramparts", 543, (59, 67)), ("blood-furnace", "The Blood Furnace", 542, (61, 68)),
        ("slave-pens", "The Slave Pens", 547, (62, 69)), ("underbog", "The Underbog", 546, (63, 70)),
        ("mana-tombs", "Mana-Tombs", 557, (64, 70)), ("auchenai-crypts", "Auchenai Crypts", 558, (65, 70)),
        ("old-hillsbrad", "Old Hillsbrad Foothills", 560, (66, 70)), ("sethekk-halls", "Sethekk Halls", 556, (67, 70)),
        ("black-morass", "The Black Morass", 269, (68, 70)), ("steamvault", "The Steamvault", 545, (68, 70)),
        ("shadow-labyrinth", "Shadow Labyrinth", 555, (69, 70)), ("shattered-halls", "The Shattered Halls", 540, (69, 70)),
        ("botanica", "The Botanica", 553, (69, 70)), ("mechanar", "The Mechanar", 554, (69, 70)),
        ("arcatraz", "The Arcatraz", 552, (69, 70)), ("magisters-terrace", "Magisters' Terrace", 585, (69, 70)),
    ],
    "northrend": [
        ("utgarde-keep", "Utgarde Keep", 574, (69, 80)), ("nexus", "The Nexus", 576, (71, 80)),
        ("azjol-nerub", "Azjol-Nerub", 601, (72, 80)), ("ahnkahet", "Ahn'kahet: The Old Kingdom", 619, (73, 80)),
        ("draktharon-keep", "Drak'Tharon Keep", 600, (74, 80)), ("violet-hold", "The Violet Hold", 608, (75, 80)),
        ("gundrak", "Gundrak", 604, (76, 80)), ("halls-of-stone", "Halls of Stone", 599, (77, 80)),
        ("halls-of-lightning", "Halls of Lightning", 602, (78, 80)), ("oculus", "The Oculus", 578, (79, 80)),
        ("utgarde-pinnacle", "Utgarde Pinnacle", 575, (78, 80)),
        ("culling-of-stratholme", "The Culling of Stratholme", 595, (78, 80)),
        ("trial-of-the-champion", "Trial of the Champion", 650, (78, 80)),
        ("forge-of-souls", "The Forge of Souls", 632, (80, 80)), ("pit-of-saron", "Pit of Saron", 658, (80, 80)),
        ("halls-of-reflection", "Halls of Reflection", 668, (80, 80)),
    ],
}
DUNGEONS = [{"id": s, "name": n, "map": m, "levels": lv, "exp": exp, "bots": True}
            for exp, rows in _D.items() for s, n, m, lv in rows]

RANDOM_QUEUES = [
    {"id": "258", "name": "Random dungeon: Azeroth", "levels": (15, 60), "exp": "azeroth", "bots": True,
     "line": "The Dungeon Finder picks one of the Azeroth dungeons for your level."},
    {"id": "259", "name": "Random dungeon: Outland", "levels": (59, 70), "exp": "outland", "bots": True,
     "line": "One of the Outland dungeons, picked for your level."},
    {"id": "260", "name": "Random Heroic: Outland", "levels": (70, 70), "exp": "outland", "bots": True,
     "line": "An Outland dungeon on Heroic, at level 70."},
    {"id": "261", "name": "Random dungeon: Northrend", "levels": (69, 80), "exp": "northrend", "bots": True,
     "line": "One of the Northrend dungeons, picked for your level."},
    {"id": "262", "name": "Random Heroic: Northrend", "levels": (80, 80), "exp": "northrend", "bots": True,
     "line": "A Northrend Heroic at 80: Emblems of Triumph, and extra for the first each day."},
]

# ---------------------------------------------------------------------------------------------
# Raids (share kind "b": a raid, or one of its wings)
# ---------------------------------------------------------------------------------------------
RAIDS = [
    # Azeroth
    {"id": "molten-core", "name": "Molten Core", "map": 409, "exp": "azeroth", "level": 60, "size": "40",
     "bosses": ["Lucifron", "Magmadar", "Gehennas", "Garr", "Shazzrah", "Baron Geddon", "Sulfuron Harbinger",
                "Golemagg the Incinerator", "Majordomo Executus", "Ragnaros"]},
    {"id": "blackwing-lair", "name": "Blackwing Lair", "map": 469, "exp": "azeroth", "level": 60, "size": "40",
     "bosses": ["Razorgore the Untamed", "Vaelastrasz the Corrupt", "Broodlord Lashlayer", "Firemaw", "Ebonroc",
                "Flamegor", "Chromaggus", "Nefarian"]},
    {"id": "zulgurub", "name": "Zul'Gurub", "map": 309, "exp": "azeroth", "level": 60, "size": "20",
     "bosses": ["High Priestess Jeklik", "High Priest Venoxis", "High Priestess Mar'li", "Bloodlord Mandokir",
                "High Priest Thekal", "High Priestess Arlokk", "Jin'do the Hexxer", "Hakkar"]},
    {"id": "ruins-of-ahnqiraj", "name": "Ruins of Ahn'Qiraj", "map": 509, "exp": "azeroth", "level": 60, "size": "20",
     "bosses": ["Kurinnaxx", "General Rajaxx", "Moam", "Buru the Gorger", "Ayamiss the Hunter", "Ossirian the Unscarred"]},
    {"id": "temple-of-ahnqiraj", "name": "Temple of Ahn'Qiraj", "map": 531, "exp": "azeroth", "level": 60, "size": "40",
     "bosses": ["The Prophet Skeram", "Battleguard Sartura", "Fankriss the Unyielding", "Princess Huhuran",
                "The Twin Emperors", "C'Thun"]},
    # Outland
    {"id": "karazhan", "name": "Karazhan", "map": 532, "exp": "outland", "level": 70, "size": "10",
     "bosses": ["Attumen the Huntsman", "Moroes", "Maiden of Virtue", "The Opera Event", "The Curator",
                "Terestian Illhoof", "Shade of Aran", "Netherspite", "The Chess Event", "Prince Malchezaar", "Nightbane"]},
    {"id": "gruuls-lair", "name": "Gruul's Lair", "map": 565, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["High King Maulgar", "Gruul the Dragonkiller"]},
    {"id": "magtheridons-lair", "name": "Magtheridon's Lair", "map": 544, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["Magtheridon"]},
    {"id": "serpentshrine-cavern", "name": "Serpentshrine Cavern", "map": 548, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["Hydross the Unstable", "The Lurker Below", "Leotheras the Blind", "Fathom-Lord Karathress",
                "Morogrim Tidewalker", "Lady Vashj"]},
    {"id": "tempest-keep", "name": "Tempest Keep: The Eye", "map": 550, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["Al'ar", "Void Reaver", "High Astromancer Solarian", "Kael'thas Sunstrider"]},
    {"id": "hyjal-summit", "name": "Hyjal Summit", "map": 534, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["Rage Winterchill", "Anetheron", "Kaz'rogal", "Azgalor", "Archimonde"]},
    {"id": "black-temple", "name": "Black Temple", "map": 564, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["High Warlord Naj'entus", "Supremus", "Shade of Akama", "Teron Gorefiend", "Gurtogg Bloodboil",
                "Reliquary of Souls", "Mother Shahraz", "The Illidari Council", "Illidan Stormrage"]},
    {"id": "zulaman", "name": "Zul'Aman", "map": 568, "exp": "outland", "level": 70, "size": "10",
     "bosses": ["Nalorakk", "Akil'zon", "Jan'alai", "Halazzi", "Hex Lord Malacrass", "Zul'jin"]},
    {"id": "sunwell-plateau", "name": "Sunwell Plateau", "map": 580, "exp": "outland", "level": 70, "size": "25",
     "bosses": ["Kalecgos", "Brutallus", "Felmyst", "The Eredar Twins", "M'uru", "Kil'jaeden"]},
    # Northrend
    {"id": "naxxramas", "name": "Naxxramas", "map": 533, "exp": "northrend", "level": 80, "size": "10 / 25",
     "hint": "All four quarters open from the central hall; the Frostwyrm Lair opens when all four are cleared.",
     "wings": [
         {"id": "naxx-arachnid", "name": "The Arachnid Quarter", "bosses": ["Anub'Rekhan", "Grand Widow Faerlina", "Maexxna"]},
         {"id": "naxx-plague", "name": "The Plague Quarter", "bosses": ["Noth the Plaguebringer", "Heigan the Unclean", "Loatheb"]},
         {"id": "naxx-military", "name": "The Military Quarter", "bosses": ["Instructor Razuvious", "Gothik the Harvester", "The Four Horsemen"]},
         {"id": "naxx-construct", "name": "The Construct Quarter", "bosses": ["Patchwerk", "Grobbulus", "Gluth", "Thaddius"]},
         {"id": "naxx-frostwyrm", "name": "The Frostwyrm Lair", "bosses": ["Sapphiron", "Kel'Thuzad"]},
     ]},
    {"id": "obsidian-sanctum", "name": "The Obsidian Sanctum", "map": 615, "exp": "northrend", "level": 80, "size": "10 / 25",
     "bosses": ["Sartharion (with up to three drakes)"]},
    {"id": "vault-of-archavon", "name": "Vault of Archavon", "map": 624, "exp": "northrend", "level": 80, "size": "10 / 25",
     "bosses": ["Archavon the Stone Watcher", "Emalon the Storm Watcher", "Koralon the Flame Watcher", "Toravon the Ice Watcher"]},
    {"id": "eye-of-eternity", "name": "The Eye of Eternity", "map": 616, "exp": "northrend", "level": 80, "size": "10 / 25",
     "bosses": ["Malygos"]},
    {"id": "onyxias-lair", "name": "Onyxia's Lair", "map": 249, "exp": "northrend", "level": 80, "size": "10 / 25",
     "bosses": ["Onyxia"]},
    {"id": "ulduar", "name": "Ulduar", "map": 603, "exp": "northrend", "level": 80, "size": "10 / 25",
     "hint": "Ulduar's teleporters, by the entrance and in each wing, open as your raid clears the way.",
     "wings": [
         {"id": "ulduar-siege", "name": "The Siege", "bosses": ["Flame Leviathan", "Ignis the Furnace Master", "Razorscale", "XT-002 Deconstructor"]},
         {"id": "ulduar-antechamber", "name": "The Antechamber", "bosses": ["The Assembly of Iron", "Kologarn", "Auriaya"]},
         {"id": "ulduar-keepers", "name": "The Keepers", "bosses": ["Hodir", "Thorim", "Freya", "Mimiron"]},
         {"id": "ulduar-descent", "name": "The Descent into Madness", "bosses": ["General Vezax", "Yogg-Saron"]},
         {"id": "ulduar-planetarium", "name": "The Celestial Planetarium", "bosses": ["Algalon the Observer"]},
     ]},
    {"id": "trial-of-the-crusader", "name": "Trial of the Crusader", "map": 649, "exp": "northrend", "level": 80, "size": "10 / 25",
     "bosses": ["The Northrend Beasts", "Lord Jaraxxus", "The Faction Champions", "The Twin Val'kyr", "Anub'arak"]},
    {"id": "icecrown-citadel", "name": "Icecrown Citadel", "map": 631, "exp": "northrend", "level": 80, "size": "10 / 25",
     "hint": "Inside, the teleporter at Light's Hammer takes your raid to every wing it has opened.",
     "wings": [
         {"id": "icc-lower-spire", "name": "The Lower Spire", "bosses": ["Lord Marrowgar", "Lady Deathwhisper", "The Gunship Battle", "Deathbringer Saurfang"]},
         {"id": "icc-plagueworks", "name": "The Plagueworks", "bosses": ["Festergut", "Rotface", "Professor Putricide"]},
         {"id": "icc-crimson-hall", "name": "The Crimson Hall", "bosses": ["The Blood Prince Council", "Blood-Queen Lana'thel"]},
         {"id": "icc-frostwing-halls", "name": "The Frostwing Halls", "bosses": ["Valithria Dreamwalker", "Sindragosa"]},
         {"id": "icc-frozen-throne", "name": "The Frozen Throne", "bosses": ["the Frozen Throne"]},
     ]},
    {"id": "ruby-sanctum", "name": "The Ruby Sanctum", "map": 724, "exp": "northrend", "level": 80, "size": "10 / 25",
     "bosses": ["Baltharus the Warborn", "Saviana Ragefire", "General Zarithrian", "Halion"]},
]

KEYS_DUNGEON = "q"
KEYS_RAID = "b"
KEYS_HANGOUT = "h"
_SLUG = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,30}[a-z0-9])?$")


def places() -> dict:
    """Every go target, "<kind>:<id>" -> a plain dict the hub and ov_go.lua both read:
    name, what (hangout | dungeon | queue | raid | wing), map, pos (map, x, y, z, o) or None, min (level),
    raid (needs a raid group), hint, bots."""
    out = {}
    for h in HANGOUTS + [DUEL]:
        out[f"h:{h['id']}"] = {"name": h["name"], "what": "hangout", "map": h["pos"][0], "pos": h["pos"],
                               "min": h["min"], "raid": False, "hint": h.get("hint", ""), "bots": False}
    for d in DUNGEONS:
        e = ENTRANCES.get(d["map"])
        out[f"q:{d['id']}"] = {"name": d["name"], "what": "dungeon", "map": d["map"],
                               "pos": (d["map"],) + e if e else None, "min": d["levels"][0], "raid": False,
                               "hint": "", "bots": True}
    for r in RANDOM_QUEUES:
        out[f"q:{r['id']}"] = {"name": r["name"], "what": "queue", "map": None, "pos": None, "min": r["levels"][0],
                               "raid": False, "hint": "", "bots": True}
    for r in RAIDS:
        e = ENTRANCES.get(r["map"])
        pos = (r["map"],) + e if e else None
        out[f"b:{r['id']}"] = {"name": r["name"], "what": "raid", "map": r["map"], "pos": pos, "min": r["level"],
                               "raid": True, "hint": r.get("hint", ""), "bots": False}
        for w in r.get("wings", []):
            out[f"b:{w['id']}"] = {"name": f"{r['name']}: {w['name']}", "what": "wing", "map": r["map"], "pos": pos,
                                   "min": r["level"], "raid": True, "hint": r.get("hint", ""), "bots": False}
    return out


def check() -> list[str]:
    """Problems with the tables (empty when fine): ids the share links would refuse, duplicates."""
    bad, seen = [], set()
    for key in places():
        kind, ident = key.split(":", 1)
        if not _SLUG.fullmatch(ident) or len(key) > 40:
            bad.append(f"bad id {key}")
    ids = ([("h", h["id"]) for h in HANGOUTS + [DUEL]] + [("q", d["id"]) for d in DUNGEONS]
           + [("q", r["id"]) for r in RANDOM_QUEUES] + [("b", r["id"]) for r in RAIDS]
           + [("b", w["id"]) for r in RAIDS for w in r.get("wings", [])])
    for k in ids:
        if k in seen:
            bad.append(f"duplicate {k[0]}:{k[1]}")
        seen.add(k)
    return bad


def _lua_str(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _num(v) -> str:
    return repr(float(v)).rstrip("0").rstrip(".") if isinstance(v, float) else str(int(v))


def lua() -> str:
    """The OV_GO_PLACES table ov_go.lua carries (generated: edit this file, then --write)."""
    lines = ["local PLACES = {"]
    for key, p in sorted(places().items()):
        pos = "nil" if not p["pos"] else "{ " + ", ".join(_num(v) for v in p["pos"]) + " }"
        lines.append(f'    [{_lua_str(key)}] = {{ name = {_lua_str(p["name"])}, what = {_lua_str(p["what"])}, '
                     f'map = {p["map"] if p["map"] is not None else "nil"}, pos = {pos}, min = {int(p["min"])}, '
                     f'raid = {"true" if p["raid"] else "false"}, hint = {_lua_str(p["hint"])} }},')
    lines.append("}")
    return "\n".join(lines) + "\n"


BEGIN = "-- BEGIN GENERATED by stream/modes_data.py --write (do not edit by hand)\n"
END = "-- END GENERATED\n"


def splice(text: str) -> str:
    """text (ov_go.lua) with the generated block replaced by lua()."""
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    return text[:a] + lua() + text[b:]


if __name__ == "__main__":
    if check():
        print("\n".join(check()), file=sys.stderr)
        sys.exit(1)
    if sys.argv[1:2] == ["--lua"]:
        sys.stdout.write(lua())
    elif sys.argv[1:2] == ["--write"] and len(sys.argv) == 3:
        with open(sys.argv[2], encoding="utf-8", newline="") as f:
            old = f.read()
        new = splice(old)
        if new != old:
            with open(sys.argv[2], "w", encoding="utf-8", newline="") as f:
                f.write(new)
        print("ov_go.lua table: " + ("updated" if new != old else "already current"))
    else:
        print(__doc__.split("\n\n")[1])
        sys.exit(2)
