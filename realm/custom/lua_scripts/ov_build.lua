-- ov_build.lua: the Builder, props players place, move and save in build areas (mod-ale, 3.3.5a).
-- The first step on the road to a sandbox: builders spawn props from a catalog, nudge and turn them, save a
-- build relative to where they stand, and share it as a short code anyone can paste somewhere else.
--
--   .build help                       the commands and the limits (.build alone is the same)
--   .build catalog [word]             the props you can place (a category or part of a name)
--   .build where                      the build areas, and whether you stand in one
--   .build spawn <id|name>            a prop at your position and facing; it becomes your selection
--   .build near                       your props within 40 yards, numbered (GMs see everyone's)
--   .build select <n>                 picks prop n from .build near
--   .build move x|y|z <yards>         moves the selection (world axes, up to 10 yards a step)
--   .build turn <degrees>             turns the selection (+ is to the left)
--   .build undo                       takes back your last spawn, move, turn, delete, clear or load
--   .build delete                     removes the selection
--   .build clear                      removes all your props in this area
--   .build save <name>                saves your props in this area as a build, relative to you
--   .build load <name|code>           pastes a build at your position and facing
--   .build share <name>               prints the build's code (6 letters and digits) to give to others
--   .build saved                      your saved builds
--   Edit mode (the browser client's free camera, EditMode.lua) also sends:
--   .build pick <object id> [add]     selects the clicked prop (its GUID counter); "add" (Shift-click) adds it
--                                     to the selection, or takes it out
--   .build spawnat <id> <x> <y> <z>   a prop at an exact point you clicked (within 100 yards, in the area)
--   .build placeat <x> <y> <z> <deg>  moves the selection to an exact point and turns it <deg> (a drag-and-drop);
--                                     a group keeps its shape around the last-picked prop
--   .build dup                        a copy of the selection 1.5 yards beside it; the copy becomes the selection
--   .build selbox <x1> <y1> <x2> <y2> [add]   every prop you may select inside a box on the ground
--   .build selall [yards]             all your own props within 20 (up to 40) yards
--   .build selclear                   nothing selected
--   .build copy                       copies the selection; .build pasteat <x> <y> <z> [deg] pastes it around a
--                                     point (.build paste alone: at your feet)
--   .build setpos <x> <y> <z> | setturn <deg> | setscale <size>   the properties panel's exact numbers
--   .build prefab save|list|paste|pasteat|share|delete ...   prefabs: a named selection, as JSON
--   .build plot [claim|add <name> [builder|visitor]|remove <name>|abandon]   your plot, built with friends
--   GM only: .build grant <name> | revoke <name> | purge <name> | trust <name> <tier>
--            .build plot list | plot remove <id> | plot transfer <id> <name>
--            .build oplog <name> [n] | rollback <name> [ops] [yards]
--
-- Group ops (move, turn, delete, dup, placeat, set*) work on the whole selection, all or none, and are one
-- undo entry each. Every change to a prop is written to mod_builder_oplog (one op per command) for rollback.
--
-- Plots (mod_builder_plots, mod_builder_plot_members; the plan's sandbox_plots): a circle claimed inside a
-- build area. In a plot only its owner, its builders and GMs place, move or delete; visitors may select and
-- copy. Outside plots (the commons) your own props are yours to change, unless OV_BUILD_PLOTS_ONLY=1.
-- Budgets: props and build points (a prop's weight, CAT_COST) per player, scaled by a trust tier (new 40%,
-- builder 100%, trusted 300%, master 800%), and per plot. Every mutation checks role, ownership or plot role,
-- area and plot bounds, distance, budget and rate.
--
-- OVBuild (global, for other realm scripts such as ov_workshop.lua): ExportPrefab(id or code),
-- ImportPrefab(data, player, x, y, z, o), SavePrefab(player, name, data), ListPrefabs(guid), ParsePrefab(data).
--
-- Who builds: GMs always; others once a GM runs .build grant <name> (stored in mod_builder_roles). Building
-- happens only inside BUILD_AREAS (below); GMs build anywhere in the open world when OV_BUILD_ANYWHERE=1.
--
-- How props live (why not PerformIngameSpawn with save = true): a saved spawn is written by the core into the
-- world database's own gameobject table. The mod rules (mods/SPEC.md) keep scripts to their own tables, and a
-- saved spawn in a grid nobody is near can't be found from Lua to delete it again, so purge and clear would
-- leak rows into the world database. Instead mod_builder_props (characters database) is the only record, and
-- props are spawned unsaved with PerformIngameSpawn(2, ...). An unsaved object goes away when its grid unloads
-- or the server restarts; sync() puts back every missing prop near a player (on login, zone and map change,
-- every build command, and a 15 s world timer), so builds come back after a restart without touching the
-- core's tables. A move is despawn + respawn at the new position.
--
-- Env (os.getenv at each use; defaults live here so no profile key, and no world-server recreate, is needed):
--   OV_BUILD              on/off                                         default 1
--   OV_BUILD_ANYWHERE     1 = GMs may build outside the build areas       default 0
--   OV_BUILD_PER_PLAYER   props one character may have (tier "builder")   default 50
--   OV_BUILD_PER_AREA     props in one build area                         default 500
--   OV_BUILD_POINTS       build points one character may use ("builder")  default 100
--   OV_BUILD_NEW_HOURS    played hours under which a character is "new"   default 2
--   OV_BUILD_PLOT_SIZE    a plot's radius in yards                        default 12
--   OV_BUILD_PLOT_PROPS   props in one plot                               default 150
--   OV_BUILD_PLOT_POINTS  build points in one plot                        default 300
--   OV_BUILD_PLOTS_EACH   plots one character may claim                   default 1
--   OV_BUILD_PLOTS_ONLY   1 = outside GMs, build only on plots            default 0
-- Rate: one spawn a second, one load every 5 s, five moves or turns a second.
-- The in-game Builder window (WrathUnleashedUI/Builder.lua, /builder) talks to this over the OVMOD channel
-- (ov_modapi.lua), mod "wubuild":
--   client -> server   cmd       <the text after .build>         runs it exactly as the dot command
--                      catalog                                   asks for the catalog
--   server -> client   catalog   id,key,category,name,points;...  the props that exist on this realm
--                      state     sel=<id>,<entry>,<name>;mine=<n>/<cap>;area=<name>;code=<code>;n=<selected>;ids=<id id ...>;
--                                pos=<x>,<y>,<z>,<deg>,<size>;pts=<used>/<cap>;tier=<tier>;
--                                plot=<id>,<owner>,<your role>,<props>/<cap>,<points>/<cap> (or -);clip=<copied>
--                      prefabs   id,name,code,count;...           your prefabs
-- mod-ale events: 3 ON_LOGIN, 4 ON_LOGOUT, 27 ON_UPDATE_ZONE, 28 ON_MAP_CHANGE, 42 ON_COMMAND.

local TAG = "|cff66ccff[Builder]|r "
local MOD = "wubuild"

------------------------------------------------------------------------------------------------
-- build areas: { name, map, x, y, z, radius }. A point is inside when it is within radius yards on the
-- ground and within radius yards up or down. Coordinates are AzerothCore's own game_tele rows
-- (data/sql/base/db_world/game_tele.sql); the spot itself is "to verify" in game for how quiet it is.
------------------------------------------------------------------------------------------------
local BUILD_AREAS = {
    -- game_tele 435 'Goldshire': the road in front of the Lion's Pride Inn, Elwynn Forest (map 0).
    { name = "Goldshire green", map = 0, x = -9448.55, y = 68.24, z = 56.32, r = 45 },
    -- A second area, off by default: game_tele 1490 'CrystalsongForest', the forest below Dalaran (map 571).
    -- { name = "Crystalsong glade", map = 571, x = 5258.39, y = 156.96, z = 191.70, r = 60 },
}

------------------------------------------------------------------------------------------------
-- catalog: gameobject entries players may place. Checked on 2026-10-25 against AzerothCore's
-- data/sql/base/db_world/gameobject_template.sql (master): every entry exists with the type shown
-- (5 generic, 7 chair, 8 spell focus) and has no AIName and no ScriptName (so no traps, loot, quests or
-- scripts ride along). The campfire and bonfire are cooking fires with no linked trap. How each one looks
-- in the world is "to verify" in game. At load, entries missing from this realm's world database are
-- dropped (verify(), one WorldDBQuery).
------------------------------------------------------------------------------------------------
local CATALOG = {
    { id = 2413,   key = "chair",       cat = "seating", name = "Wooden Chair" },       -- type 7
    { id = 2489,   key = "highchair",   cat = "seating", name = "High Back Chair" },    -- type 7
    { id = 182593, key = "stool",       cat = "seating", name = "Stool" },              -- type 7
    { id = 24538,  key = "bench",       cat = "seating", name = "Wooden Bench" },       -- type 7
    { id = 24388,  key = "stonebench",  cat = "seating", name = "Stone Bench" },        -- type 7
    { id = 181075, key = "table",       cat = "tables",  name = "Table" },
    { id = 181305, key = "camptable",   cat = "tables",  name = "Camp Table" },
    { id = 186422, key = "roundtable",  cat = "tables",  name = "Round Table" },
    { id = 183105, key = "orctable",    cat = "tables",  name = "Orc Table" },
    { id = 180698, key = "partytable",  cat = "tables",  name = "Party Table" },
    { id = 179967, key = "barrel",      cat = "barrels", name = "Barrel" },
    { id = 179973, key = "innbarrel",   cat = "barrels", name = "Inn Barrel" },
    { id = 190559, key = "applebarrel", cat = "barrels", name = "Apple Barrel" },
    { id = 179976, key = "beerkeg",     cat = "barrels", name = "Beer Keg" },
    { id = 180575, key = "keg",         cat = "barrels", name = "Keg" },
    { id = 179969, key = "crate",       cat = "crates",  name = "Crate" },
    { id = 179970, key = "crate2",      cat = "crates",  name = "Crate, tall" },
    { id = 179972, key = "citycrate",   cat = "crates",  name = "City Crate" },
    { id = 181302, key = "campcrate",   cat = "crates",  name = "Camp Crate" },
    { id = 201752, key = "bigcrate",    cat = "crates",  name = "Large Crate" },
    { id = 195198, key = "crate3",      cat = "crates",  name = "Crate, small" },
    { id = 19457,  key = "lamppost",    cat = "lights",  name = "Lamp Post" },
    { id = 179977, key = "lantern",     cat = "lights",  name = "Lantern" },
    { id = 180765, key = "lantern2",    cat = "lights",  name = "Hanging Lantern" },
    { id = 180043, key = "torch",       cat = "lights",  name = "Standing Torch" },
    { id = 180352, key = "walltorch",   cat = "lights",  name = "Torch" },
    { id = 180773, key = "banner",      cat = "banners", name = "Banner" },
    { id = 180774, key = "banner2",     cat = "banners", name = "Banner, second" },
    { id = 180775, key = "banner3",     cat = "banners", name = "Banner, third" },
    { id = 19664,  key = "owlbanner",   cat = "banners", name = "Owl Banner" },
    { id = 184592, key = "tent",        cat = "tents",   name = "Tent" },
    { id = 184593, key = "bigtent",     cat = "tents",   name = "Large Tent" },
    { id = 188179, key = "goblintent",  cat = "tents",   name = "Goblin Tent" },
    { id = 179966, key = "carnivaltent", cat = "tents",  name = "Carnival Tent" },
    { id = 1953,   key = "campfire",    cat = "fires",   name = "Campfire" },           -- type 8, cooking
    { id = 50910,  key = "bonfire",     cat = "fires",   name = "Bonfire" },            -- type 8, cooking
    { id = 180035, key = "fence",       cat = "fences",  name = "Fence" },
    { id = 211062, key = "woodfence",   cat = "fences",  name = "Wooden Fence" },
    { id = 211063, key = "woodfence2",  cat = "fences",  name = "Wooden Fence, short" },
    { id = 19455,  key = "stonefence",  cat = "fences",  name = "Stone Fence" },
    { id = 19434,  key = "fencesegment", cat = "fences", name = "Fence Segment" },

    -- Added 2026-10-25 for edit mode: decorative, script-free entries (type 5 generic / 7 chair) picked by name
    -- from AzerothCore's gameobject_template.sql (no AIName, no ScriptName, size 0.2-3, one per model).
    { id = 19478, key = "karazahnthrone", cat = "seating", name = "Karazahn Throne" },   -- type 5, display 9478
    { id = 28611, key = "dwarvenhighbac", cat = "seating", name = "Dwarven High Back Chair" },   -- type 7, display 648
    { id = 48403, key = "shortwoodensea", cat = "seating", name = "Short Wooden Seat" },   -- type 7, display 138
    { id = 61919, key = "woodenchair", cat = "seating", name = "Wooden Chair" },   -- type 7, display 380
    { id = 92703, key = "bench2", cat = "seating", name = "Bench" },   -- type 7, display 682
    { id = 112068, key = "woodenchair2", cat = "seating", name = "Wooden Chair" },   -- type 7, display 92
    { id = 126050, key = "bench3", cat = "seating", name = "Bench" },   -- type 7, display 1569
    { id = 136924, key = "bench4", cat = "seating", name = "Bench" },   -- type 7, display 987
    { id = 136929, key = "chair2", cat = "seating", name = "Chair" },   -- type 7, display 988
    { id = 136930, key = "chair3", cat = "seating", name = "Chair" },   -- type 7, display 989
    { id = 136931, key = "bench5", cat = "seating", name = "Bench" },   -- type 7, display 990
    { id = 142947, key = "stonechair", cat = "seating", name = "Stone Chair" },   -- type 7, display 2087
    { id = 160846, key = "bench6", cat = "seating", name = "Bench" },   -- type 7, display 673
    { id = 170592, key = "imperialthrone", cat = "seating", name = "Imperial Throne" },   -- type 7, display 2810
    { id = 171674, key = "stonechair2", cat = "seating", name = "Stone Chair" },   -- type 7, display 2088
    { id = 176004, key = "subwaybench", cat = "seating", name = "Subway Bench" },   -- type 7, display 4091
    { id = 176561, key = "krastinovswork", cat = "seating", name = "Krastinov's Work Bench" },   -- type 5, display 4391
    { id = 178934, key = "thechair", cat = "seating", name = "The Chair" },   -- type 7, display 5551
    { id = 179118, key = "throne", cat = "seating", name = "Throne" },   -- type 7, display 5592
    { id = 182077, key = "nightelfstool", cat = "seating", name = "Night Elf Stool" },   -- type 5, display 6912
    { id = 182598, key = "chair4", cat = "seating", name = "Chair" },   -- type 7, display 6975
    { id = 182608, key = "bench7", cat = "seating", name = "Bench" },   -- type 7, display 6979
    { id = 182654, key = "chair5", cat = "seating", name = "Chair" },   -- type 7, display 6981
    { id = 182762, key = "chair6", cat = "seating", name = "Chair" },   -- type 7, display 6997
    { id = 183753, key = "chair7", cat = "seating", name = "Chair" },   -- type 7, display 7070
    { id = 184038, key = "bench8", cat = "seating", name = "Bench" },   -- type 7, display 7134
    { id = 184671, key = "chair8", cat = "seating", name = "Chair" },   -- type 7, display 6980
    { id = 184733, key = "chair9", cat = "seating", name = "Chair" },   -- type 7, display 4678
    { id = 186475, key = "fishingchair", cat = "seating", name = "Fishing Chair" },   -- type 7, display 7467
    { id = 186695, key = "chair10", cat = "seating", name = "Chair" },   -- type 7, display 7504
    { id = 187118, key = "zulamaneagleth", cat = "seating", name = "Zul'Aman - Eagle Throne" },   -- type 7, display 7594
    { id = 188227, key = "agmarsthrone", cat = "seating", name = "Agmar's Throne" },   -- type 7, display 7744
    { id = 190694, key = "apothecarybenc", cat = "seating", name = "Apothecary Bench" },   -- type 5, display 7986
    { id = 191475, key = "chair11", cat = "seating", name = "Chair" },   -- type 7, display 8095
    { id = 191476, key = "bench9", cat = "seating", name = "Bench" },   -- type 7, display 8096
    { id = 191886, key = "chair12", cat = "seating", name = "Chair" },   -- type 7, display 7074
    { id = 191887, key = "chair13", cat = "seating", name = "Chair" },   -- type 7, display 8204
    { id = 192199, key = "bench10", cat = "seating", name = "Bench" },   -- type 7, display 8248
    { id = 192722, key = "throne2", cat = "seating", name = "Throne" },   -- type 5, display 8323
    { id = 192723, key = "throne3", cat = "seating", name = "Throne" },   -- type 5, display 8324
    { id = 192724, key = "throne4", cat = "seating", name = "Throne" },   -- type 5, display 8325
    { id = 2686, key = "apothecarytabl", cat = "tables", name = "Apothecary Table" },   -- type 5, display 234
    { id = 19477, key = "karazahntable", cat = "tables", name = "Karazahn Table" },   -- type 5, display 9477
    { id = 19624, key = "shopcounter", cat = "tables", name = "Shop Counter" },   -- type 5, display 9624
    { id = 174681, key = "jdsworktable", cat = "tables", name = "J.D.'s Work Table" },   -- type 5, display 3371
    { id = 177724, key = "dredanstable", cat = "tables", name = "Dredan's Table" },   -- type 5, display 221
    { id = 181246, key = "icoketable", cat = "tables", name = "iCoke Table" },   -- type 5, display 581
    { id = 182093, key = "bloodelftables", cat = "tables", name = "Blood Elf Table - Small" },   -- type 5, display 6916
    { id = 184657, key = "ironridgetable", cat = "tables", name = "Ironridge Table" },   -- type 5, display 7209
    { id = 187114, key = "alchemytable", cat = "tables", name = "Alchemy Table" },   -- type 5, display 7591
    { id = 189289, key = "table2", cat = "tables", name = "Table" },   -- type 5, display 7838
    { id = 190190, key = "onslaughttable", cat = "tables", name = "Onslaught Table" },   -- type 5, display 7867
    { id = 190665, key = "labtable", cat = "tables", name = "Lab Table" },   -- type 5, display 7977
    { id = 190689, key = "apothecaryta2", cat = "tables", name = "Apothecary Table Round" },   -- type 5, display 7094
    { id = 192547, key = "apprenticesalc", cat = "tables", name = "Apprentice's Alchemy Table" },   -- type 5, display 8109
    { id = 192548, key = "apprenticessur", cat = "tables", name = "Apprentice's Surgical Table" },   -- type 5, display 8074
    { id = 202564, key = "gnometable", cat = "tables", name = "Gnome Table" },   -- type 5, display 9366
    { id = 1670, key = "barrelofpowder", cat = "barrels", name = "Barrel of Powder" },   -- type 5, display 33
    { id = 2130, key = "thewinecask", cat = "barrels", name = "The Wine Cask" },   -- type 5, display 170
    { id = 19897, key = "caskoffoolssto", cat = "barrels", name = "Cask of Fool's Stout" },   -- type 5, display 32
    { id = 181245, key = "icokekeg", cat = "barrels", name = "iCoke Keg" },   -- type 5, display 1727
    { id = 184863, key = "barrela", cat = "barrels", name = "Barrel A" },   -- type 5, display 288
    { id = 186173, key = "brewfestkegbre", cat = "barrels", name = "Brewfest Keg Breakable" },   -- type 5, display 3152
    { id = 186281, key = "intactbarrel", cat = "barrels", name = "Intact Barrel" },   -- type 5, display 6366
    { id = 186709, key = "standingbrewfe", cat = "barrels", name = "Standing Brewfest Keg" },   -- type 5, display 7414
    { id = 186808, key = "brokenkeg", cat = "barrels", name = "Broken Keg" },   -- type 5, display 7525
    { id = 186809, key = "brokenkeg2", cat = "barrels", name = "Broken Keg" },   -- type 5, display 7526
    { id = 200337, key = "forsakenplague", cat = "barrels", name = "Forsaken Plague Barrel" },   -- type 5, display 7470
    { id = 200338, key = "forsakenplag2", cat = "barrels", name = "Forsaken Plague Barrel Empty" },   -- type 5, display 9162
    { id = 201774, key = "quenchingbarre", cat = "barrels", name = "Quenching Barrel" },   -- type 5, display 5112
    { id = 202218, key = "druganskeg", cat = "barrels", name = "Drugan's Keg" },   -- type 5, display 7549
    { id = 26491, key = "pithwicksbagsa", cat = "crates", name = "Pithwick's Bags and Supplies" },   -- type 5, display 637
    { id = 58624, key = "bagvendor", cat = "crates", name = "Bag Vendor" },   -- type 5, display 745
    { id = 92527, key = "bags", cat = "crates", name = "Bags" },   -- type 5, display 954
    { id = 178304, key = "boxosquirrels", cat = "crates", name = "Box o' Squirrels" },   -- type 5, display 528
    { id = 180853, key = "dukesbox", cat = "crates", name = "Duke's Box" },   -- type 5, display 6606
    { id = 181128, key = "frontlinescrat", cat = "crates", name = "Front Lines Crate" },   -- type 5, display 6448
    { id = 181962, key = "dustbag", cat = "crates", name = "Dust Bag" },   -- type 5, display 6895
    { id = 182076, key = "elfcrate", cat = "crates", name = "Elf Crate" },   -- type 5, display 6035
    { id = 183992, key = "amadicrate", cat = "crates", name = "Amadi Crate" },   -- type 5, display 31
    { id = 183993, key = "amadisack", cat = "crates", name = "Amadi Sack" },   -- type 5, display 5511
    { id = 184854, key = "boxa", cat = "crates", name = "Box A" },   -- type 5, display 285
    { id = 184855, key = "boxb", cat = "crates", name = "Box B" },   -- type 5, display 286
    { id = 184856, key = "boxc", cat = "crates", name = "Box C" },   -- type 5, display 1988
    { id = 184857, key = "boxd", cat = "crates", name = "Box D" },   -- type 5, display 5271
    { id = 184858, key = "baga", cat = "crates", name = "Bag A" },   -- type 5, display 323
    { id = 185004, key = "stranglekelpsa", cat = "crates", name = "Stranglekelp Sack" },   -- type 5, display 7224
    { id = 185007, key = "jhangssack", cat = "crates", name = "Jhang's Sack" },   -- type 5, display 2890
    { id = 186307, key = "zulamanexterio", cat = "crates", name = "Zul'Aman Exterior Crate B" },   -- type 5, display 347
    { id = 188076, key = "salvagecrate", cat = "crates", name = "Salvage Crate" },   -- type 5, display 335
    { id = 190094, key = "suspiciousgrai", cat = "crates", name = "Suspicious Grain Crate" },   -- type 5, display 7856
    { id = 190095, key = "plaguedgraincr", cat = "crates", name = "Plagued Grain Crate" },   -- type 5, display 7857
    { id = 190117, key = "cratehighlight", cat = "crates", name = "Crate Highlight" },   -- type 5, display 2233
    { id = 195192, key = "basketofcorn", cat = "crates", name = "Basket of Corn" },   -- type 5, display 8961
    { id = 202891, key = "closedweaponcr", cat = "crates", name = "Closed Weapon Crate" },   -- type 5, display 6959
    { id = 202892, key = "openweaponcrat", cat = "crates", name = "Open Weapon Crate" },   -- type 5, display 8703
    { id = 1558, key = "candleofbeckon", cat = "lights", name = "Candle of Beckoning" },   -- type 5, display 100
    { id = 19466, key = "karazahnchande", cat = "lights", name = "Karazahn Chandelier" },   -- type 5, display 9466
    { id = 19469, key = "karazahnsconce", cat = "lights", name = "Karazahn Sconce" },   -- type 5, display 9469
    { id = 176093, key = "beacontorch", cat = "lights", name = "Beacon Torch" },   -- type 5, display 4095
    { id = 180473, key = "brazier", cat = "lights", name = "Brazier" },   -- type 5, display 475
    { id = 180766, key = "lantern3", cat = "lights", name = "Lantern" },   -- type 5, display 6538
    { id = 180767, key = "lantern4", cat = "lights", name = "Lantern" },   -- type 5, display 6539
    { id = 180768, key = "lantern5", cat = "lights", name = "Lantern" },   -- type 5, display 6540
    { id = 181959, key = "cavetorch", cat = "lights", name = "Cave Torch" },   -- type 5, display 4094
    { id = 182014, key = "darkbrazier", cat = "lights", name = "Dark Brazier" },   -- type 5, display 474
    { id = 184284, key = "ammenvaletorch", cat = "lights", name = "Ammen Vale Torch" },   -- type 5, display 7160
    { id = 184613, key = "doomclawsbrazi", cat = "lights", name = "Doomclaw's Brazier" },   -- type 5, display 7204
    { id = 185003, key = "shadowcouncilt", cat = "lights", name = "Shadow Council Torch" },   -- type 5, display 7255
    { id = 185005, key = "jhangslantern", cat = "lights", name = "Jhang's Lantern" },   -- type 5, display 6038
    { id = 186678, key = "bindersbrazier", cat = "lights", name = "Binder's Brazier" },   -- type 5, display 3411
    { id = 187457, key = "brazierofdanci", cat = "lights", name = "Brazier of Dancing Flames" },   -- type 5, display 7692
    { id = 187708, key = "torchtargetbra", cat = "lights", name = "Torch Target Brazier" },   -- type 5, display 6765
    { id = 187988, key = "twilighttorch", cat = "lights", name = "Twilight Torch" },   -- type 5, display 4771
    { id = 188287, key = "drakurusbrazie", cat = "lights", name = "Drakuru's Brazier" },   -- type 5, display 2570
    { id = 188436, key = "magnataurworsh", cat = "lights", name = "Magnataur Worship Candles" },   -- type 5, display 7773
    { id = 188437, key = "magnataurwor2", cat = "lights", name = "Magnataur Worship Candles" },   -- type 5, display 7774
    { id = 188438, key = "magnataurwor3", cat = "lights", name = "Magnataur Worship Candle" },   -- type 5, display 7772
    { id = 188439, key = "magnataurwor4", cat = "lights", name = "Magnataur Worship Candle" },   -- type 5, display 7775
    { id = 188701, key = "snowplaintorch", cat = "lights", name = "Snowplain Torch" },   -- type 5, display 6370
    { id = 190215, key = "humanbrazierco", cat = "lights", name = "Human Brazier Corrupt" },   -- type 5, display 3971
    { id = 190692, key = "apothecaryskul", cat = "lights", name = "Apothecary Skull Candle" },   -- type 5, display 6406
    { id = 191706, key = "hellfiredwfloo", cat = "lights", name = "Hellfire DW Floor Brazier" },   -- type 5, display 7185
    { id = 194237, key = "drakmarbrazier", cat = "lights", name = "Drak'Mar Brazier" },   -- type 5, display 8563
    { id = 195318, key = "mistcallersbra", cat = "lights", name = "Mistcaller's Brazier" },   -- type 5, display 8303
    { id = 202924, key = "celebrationtor", cat = "lights", name = "Celebration Torch" },   -- type 5, display 9464
    { id = 19665, key = "nightelftreeba", cat = "banners", name = "Night Elf Tree Banner" },   -- type 5, display 9665
    { id = 152080, key = "kadraksflag", cat = "banners", name = "Kadrak's Flag" },   -- type 5, display 2552
    { id = 180432, key = "forsakenbanner", cat = "banners", name = "Forsaken Banner" },   -- type 5, display 6388
    { id = 180776, key = "banner4", cat = "banners", name = "Banner" },   -- type 5, display 6548
    { id = 180777, key = "banner5", cat = "banners", name = "Banner" },   -- type 5, display 6549
    { id = 180778, key = "banner6", cat = "banners", name = "Banner" },   -- type 5, display 6550
    { id = 181058, key = "bannerofprovoc", cat = "banners", name = "Banner of Provocation" },   -- type 5, display 6663
    { id = 181505, key = "bannerofthebla", cat = "banners", name = "Banner of the Blackrock Clan" },   -- type 5, display 6783
    { id = 181506, key = "bannerofthewar", cat = "banners", name = "Banner of the Warsong Clan" },   -- type 5, display 6707
    { id = 181507, key = "bannerofthedra", cat = "banners", name = "Banner of the Dragonmaw Clan" },   -- type 5, display 6784
    { id = 181509, key = "bannerofthefro", cat = "banners", name = "Banner of the Frostwol Clan" },   -- type 5, display 6387
    { id = 181917, key = "draeneibanner", cat = "banners", name = "Draenei Banner" },   -- type 5, display 6882
    { id = 182353, key = "warmaulogreban", cat = "banners", name = "Warmaul Ogre Banner" },   -- type 5, display 6957
    { id = 182354, key = "kilsorrowbanne", cat = "banners", name = "Kil'sorrow Banner" },   -- type 5, display 6958
    { id = 182366, key = "warmaulbannero", cat = "banners", name = "Warmaul Banner of Conquering" },   -- type 5, display 6960
    { id = 184493, key = "netherstormfla", cat = "banners", name = "Netherstorm Flag" },   -- type 5, display 7153
    { id = 185106, key = "bloodelfbanner", cat = "banners", name = "Blood Elf Banner" },   -- type 5, display 6796
    { id = 185107, key = "draeneibanne2", cat = "banners", name = "Draenei Banner" },   -- type 5, display 7268
    { id = 186717, key = "brewfestbanner", cat = "banners", name = "Brewfest Banner" },   -- type 5, display 7508
    { id = 186983, key = "standardofkael", cat = "banners", name = "Standard of Kael'Thas" },   -- type 5, display 6794
    { id = 187083, key = "pirateflag", cat = "banners", name = "Pirate Flag" },   -- type 5, display 7589
    { id = 187123, key = "shatteredsunba", cat = "banners", name = "Shattered Sun Banner" },   -- type 5, display 7617
    { id = 187771, key = "warsongbanner", cat = "banners", name = "Warsong Banner" },   -- type 5, display 5111
    { id = 188020, key = "campbanner", cat = "banners", name = "Camp Banner" },   -- type 5, display 7682
    { id = 190589, key = "flagofownershi", cat = "banners", name = "Flag of Ownership" },   -- type 5, display 7953
    { id = 190670, key = "apothecarybann", cat = "banners", name = "Apothecary Banner" },   -- type 5, display 7979
    { id = 192123, key = "theshadowvault", cat = "banners", name = "The Shadow Vault Banner" },   -- type 5, display 8225
    { id = 194008, key = "voldrunebanner", cat = "banners", name = "Voldrune Banner" },   -- type 5, display 8528
    { id = 194279, key = "gnomereganbann", cat = "banners", name = "Gnomeregan Banner" },   -- type 5, display 8619
    { id = 194281, key = "senjinbanner", cat = "banners", name = "Sen'jin Banner" },   -- type 5, display 8615
    { id = 195319, key = "kvaldirbanner", cat = "banners", name = "Kvaldir Banner" },   -- type 5, display 9009
    { id = 196871, key = "silvercovenant", cat = "banners", name = "Silver Covenant Banner" },   -- type 5, display 9050
    { id = 19637, key = "humanvendorten", cat = "tents", name = "Human Vendor Tent" },   -- type 5, display 9637
    { id = 180030, key = "fortunetellers", cat = "tents", name = "Fortune Teller's Tent" },   -- type 5, display 6138
    { id = 180031, key = "foodtent", cat = "tents", name = "Food Tent" },   -- type 5, display 6139
    { id = 180032, key = "souvenirtent", cat = "tents", name = "Souvenir Tent" },   -- type 5, display 6141
    { id = 180034, key = "ticketmasterte", cat = "tents", name = "Ticket Master Tent" },   -- type 5, display 6142
    { id = 180039, key = "animaltrainert", cat = "tents", name = "Animal Trainer Tent" },   -- type 5, display 6147
    { id = 180042, key = "targetpractice", cat = "tents", name = "Target Practice Tent" },   -- type 5, display 6149
    { id = 181244, key = "icoketent", cat = "tents", name = "iCoke Tent" },   -- type 5, display 6703
    { id = 181301, key = "camppavilion", cat = "tents", name = "Camp Pavilion" },   -- type 5, display 6738
    { id = 183355, key = "shattrathsoupt", cat = "tents", name = "Shattrath Soup Tent" },   -- type 5, display 7170
    { id = 184696, key = "apothecaryzela", cat = "tents", name = "Apothecary Zelana Tent" },   -- type 5, display 7211
    { id = 186680, key = "brewfestcanopy", cat = "tents", name = "Brewfest Canopy" },   -- type 5, display 7498
    { id = 186681, key = "brewfestfoodte", cat = "tents", name = "Brewfest Food Tent" },   -- type 5, display 7499
    { id = 186682, key = "brewfestbeerte", cat = "tents", name = "Brewfest Beer Tent" },   -- type 5, display 7500
    { id = 188021, key = "camppavilion2", cat = "tents", name = "Camp Pavilion" },   -- type 5, display 7683
    { id = 190666, key = "apothecarytent", cat = "tents", name = "Apothecary Tent" },   -- type 5, display 7978
    { id = 193215, key = "orctent", cat = "tents", name = "Orc Tent" },   -- type 5, display 8184
    { id = 193216, key = "orctent2", cat = "tents", name = "Orc Tent" },   -- type 5, display 8397
    { id = 193217, key = "orctent3", cat = "tents", name = "Orc Tent" },   -- type 5, display 8421
    { id = 193218, key = "orctent4", cat = "tents", name = "Orc Tent" },   -- type 5, display 8422
    { id = 193219, key = "orctent5", cat = "tents", name = "Orc Tent" },   -- type 5, display 8423
    { id = 211022, key = "commanderstent", cat = "tents", name = "Commander's Tent" },   -- type 5, display 4176
    { id = 2552, key = "cauldronsteam", cat = "fires", name = "Cauldron Steam" },   -- type 5, display 431
    { id = 19522, key = "cauldron", cat = "fires", name = "Cauldron" },   -- type 5, display 9522
    { id = 19604, key = "undeadcampfire", cat = "fires", name = "Undead Campfire" },   -- type 5, display 9604
    { id = 59850, key = "boucherscauldr", cat = "fires", name = "Boucher's Cauldron" },   -- type 5, display 751
    { id = 173016, key = "borstansfirepi", cat = "fires", name = "Borstan's Firepit" },   -- type 5, display 709
    { id = 180414, key = "cauldron2", cat = "fires", name = "Cauldron" },   -- type 5, display 216
    { id = 181289, key = "midsummerbonfi", cat = "fires", name = "Midsummer Bonfire Large" },   -- type 5, display 680
    { id = 182059, key = "campfire2", cat = "fires", name = "Campfire" },   -- type 5, display 396
    { id = 184717, key = "cauldronsmoke", cat = "fires", name = "Cauldron Smoke" },   -- type 5, display 5071
    { id = 184866, key = "bladesedgebonf", cat = "fires", name = "Blade's Edge Bonfire" },   -- type 5, display 200
    { id = 188073, key = "ahunebonfire", cat = "fires", name = "Ahune Bonfire" },   -- type 5, display 1967
    { id = 188468, key = "zortscauldron", cat = "fires", name = "Zort's Cauldron" },   -- type 5, display 7409
    { id = 190395, key = "cauldronsmok2", cat = "fires", name = "Cauldron Smoke" },   -- type 5, display 4852
    { id = 202926, key = "celebrationbon", cat = "fires", name = "Celebration Bonfire" },   -- type 5, display 6411
    { id = 19028, key = "scarletwatchpo", cat = "fences", name = "Scarlet Watch Post" },   -- type 5, display 22
    { id = 19392, key = "pvpwall", cat = "fences", name = "PvP Wall" },   -- type 5, display 9392
    { id = 19395, key = "spikewall", cat = "fences", name = "Spike Wall" },   -- type 5, display 9395
    { id = 19435, key = "gate", cat = "fences", name = "Gate" },   -- type 5, display 9435
    { id = 19436, key = "cementerygate", cat = "fences", name = "Cementery Gate" },   -- type 5, display 9436
    { id = 19439, key = "gatesegment", cat = "fences", name = "Gate Segment" },   -- type 5, display 9439
    { id = 19444, key = "rockwall", cat = "fences", name = "Rock Wall" },   -- type 5, display 9444
    { id = 19454, key = "fence2", cat = "fences", name = "Fence" },   -- type 5, display 9454
    { id = 19626, key = "humansignpost", cat = "fences", name = "Human Sign Post" },   -- type 5, display 9626
    { id = 19638, key = "greatwallportc", cat = "fences", name = "Great Wall Portcullis" },   -- type 5, display 9638
    { id = 19640, key = "crimsonwallshi", cat = "fences", name = "Crimson Wall Shield" },   -- type 5, display 9640
    { id = 19658, key = "wallshield", cat = "fences", name = "Wall Shield" },   -- type 5, display 9658
    { id = 19659, key = "wallsword", cat = "fences", name = "Wall Sword" },   -- type 5, display 9659
    { id = 19840, key = "freewindpost", cat = "fences", name = "Freewind Post" },   -- type 5, display 308
    { id = 19863, key = "maestraspost", cat = "fences", name = "Maestra's Post" },   -- type 5, display 386
    { id = 175444, key = "maingate", cat = "fences", name = "Main Gate" },   -- type 5, display 26
    { id = 177905, key = "mercutiopost", cat = "fences", name = "Mercutio Post" },   -- type 5, display 1287
    { id = 179694, key = "deathpost", cat = "fences", name = "Death Post" },   -- type 5, display 5834
    { id = 180007, key = "excavationstak", cat = "fences", name = "Excavation Stake" },   -- type 5, display 2270
    { id = 180322, key = "ghostgate", cat = "fences", name = "Ghost Gate" },   -- type 5, display 6391
    { id = 182186, key = "sungate", cat = "fences", name = "Sun Gate" },   -- type 5, display 6927
    { id = 182314, key = "swampratpost", cat = "fences", name = "Swamprat Post" },   -- type 5, display 6953
    { id = 182341, key = "magistersgate", cat = "fences", name = "Magister's Gate" },   -- type 5, display 6954
    { id = 183200, key = "sunspringpost", cat = "fences", name = "Sunspring Post" },   -- type 5, display 7029
    { id = 185318, key = "warpgatesmoke", cat = "fences", name = "Warp-Gate Smoke" },   -- type 5, display 45
    { id = 187912, key = "gate2", cat = "fences", name = "Gate" },   -- type 5, display 3614
    { id = 190664, key = "walllight", cat = "fences", name = "Wall Light" },   -- type 5, display 7976
    { id = 192044, key = "steelgate", cat = "fences", name = "Steel Gate" },   -- type 5, display 7468
    { id = 193007, key = "metalpost", cat = "fences", name = "Metal Post" },   -- type 5, display 8380
    { id = 193612, key = "barricade", cat = "fences", name = "Barricade" },   -- type 5, display 8477
    { id = 193613, key = "barricade2", cat = "fences", name = "Barricade" },   -- type 5, display 8478
    { id = 193614, key = "barricade3", cat = "fences", name = "Barricade" },   -- type 5, display 8479
    { id = 202835, key = "senjinbatroost", cat = "fences", name = "Sen'jin Bat Roost Fence" },   -- type 5, display 9423
    { id = 202839, key = "senjinbatroo2", cat = "fences", name = "Sen'jin Bat Roost Fence Post" },   -- type 5, display 8721
    { id = 211064, key = "rockwallfence", cat = "fences", name = "Rockwall Fence" },   -- type 5, display 134
    { id = 2109, key = "fragrantflower", cat = "nature", name = "Fragrant Flowers" },   -- type 5, display 169
    { id = 2711, key = "chargingstone", cat = "nature", name = "Charging Stone" },   -- type 5, display 236
    { id = 19413, key = "rockbridge", cat = "nature", name = "Rock Bridge" },   -- type 5, display 9413
    { id = 19416, key = "rockarch", cat = "nature", name = "Rock Arch" },   -- type 5, display 9416
    { id = 19429, key = "haystack", cat = "nature", name = "Hay Stack" },   -- type 5, display 9429
    { id = 19430, key = "haywagon", cat = "nature", name = "Hay Wagon" },   -- type 5, display 9430
    { id = 19445, key = "warningtree", cat = "nature", name = "Warning Tree" },   -- type 5, display 9445
    { id = 19458, key = "rockmonument", cat = "nature", name = "Rock Monument" },   -- type 5, display 9458
    { id = 19461, key = "stonepyre", cat = "nature", name = "Stone Pyre" },   -- type 5, display 9461
    { id = 19494, key = "emeralddreamfo", cat = "nature", name = "Emerald Dream Fountain Tree" },   -- type 5, display 9494
    { id = 19532, key = "meetingstone", cat = "nature", name = "Meeting Stone" },   -- type 5, display 9532
    { id = 19537, key = "gemrock", cat = "nature", name = "Gem Rock" },   -- type 5, display 9537
    { id = 19583, key = "sunrockretreat", cat = "nature", name = "Sun Rock Retreat" },   -- type 5, display 309
    { id = 20939, key = "bogbeanplant", cat = "nature", name = "Bogbean Plant" },   -- type 5, display 148
    { id = 175471, key = "thestonecrowta", cat = "nature", name = "The Stone Crow Tavern" },   -- type 5, display 3671
    { id = 177140, key = "frostsaberrock", cat = "nature", name = "Frostsaber Rock" },   -- type 5, display 388
    { id = 177684, key = "stoneofshyrota", cat = "nature", name = "Stone of Shy-Rotam" },   -- type 5, display 362
    { id = 178425, key = "christmastreel", cat = "nature", name = "Christmas Tree (Large)" },   -- type 5, display 5253
    { id = 178557, key = "christmastreem", cat = "nature", name = "Christmas Tree (Medium)" },   -- type 5, display 5315
    { id = 178558, key = "christmastre2", cat = "nature", name = "Christmas Tree (Large Snowy)" },   -- type 5, display 5316
    { id = 178647, key = "christmastree", cat = "nature", name = "Christmas Tree" },   -- type 5, display 5371
    { id = 178904, key = "healedcelebria", cat = "nature", name = "Healed Celebrian Vine" },   -- type 5, display 2991
    { id = 181063, key = "flowersfortony", cat = "nature", name = "Flowers for Tony" },   -- type 5, display 6646
    { id = 181064, key = "flowersforto2", cat = "nature", name = "Flowers for Tony" },   -- type 5, display 6647
    { id = 181065, key = "flowersforto3", cat = "nature", name = "Flowers for Tony" },   -- type 5, display 63
    { id = 181066, key = "flowersforto4", cat = "nature", name = "Flowers for Tony" },   -- type 5, display 6648
    { id = 181067, key = "flowersforto5", cat = "nature", name = "Flowers for Tony" },   -- type 5, display 6313
    { id = 181087, key = "plant", cat = "nature", name = "Plant" },   -- type 5, display 6642
    { id = 181103, key = "flower", cat = "nature", name = "Flower" },   -- type 5, display 6662
    { id = 181361, key = "nightelfmooncr", cat = "nature", name = "Night Elf Moon Crystal" },   -- type 5, display 6749
    { id = 181824, key = "concealingbush", cat = "nature", name = "Concealing Bush" },   -- type 5, display 6857
    { id = 182036, key = "naaruroomcryst", cat = "nature", name = "Naaru Room Crystal" },   -- type 5, display 6905
    { id = 182079, key = "nightelfstoner", cat = "nature", name = "Nightelf Stone Rune" },   -- type 5, display 6914
    { id = 182080, key = "nightelfston2", cat = "nature", name = "Nightelf Stone Rune" },   -- type 5, display 247
    { id = 182251, key = "thecrystalhall", cat = "nature", name = "The Crystal Hall" },   -- type 5, display 6824
    { id = 183492, key = "redridinghoodt", cat = "nature", name = "Red Riding Hood Tree" },   -- type 5, display 7062
    { id = 183496, key = "wizardofozhay", cat = "nature", name = "Wizard of Oz Hay" },   -- type 5, display 7065
    { id = 184306, key = "darkcrystal", cat = "nature", name = "Dark Crystal" },   -- type 5, display 5811
    { id = 184731, key = "demoniccrystal", cat = "nature", name = "Demonic Crystal" },   -- type 5, display 6706
    { id = 185294, key = "mountedboulder", cat = "nature", name = "Mounted Boulder'mok Head" },   -- type 5, display 3081
    { id = 185542, key = "invisravenston", cat = "nature", name = "Invis Raven Stone" },   -- type 5, display 2770
    { id = 185901, key = "ogrilacrystals", cat = "nature", name = "Ogri'la Crystal Smoke Image" },   -- type 5, display 7380
    { id = 187591, key = "thestonecrow2", cat = "nature", name = "The Stone Crow Tavern" },   -- type 5, display 538
    { id = 188048, key = "twilightcrysta", cat = "nature", name = "Twilight Crystal Base" },   -- type 5, display 7684
    { id = 188050, key = "twilightcrys2", cat = "nature", name = "Twilight Crystal Base" },   -- type 5, display 7685
    { id = 2148, key = "thecheesecutte", cat = "decor", name = "The Cheese Cutters" },   -- type 5, display 178
    { id = 2371, key = "headhunterskul", cat = "decor", name = "Headhunter Skull" },   -- type 5, display 226
    { id = 2562, key = "bakedbread", cat = "decor", name = "Baked Bread" },   -- type 5, display 229
    { id = 2687, key = "bottle", cat = "decor", name = "Bottle" },   -- type 5, display 225
    { id = 2695, key = "book", cat = "decor", name = "Book" },   -- type 5, display 107
    { id = 13948, key = "fancybed", cat = "decor", name = "Fancy Bed" },   -- type 7, display 392
    { id = 19397, key = "goblinstatue", cat = "decor", name = "Goblin Statue" },   -- type 5, display 9397
    { id = 19404, key = "burntgiantwhee", cat = "decor", name = "Burnt Giant Wheel" },   -- type 5, display 9404
    { id = 19410, key = "lotharstatue", cat = "decor", name = "Lothar Statue" },   -- type 5, display 9410
    { id = 19412, key = "goblinmeltingp", cat = "decor", name = "Goblin Melting Pot" },   -- type 5, display 9412
    { id = 19419, key = "wagon", cat = "decor", name = "Wagon" },   -- type 5, display 9419
    { id = 19459, key = "ruinedfountain", cat = "decor", name = "Ruined Fountain" },   -- type 5, display 9459
    { id = 19460, key = "lionstatue", cat = "decor", name = "Lion Statue" },   -- type 5, display 9460
    { id = 19483, key = "holyspringwell", cat = "decor", name = "Holy Spring Well" },   -- type 5, display 9483
    { id = 19485, key = "snakestatue", cat = "decor", name = "Snake Statue" },   -- type 5, display 9485
    { id = 19504, key = "bed", cat = "decor", name = "Bed" },   -- type 5, display 9504
    { id = 19506, key = "mountainkingst", cat = "decor", name = "Mountain King Statue" },   -- type 5, display 9506
    { id = 19507, key = "fountain", cat = "decor", name = "Fountain" },   -- type 5, display 9507
    { id = 19508, key = "frangerstatue", cat = "decor", name = "Franger Statue" },   -- type 5, display 9508
    { id = 19509, key = "magestatue", cat = "decor", name = "Mage Statue" },   -- type 5, display 9509
    { id = 19510, key = "spearmanstatue", cat = "decor", name = "Spearman Statue" },   -- type 5, display 9510
    { id = 19511, key = "sunshieldstatu", cat = "decor", name = "Sunshield Statue" },   -- type 5, display 9511
    { id = 19513, key = "twinbladesstat", cat = "decor", name = "Twinblades Statue" },   -- type 5, display 9513
    { id = 19514, key = "captainstatue", cat = "decor", name = "Captain Statue" },   -- type 5, display 9514
    { id = 19516, key = "crusaderstatue", cat = "decor", name = "Crusader Statue" },   -- type 5, display 9516
    { id = 19519, key = "humanstatue", cat = "decor", name = "Human Statue" },   -- type 5, display 9519
    { id = 19520, key = "paladinstatue", cat = "decor", name = "Paladin Statue" },   -- type 5, display 9520
    { id = 19521, key = "prieststatue", cat = "decor", name = "Priest Statue" },   -- type 5, display 9521
    { id = 19607, key = "plaguedfountai", cat = "decor", name = "Plagued Fountain" },   -- type 5, display 9607
    { id = 19608, key = "snowfountain", cat = "decor", name = "Snow Fountain" },   -- type 5, display 9608
    { id = 19609, key = "humanfountain", cat = "decor", name = "Human Fountain" },   -- type 5, display 9609
    { id = 19610, key = "undeadfountain", cat = "decor", name = "Undead Fountain" },   -- type 5, display 9610
    { id = 19619, key = "gypsywagon", cat = "decor", name = "Gypsy Wagon" },   -- type 5, display 9619
    { id = 19627, key = "alleriastatue", cat = "decor", name = "Alleria Statue" },   -- type 5, display 9627
    { id = 19628, key = "danathstatue", cat = "decor", name = "Danath Statue" },   -- type 5, display 9628
    { id = 19629, key = "khadgarstatue", cat = "decor", name = "Khadgar Statue" },   -- type 5, display 9629
    { id = 19630, key = "kurdranstatue", cat = "decor", name = "Kurdran Statue" },   -- type 5, display 9630
    { id = 19631, key = "lionstatue2", cat = "decor", name = "Lion Statue" },   -- type 5, display 9631
    { id = 19632, key = "turalyonstatue", cat = "decor", name = "Turalyon Statue" },   -- type 5, display 9632
    { id = 19633, key = "utherstatue", cat = "decor", name = "Uther Statue" },   -- type 5, display 9633
    { id = 19635, key = "rack", cat = "decor", name = "Rack" },   -- type 5, display 9635
    { id = 20724, key = "dordanilpillar", cat = "decor", name = "Dor'Danil Pillar" },   -- type 5, display 249
    { id = 20818, key = "nightelfmoonwe", cat = "decor", name = "Night Elf Moon Well" },   -- type 5, display 4691
    { id = 26480, key = "craghelmsplate", cat = "decor", name = "Craghelm's Plate and Chain" },   -- type 5, display 635
    { id = 32372, key = "thegreatforge", cat = "decor", name = "The Great Forge" },   -- type 5, display 660
}
local CATEGORIES = { "seating", "tables", "barrels", "crates", "lights", "banners", "tents", "fires", "fences", "nature", "decor" }

-- Build points: how heavy a prop is for the realm and for everyone's frame rate. Lights and fires carry
-- effects, tents and statues are big models; a few huge ones cost more.
local CAT_COST = { seating = 1, tables = 1, barrels = 1, crates = 1, banners = 1, lights = 2, fires = 2,
    fences = 2, nature = 2, tents = 3, decor = 3 }
local BIG_COST = { [32372] = 6, [175471] = 6, [187591] = 6, [182251] = 6, [19413] = 4, [19416] = 4,
    [19494] = 4, [181289] = 4, [19583] = 4 }

-- Trust tiers: a share of the per-player limits. New characters (under OV_BUILD_NEW_HOURS played) start on
-- "new"; everyone else on "builder"; a GM sets any tier with .build trust <name> <tier>.
local TIERS = {
    { key = "new",     mult = 0.4 },
    { key = "builder", mult = 1 },
    { key = "trusted", mult = 3 },
    { key = "master",  mult = 8 },
}

local K = {
    NEAR_RANGE = 40,         -- .build near, .build selall
    SYNC_RANGE = 150,        -- props put back around a player; also how far a selection may be
    SYNC_EVERY_MS = 15000,
    MAX_STEP = 10,           -- yards per .build move
    MAX_TURN = 180,
    UNDO_DEPTH = 30,
    LOAD_COOLDOWN = 5,
    MOVES_PER_SECOND = 5,
    BUILD_NAME_MAX = 24,
    CODE_LEN = 6,
    CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789",   -- no 0/O, 1/I
    EXACT_RANGE = 100,       -- yards from the builder an exact point (a click) may be
    GROUP_MAX = 40,          -- props in one selection
    PREFAB_MAX = 60,         -- props in one prefab
    PREFAB_SPAN = 40,        -- yards a prefab's prop may lie from its centre
    PLOT_HEIGHT = 40,        -- a plot reaches this far up and down
    PLOT_MEMBERS = 20,
    OPLOG_KEEP = 3000,       -- ops kept in memory for rollback
}
local SCALE_MIN, SCALE_MAX = 0.5, 2.5

------------------------------------------------------------------------------------------------
-- env and helpers
------------------------------------------------------------------------------------------------
local function flag(name, default)
    local v = os.getenv(name)
    if v == "1" then return true end
    if v == "0" then return false end
    return default
end

local function num(name, default, lo, hi)
    local v = tonumber(os.getenv(name) or "") or default
    v = math.floor(v)
    if v < lo then v = lo end
    if v > hi then v = hi end
    return v
end

local function onSwitch()   return flag("OV_BUILD", true) end
local function anywhere()   return flag("OV_BUILD_ANYWHERE", false) end
local function perPlayer()  return num("OV_BUILD_PER_PLAYER", 50, 0, 1000) end
local function perArea()    return num("OV_BUILD_PER_AREA", 500, 0, 10000) end
local function perPoints()  return num("OV_BUILD_POINTS", 100, 0, 100000) end
local function plotSize()   return num("OV_BUILD_PLOT_SIZE", 12, 4, 40) end
local function plotProps()  return num("OV_BUILD_PLOT_PROPS", 150, 0, 10000) end
local function plotPoints() return num("OV_BUILD_PLOT_POINTS", 300, 0, 100000) end
local function plotsEach()  return num("OV_BUILD_PLOTS_EACH", 1, 0, 10) end
local function plotsOnly()  return flag("OV_BUILD_PLOTS_ONLY", false) end
local function newHours()   return num("OV_BUILD_NEW_HOURS", 2, 0, 1000) end

local function say(player, text) player:SendBroadcastMessage(TAG .. text) end

local function try(obj, method, ...)
    if not obj then return nil end
    local ok, fn = pcall(function() return obj[method] end)
    if not ok or type(fn) ~= "function" then return nil end
    local ok2, a, b = pcall(fn, obj, ...)
    if ok2 then return a, b end
    return nil
end

local function has(obj, method)
    if not obj then return false end
    local ok, fn = pcall(function() return obj[method] end)
    return ok and type(fn) == "function"
end

local function isGM(player) return (tonumber(try(player, "GetGMRank")) or 0) > 0 end

local function inInstance(player)
    if try(player, "InBattleground") or try(player, "InArena") then return true end
    local map = try(player, "GetMap")
    return map ~= nil and (try(map, "IsBattlegroundOrArena") or try(map, "IsDungeon") or try(map, "IsRaid")) == true
end

local function plural(n, word) return n .. " " .. word .. (n == 1 and "" or "s") end
local function dist2(ax, ay, bx, by) local dx, dy = ax - bx, ay - by; return math.sqrt(dx * dx + dy * dy) end
local function finite(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end

local function normO(o)
    local tau = 2 * math.pi
    o = o % tau
    if o < 0 then o = o + tau end
    return o
end

local function clampScale(s)
    s = tonumber(s) or 1
    if not finite(s) then return 1 end
    if s < SCALE_MIN then s = SCALE_MIN end
    if s > SCALE_MAX then s = SCALE_MAX end
    return math.floor(s * 100 + 0.5) / 100
end

-- Character names and build names only ever reach SQL through these (letters, digits, _ and -).
local function cleanName(s) return (tostring(s or ""):gsub("[^%w]", ""):sub(1, 12)) end
local function cleanBuild(s)
    s = tostring(s or ""):lower()
    if #s < 1 or #s > K.BUILD_NAME_MAX or not s:match("^[%w_%-]+$") then return nil end
    return s
end
local function isCode(s) return type(s) == "string" and #s == K.CODE_LEN and s:upper():match("^[A-HJ-NP-Z2-9]+$") ~= nil end

local function query(sql)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, sql)
    if ok then return q end
    return nil
end
local function exec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end

------------------------------------------------------------------------------------------------
-- tables (characters database). The plan calls the plot and op-log tables sandbox_plots and sandbox_oplog;
-- the mod rules (mods/SPEC.md) keep a script to its own mod_<id>_ tables, so here they are
-- mod_builder_plots (+ _plot_members) and mod_builder_oplog.
------------------------------------------------------------------------------------------------
exec("CREATE TABLE IF NOT EXISTS mod_builder_roles ("
    .. "guid INT UNSIGNED NOT NULL PRIMARY KEY, name VARCHAR(12) NOT NULL, "
    .. "granted_by VARCHAR(12) NOT NULL DEFAULT '', granted_at INT UNSIGNED NOT NULL DEFAULT 0, KEY name (name))")
exec("CREATE TABLE IF NOT EXISTS mod_builder_props ("
    .. "id INT UNSIGNED NOT NULL PRIMARY KEY, owner INT UNSIGNED NOT NULL, owner_name VARCHAR(12) NOT NULL, "
    .. "area VARCHAR(24) NOT NULL, entry INT UNSIGNED NOT NULL, map SMALLINT UNSIGNED NOT NULL, "
    .. "x FLOAT NOT NULL, y FLOAT NOT NULL, z FLOAT NOT NULL, o FLOAT NOT NULL, "
    .. "created_at INT UNSIGNED NOT NULL DEFAULT 0, KEY owner (owner), KEY area (area))")
exec("CREATE TABLE IF NOT EXISTS mod_builder_builds ("
    .. "id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, owner INT UNSIGNED NOT NULL, "
    .. "owner_name VARCHAR(12) NOT NULL, name VARCHAR(24) NOT NULL, code CHAR(6) NULL, props TEXT NOT NULL, "
    .. "created_at INT UNSIGNED NOT NULL DEFAULT 0, UNIQUE KEY owner_name_key (owner, name), UNIQUE KEY code (code))")
exec("CREATE TABLE IF NOT EXISTS mod_builder_prop_scale ("
    .. "id INT UNSIGNED NOT NULL PRIMARY KEY, scale FLOAT NOT NULL DEFAULT 1)")
exec("CREATE TABLE IF NOT EXISTS mod_builder_trust ("
    .. "guid INT UNSIGNED NOT NULL PRIMARY KEY, name VARCHAR(12) NOT NULL, tier TINYINT UNSIGNED NOT NULL, "
    .. "set_by VARCHAR(12) NOT NULL DEFAULT '', set_at INT UNSIGNED NOT NULL DEFAULT 0)")
exec("CREATE TABLE IF NOT EXISTS mod_builder_plots ("
    .. "id INT UNSIGNED NOT NULL PRIMARY KEY, owner INT UNSIGNED NOT NULL, owner_name VARCHAR(12) NOT NULL, "
    .. "area VARCHAR(24) NOT NULL, map SMALLINT UNSIGNED NOT NULL, x FLOAT NOT NULL, y FLOAT NOT NULL, "
    .. "z FLOAT NOT NULL, r FLOAT NOT NULL, created_at INT UNSIGNED NOT NULL DEFAULT 0, KEY owner (owner))")
exec("CREATE TABLE IF NOT EXISTS mod_builder_plot_members ("
    .. "plot INT UNSIGNED NOT NULL, guid INT UNSIGNED NOT NULL, name VARCHAR(12) NOT NULL, "
    .. "role VARCHAR(8) NOT NULL, PRIMARY KEY (plot, guid))")
exec("CREATE TABLE IF NOT EXISTS mod_builder_prefabs ("
    .. "id INT UNSIGNED NOT NULL PRIMARY KEY, owner INT UNSIGNED NOT NULL, owner_name VARCHAR(12) NOT NULL, "
    .. "name VARCHAR(24) NOT NULL, code CHAR(6) NULL, data TEXT NOT NULL, created_at INT UNSIGNED NOT NULL DEFAULT 0, "
    .. "UNIQUE KEY owner_name_key (owner, name), UNIQUE KEY code (code))")
exec("CREATE TABLE IF NOT EXISTS mod_builder_oplog ("
    .. "id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, op_id INT UNSIGNED NOT NULL, "
    .. "guid INT UNSIGNED NOT NULL, name VARCHAR(12) NOT NULL, op VARCHAR(12) NOT NULL, prop INT UNSIGNED NOT NULL, "
    .. "before_state VARCHAR(120) NOT NULL DEFAULT '', after_state VARCHAR(120) NOT NULL DEFAULT '', "
    .. "at INT UNSIGNED NOT NULL DEFAULT 0, undone TINYINT UNSIGNED NOT NULL DEFAULT 0, "
    .. "KEY guid (guid), KEY op_id (op_id), KEY at (at))")

------------------------------------------------------------------------------------------------
-- catalog lookups
------------------------------------------------------------------------------------------------
local byId, byKey = {}, {}
local function index()
    for k in pairs(byId) do byId[k] = nil end
    for k in pairs(byKey) do byKey[k] = nil end
    for _, c in ipairs(CATALOG) do
        c.cost = BIG_COST[c.id] or CAT_COST[c.cat] or 1
        byId[c.id] = c; byKey[c.key] = c
    end
end

-- Drops entries this realm's world database doesn't have (a custom or older world).
local function verify()
    if not WorldDBQuery then index(); return end
    local ids = {}
    for _, c in ipairs(CATALOG) do ids[#ids + 1] = tostring(c.id) end
    local ok, q = pcall(WorldDBQuery, "SELECT entry FROM gameobject_template WHERE entry IN (" .. table.concat(ids, ",") .. ")")
    if ok and q then
        local have = {}
        repeat have[q:GetUInt32(0)] = true until not q:NextRow()
        local kept = {}
        for _, c in ipairs(CATALOG) do
            if have[c.id] then kept[#kept + 1] = c else print("[ov_build] catalog entry " .. c.id .. " not in this world database; dropped") end
        end
        CATALOG = kept
    end
    index()
end
verify()

local function costOf(entry) local c = byId[entry]; return (c and c.cost) or 1 end

local function findProp(word)
    if not word or word == "" then return nil end
    local n = tonumber(word)
    if n then return byId[n] end
    word = word:lower()
    if byKey[word] then return byKey[word] end
    local hit, count = nil, 0
    for _, c in ipairs(CATALOG) do
        if c.name:lower():find(word, 1, true) then hit = hit or c; count = count + 1 end
    end
    if count == 1 then return hit end
    return nil, count
end

------------------------------------------------------------------------------------------------
-- state
------------------------------------------------------------------------------------------------
local roles = {}       -- [guid] = { name, lname }
local trust = {}       -- [guid] = tier index set by a GM
local props = {}       -- [id] = { id, owner, ownerName, area, entry, map, x, y, z, o, s }
local live = {}        -- [id] = object guid of the spawned prop
local selected = {}    -- [guid] = prop id: the selection, or the last one picked in a group
local group = {}       -- [guid] = { prop ids } when more than one prop is selected
local clip = {}        -- [guid] = { rel = relative props } from .build copy
local nearList = {}    -- [guid] = { ids from the last .build near }
local undo = {}        -- [guid] = { actions }
local lastSpawn, lastLoad, moves = {}, {}, {}
local builds = {}      -- cache: [owner] = { [name] = { props = text, code = code } }
local byCode = {}      -- cache: [code] = { owner, name, props }
local lastCode = {}    -- [guid] = the code .build share printed last (for the window)
local plots = {}       -- [id] = { id, owner, ownerName, area, map, x, y, z, r, members = { [guid] = { name, role } } }
local prefabs = {}     -- [id] = { id, owner, ownerName, name, code, data (JSON text), n }
local oplog = {}       -- ops, oldest first: { id, guid, name, op, at, rows = { { id, before, after } } }
local nextId, nextPlot, nextPrefab, opSeq = 0, 0, 0, 0
local curOp            -- the op the running command records into

------------------------------------------------------------------------------------------------
-- a prop's state as text, for the op log: entry,map,x,y,z,o,scale,owner,ownerName,area
------------------------------------------------------------------------------------------------
local function copyProp(p)
    return { id = p.id, owner = p.owner, ownerName = p.ownerName, area = p.area, entry = p.entry, map = p.map,
        x = p.x, y = p.y, z = p.z, o = p.o, s = p.s }
end

local function stateStr(c)
    if not c then return "" end
    return string.format("%d,%d,%.3f,%.3f,%.3f,%.4f,%.2f,%d,%s,%s", c.entry, c.map, c.x, c.y, c.z, c.o, c.s or 1,
        c.owner, cleanName(c.ownerName), tostring(c.area):gsub("[^%w]", ""))
end

local function parseStateStr(id, s)
    local e, m, x, y, z, o, sc, ow, on, a = tostring(s or ""):match(
        "^(%d+),(%d+),(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+),([%d%.]+),(%d+),(%w*),(%w+)$")
    if not e then return nil end
    return { id = id, entry = tonumber(e), map = tonumber(m), x = tonumber(x), y = tonumber(y), z = tonumber(z),
        o = tonumber(o), s = tonumber(sc) ~= 1 and tonumber(sc) or nil, owner = tonumber(ow), ownerName = on, area = a }
end

local function loadState()
    local q = query("SELECT guid, name FROM mod_builder_roles")
    if q then repeat roles[q:GetUInt32(0)] = { name = q:GetString(1), lname = q:GetString(1):lower() } until not q:NextRow() end
    q = query("SELECT guid, tier FROM mod_builder_trust")
    if q then repeat local t = q:GetUInt32(1); if TIERS[t] then trust[q:GetUInt32(0)] = t end until not q:NextRow() end
    q = query("SELECT id, owner, owner_name, area, entry, map, x, y, z, o FROM mod_builder_props")
    if q then
        repeat
            local id = q:GetUInt32(0)
            props[id] = { id = id, owner = q:GetUInt32(1), ownerName = q:GetString(2), area = q:GetString(3),
                entry = q:GetUInt32(4), map = q:GetUInt32(5), x = q:GetFloat(6), y = q:GetFloat(7), z = q:GetFloat(8),
                o = q:GetFloat(9) }
            if id > nextId then nextId = id end
        until not q:NextRow()
    end
    q = query("SELECT id, scale FROM mod_builder_prop_scale")
    if q then repeat local p = props[q:GetUInt32(0)]; if p then p.s = clampScale(q:GetFloat(1)); if p.s == 1 then p.s = nil end end until not q:NextRow() end
    q = query("SELECT id, owner, owner_name, area, map, x, y, z, r FROM mod_builder_plots")
    if q then
        repeat
            local id = q:GetUInt32(0)
            plots[id] = { id = id, owner = q:GetUInt32(1), ownerName = q:GetString(2), area = q:GetString(3),
                map = q:GetUInt32(4), x = q:GetFloat(5), y = q:GetFloat(6), z = q:GetFloat(7), r = q:GetFloat(8), members = {} }
            if id > nextPlot then nextPlot = id end
        until not q:NextRow()
    end
    q = query("SELECT plot, guid, name, role FROM mod_builder_plot_members")
    if q then
        repeat
            local pl = plots[q:GetUInt32(0)]
            if pl then pl.members[q:GetUInt32(1)] = { name = q:GetString(2), role = q:GetString(3) } end
        until not q:NextRow()
    end
    q = query("SELECT id, owner, owner_name, name, code, data FROM mod_builder_prefabs")
    if q then
        repeat
            local id = q:GetUInt32(0)
            local code = q:GetString(4)
            prefabs[id] = { id = id, owner = q:GetUInt32(1), ownerName = q:GetString(2), name = q:GetString(3),
                code = code ~= "" and code or nil, data = q:GetString(5) }
            if id > nextPrefab then nextPrefab = id end
        until not q:NextRow()
    end
    q = query("SELECT MAX(op_id) FROM mod_builder_oplog")
    if q then opSeq = tonumber(q:GetUInt32(0)) or 0 end
    -- The last week's ops (not rolled back), so a GM rollback still works after a restart.
    q = query(string.format("SELECT op_id, guid, name, op, prop, before_state, after_state, at FROM mod_builder_oplog "
        .. "WHERE undone = 0 AND at > %d ORDER BY id DESC LIMIT %d", os.time() - 7 * 86400, K.OPLOG_KEEP))
    if q then
        local ops, order = {}, {}
        repeat
            local oid = q:GetUInt32(0)
            local op = ops[oid]
            if not op then
                op = { id = oid, guid = q:GetUInt32(1), name = q:GetString(2), op = q:GetString(3), at = q:GetUInt32(7), rows = {} }
                ops[oid] = op; order[#order + 1] = op
            end
            local pid = q:GetUInt32(4)
            table.insert(op.rows, 1, { id = pid, before = parseStateStr(pid, q:GetString(5)), after = parseStateStr(pid, q:GetString(6)) })
        until not q:NextRow()
        for i = #order, 1, -1 do oplog[#oplog + 1] = order[i] end
    end
end
loadState()

local function isBuilder(player)
    return isGM(player) or roles[player:GetGUIDLow()] ~= nil
end

------------------------------------------------------------------------------------------------
-- areas and plots
------------------------------------------------------------------------------------------------
-- The build area key a point is in: "1", "2"... for BUILD_AREAS, "m<map>" anywhere (GMs with OV_BUILD_ANYWHERE).
local function areaAt(map, x, y, z)
    for i, a in ipairs(BUILD_AREAS) do
        if a.map == map and dist2(x, y, a.x, a.y) <= a.r and math.abs(z - a.z) <= a.r then return tostring(i), a end
    end
    return nil
end

local function areaName(key)
    local a = BUILD_AREAS[tonumber(key or "") or 0]
    if a then return a.name end
    if key and key:match("^m%d+$") then return "open world (map " .. key:sub(2) .. ")" end
    return "-"
end

-- Where the player may build now: the area key, or nil and a reason.
local function buildArea(player)
    local map, x, y, z = player:GetMapId(), player:GetX(), player:GetY(), player:GetZ()
    local key = areaAt(map, x, y, z)
    if key then return key end
    if isGM(player) and anywhere() then
        if inInstance(player) then return nil, "Not inside dungeons, raids or battlegrounds." end
        return "m" .. map
    end
    return nil, "You can build only in a build area (|cffffff00.build where|r)."
end

-- A point a prop may move to: inside the same area it belongs to.
local function insideArea(key, map, x, y, z)
    if key:match("^m%d+$") then return map == tonumber(key:sub(2)) end
    local a = BUILD_AREAS[tonumber(key)]
    return a ~= nil and a.map == map and dist2(x, y, a.x, a.y) <= a.r and math.abs(z - a.z) <= a.r
end

-- A plot is a circle on the ground (r yards) reaching K.PLOT_HEIGHT up and down.
local function plotAt(map, x, y, z)
    for _, pl in pairs(plots) do
        if pl.map == map and dist2(x, y, pl.x, pl.y) <= pl.r and math.abs(z - pl.z) <= K.PLOT_HEIGHT then return pl end
    end
    return nil
end

local function roleIn(pl, guid)
    if not pl then return nil end
    if pl.owner == guid then return "owner" end
    local m = pl.members[guid]
    return m and m.role or nil
end

local function plotUsage(pl)
    local n, pts = 0, 0
    for _, p in pairs(props) do
        if p.map == pl.map and dist2(p.x, p.y, pl.x, pl.y) <= pl.r and math.abs(p.z - pl.z) <= K.PLOT_HEIGHT then
            n = n + 1; pts = pts + costOf(p.entry)
        end
    end
    return n, pts
end

-- May the player put a prop at this point? (GMs always; in a plot its owner and builders; outside plots
-- everyone with the role, unless OV_BUILD_PLOTS_ONLY=1.)
local function canBuildAt(player, map, x, y, z)
    if isGM(player) then return true end
    local pl = plotAt(map, x, y, z)
    if pl then
        local r = roleIn(pl, player:GetGUIDLow())
        if r == "owner" or r == "builder" then return true end
        if r == "visitor" then return false, "You're a visitor on " .. pl.ownerName .. "'s plot: you can look and copy, not build." end
        return false, "That's " .. pl.ownerName .. "'s plot."
    end
    if plotsOnly() then return false, "Claim a plot first (|cffffff00.build plot claim|r)." end
    return true
end

-- May the player change this prop?
local function canEdit(player, p)
    if isGM(player) then return true end
    local guid = player:GetGUIDLow()
    local pl = plotAt(p.map, p.x, p.y, p.z)
    if pl then
        local r = roleIn(pl, guid)
        if r == "owner" or r == "builder" then return true end
        if r == "visitor" then return false, "You're a visitor on " .. pl.ownerName .. "'s plot: you can copy, not edit." end
        return false, "That's in " .. pl.ownerName .. "'s plot."
    end
    if p.owner == guid then return true end
    return false, "That prop isn't yours."
end

-- May the player select and copy it? (Editors, and visitors of its plot.)
local function canCopy(player, p)
    local ok, why = canEdit(player, p)
    if ok then return true end
    local pl = plotAt(p.map, p.x, p.y, p.z)
    if pl and roleIn(pl, player:GetGUIDLow()) == "visitor" then return true end
    if not pl and p.owner ~= player:GetGUIDLow() then return false, "That prop is " .. p.ownerName .. "'s." end
    return false, why
end

------------------------------------------------------------------------------------------------
-- budgets
------------------------------------------------------------------------------------------------
local function tierOf(player)
    local t = trust[player:GetGUIDLow()]
    if t then return t end
    local played = tonumber(try(player, "GetTotalPlayedTime"))
    if played and played < newHours() * 3600 then return 1 end
    return 2
end

local function budgetOf(player)
    local t = tierOf(player)
    local m = TIERS[t].mult
    return { tier = TIERS[t].key, props = math.floor(perPlayer() * m + 0.5), points = math.floor(perPoints() * m + 0.5) }
end

local function countOwner(guid)
    local n = 0
    for _, p in pairs(props) do if p.owner == guid then n = n + 1 end end
    return n
end
local function pointsOwner(guid)
    local n = 0
    for _, p in pairs(props) do if p.owner == guid then n = n + costOf(p.entry) end end
    return n
end
local function countArea(key)
    local n = 0
    for _, p in pairs(props) do if p.area == key then n = n + 1 end end
    return n
end

-- items: { { entry, x, y, z, map, new = true for a prop that doesn't exist yet, from = the prop moving } }
-- Checks the player's points and every plot the items land in. (Prop counts are checked by the callers,
-- with their own words.)
local function checkBudget(player, items)
    local guid, cap = player:GetGUIDLow(), budgetOf(player)
    local addPts = 0
    local perPlot = {}
    for _, it in ipairs(items) do
        local c = costOf(it.entry)
        if it.new then addPts = addPts + c end
        local pl = plotAt(it.map, it.x, it.y, it.z)
        local fromPl = it.from and plotAt(it.from.map, it.from.x, it.from.y, it.from.z)
        if pl and pl ~= fromPl then
            local e = perPlot[pl] or { n = 0, pts = 0 }
            perPlot[pl] = e
            e.n, e.pts = e.n + 1, e.pts + c
        end
    end
    if addPts > 0 then
        local used = pointsOwner(guid)
        if used + addPts > cap.points then
            return false, string.format("That needs %d build points; you have %d of %d left. Delete something to make room.",
                addPts, math.max(0, cap.points - used), cap.points)
        end
    end
    for pl, e in pairs(perPlot) do
        local n, pts = plotUsage(pl)
        if n + e.n > plotProps() or pts + e.pts > plotPoints() then
            return false, string.format("%s's plot is full (%d props, %d points at most).", pl.ownerName, plotProps(), plotPoints())
        end
    end
    return true
end

------------------------------------------------------------------------------------------------
-- the op log: every change to a prop, grouped per command, for a GM rollback
------------------------------------------------------------------------------------------------
local function rec(id, before, after)
    if curOp then curOp.rows[#curOp.rows + 1] = { id = id, before = before, after = after } end
end

local function beginOp(player, name)
    local prev = curOp
    curOp = { guid = player:GetGUIDLow(), name = cleanName(player:GetName()), op = tostring(name or ""):gsub("[^%w]", ""):sub(1, 12),
        at = os.time(), rows = {} }
    return prev
end

local function endOp(prev)
    local op = curOp
    curOp = prev
    if not op or #op.rows == 0 then return end
    opSeq = opSeq + 1
    op.id = opSeq
    oplog[#oplog + 1] = op
    if #oplog > K.OPLOG_KEEP then table.remove(oplog, 1) end
    for i = 1, #op.rows, 40 do
        local vals = {}
        for j = i, math.min(#op.rows, i + 39) do
            local r = op.rows[j]
            vals[#vals + 1] = string.format("(%d, %d, '%s', '%s', %d, '%s', '%s', %d)", op.id, op.guid, op.name,
                op.op ~= "" and op.op or "op", r.id, stateStr(r.before), stateStr(r.after), op.at)
        end
        exec("INSERT INTO mod_builder_oplog (op_id, guid, name, op, prop, before_state, after_state, at) VALUES "
            .. table.concat(vals, ", "))
    end
end

------------------------------------------------------------------------------------------------
-- spawning
------------------------------------------------------------------------------------------------
local function mapFor(mapId, player)
    if player and player:GetMapId() == mapId then
        local m = try(player, "GetMap")
        if m then return m end
    end
    if GetMapById then
        local ok, m = pcall(GetMapById, mapId, 0)
        if ok and m then return m end
    end
    return nil
end

local function liveObject(p, player)
    local g = live[p.id]
    if not g then return nil end
    local map = mapFor(p.map, player)
    if not map then return nil end
    return try(map, "GetWorldObject", g)
end

local function despawn(p, player)
    local go = liveObject(p, player)
    if go then
        if try(go, "RemoveFromWorld", false) == nil then try(go, "Despawn") end
    end
    live[p.id] = nil
end

local function spawn(p)
    if not PerformIngameSpawn then return false end
    local ok, go = pcall(PerformIngameSpawn, 2, p.entry, p.map, 0, p.x, p.y, p.z, p.o, false, 0, 1)
    if not ok or not go then return false end
    live[p.id] = try(go, "GetGUID")
    if p.s and p.s ~= 1 then try(go, "SetScale", p.s) end
    return true
end

-- Puts back every missing prop near the player (grid unloaded, or a restart).
local lastSync = {}
local function sync(player, force)
    if not player then return 0 end
    local guid, now = player:GetGUIDLow(), os.time()
    if not force and lastSync[guid] and now - lastSync[guid] < 5 then return 0 end
    lastSync[guid] = now
    local map, x, y = player:GetMapId(), player:GetX(), player:GetY()
    local n = 0
    for _, p in pairs(props) do
        if p.map == map and dist2(p.x, p.y, x, y) <= K.SYNC_RANGE and not liveObject(p, player) then
            if spawn(p) then n = n + 1 end
        end
    end
    return n
end

local function sqlProp(p)
    return string.format("INSERT INTO mod_builder_props (id, owner, owner_name, area, entry, map, x, y, z, o, created_at) "
        .. "VALUES (%d, %d, '%s', '%s', %d, %d, %.3f, %.3f, %.3f, %.4f, %d)",
        p.id, p.owner, cleanName(p.ownerName), p.area:gsub("[^%w]", ""), p.entry, p.map, p.x, p.y, p.z, p.o, os.time())
end

local function saveScale(p)
    if p.s and p.s ~= 1 then
        exec(string.format("REPLACE INTO mod_builder_prop_scale (id, scale) VALUES (%d, %.2f)", p.id, p.s))
    else
        exec(string.format("DELETE FROM mod_builder_prop_scale WHERE id = %d", p.id))
    end
end

local function addProp(owner, ownerName, area, entry, map, x, y, z, o, id, s)
    if not id then nextId = nextId + 1; id = nextId end
    local p = { id = id, owner = owner, ownerName = ownerName, area = area, entry = entry, map = map,
        x = x, y = y, z = z, o = normO(o) }
    if s and s ~= 1 then p.s = clampScale(s) end
    props[id] = p
    exec(sqlProp(p))
    if p.s then saveScale(p) end
    spawn(p)
    rec(id, nil, copyProp(p))
    return p
end

-- A prop the realm couldn't spawn: gone again, and not in the op log.
local function unplace(p)
    props[p.id] = nil
    live[p.id] = nil
    exec(string.format("DELETE FROM mod_builder_props WHERE id = %d", p.id))
    if p.s then exec(string.format("DELETE FROM mod_builder_prop_scale WHERE id = %d", p.id)) end
    if curOp and curOp.rows[#curOp.rows] and curOp.rows[#curOp.rows].id == p.id then table.remove(curOp.rows) end
end

local function removeProp(p, player)
    rec(p.id, copyProp(p), nil)
    despawn(p, player)
    props[p.id] = nil
    exec(string.format("DELETE FROM mod_builder_props WHERE id = %d", p.id))
    if p.s then exec(string.format("DELETE FROM mod_builder_prop_scale WHERE id = %d", p.id)) end
end

local function placeProp(p, x, y, z, o, player, s)
    local before = copyProp(p)
    despawn(p, player)
    p.x, p.y, p.z, p.o = x, y, z, normO(o)
    exec(string.format("UPDATE mod_builder_props SET x = %.3f, y = %.3f, z = %.3f, o = %.4f WHERE id = %d", p.x, p.y, p.z, p.o, p.id))
    if s ~= nil then
        local ns = clampScale(s)
        if ns == 1 then ns = nil end
        if ns ~= p.s then p.s = ns; saveScale(p) end
    end
    spawn(p)
    rec(p.id, before, copyProp(p))
end

local function pushUndo(guid, action)
    local stack = undo[guid] or {}
    undo[guid] = stack
    stack[#stack + 1] = action
    if #stack > K.UNDO_DEPTH then table.remove(stack, 1) end
end

------------------------------------------------------------------------------------------------
-- selection: one prop, or a group
------------------------------------------------------------------------------------------------
local function selectOne(guid, id)
    group[guid] = nil
    selected[guid] = id
end

local function selectMany(guid, ids)
    if #ids <= 1 then return selectOne(guid, ids[1]) end
    local g = {}
    for i = 1, math.min(#ids, K.GROUP_MAX) do g[i] = ids[i] end
    group[guid] = g
    selected[guid] = g[#g]
end

-- The props selected now (missing ones dropped).
local function selList(guid)
    local g = group[guid]
    if g and #g > 0 then
        local out = {}
        for _, id in ipairs(g) do if props[id] then out[#out + 1] = props[id] end end
        if #out > 0 then return out end
    end
    local p = props[selected[guid] or 0]
    return p and { p } or {}
end

local function primary(guid, list)
    local p = props[selected[guid] or 0]
    if p then for _, q in ipairs(list) do if q == p then return p end end end
    return list[#list]
end

local NOTHING = "Nothing selected: |cffffff00.build spawn|r a prop, or |cffffff00.build near|r then |cffffff00.build select <n>|r."

-- The selection, if the player may change all of it here; otherwise nil (and says why).
local function editList(player, forDelete)
    local guid = player:GetGUIDLow()
    local list = selList(guid)
    if #list == 0 then say(player, NOTHING); return nil end
    for _, p in ipairs(list) do
        local ok, why = canEdit(player, p)
        if not ok and not (forDelete and p.owner == guid) then say(player, why); return nil end
        if p.map ~= player:GetMapId() or dist2(p.x, p.y, player:GetX(), player:GetY()) > K.SYNC_RANGE then
            say(player, "Your selection is too far away."); return nil
        end
    end
    return list
end

local function copyList(player)
    local guid = player:GetGUIDLow()
    local list = selList(guid)
    if #list == 0 then say(player, NOTHING); return nil end
    for _, p in ipairs(list) do
        local ok, why = canCopy(player, p)
        if not ok then say(player, why); return nil end
    end
    return list
end

-- Offsets from the group's centre (middle on the ground, lowest z), in world directions.
local function relFrom(list)
    local copy = {}
    for i, p in ipairs(list) do copy[i] = p end
    list = copy
    local cx, cy, mz = 0, 0, math.huge
    for _, p in ipairs(list) do cx = cx + p.x; cy = cy + p.y; if p.z < mz then mz = p.z end end
    cx, cy = cx / #list, cy / #list
    local rel = {}
    table.sort(list, function(a, b) return a.id < b.id end)
    for _, p in ipairs(list) do
        rel[#rel + 1] = { entry = p.entry, dx = p.x - cx, dy = p.y - cy, dz = p.z - mz, o = normO(p.o), s = p.s }
    end
    return rel, cx, cy, mz
end

------------------------------------------------------------------------------------------------
-- the Builder window's channel
------------------------------------------------------------------------------------------------
local OVMod
do
    local ok, m = pcall(function() return require("ov_modapi") end)
    if ok and type(m) == "table" then OVMod = m end
    if not OVMod and type(rawget(_G, "OVMod")) == "table" then OVMod = rawget(_G, "OVMod") end
end

-- id,key,category,name,points;... (the server's allowlist: the window and the spawn menu show only these)
local function catalogText()
    local out = {}
    for _, c in ipairs(CATALOG) do out[#out + 1] = c.id .. "," .. c.key .. "," .. c.cat .. "," .. c.name:gsub("[,;]", "") .. "," .. c.cost end
    return table.concat(out, ";")
end

local function prefabsOf(guid)
    local out = {}
    for _, f in pairs(prefabs) do if f.owner == guid then out[#out + 1] = f end end
    table.sort(out, function(a, b) return a.name < b.name end)
    return out
end

local function prefabCount(f)
    if not f.n then local n = 0; for _ in tostring(f.data):gmatch('"e":') do n = n + 1 end; f.n = n end
    return f.n
end

local function sendPrefabs(player)
    if not OVMod then return end
    local out = {}
    for _, f in ipairs(prefabsOf(player:GetGUIDLow())) do out[#out + 1] = f.id .. "," .. f.name .. "," .. (f.code or "-") .. "," .. prefabCount(f) end
    pcall(OVMod.Send, player, MOD, "prefabs", table.concat(out, ";"))
end

local function sendState(player)
    if not OVMod then return end
    local guid = player:GetGUIDLow()
    local list = selList(guid)
    local p = (#list > 0) and primary(guid, list) or nil
    local sel, pos = "-", "-"
    if p then
        sel = p.id .. "," .. p.entry .. "," .. ((byId[p.entry] and byId[p.entry].name) or ("#" .. p.entry)):gsub("[,;=]", "")
        pos = string.format("%.2f,%.2f,%.2f,%.0f,%.2f", p.x, p.y, p.z, math.deg(p.o) % 360, p.s or 1)
    end
    local key = buildArea(player)
    local cap = budgetOf(player)
    local pl = plotAt(player:GetMapId(), player:GetX(), player:GetY(), player:GetZ())
    local plot = "-"
    if pl then
        local n, pts = plotUsage(pl)
        plot = string.format("%d,%s,%s,%d/%d,%d/%d", pl.id, cleanName(pl.ownerName), roleIn(pl, guid) or (isGM(player) and "gm") or "none",
            n, plotProps(), pts, plotPoints())
    end
    -- ids: every selected prop's object id, so the browser client can carry the whole group on screen
    -- (LeylineEdit "group", client 20261026a)
    local ids = {}
    for i = 1, math.min(#list, 40) do ids[#ids + 1] = tostring(list[i].id) end
    local data = string.format("sel=%s;mine=%d/%d;area=%s;code=%s;n=%d;pos=%s;pts=%d/%d;tier=%s;plot=%s;clip=%d;ids=%s",
        sel, countOwner(guid), cap.props, (areaName(key)):gsub("[;=]", ""), lastCode[guid] or "-",
        #list, pos, pointsOwner(guid), cap.points, cap.tier, plot, clip[guid] and #clip[guid].rel or 0,
        #ids > 0 and table.concat(ids, " ") or "-")
    pcall(OVMod.Send, player, MOD, "state", data)
end

------------------------------------------------------------------------------------------------
-- commands
------------------------------------------------------------------------------------------------
local function propName(p) return (byId[p.entry] and byId[p.entry].name) or ("prop " .. p.entry) end

-- Plot and prefab changes (they write to the database): five a second.
local writes = {}
local function rateWrite(player)
    local guid, now = player:GetGUIDLow(), os.time()
    local w = writes[guid]
    if not w or w.sec ~= now then writes[guid] = { sec = now, n = 1 }; return true end
    w.n = w.n + 1
    if w.n <= 5 then return true end
    say(player, "Slow down a little.")
    return false
end

local function rateMove(guid)
    local now = os.time()
    local m = moves[guid]
    if not m or m.sec ~= now then moves[guid] = { sec = now, n = 1 }; return true end
    m.n = m.n + 1
    return m.n <= K.MOVES_PER_SECOND
end

local function spawnCommand(player, word, at)
    local c, count = findProp(word)
    if not c then
        if count and count > 1 then return say(player, "More than one prop matches '" .. word .. "'; use its id (|cffffff00.build catalog " .. word .. "|r).") end
        return say(player, "No prop called '" .. tostring(word or "") .. "' (|cffffff00.build catalog|r lists them).")
    end
    local key, why = buildArea(player)
    if not key then return say(player, why) end
    if at and not insideArea(key, player:GetMapId(), at.x, at.y, at.z) then
        return say(player, "That spot is outside the build area.")
    end
    local px, py, pz, po = player:GetX(), player:GetY(), player:GetZ(), player:GetO()
    if at then px, py, pz = at.x, at.y, at.z end
    local okHere, whyNot = canBuildAt(player, player:GetMapId(), px, py, pz)
    if not okHere then return say(player, whyNot) end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastSpawn[guid] == now then return say(player, "One prop a second.") end
    local cap = budgetOf(player)
    if countOwner(guid) >= cap.props then return say(player, string.format("You have %s, the most allowed (|cffffff00.build delete|r or |cffffff00.build clear|r).", plural(countOwner(guid), "prop"))) end
    if countArea(key) >= perArea() then return say(player, string.format("This area is full (%d props).", perArea())) end
    local okB, whyB = checkBudget(player, { { entry = c.id, map = player:GetMapId(), x = px, y = py, z = pz, new = true } })
    if not okB then return say(player, whyB) end
    lastSpawn[guid] = now
    local p = addProp(guid, player:GetName(), key, c.id, player:GetMapId(), px, py, pz, po)
    if not live[p.id] then
        unplace(p)
        return say(player, "The realm couldn't place that prop here.")
    end
    selectOne(guid, p.id)
    pushUndo(guid, { kind = "spawn", id = p.id })
    say(player, string.format("%s placed (%d/%d). Nudge it with |cffffff00.build move|r and |cffffff00.build turn|r.", c.name, countOwner(guid), cap.props))
end

local function nearCommand(player)
    local guid, map, x, y = player:GetGUIDLow(), player:GetMapId(), player:GetX(), player:GetY()
    local gm = isGM(player)
    local list = {}
    for _, p in pairs(props) do
        if p.map == map and (p.owner == guid or gm or canEdit(player, p)) then
            local d = dist2(p.x, p.y, x, y)
            if d <= K.NEAR_RANGE then list[#list + 1] = { p = p, d = d } end
        end
    end
    table.sort(list, function(a, b) if a.d ~= b.d then return a.d < b.d end return a.p.id < b.p.id end)
    nearList[guid] = {}
    if #list == 0 then return say(player, "None of your props within " .. K.NEAR_RANGE .. " yards.") end
    say(player, string.format("Props within %d yards (|cffffff00.build select <n>|r):", K.NEAR_RANGE))
    for i = 1, math.min(#list, 15) do
        local e = list[i]
        nearList[guid][i] = e.p.id
        say(player, string.format("  %d. %s, %.0f yd%s%s", i, propName(e.p), e.d,
            e.p.owner ~= guid and (" (" .. e.p.ownerName .. ")") or "", selected[guid] == e.p.id and " [selected]" or ""))
    end
    if #list > 15 then say(player, string.format("  ... and %d more further away.", #list - 15)) end
end

local function selectCommand(player, arg)
    local guid = player:GetGUIDLow()
    local n = tonumber(arg or "")
    local id = n and nearList[guid] and nearList[guid][math.floor(n)]
    if not id or not props[id] then return say(player, "Run |cffffff00.build near|r, then |cffffff00.build select <n>|r with a number from the list.") end
    selectOne(guid, id)
    say(player, propName(props[id]) .. " selected.")
end

-- Moves every prop in list to where fn(p) says ({x, y, z, o}), all or none; one undo entry.
local function moveGroup(player, list, fn, what)
    local guid = player:GetGUIDLow()
    local plan, items = {}, {}
    for _, p in ipairs(list) do
        local t = fn(p)
        if not finite(t.x) or not finite(t.y) or not finite(t.z) then return say(player, "Those numbers don't work.") end
        if not insideArea(p.area, p.map, t.x, t.y, t.z) then
            return say(player, #list > 1 and "That would take part of the selection out of the build area." or "That would take it out of the build area.")
        end
        local ok, why = canBuildAt(player, p.map, t.x, t.y, t.z)
        if not ok then return say(player, why) end
        plan[#plan + 1] = { p = p, t = t }
        items[#items + 1] = { entry = p.entry, map = p.map, x = t.x, y = t.y, z = t.z, from = p }
    end
    local okB, whyB = checkBudget(player, items)
    if not okB then return say(player, whyB) end
    local back = {}
    for _, e in ipairs(plan) do back[#back + 1] = { id = e.p.id, x = e.p.x, y = e.p.y, z = e.p.z, o = e.p.o, s = e.p.s } end
    pushUndo(guid, { kind = "places", list = back })
    for _, e in ipairs(plan) do placeProp(e.p, e.t.x, e.t.y, e.t.z, e.t.o or e.p.o, player, e.t.s) end
    return true
end

local function moveCommand(player, axis, amount)
    local d = tonumber(amount or "")
    if not (axis == "x" or axis == "y" or axis == "z") or not d then return say(player, "Usage: |cffffff00.build move x|y|z <yards>|r  (e.g. .build move z 0.5)") end
    if d ~= d or math.abs(d) > K.MAX_STEP then return say(player, "Up to " .. K.MAX_STEP .. " yards a step.") end
    local list = editList(player)
    if not list then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    local ok = moveGroup(player, list, function(p)
        local x, y, z = p.x, p.y, p.z
        if axis == "x" then x = x + d elseif axis == "y" then y = y + d else z = z + d end
        return { x = x, y = y, z = z }
    end)
    if not ok then return end
    if #list == 1 then say(player, string.format("%s moved %+.2f on %s.", propName(list[1]), d, axis))
    else say(player, string.format("%s moved %+.2f on %s.", plural(#list, "prop"), d, axis)) end
end

-- Turns the list by rad around (cx, cy); each prop turns with it.
local function turnAround(cx, cy, rad)
    local c, s = math.cos(rad), math.sin(rad)
    return function(p)
        local dx, dy = p.x - cx, p.y - cy
        return { x = cx + dx * c - dy * s, y = cy + dx * s + dy * c, z = p.z, o = p.o + rad }
    end
end

local function turnCommand(player, amount)
    local deg = tonumber(amount or "")
    if not deg or deg ~= deg then return say(player, "Usage: |cffffff00.build turn <degrees>|r  (e.g. .build turn 15, .build turn -90)") end
    if math.abs(deg) > K.MAX_TURN then return say(player, "Up to " .. K.MAX_TURN .. " degrees a turn.") end
    local list = editList(player)
    if not list then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    local fn
    if #list == 1 then
        fn = function(p) return { x = p.x, y = p.y, z = p.z, o = p.o + math.rad(deg) } end
    else
        local _, cx, cy = relFrom(list)
        fn = turnAround(cx, cy, math.rad(deg))
    end
    if not moveGroup(player, list, fn) then return end
    if #list == 1 then say(player, string.format("%s turned %+d degrees.", propName(list[1]), math.floor(deg + 0.5)))
    else say(player, string.format("%s turned %+d degrees.", plural(#list, "prop"), math.floor(deg + 0.5))) end
end

local function deleteCommand(player)
    local list = editList(player, true)
    if not list then return end
    local guid = player:GetGUIDLow()
    local saved = {}
    for _, p in ipairs(list) do saved[#saved + 1] = copyProp(p); removeProp(p, player) end
    pushUndo(guid, { kind = "restore", list = saved })
    selectOne(guid, nil)
    if #list == 1 then say(player, propName(list[1]) .. " removed (|cffffff00.build undo|r brings it back).")
    else say(player, plural(#list, "prop") .. " removed (|cffffff00.build undo|r brings them back).") end
end

local function clearCommand(player)
    local key, why = buildArea(player)
    if not key then return say(player, why) end
    local guid = player:GetGUIDLow()
    local gone = {}
    for _, p in pairs(props) do if p.owner == guid and p.area == key then gone[#gone + 1] = p end end
    if #gone == 0 then return say(player, "You have no props in this area.") end
    local saved = {}
    for _, p in ipairs(gone) do saved[#saved + 1] = copyProp(p); removeProp(p, player) end
    pushUndo(guid, { kind = "restore", list = saved })
    selectOne(guid, nil)
    say(player, string.format("Cleared %s from %s (|cffffff00.build undo|r puts them back).", plural(#gone, "prop"), areaName(key)))
end

local function undoCommand(player)
    local guid = player:GetGUIDLow()
    local stack = undo[guid]
    local a = stack and table.remove(stack)
    if not a then return say(player, "Nothing to undo.") end
    if a.kind == "spawn" then
        local p = props[a.id]
        if p then removeProp(p, player) end
        if selected[guid] == a.id then selectOne(guid, nil) end
        return say(player, "Undone: the prop you placed is gone.")
    elseif a.kind == "places" then
        local n, last = 0, nil
        for _, b in ipairs(a.list) do
            local p = props[b.id]
            if p then placeProp(p, b.x, b.y, b.z, b.o, player, b.s or 1); n = n + 1; last = p end
        end
        if n == 0 then return say(player, "That prop is gone already.") end
        local ids = {}
        for _, b in ipairs(a.list) do if props[b.id] then ids[#ids + 1] = b.id end end
        selectMany(guid, ids)
        if #a.list == 1 then return say(player, "Undone: " .. propName(last) .. " is back where it was.") end
        return say(player, "Undone: " .. plural(n, "prop") .. " back where they were.")
    elseif a.kind == "restore" then
        local room = budgetOf(player).props - countOwner(guid)
        local n, ids = 0, {}
        for _, c in ipairs(a.list) do
            if n >= room and c.owner == guid then break end
            if not props[c.id] then
                addProp(c.owner, c.ownerName, c.area, c.entry, c.map, c.x, c.y, c.z, c.o, c.id, c.s)
                n = n + 1; ids[#ids + 1] = c.id
            end
        end
        if #ids > 0 then selectMany(guid, ids) end
        return say(player, "Undone: " .. plural(n, "prop") .. " back.")
    elseif a.kind == "load" then
        local n = 0
        for _, id in ipairs(a.ids) do
            if props[id] then removeProp(props[id], player); n = n + 1 end
        end
        selectOne(guid, nil)
        return say(player, "Undone: the pasted build (" .. plural(n, "prop") .. ") is gone.")
    end
end

-- builds ---------------------------------------------------------------------------------------
-- A build is "entry,dx,dy,dz,do;..." with the offsets turned into the saver's facing, so a paste faces the
-- same way relative to whoever pastes it.
local function encode(list, ax, ay, az, ao)
    local out = {}
    local c, s = math.cos(-ao), math.sin(-ao)
    for _, p in ipairs(list) do
        local dx, dy = p.x - ax, p.y - ay
        out[#out + 1] = string.format("%d,%.2f,%.2f,%.2f,%.3f", p.entry, dx * c - dy * s, dx * s + dy * c, p.z - az, normO(p.o - ao))
    end
    return table.concat(out, ";")
end

local function decode(text)
    local out = {}
    for e, dx, dy, dz, d_o in tostring(text or ""):gmatch("(%d+),(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+)") do
        out[#out + 1] = { entry = tonumber(e), dx = tonumber(dx), dy = tonumber(dy), dz = tonumber(dz), o = tonumber(d_o) }
    end
    return out
end

-- Pastes rel (offsets and facings, see relFrom / decode) around origin {x, y, z, o}: the offsets turn by o.
-- Everything is checked: the allowlist, the area, plots, the player's and the plots' budgets, the paste rate.
-- Returns the new prop ids, or nil (having said why).
local function placeMany(player, rel, origin, label)
    local key, why = buildArea(player)
    if not key then say(player, why); return nil end
    local guid, now, map = player:GetGUIDLow(), os.time(), player:GetMapId()
    if lastLoad[guid] and now - lastLoad[guid] < K.LOAD_COOLDOWN then say(player, "One paste every " .. K.LOAD_COOLDOWN .. " seconds."); return nil end
    local placeable, skipped = {}, 0
    local c, s = math.cos(origin.o or 0), math.sin(origin.o or 0)
    for _, e in ipairs(rel) do
        if byId[e.entry] then
            local x, y, z = origin.x + e.dx * c - e.dy * s, origin.y + e.dx * s + e.dy * c, origin.z + e.dz
            if insideArea(key, map, x, y, z) and canBuildAt(player, map, x, y, z) then
                placeable[#placeable + 1] = { e = e, x = x, y = y, z = z }
            else
                skipped = skipped + 1
            end
        else
            skipped = skipped + 1
        end
    end
    if #placeable == 0 then say(player, "None of that build fits here (step further into the area)."); return nil end
    local cap = budgetOf(player)
    if countOwner(guid) + #placeable > cap.props then
        say(player, string.format("That build has %s; you have room for %d (|cffffff00.build clear|r makes room).",
            plural(#placeable, "prop"), math.max(0, cap.props - countOwner(guid))))
        return nil
    end
    if countArea(key) + #placeable > perArea() then say(player, "This area hasn't room for that build."); return nil end
    local items = {}
    for _, pl in ipairs(placeable) do items[#items + 1] = { entry = pl.e.entry, map = map, x = pl.x, y = pl.y, z = pl.z, new = true } end
    local okB, whyB = checkBudget(player, items)
    if not okB then say(player, whyB); return nil end
    lastLoad[guid] = now
    local ids = {}
    for _, pl in ipairs(placeable) do
        local p = addProp(guid, player:GetName(), key, pl.e.entry, map, pl.x, pl.y, pl.z, (origin.o or 0) + pl.e.o, nil, pl.e.s)
        if live[p.id] then ids[#ids + 1] = p.id else unplace(p); skipped = skipped + 1 end
    end
    if #ids == 0 then say(player, "The realm couldn't place that here."); return nil end
    pushUndo(guid, { kind = "load", ids = ids })
    selectMany(guid, ids)
    say(player, string.format("Pasted '%s': %s%s.", label, plural(#ids, "prop"),
        skipped > 0 and string.format(" (%d didn't fit here)", skipped) or ""))
    return ids
end

local function cacheBuild(owner, name, text, code)
    builds[owner] = builds[owner] or {}
    builds[owner][name] = { props = text, code = code }
    if code then byCode[code] = { owner = owner, name = name, props = text } end
end

local function getBuild(owner, name)
    local b = builds[owner] and builds[owner][name]
    if b then return b end
    local q = query(string.format("SELECT props, code FROM mod_builder_builds WHERE owner = %d AND name = '%s'", owner, name))
    if q then
        local code = q:GetString(1)
        if code == "" then code = nil end
        cacheBuild(owner, name, q:GetString(0), code)
        return builds[owner][name]
    end
    return nil
end

local function getByCode(code)
    code = code:upper()
    if byCode[code] then return byCode[code] end
    local q = query(string.format("SELECT owner, name, props FROM mod_builder_builds WHERE code = '%s'", code))
    if q then
        local owner, name = q:GetUInt32(0), q:GetString(1)
        cacheBuild(owner, name, q:GetString(2), code)
        return byCode[code]
    end
    return nil
end

local function prefabByCode(code)
    code = tostring(code or ""):upper()
    for _, f in pairs(prefabs) do if f.code == code then return f end end
    return nil
end

local function saveCommand(player, arg)
    local name = cleanBuild(arg)
    if not name then return say(player, "Usage: |cffffff00.build save <name>|r  (letters, digits, - and _, up to " .. K.BUILD_NAME_MAX .. ")") end
    local key, why = buildArea(player)
    if not key then return say(player, why) end
    local guid = player:GetGUIDLow()
    local list = {}
    for _, p in pairs(props) do if p.owner == guid and p.area == key then list[#list + 1] = p end end
    if #list == 0 then return say(player, "You have no props in this area to save.") end
    table.sort(list, function(a, b) return a.id < b.id end)
    local text = encode(list, player:GetX(), player:GetY(), player:GetZ(), player:GetO())
    local old = getBuild(guid, name)
    cacheBuild(guid, name, text, old and old.code)
    exec(string.format("INSERT INTO mod_builder_builds (owner, owner_name, name, props, created_at) VALUES (%d, '%s', '%s', '%s', %d) "
        .. "ON DUPLICATE KEY UPDATE props = VALUES(props), created_at = VALUES(created_at)",
        guid, cleanName(player:GetName()), name, text, os.time()))
    say(player, string.format("Saved '%s': %s, relative to where you stand. |cffffff00.build share %s|r gives it a code.",
        name, plural(#list, "prop"), name))
end

local function newCode()
    for _ = 1, 20 do
        local t = {}
        for i = 1, K.CODE_LEN do
            local k = math.random(#K.CODE_ALPHABET)
            t[i] = K.CODE_ALPHABET:sub(k, k)
        end
        local code = table.concat(t)
        if not getByCode(code) and not prefabByCode(code) then return code end
    end
    return nil
end

local function shareCommand(player, arg)
    local name = cleanBuild(arg)
    if not name then return say(player, "Usage: |cffffff00.build share <name>|r") end
    local guid = player:GetGUIDLow()
    local b = getBuild(guid, name)
    if not b then return say(player, "You have no build called '" .. name .. "' (|cffffff00.build saved|r).") end
    if not b.code then
        local code = newCode()
        if not code then return say(player, "Couldn't make a code just now; try again.") end
        cacheBuild(guid, name, b.props, code)
        b = builds[guid][name]
        exec(string.format("UPDATE mod_builder_builds SET code = '%s' WHERE owner = %d AND name = '%s'", code, guid, name))
    end
    lastCode[guid] = b.code
    say(player, string.format("Code for '%s': |cffffff00%s|r. Anyone who builds can paste it with |cffffff00.build load %s|r.", name, b.code, b.code))
end

local prefabRel   -- below

local function loadCommand(player, arg)
    if not arg or arg == "" then return say(player, "Usage: |cffffff00.build load <name|code>|r") end
    local key, why = buildArea(player)
    if not key then return say(player, why) end
    local guid = player:GetGUIDLow()
    local name = cleanBuild(arg)
    local b = name and getBuild(guid, name)
    local label = name
    if not b and isCode(arg) then
        local c = getByCode(arg)
        if c then b = c; label = arg:upper() end
    end
    local ax, ay, az, ao = player:GetX(), player:GetY(), player:GetZ(), player:GetO()
    if not b and isCode(arg) then
        -- a prefab's code works here too: pasted at your feet as it was saved
        local f = prefabByCode(arg)
        local rel = f and prefabRel(f)
        if rel then return placeMany(player, rel, { x = ax, y = ay, z = az, o = 0 }, arg:upper()) end
    end
    if not b then return say(player, "No build '" .. tostring(arg) .. "': one of your names (|cffffff00.build saved|r) or a 6-letter code.") end
    placeMany(player, decode(b.props), { x = ax, y = ay, z = az, o = ao }, label)
end

local function savedCommand(player)
    local guid = player:GetGUIDLow()
    local names, seen = {}, {}
    local q = query(string.format("SELECT name, code FROM mod_builder_builds WHERE owner = %d ORDER BY name", guid))
    if q then repeat local n = q:GetString(0); seen[n] = true; names[#names + 1] = n .. (q:GetString(1) ~= "" and (" (" .. q:GetString(1) .. ")") or "") until not q:NextRow() end
    for n, b in pairs(builds[guid] or {}) do if not seen[n] then names[#names + 1] = n .. (b.code and (" (" .. b.code .. ")") or "") end end
    table.sort(names)
    if #names == 0 then return say(player, "No saved builds yet (|cffffff00.build save <name>|r).") end
    say(player, "Your builds: " .. table.concat(names, ", "))
end

local function catalogCommand(player, word)
    word = word and word:lower()
    local lines = {}
    for _, cat in ipairs(CATEGORIES) do
        local items = {}
        for _, c in ipairs(CATALOG) do
            if c.cat == cat and (not word or cat == word or c.name:lower():find(word, 1, true) or c.key:find(word, 1, true)) then
                items[#items + 1] = c.key .. " (" .. c.id .. ")"
            end
        end
        if #items > 0 then lines[#lines + 1] = "  |cffffd100" .. cat .. "|r: " .. table.concat(items, ", ") end
    end
    if #lines == 0 then return say(player, "No props match '" .. word .. "'.") end
    say(player, "Props (|cffffff00.build spawn <name or id>|r):")
    for _, l in ipairs(lines) do say(player, l) end
end

local function whereCommand(player)
    local key = buildArea(player)
    for i, a in ipairs(BUILD_AREAS) do
        say(player, string.format("  %d. %s (map %d, %d yards across)%s", i, a.name, a.map, a.r * 2,
            key == tostring(i) and "  |cff40ff40you are here|r" or ""))
    end
    if key and key:match("^m") then say(player, "You're a GM with OV_BUILD_ANYWHERE=1: you can build here.")
    elseif not key then say(player, "You're not in a build area.") end
end

------------------------------------------------------------------------------------------------
-- edit mode: exact points from the browser client's free camera (EditMode.lua)
------------------------------------------------------------------------------------------------
local function guidCounter(g)
    if g == nil then return nil end
    if GetGUIDLow then
        local ok, v = pcall(GetGUIDLow, g)
        if ok and v then return tonumber(v) end
    end
    return nil
end

-- Three numbers, a real point, near the player.
local function exactPoint(player, xs, ys, zs)
    local x, y, z = tonumber(xs or ""), tonumber(ys or ""), tonumber(zs or "")
    if not (x and y and z) or not finite(x) or not finite(y) or not finite(z) then return nil end
    if dist2(x, y, player:GetX(), player:GetY()) > K.EXACT_RANGE or math.abs(z - player:GetZ()) > K.EXACT_RANGE then
        return nil, "too far"
    end
    return { x = x, y = y, z = z }
end

local function pointUsage(player, why, usage)
    say(player, why == "too far" and "That spot is too far from your character." or ("Usage: |cffffff00" .. usage .. "|r"))
end

local function propByObject(want)
    for id, g in pairs(live) do
        local p = props[id]
        if p and guidCounter(g) == want then return p end
    end
    return nil
end

-- .build pick <object id> [add]: select it; with "add" (Shift-click) add it to the group or take it out.
local function pickCommand(player, arg, mode)
    local want = tonumber(arg or "")
    if not want then return say(player, "Usage: |cffffff00.build pick <object id>|r (edit mode sends it when you click a prop).") end
    local guid = player:GetGUIDLow()
    local p = propByObject(want)
    if not p then return say(player, "That isn't a Builder prop.") end
    local ok, why = canCopy(player, p)
    if not ok then return say(player, why) end
    if mode ~= "add" then
        selectOne(guid, p.id)
        return say(player, propName(p) .. " selected.")
    end
    local ids = {}
    for _, q in ipairs(selList(guid)) do ids[#ids + 1] = q.id end
    for i, id in ipairs(ids) do
        if id == p.id then
            table.remove(ids, i)
            selectMany(guid, ids)
            return say(player, string.format("%s taken out (%d selected).", propName(p), #ids))
        end
    end
    if #ids >= K.GROUP_MAX then return say(player, "Up to " .. K.GROUP_MAX .. " props in a selection.") end
    ids[#ids + 1] = p.id
    selectMany(guid, ids)
    say(player, string.format("%s added (%d selected).", propName(p), #ids))
end

-- Selects what passes keep(p) near the player, nearest first, up to K.GROUP_MAX; add keeps the old selection.
local function selectWhere(player, keep, add, none)
    local guid, map, x, y = player:GetGUIDLow(), player:GetMapId(), player:GetX(), player:GetY()
    local ids, seen = {}, {}
    if add then for _, q in ipairs(selList(guid)) do ids[#ids + 1] = q.id; seen[q.id] = true end end
    local found = {}
    for _, p in pairs(props) do
        if p.map == map and not seen[p.id] and dist2(p.x, p.y, x, y) <= K.EXACT_RANGE and keep(p) and canCopy(player, p) then
            found[#found + 1] = { p = p, d = dist2(p.x, p.y, x, y) }
        end
    end
    table.sort(found, function(a, b) if a.d ~= b.d then return a.d < b.d end return a.p.id < b.p.id end)
    local capped = false
    for _, f in ipairs(found) do
        if #ids >= K.GROUP_MAX then capped = true; break end
        ids[#ids + 1] = f.p.id
    end
    if #ids == 0 then selectOne(guid, nil); return say(player, none) end
    selectMany(guid, ids)
    say(player, string.format("%s selected%s.", plural(#ids, "prop"), capped and (" (the most in one selection is " .. K.GROUP_MAX .. ")") or ""))
end

-- .build selbox x1 y1 x2 y2 [add]: every prop on the ground inside the box (two corners you clicked).
local function selboxCommand(player, words)
    local x1, y1, x2, y2 = tonumber(words[2] or ""), tonumber(words[3] or ""), tonumber(words[4] or ""), tonumber(words[5] or "")
    if not (x1 and y1 and x2 and y2) or not (finite(x1) and finite(y1) and finite(x2) and finite(y2)) then
        return say(player, "Usage: |cffffff00.build selbox <x1> <y1> <x2> <y2>|r (edit mode sends it for a box)")
    end
    local px, py = player:GetX(), player:GetY()
    if dist2(x1, y1, px, py) > K.EXACT_RANGE or dist2(x2, y2, px, py) > K.EXACT_RANGE then return say(player, "That box is too far from your character.") end
    local lx, hx, ly, hy = math.min(x1, x2), math.max(x1, x2), math.min(y1, y2), math.max(y1, y2)
    selectWhere(player, function(p) return p.x >= lx and p.x <= hx and p.y >= ly and p.y <= hy end,
        (words[6] or ""):lower() == "add", "No props you can select in that box.")
end

-- .build selall [yards]: all of your own props within range (20 by default, 40 at most).
local function selallCommand(player, arg)
    local r = tonumber(arg or "") or 20
    if not finite(r) or r < 1 then r = 20 end
    if r > K.NEAR_RANGE then r = K.NEAR_RANGE end
    local guid, x, y = player:GetGUIDLow(), player:GetX(), player:GetY()
    selectWhere(player, function(p) return p.owner == guid and dist2(p.x, p.y, x, y) <= r end, false,
        "None of your props within " .. math.floor(r) .. " yards.")
end

local function placeAtCommand(player, words)
    local at, why = exactPoint(player, words[2], words[3], words[4])
    if not at then return pointUsage(player, why, ".build placeat <x> <y> <z> [degrees]") end
    local deg = tonumber(words[5] or "0") or 0
    if not finite(deg) or math.abs(deg) > 360 then return say(player, "Turn by up to 360 degrees.") end
    local list = editList(player)
    if not list then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    local guid = player:GetGUIDLow()
    local pp = primary(guid, list)
    if pp.map ~= player:GetMapId() then return say(player, "That would take it out of the build area.") end
    -- The carried prop goes to the point; the rest of the group keeps its place around it and turns with it.
    local rad = math.rad(deg)
    local c, s = math.cos(rad), math.sin(rad)
    local ok = moveGroup(player, list, function(p)
        local dx, dy = p.x - pp.x, p.y - pp.y
        return { x = at.x + dx * c - dy * s, y = at.y + dx * s + dy * c, z = at.z + (p.z - pp.z), o = p.o + rad }
    end)
    if not ok then return end
    say(player, #list == 1 and (propName(pp) .. " placed.") or (plural(#list, "prop") .. " placed."))
end

-- .build setpos <x> <y> <z>, setturn <degrees>, setscale <size>: the properties panel. With a group, the
-- last-picked prop gets the numbers and the rest move (or turn) with it.
local function setposCommand(player, words)
    local at, why = exactPoint(player, words[2], words[3], words[4])
    if not at then return pointUsage(player, why, ".build setpos <x> <y> <z>") end
    local list = editList(player)
    if not list then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    local pp = primary(player:GetGUIDLow(), list)
    local dx, dy, dz = at.x - pp.x, at.y - pp.y, at.z - pp.z
    if moveGroup(player, list, function(p) return { x = p.x + dx, y = p.y + dy, z = p.z + dz } end) then
        say(player, #list == 1 and (propName(pp) .. " moved.") or (plural(#list, "prop") .. " moved."))
    end
end

local function setturnCommand(player, arg)
    local deg = tonumber(arg or "")
    if not deg or not finite(deg) then return say(player, "Usage: |cffffff00.build setturn <degrees>|r (0 to 359)") end
    local list = editList(player)
    if not list then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    local pp = primary(player:GetGUIDLow(), list)
    local rad = normO(math.rad(deg)) - pp.o
    if moveGroup(player, list, turnAround(pp.x, pp.y, rad)) then
        say(player, string.format("%s facing %d degrees.", #list == 1 and propName(pp) or plural(#list, "prop"), math.floor(deg % 360 + 0.5)))
    end
end

local function setscaleCommand(player, arg)
    local s = tonumber(arg or "")
    if not s or not finite(s) then return say(player, string.format("Usage: |cffffff00.build setscale <size>|r (%.1f to %.1f)", SCALE_MIN, SCALE_MAX)) end
    if s < SCALE_MIN or s > SCALE_MAX then return say(player, string.format("Size goes from %.1f to %.1f.", SCALE_MIN, SCALE_MAX)) end
    local list = editList(player)
    if not list then return end
    local go = liveObject(list[1], player)
    if go and not has(go, "SetScale") then return say(player, "Size isn't supported on this realm.") end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    s = clampScale(s)
    if moveGroup(player, list, function(p) return { x = p.x, y = p.y, z = p.z, s = s } end) then
        say(player, string.format("%s at size %.2f.", #list == 1 and propName(list[1]) or plural(#list, "prop"), s))
    end
end

local function dupCommand(player)
    local list = editList(player)
    if not list then return end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastSpawn[guid] == now then return say(player, "One prop a second.") end
    local cap = budgetOf(player)
    if countOwner(guid) + #list > cap.props then
        if #list == 1 then return say(player, string.format("You have %s, the most allowed.", plural(countOwner(guid), "prop"))) end
        return say(player, string.format("That's %s; you have room for %d.", plural(#list, "prop"), math.max(0, cap.props - countOwner(guid))))
    end
    local pp = primary(guid, list)
    if countArea(pp.area) + #list > perArea() then return say(player, string.format("This area is full (%d props).", perArea())) end
    -- Beside it, along the (last-picked) prop's right-hand side; inside the area or not at all.
    local ox, oy = math.cos(pp.o - math.pi / 2) * 1.5, math.sin(pp.o - math.pi / 2) * 1.5
    local items = {}
    for _, p in ipairs(list) do
        local x, y = p.x + ox, p.y + oy
        if not insideArea(p.area, p.map, x, y, p.z) then return say(player, "No room for a copy inside the build area there.") end
        local ok, why = canBuildAt(player, p.map, x, y, p.z)
        if not ok then return say(player, why) end
        items[#items + 1] = { entry = p.entry, map = p.map, x = x, y = y, z = p.z, new = true }
    end
    local okB, whyB = checkBudget(player, items)
    if not okB then return say(player, whyB) end
    lastSpawn[guid] = now
    local ids = {}
    for _, p in ipairs(list) do
        local c = addProp(guid, player:GetName(), p.area, p.entry, p.map, p.x + ox, p.y + oy, p.z, p.o, nil, p.s)
        if live[c.id] then ids[#ids + 1] = c.id else unplace(c) end
    end
    if #ids == 0 then return say(player, "The realm couldn't place the copy there.") end
    if #ids == 1 then
        selectOne(guid, ids[1])
        pushUndo(guid, { kind = "spawn", id = ids[1] })
        return say(player, string.format("%s copied (%d/%d).", propName(props[ids[1]]), countOwner(guid), cap.props))
    end
    selectMany(guid, ids)
    pushUndo(guid, { kind = "load", ids = ids })
    say(player, string.format("%s copied (%d/%d).", plural(#ids, "prop"), countOwner(guid), cap.props))
end

-- copy and paste ----------------------------------------------------------------------------------
local function copyCommand(player)
    local list = copyList(player)
    if not list then return end
    local rel = relFrom(list)
    clip[player:GetGUIDLow()] = { rel = rel }
    say(player, string.format("Copied %s. Paste puts them where you click (|cffffff00.build paste|r: at your feet).", plural(#rel, "prop")))
end

local function pasteClip(player, at, deg)
    local c = clip[player:GetGUIDLow()]
    if not c then return say(player, "Nothing copied yet: select props and Copy (|cffffff00.build copy|r).") end
    placeMany(player, c.rel, { x = at.x, y = at.y, z = at.z, o = math.rad(deg or 0) }, "copy")
end

local function pasteAtCommand(player, words)
    local at, why = exactPoint(player, words[2], words[3], words[4])
    if not at then return pointUsage(player, why, ".build pasteat <x> <y> <z> [degrees]") end
    local deg = tonumber(words[5] or "0") or 0
    if not finite(deg) or math.abs(deg) > 360 then return say(player, "Turn by up to 360 degrees.") end
    pasteClip(player, at, deg)
end

------------------------------------------------------------------------------------------------
-- prefabs: a named selection, saved as JSON, relative to its centre
--   {"v":1,"name":"camp","props":[{"e":2413,"x":0.50,"y":-1.25,"z":0.00,"o":1.571,"s":1.00}, ...]}
------------------------------------------------------------------------------------------------
-- A small strict JSON reader (objects, arrays, strings, numbers, true, false, null) with size and depth
-- limits. Nothing in the input is ever run.
local function jsonDecode(s, maxLen)
    if type(s) ~= "string" then return nil, "not text" end
    if #s > (maxLen or 32768) then return nil, "too big" end
    local i, depth = 1, 0
    local ESC = { ['"'] = '"', ["\\"] = "\\", ["/"] = "/", b = "\b", f = "\f", n = "\n", r = "\r", t = "\t" }
    local function ws() i = s:find("[^ \t\r\n]", i) or (#s + 1) end
    local function str()
        local out = {}
        i = i + 1
        while true do
            local c = s:sub(i, i)
            if c == "" then error("unfinished text", 0) end
            if c == '"' then i = i + 1; return table.concat(out) end
            if c == "\\" then
                local n = s:sub(i + 1, i + 1)
                if ESC[n] then out[#out + 1] = ESC[n]; i = i + 2
                elseif n == "u" and s:sub(i + 2, i + 5):match("^%x%x%x%x$") then
                    local cp = tonumber(s:sub(i + 2, i + 5), 16)
                    out[#out + 1] = cp < 128 and string.char(cp) or "?"
                    i = i + 6
                else error("bad escape", 0) end
            elseif c:byte() < 32 then error("control character", 0)
            else out[#out + 1] = c; i = i + 1 end
        end
    end
    local value
    value = function()
        ws()
        local c = s:sub(i, i)
        if c == "{" or c == "[" then
            depth = depth + 1
            if depth > 8 then error("too deep", 0) end
            local t, n, close = {}, 0, (c == "{") and "}" or "]"
            i = i + 1; ws()
            if s:sub(i, i) == close then i = i + 1; depth = depth - 1; return t end
            while true do
                if c == "{" then
                    ws()
                    if s:sub(i, i) ~= '"' then error("expected a key", 0) end
                    local k = str(); ws()
                    if s:sub(i, i) ~= ":" then error("expected :", 0) end
                    i = i + 1
                    t[k] = value()
                else
                    n = n + 1
                    if n > 1000 then error("too long", 0) end
                    t[n] = value()
                end
                ws()
                local d = s:sub(i, i); i = i + 1
                if d == close then break elseif d ~= "," then error("expected , or " .. close, 0) end
            end
            depth = depth - 1
            return t
        elseif c == '"' then return str()
        elseif s:sub(i, i + 3) == "true" then i = i + 4; return true
        elseif s:sub(i, i + 4) == "false" then i = i + 5; return false
        elseif s:sub(i, i + 3) == "null" then i = i + 4; return nil
        end
        local numText = s:match("^%-?%d+%.?%d*[eE]?[%-+]?%d*", i)
        if not numText or numText == "" then error("unexpected input", 0) end
        i = i + #numText
        local v = tonumber(numText)
        if not v then error("bad number", 0) end
        return v
    end
    local ok, result = pcall(function()
        local v = value()
        ws()
        if i <= #s then error("extra input", 0) end
        return v
    end)
    if not ok then return nil, result end
    return result
end

local function prefabJson(name, rel)
    local parts = {}
    for _, e in ipairs(rel) do
        parts[#parts + 1] = string.format('{"e":%d,"x":%.2f,"y":%.2f,"z":%.2f,"o":%.3f,"s":%.2f}', e.entry, e.dx, e.dy, e.dz, normO(e.o), e.s or 1)
    end
    return string.format('{"v":1,"name":"%s","props":[%s]}', name, table.concat(parts, ","))
end

-- Checks prefab data (JSON text or an already-read table): the props this realm allows, sane numbers,
-- size. Returns rel, skipped (entries this realm lacks), name; or nil and a plain reason.
local function parsePrefab(data)
    local t = data
    if type(data) == "string" then
        local err
        t, err = jsonDecode(data, 32768)
        if t == nil then return nil, "That isn't prefab data." end
    end
    if type(t) ~= "table" or type(t.props) ~= "table" then return nil, "That prefab has no props." end
    if #t.props < 1 or #t.props > K.PREFAB_MAX then return nil, "A prefab holds 1 to " .. K.PREFAB_MAX .. " props." end
    local rel, skipped = {}, 0
    for _, e in ipairs(t.props) do
        if type(e) ~= "table" then return nil, "That prefab's props aren't readable." end
        local id, x, y, z, o, s = tonumber(e.e), tonumber(e.x), tonumber(e.y), tonumber(e.z), tonumber(e.o or 0), tonumber(e.s or 1)
        if not (id and finite(x) and finite(y) and finite(z) and finite(o) and finite(s)) then return nil, "That prefab has bad numbers." end
        if math.abs(x) > K.PREFAB_SPAN or math.abs(y) > K.PREFAB_SPAN or math.abs(z) > K.PREFAB_SPAN then
            return nil, "A prop in that prefab is too far from its centre."
        end
        if byId[id] then
            rel[#rel + 1] = { entry = id, dx = x, dy = y, dz = z, o = normO(o), s = clampScale(s) ~= 1 and clampScale(s) or nil }
        else
            skipped = skipped + 1
        end
    end
    if #rel == 0 then return nil, "None of that prefab's props are on this realm." end
    return rel, skipped, cleanBuild(t.name)
end

prefabRel = function(f)
    local rel = parsePrefab(f.data)
    return rel
end

local function myPrefab(guid, name)
    for _, f in pairs(prefabs) do if f.owner == guid and f.name == name then return f end end
    return nil
end

-- A prefab by one of your names, or anyone's code.
local function findPrefab(guid, arg)
    local name = cleanBuild(arg)
    local f = name and myPrefab(guid, name)
    if not f and isCode(arg) then f = prefabByCode(arg) end
    return f
end

local function storePrefab(guid, ownerName, name, rel)
    local f = myPrefab(guid, name)
    if not f then
        nextPrefab = nextPrefab + 1
        f = { id = nextPrefab, owner = guid, ownerName = cleanName(ownerName), name = name }
        prefabs[f.id] = f
    end
    f.data, f.n = prefabJson(name, rel), #rel
    exec(string.format("REPLACE INTO mod_builder_prefabs (id, owner, owner_name, name, code, data, created_at) VALUES (%d, %d, '%s', '%s', %s, '%s', %d)",
        f.id, guid, f.ownerName, name, f.code and ("'" .. f.code .. "'") or "NULL", f.data, os.time()))
    return f
end

local function prefabSave(player, arg)
    local name = cleanBuild(arg)
    if not name then return say(player, "Usage: |cffffff00.build prefab save <name>|r  (letters, digits, - and _)") end
    local list = copyList(player)
    if not list then return end
    if #list > K.PREFAB_MAX then return say(player, "A prefab holds up to " .. K.PREFAB_MAX .. " props.") end
    local rel = relFrom(list)
    for _, e in ipairs(rel) do
        if math.abs(e.dx) > K.PREFAB_SPAN or math.abs(e.dy) > K.PREFAB_SPAN or math.abs(e.dz) > K.PREFAB_SPAN then
            return say(player, "That selection is too spread out for a prefab.")
        end
    end
    local guid = player:GetGUIDLow()
    if not myPrefab(guid, name) and #prefabsOf(guid) >= 50 then return say(player, "You have 50 prefabs, the most allowed.") end
    storePrefab(guid, player:GetName(), name, rel)
    say(player, string.format("Prefab '%s' saved: %s. Paste it from the spawn menu, or |cffffff00.build prefab paste %s|r.", name, plural(#rel, "prop"), name))
end

local function prefabList(player)
    local list = prefabsOf(player:GetGUIDLow())
    if #list == 0 then return say(player, "No prefabs yet: select props, then |cffffff00.build prefab save <name>|r.") end
    local names = {}
    for _, f in ipairs(list) do names[#names + 1] = string.format("%s (%d%s)", f.name, prefabCount(f), f.code and (", " .. f.code) or "") end
    say(player, "Your prefabs: " .. table.concat(names, ", "))
end

local function prefabShare(player, arg)
    local name = cleanBuild(arg)
    local guid = player:GetGUIDLow()
    local f = name and myPrefab(guid, name)
    if not f then return say(player, "You have no prefab called '" .. tostring(arg or "") .. "'.") end
    if not f.code then
        local code = newCode()
        if not code then return say(player, "Couldn't make a code just now; try again.") end
        f.code = code
        exec(string.format("UPDATE mod_builder_prefabs SET code = '%s' WHERE id = %d", code, f.id))
    end
    lastCode[guid] = f.code
    say(player, string.format("Code for prefab '%s': |cffffff00%s|r. Others paste it with |cffffff00.build prefab paste %s|r.", f.name, f.code, f.code))
end

local function prefabDelete(player, arg)
    local name = cleanBuild(arg)
    local f = name and myPrefab(player:GetGUIDLow(), name)
    if not f then return say(player, "You have no prefab called '" .. tostring(arg or "") .. "'.") end
    prefabs[f.id] = nil
    exec(string.format("DELETE FROM mod_builder_prefabs WHERE id = %d", f.id))
    say(player, "Prefab '" .. f.name .. "' deleted.")
end

local function prefabPaste(player, arg, at, deg)
    local f = findPrefab(player:GetGUIDLow(), arg)
    if not f then return say(player, "No prefab '" .. tostring(arg or "") .. "': one of yours (|cffffff00.build prefab list|r) or a 6-letter code.") end
    local rel, why = parsePrefab(f.data)
    if not rel then return say(player, why) end
    at = at or { x = player:GetX(), y = player:GetY(), z = player:GetZ() }
    placeMany(player, rel, { x = at.x, y = at.y, z = at.z, o = math.rad(deg or 0) }, f.code == tostring(arg):upper() and f.code or f.name)
end

local function prefabCommand(player, words)
    local verb = (words[2] or "list"):lower()
    if (verb == "save" or verb == "share" or verb == "code" or verb == "delete" or verb == "remove") and not rateWrite(player) then return end
    if verb == "save" then return prefabSave(player, words[3])
    elseif verb == "list" then return prefabList(player)
    elseif verb == "share" or verb == "code" then return prefabShare(player, words[3])
    elseif verb == "delete" or verb == "remove" then return prefabDelete(player, words[3])
    elseif verb == "paste" or verb == "load" then
        if not words[3] then return say(player, "Usage: |cffffff00.build prefab paste <name|code>|r") end
        return prefabPaste(player, words[3])
    elseif verb == "pasteat" then
        local at, why = exactPoint(player, words[4], words[5], words[6])
        if not words[3] or not at then return pointUsage(player, why, ".build prefab pasteat <name|code> <x> <y> <z> [degrees]") end
        local deg = tonumber(words[7] or "0") or 0
        if not finite(deg) or math.abs(deg) > 360 then return say(player, "Turn by up to 360 degrees.") end
        return prefabPaste(player, words[3], at, deg)
    end
    say(player, "Prefabs: |cffffff00.build prefab save <name>|r  |cffffff00list|r  |cffffff00paste <name|code>|r  |cffffff00share <name>|r  |cffffff00delete <name>|r")
end

------------------------------------------------------------------------------------------------
-- plots
------------------------------------------------------------------------------------------------
local plotCommand, findCharacter
do
    local function plotLabel(pl) return pl.ownerName .. "'s plot" end

    local function myPlot(player)
        local guid = player:GetGUIDLow()
        local here = plotAt(player:GetMapId(), player:GetX(), player:GetY(), player:GetZ())
        if here and (here.owner == guid or isGM(player)) then return here end
        for _, pl in pairs(plots) do if pl.owner == guid then return pl end end
        return nil
    end

    local function savePlot(pl)
        exec(string.format("REPLACE INTO mod_builder_plots (id, owner, owner_name, area, map, x, y, z, r, created_at) "
            .. "VALUES (%d, %d, '%s', '%s', %d, %.3f, %.3f, %.3f, %.2f, %d)", pl.id, pl.owner, cleanName(pl.ownerName),
            tostring(pl.area):gsub("[^%w]", ""), pl.map, pl.x, pl.y, pl.z, pl.r, os.time()))
    end

    local function dropPlot(pl)
        plots[pl.id] = nil
        exec(string.format("DELETE FROM mod_builder_plots WHERE id = %d", pl.id))
        exec(string.format("DELETE FROM mod_builder_plot_members WHERE plot = %d", pl.id))
    end

    local function plotClaim(player)
        local key, why = buildArea(player)
        if not key then return say(player, why) end
        local a = BUILD_AREAS[tonumber(key) or 0]
        if not a then return say(player, "Plots are only in build areas (|cffffff00.build where|r).") end
        local guid, map, x, y, z = player:GetGUIDLow(), player:GetMapId(), player:GetX(), player:GetY(), player:GetZ()
        local mine = 0
        for _, pl in pairs(plots) do if pl.owner == guid then mine = mine + 1 end end
        if mine >= plotsEach() then return say(player, "You have a plot already (|cffffff00.build plot|r). |cffffff00.build plot abandon|r gives it up.") end
        local r = plotSize()
        if dist2(x, y, a.x, a.y) + r > a.r then return say(player, "Too close to the edge of the build area; step further in.") end
        for _, pl in pairs(plots) do
            if pl.map == map and dist2(x, y, pl.x, pl.y) < r + pl.r then return say(player, "Too close to " .. plotLabel(pl) .. ".") end
        end
        for _, p in pairs(props) do
            if p.owner ~= guid and p.map == map and dist2(p.x, p.y, x, y) <= r and math.abs(p.z - z) <= K.PLOT_HEIGHT then
                return say(player, "Someone else's props are here; pick a clear spot.")
            end
        end
        nextPlot = nextPlot + 1
        local pl = { id = nextPlot, owner = guid, ownerName = player:GetName(), area = key, map = map, x = x, y = y, z = z, r = r, members = {} }
        plots[pl.id] = pl
        savePlot(pl)
        say(player, string.format("Plot claimed: %d yards across, around where you stand. Only you (and who you add) build here. "
            .. "Add friends with |cffffff00.build plot add <name>|r.", r * 2))
    end

    local function plotInfo(player)
        local guid = player:GetGUIDLow()
        local pl = plotAt(player:GetMapId(), player:GetX(), player:GetY(), player:GetZ())
        if not pl then
            for _, q in pairs(plots) do if q.owner == guid then pl = q end end
            if not pl then return say(player, "You're not on a plot. |cffffff00.build plot claim|r claims one where you stand (in a build area).") end
        end
        local b, v = {}, {}
        for _, m in pairs(pl.members) do if m.role == "builder" then b[#b + 1] = m.name else v[#v + 1] = m.name end end
        table.sort(b); table.sort(v)
        local n, pts = plotUsage(pl)
        say(player, string.format("%s (#%d), %d yards across, in %s. %d/%d props, %d/%d points.", plotLabel(pl), pl.id, pl.r * 2,
            areaName(pl.area), n, plotProps(), pts, plotPoints()))
        say(player, "  Builders: " .. (#b > 0 and table.concat(b, ", ") or "none") .. ".  Visitors: " .. (#v > 0 and table.concat(v, ", ") or "none") .. ".")
        local r = roleIn(pl, guid)
        say(player, "  You: " .. (r or (isGM(player) and "GM" or "not a member")) .. ".")
    end

    -- A character by name: online, or one with the builder role.
    findCharacter = function(name)
        local target = GetPlayerByName and GetPlayerByName(name)
        if target then return target:GetGUIDLow(), target:GetName(), target end
        local l = name:lower()
        for g, r in pairs(roles) do if r.lname == l then return g, r.name, nil end end
        return nil
    end

    local function plotAdd(player, words)
        local pl = myPlot(player)
        if not pl then return say(player, "You have no plot (|cffffff00.build plot claim|r).") end
        local name = cleanName(words[3])
        local role = (words[4] or "builder"):lower()
        if name == "" or (role ~= "builder" and role ~= "visitor") then return say(player, "Usage: |cffffff00.build plot add <name> [builder|visitor]|r") end
        local g, real, target = findCharacter(name)
        if not g then return say(player, name .. " isn't online.") end
        if g == pl.owner then return say(player, "That's the plot's owner.") end
        if role == "builder" and not roles[g] and not (target and isGM(target)) then
            return say(player, real .. " needs the builder role first (ask a GM). You can add them as a visitor.")
        end
        local count = 0
        for _ in pairs(pl.members) do count = count + 1 end
        if not pl.members[g] and count >= K.PLOT_MEMBERS then return say(player, "A plot has up to " .. K.PLOT_MEMBERS .. " members.") end
        pl.members[g] = { name = real, role = role }
        exec(string.format("REPLACE INTO mod_builder_plot_members (plot, guid, name, role) VALUES (%d, %d, '%s', '%s')", pl.id, g, cleanName(real), role))
        say(player, string.format("%s is a %s on %s.", real, role, plotLabel(pl)))
        if target then say(target, string.format("You're a %s on %s now.", role, plotLabel(pl))) end
    end

    local function plotKick(player, name)
        local pl = myPlot(player)
        if not pl then return say(player, "You have no plot (|cffffff00.build plot claim|r).") end
        name = cleanName(name):lower()
        if name == "" then return say(player, "Usage: |cffffff00.build plot remove <name>|r") end
        for g, m in pairs(pl.members) do
            if m.name:lower() == name then
                pl.members[g] = nil
                exec(string.format("DELETE FROM mod_builder_plot_members WHERE plot = %d AND guid = %d", pl.id, g))
                return say(player, m.name .. " is off " .. plotLabel(pl) .. ". Their props there stay (you can remove them).")
            end
        end
        say(player, name .. " isn't on your plot.")
    end

    local function plotAbandon(player)
        local guid = player:GetGUIDLow()
        for _, pl in pairs(plots) do
            if pl.owner == guid then
                dropPlot(pl)
                return say(player, "Your plot is gone; your props stay where they are.")
            end
        end
        say(player, "You have no plot.")
    end

    -- GM: list, remove <id>, transfer <id> <name>
    local function plotListGM(player)
        local list = {}
        for _, pl in pairs(plots) do list[#list + 1] = pl end
        table.sort(list, function(a, b) return a.id < b.id end)
        if #list == 0 then return say(player, "No plots yet.") end
        say(player, string.format("%s:", plural(#list, "plot")))
        for i = 1, math.min(#list, 25) do
            local pl = list[i]
            local m = 0
            for _ in pairs(pl.members) do m = m + 1 end
            local n = plotUsage(pl)
            say(player, string.format("  #%d %s, %s, %s, %s", pl.id, pl.ownerName, areaName(pl.area), plural(m, "member"), plural(n, "prop")))
        end
        if #list > 25 then say(player, "  ... and " .. (#list - 25) .. " more.") end
    end

    local function plotRemoveGM(player, id)
        local pl = plots[id]
        if not pl then return say(player, "No plot #" .. id .. " (|cffffff00.build plot list|r).") end
        dropPlot(pl)
        say(player, string.format("Plot #%d (%s) removed; its props stay.", id, pl.ownerName))
    end

    local function plotTransferGM(player, words)
        local id = tonumber(words[3] or "")
        local pl = id and plots[id]
        if not pl then return say(player, "Usage: |cffffff00.build plot transfer <plot id> <name>|r") end
        local g, real = findCharacter(cleanName(words[4]))
        if not g then return say(player, tostring(words[4] or "") .. " isn't online.") end
        pl.members[g] = nil
        exec(string.format("DELETE FROM mod_builder_plot_members WHERE plot = %d AND guid = %d", pl.id, g))
        local old = pl.ownerName
        pl.owner, pl.ownerName = g, real
        savePlot(pl)
        say(player, string.format("Plot #%d is %s's now (was %s's).", pl.id, real, old))
    end

    plotCommand = function(player, words)
        local verb = (words[2] or "info"):lower()
        if verb == "info" or verb == "here" then return plotInfo(player) end
        local gm = isGM(player)
        if verb == "list" then
            if not gm then return say(player, "Only GMs can do that.") end
            return plotListGM(player)
        elseif verb == "transfer" then
            if not gm then return say(player, "Only GMs can do that.") end
            return plotTransferGM(player, words)
        elseif (verb == "remove" or verb == "delete") and tonumber(words[3] or "") then
            if not gm then return say(player, "Only GMs can do that.") end
            return plotRemoveGM(player, tonumber(words[3]))
        end
        if not isBuilder(player) then return say(player, "You don't have the builder role yet: ask a GM.") end
        if not rateWrite(player) then return end
        if verb == "claim" then return plotClaim(player)
        elseif verb == "add" or verb == "invite" then return plotAdd(player, words)
        elseif verb == "remove" or verb == "kick" then return plotKick(player, words[3])
        elseif verb == "abandon" then return plotAbandon(player)
        end
        say(player, "Plots: |cffffff00.build plot claim|r  |cffffff00plot add <name> [builder|visitor]|r  |cffffff00plot remove <name>|r  |cffffff00plot abandon|r")
    end

end

------------------------------------------------------------------------------------------------
-- GM only
------------------------------------------------------------------------------------------------
local GM_ONLY
do
    local function grantCommand(player, arg)
        local name = cleanName(arg)
        if name == "" then return say(player, "Usage: |cffffff00.build grant <name>|r (the player must be online)") end
        local target = GetPlayerByName and GetPlayerByName(name)
        if not target then return say(player, name .. " isn't online; grant when they are.") end
        local guid = target:GetGUIDLow()
        roles[guid] = { name = target:GetName(), lname = target:GetName():lower() }
        exec(string.format("REPLACE INTO mod_builder_roles (guid, name, granted_by, granted_at) VALUES (%d, '%s', '%s', %d)",
            guid, cleanName(target:GetName()), cleanName(player:GetName()), os.time()))
        say(player, target:GetName() .. " can build now.")
        say(target, "You can build now: |cffffff00.build help|r, or /builder for the window.")
    end

    local function revokeCommand(player, arg)
        local name = cleanName(arg):lower()
        if name == "" then return say(player, "Usage: |cffffff00.build revoke <name>|r") end
        for guid, r in pairs(roles) do
            if r.lname == name then
                roles[guid] = nil
                exec(string.format("DELETE FROM mod_builder_roles WHERE guid = %d", guid))
                return say(player, r.name .. " can't build any more (their props stay; |cffffff00.build purge " .. r.name .. "|r removes them).")
            end
        end
        say(player, arg .. " has no builder role.")
    end

    local function purgeCommand(player, arg)
        local name = cleanName(arg):lower()
        if name == "" then return say(player, "Usage: |cffffff00.build purge <name>|r") end
        local owner, n = nil, 0
        for _, p in pairs(props) do
            if p.ownerName:lower() == name then
                owner = p.owner
                rec(p.id, copyProp(p), nil)
                despawn(p, player)
                props[p.id] = nil
                n = n + 1
            end
        end
        if not owner then return say(player, arg .. " has no props.") end
        exec(string.format("DELETE FROM mod_builder_props WHERE owner = %d", owner))
        for g, id in pairs(selected) do if not props[id] then selected[g] = nil end end
        say(player, string.format("Purged %s of %s.", plural(n, "prop"), arg))
    end

    -- .build trust <name> <new|builder|trusted|master|auto>
    local function trustCommand(player, arg, words)
        local name, want = cleanName(arg), (words[3] or ""):lower()
        local t
        for i, tier in ipairs(TIERS) do if tier.key == want then t = i end end
        if name == "" or not (t or want == "auto") then
            return say(player, "Usage: |cffffff00.build trust <name> <new|builder|trusted|master|auto>|r")
        end
        local g, real, target = findCharacter(name)
        if not g then return say(player, name .. " isn't online.") end
        trust[g] = t
        if t then
            exec(string.format("REPLACE INTO mod_builder_trust (guid, name, tier, set_by, set_at) VALUES (%d, '%s', %d, '%s', %d)",
                g, cleanName(real), t, cleanName(player:GetName()), os.time()))
        else
            exec(string.format("DELETE FROM mod_builder_trust WHERE guid = %d", g))
        end
        local b = target and budgetOf(target)
        say(player, string.format("%s: %s%s.", real, t and TIERS[t].key or "automatic tier",
            b and string.format(" (%d props, %d points)", b.props, b.points) or ""))
        if target and b then say(target, string.format("Your build limits are now %d props and %d points.", b.props, b.points)) end
    end

    local function touches(op, map, x, y, range)
        for _, r in ipairs(op.rows) do
            for _, s in ipairs({ r.before or false, r.after or false }) do
                if s and s.map == map and dist2(s.x, s.y, x, y) <= range then return true end
            end
        end
        return false
    end

    -- .build oplog <name> [n]: a player's last ops near you
    local function oplogCommand(player, arg, words)
        local name = cleanName(arg):lower()
        if name == "" then return say(player, "Usage: |cffffff00.build oplog <name> [count]|r") end
        local want = math.max(1, math.min(30, math.floor(tonumber(words[3] or "") or 10)))
        local lines = {}
        for i = #oplog, 1, -1 do
            local op = oplog[i]
            if op.name:lower() == name then
                lines[#lines + 1] = string.format("  %s  %s, %s", os.date("%m-%d %H:%M", op.at), op.op, plural(#op.rows, "prop"))
                if #lines >= want then break end
            end
        end
        if #lines == 0 then return say(player, "No build changes from " .. arg .. " in the log.") end
        say(player, string.format("Last %d changes by %s (newest first):", #lines, arg))
        for _, l in ipairs(lines) do say(player, l) end
    end

    -- Puts one logged change back the way it was before.
    local function revert(row, player)
        local p = props[row.id]
        local b = row.before
        if not b then
            if p then removeProp(p, player) end
        elseif row.after then
            if p then
                placeProp(p, b.x, b.y, b.z, b.o, player, b.s or 1)
            end
        elseif not p then
            addProp(b.owner, b.ownerName, b.area, b.entry, b.map, b.x, b.y, b.z, b.o, row.id, b.s)
        end
    end

    -- .build rollback <name> [ops] [yards]: undoes that player's last ops (10, up to 200) that touched props
    -- within range of you (60 yards, up to 300).
    local function rollbackCommand(player, arg, words)
        local name = cleanName(arg):lower()
        if name == "" then return say(player, "Usage: |cffffff00.build rollback <name> [ops] [yards]|r") end
        local n = math.max(1, math.min(200, math.floor(tonumber(words[3] or "") or 10)))
        local range = math.floor(math.max(5, math.min(300, tonumber(words[4] or "") or 60)))
        local map, x, y = player:GetMapId(), player:GetX(), player:GetY()
        local done, rows, ids, victim = 0, 0, {}, nil
        for i = #oplog, 1, -1 do
            if done >= n then break end
            local op = oplog[i]
            if op.name:lower() == name and op.op ~= "rollback" and touches(op, map, x, y, range) then
                for j = #op.rows, 1, -1 do revert(op.rows[j], player); rows = rows + 1 end
                ids[#ids + 1] = op.id
                victim = op.guid
                table.remove(oplog, i)
                done = done + 1
            end
        end
        if done == 0 then return say(player, string.format("No changes by %s within %d yards of you.", arg, range)) end
        exec("UPDATE mod_builder_oplog SET undone = 1 WHERE op_id IN (" .. table.concat(ids, ",") .. ")")
        if victim then undo[victim] = nil; group[victim] = nil; selected[victim] = nil end
        for g, id in pairs(selected) do if not props[id] then selected[g] = nil end end
        say(player, string.format("Rolled back %s by %s (%s).", plural(done, "change"), arg, plural(rows, "prop change")))
    end

    GM_ONLY = { grant = grantCommand, revoke = revokeCommand, purge = purgeCommand, trust = trustCommand,
        rollback = rollbackCommand, oplog = oplogCommand }
end

local function showHelp(player)
    local cap = budgetOf(player)
    say(player, "Builder: place props in build areas and share builds as codes. /builder opens the window.")
    say(player, "  |cffffff00.build catalog [word]|r  |cffffff00.build spawn <id|name>|r  |cffffff00.build near|r  |cffffff00.build select <n>|r")
    say(player, "  |cffffff00.build move x|y|z <yards>|r  |cffffff00.build turn <deg>|r  |cffffff00.build undo|r  |cffffff00.build delete|r  |cffffff00.build clear|r")
    say(player, "  Edit mode (F7 in the browser client): click a prop to select it, Shift-click to add more, G to carry, Q for the spawn menu.")
    say(player, "  |cffffff00.build selall|r  |cffffff00.build copy|r  |cffffff00.build paste|r  |cffffff00.build prefab save <name>|r  |cffffff00.build prefab list|r")
    say(player, "  |cffffff00.build save <name>|r  |cffffff00.build load <name|code>|r  |cffffff00.build share <name>|r  |cffffff00.build saved|r  |cffffff00.build where|r")
    say(player, "  |cffffff00.build plot claim|r  |cffffff00.build plot add <name>|r  |cffffff00.build plot|r: your own plot to build on with friends.")
    say(player, string.format("  Limits: %d props per player, %d per area, one spawn a second.", perPlayer(), perArea()))
    say(player, string.format("  You: %d props and %d build points (%s).", cap.props, cap.points, cap.tier))
    if isGM(player) then
        say(player, "  GM: |cffffff00.build grant|r / |cffffff00revoke|r / |cffffff00purge <name>|r  |cffffff00trust <name> <tier>|r  "
            .. "|cffffff00plot list|r / |cffffff00remove <id>|r / |cffffff00transfer <id> <name>|r  |cffffff00oplog <name>|r  |cffffff00rollback <name> [ops] [yards]|r")
    end
    if not isBuilder(player) then say(player, "  You don't have the builder role yet: ask a GM.") end
end

local OPEN = { help = true, where = true, catalog = true, saved = true, plot = true, plots = true }

local function dispatch(player, sub, words)
    if sub == "catalog" or sub == "props" then catalogCommand(player, words[2])
    elseif sub == "where" or sub == "areas" then whereCommand(player)
    elseif sub == "saved" or sub == "builds" then savedCommand(player)
    elseif sub == "plot" or sub == "plots" then plotCommand(player, words)
    elseif sub == "spawn" or sub == "place" then spawnCommand(player, table.concat(words, " ", 2))
    elseif sub == "spawnat" then
        local at, why = exactPoint(player, words[3], words[4], words[5])
        if not at then return pointUsage(player, why, ".build spawnat <id> <x> <y> <z>") end
        spawnCommand(player, words[2], at)
    elseif sub == "placeat" then placeAtCommand(player, words)
    elseif sub == "pick" then pickCommand(player, words[2], (words[3] or ""):lower())
    elseif sub == "selbox" then selboxCommand(player, words)
    elseif sub == "selall" then selallCommand(player, words[2])
    elseif sub == "selclear" or sub == "deselect" or sub == "none" then selectOne(player:GetGUIDLow(), nil); say(player, "Nothing selected.")
    elseif sub == "dup" or sub == "duplicate" then dupCommand(player)
    elseif sub == "copy" then copyCommand(player)
    elseif sub == "pasteat" then pasteAtCommand(player, words)
    elseif sub == "near" or sub == "list" then nearCommand(player)
    elseif sub == "select" or sub == "sel" then selectCommand(player, words[2])
    elseif sub == "move" then moveCommand(player, (words[2] or ""):lower(), words[3])
    elseif sub == "turn" or sub == "rotate" then turnCommand(player, words[2])
    elseif sub == "setpos" then setposCommand(player, words)
    elseif sub == "setturn" then setturnCommand(player, words[2])
    elseif sub == "setscale" or sub == "scale" then setscaleCommand(player, words[2])
    elseif sub == "undo" then undoCommand(player)
    elseif sub == "delete" or sub == "remove" then deleteCommand(player)
    elseif sub == "clear" then clearCommand(player)
    elseif sub == "save" then saveCommand(player, words[2])
    elseif sub == "paste" and not words[2] then pasteClip(player, { x = player:GetX(), y = player:GetY(), z = player:GetZ() }, 0)
    elseif sub == "load" or sub == "paste" then loadCommand(player, words[2])
    elseif sub == "share" or sub == "code" then shareCommand(player, words[2])
    elseif sub == "prefab" then prefabCommand(player, words)
    elseif sub == "prefabs" then prefabList(player)
    else showHelp(player) end
end

-- Runs ".build <text>" for the player (the dot command and the window both come here). Every prop change
-- the command makes goes into the op log as one op.
local function run(player, text)
    local words = {}
    for w in tostring(text or ""):gmatch("%S+") do words[#words + 1] = w end
    local sub = (words[1] or "help"):lower()
    if sub == "help" or sub == "?" then return showHelp(player) end
    if not onSwitch() then return say(player, "The Builder is off on this realm.") end
    local prev = beginOp(player, sub)
    local ok, err = pcall(function()
        if GM_ONLY[sub] then
            if not isGM(player) then return say(player, "Only GMs can do that.") end
            return GM_ONLY[sub](player, words[2], words)
        end
        if not OPEN[sub] and not isBuilder(player) then return say(player, "You don't have the builder role yet: ask a GM.") end
        sync(player)
        dispatch(player, sub, words)
    end)
    endOp(prev)
    if not ok then error(err, 0) end
end

local function onCommand(event, player, command)
    if not player then return end
    local text = (command or ""):gsub("^[%.!]", "")
    local verb, rest = text:match("^(%S+)%s*(.*)$")
    verb = (verb or ""):lower()
    if verb ~= "build" and verb ~= "builder" then return end
    run(player, rest)
    sendState(player)
    if rest:lower():find("^prefab") then sendPrefabs(player) end
    return false
end

if OVMod then
    OVMod.On(MOD, "cmd", function(player, data)
        if #data > 120 then return end
        run(player, data)
        sendState(player)
        if data:lower():find("^prefab") then sendPrefabs(player) end
    end)
    OVMod.On(MOD, "catalog", function(player)
        OVMod.Send(player, MOD, "catalog", catalogText())
        sendState(player)
        sendPrefabs(player)
    end)
end

local function onArrive(event, player) if player then sync(player, true) end end

local function onLogout(event, player)
    if not player then return end
    local guid = player:GetGUIDLow()
    selected[guid], nearList[guid], undo[guid], lastSpawn[guid], lastLoad[guid], moves[guid], lastSync[guid] =
        nil, nil, nil, nil, nil, nil, nil
    group[guid], clip[guid], lastCode[guid], writes[guid] = nil, nil, nil, nil
end

-- Every 15 s: props near any player who is in or close to a build area (or anywhere, if a prop is near).
local function syncAll()
    if not GetPlayersInWorld then return end
    local ok, players = pcall(GetPlayersInWorld)
    if not ok or type(players) ~= "table" then return end
    for _, pl in ipairs(players) do pcall(sync, pl, true) end
end

RegisterPlayerEvent(3, onArrive)    -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, onLogout)    -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(27, onArrive)   -- PLAYER_EVENT_ON_UPDATE_ZONE
RegisterPlayerEvent(28, onArrive)   -- PLAYER_EVENT_ON_MAP_CHANGE
RegisterPlayerEvent(42, onCommand)  -- PLAYER_EVENT_ON_COMMAND
if CreateLuaEvent then CreateLuaEvent(syncAll, K.SYNC_EVERY_MS, 0) end

------------------------------------------------------------------------------------------------
-- OVBuild: for other realm scripts (ov_workshop.lua publishes prefabs as Workshop items)
------------------------------------------------------------------------------------------------
OVBuild = rawget(_G, "OVBuild") or {}
OVBuild.PREFAB_MAX = K.PREFAB_MAX

local function prefabInfo(f)
    return { id = f.id, name = f.name, owner = f.owner, ownerName = f.ownerName, code = f.code, count = prefabCount(f),
        points = (function() local n = 0; for _, e in ipairs(prefabRel(f) or {}) do n = n + costOf(e.entry) end; return n end)() }
end

-- OVBuild.ExportPrefab(id or code) -> JSON text, info { id, name, owner, ownerName, code, count, points }
--   or nil, reason. The JSON holds only catalog entry ids and numbers (it references the realm's props by id).
function OVBuild.ExportPrefab(id)
    local f = prefabs[tonumber(id) or -1] or (isCode(tostring(id or "")) and prefabByCode(id)) or nil
    if not f then return nil, "No such prefab." end
    local rel, why = parsePrefab(f.data)
    if not rel then return nil, why end
    return prefabJson(f.name, rel), prefabInfo(f)
end

-- OVBuild.ImportPrefab(data, player, x, y, z, o) -> true, prop ids  or  nil, reason
--   Pastes prefab data (JSON text or a table of that shape) for player at x, y, z (default: where they stand),
--   turned by o radians (default 0), with every check a paste has: the builder role, the build area and plots,
--   budgets, the allowlist, the paste rate. One undo entry; one op in the op log.
function OVBuild.ImportPrefab(data, player, x, y, z, o)
    if not player then return nil, "No player." end
    if not onSwitch() then return nil, "The Builder is off on this realm." end
    if not isBuilder(player) then return nil, "You don't have the builder role yet: ask a GM." end
    local rel, why = parsePrefab(data)
    if not rel then say(player, why); return nil, why end
    local at = { x = player:GetX(), y = player:GetY(), z = player:GetZ() }
    if x ~= nil or y ~= nil or z ~= nil then
        local p, w = exactPoint(player, x, y, z)
        if not p then
            local reason = w == "too far" and "That spot is too far from your character." or "Bad point."
            say(player, reason); return nil, reason
        end
        at = p
    end
    o = tonumber(o or 0) or 0
    if not finite(o) then o = 0 end
    local prev = beginOp(player, "import")
    local ok, ids = pcall(placeMany, player, rel, { x = at.x, y = at.y, z = at.z, o = o }, "prefab")
    endOp(prev)
    sendState(player)
    if not ok then return nil, tostring(ids) end
    if not ids then return nil, "It doesn't fit here." end
    return true, ids
end

-- OVBuild.SavePrefab(player, name, data) -> prefab id  or  nil, reason: keeps prefab data in the player's list.
function OVBuild.SavePrefab(player, name, data)
    if not player then return nil, "No player." end
    local rel, why, own = parsePrefab(data)
    if not rel then return nil, why end
    name = cleanBuild(name) or own
    if not name then return nil, "Bad name." end
    local guid = player:GetGUIDLow()
    if not myPrefab(guid, name) and #prefabsOf(guid) >= 50 then return nil, "You have 50 prefabs, the most allowed." end
    return storePrefab(guid, player:GetName(), name, rel).id
end

-- OVBuild.ListPrefabs(guid) -> { info, ... } for that character, by name.
function OVBuild.ListPrefabs(guid)
    local out = {}
    for _, f in ipairs(prefabsOf(tonumber(guid) or -1)) do out[#out + 1] = prefabInfo(f) end
    return out
end

-- OVBuild.ParsePrefab(data) -> count, skipped  or  nil, reason (checks data without placing anything).
function OVBuild.ParsePrefab(data)
    local rel, skipped = parsePrefab(data)
    if not rel then return nil, skipped end
    return #rel, skipped
end

-- for stream/tests/test_ov_build.lua (read only)
OV_BUILD_TEST = { props = props, live = live, roles = roles, selected = selected, undo = undo, builds = builds,
    byCode = byCode, CATALOG = function() return CATALOG end, BUILD_AREAS = BUILD_AREAS, run = run, sync = sync,
    syncAll = syncAll, encode = encode, decode = decode, catalogText = catalogText, areaAt = areaAt,
    group = group, clip = clip, plots = plots, prefabs = prefabs, oplog = oplog, trust = trust,
    jsonDecode = jsonDecode, budgetOf = budgetOf, plotAt = plotAt, costOf = costOf, TIERS = TIERS }
