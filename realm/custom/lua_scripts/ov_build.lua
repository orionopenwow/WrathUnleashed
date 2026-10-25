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
--   GM only: .build grant <name> | revoke <name> | purge <name>
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
--   OV_BUILD_PER_PLAYER   props one character may have                    default 50
--   OV_BUILD_PER_AREA     props in one build area                         default 500
-- Rate: one spawn a second, one load every 5 s, five moves or turns a second.
-- The in-game Builder window (WrathUnleashedUI/Builder.lua, /builder) talks to this over the OVMOD channel
-- (ov_modapi.lua), mod "wubuild":
--   client -> server   cmd       <the text after .build>         runs it exactly as the dot command
--                      catalog                                   asks for the catalog
--   server -> client   catalog   id,key,category,name;...        the props that exist on this realm
--                      state     sel=<id>,<entry>,<name>;mine=<n>/<cap>;area=<name>;code=<code>
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
}
local CATEGORIES = { "seating", "tables", "barrels", "crates", "lights", "banners", "tents", "fires", "fences" }

local NEAR_RANGE = 40         -- .build near
local SYNC_RANGE = 150        -- props put back around a player
local SYNC_EVERY_MS = 15000
local MAX_STEP = 10           -- yards per .build move
local MAX_TURN = 180
local UNDO_DEPTH = 30
local LOAD_COOLDOWN = 5
local MOVES_PER_SECOND = 5
local BUILD_NAME_MAX = 24
local CODE_LEN = 6
local CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"   -- no 0/O, 1/I

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

local function onSwitch()  return flag("OV_BUILD", true) end
local function anywhere()  return flag("OV_BUILD_ANYWHERE", false) end
local function perPlayer() return num("OV_BUILD_PER_PLAYER", 50, 0, 1000) end
local function perArea()   return num("OV_BUILD_PER_AREA", 500, 0, 10000) end

local function say(player, text) player:SendBroadcastMessage(TAG .. text) end

local function try(obj, method, ...)
    if not obj then return nil end
    local ok, fn = pcall(function() return obj[method] end)
    if not ok or type(fn) ~= "function" then return nil end
    local ok2, a, b = pcall(fn, obj, ...)
    if ok2 then return a, b end
    return nil
end

local function isGM(player) return (tonumber(try(player, "GetGMRank")) or 0) > 0 end

local function inInstance(player)
    if try(player, "InBattleground") or try(player, "InArena") then return true end
    local map = try(player, "GetMap")
    return map ~= nil and (try(map, "IsBattlegroundOrArena") or try(map, "IsDungeon") or try(map, "IsRaid")) == true
end

local function plural(n, word) return n .. " " .. word .. (n == 1 and "" or "s") end
local function dist2(ax, ay, bx, by) local dx, dy = ax - bx, ay - by; return math.sqrt(dx * dx + dy * dy) end

local function normO(o)
    local tau = 2 * math.pi
    o = o % tau
    if o < 0 then o = o + tau end
    return o
end

-- Character names and build names only ever reach SQL through these (letters, digits, _ and -).
local function cleanName(s) return (tostring(s or ""):gsub("[^%w]", ""):sub(1, 12)) end
local function cleanBuild(s)
    s = tostring(s or ""):lower()
    if #s < 1 or #s > BUILD_NAME_MAX or not s:match("^[%w_%-]+$") then return nil end
    return s
end
local function isCode(s) return type(s) == "string" and #s == CODE_LEN and s:upper():match("^[A-HJ-NP-Z2-9]+$") ~= nil end

local function query(sql)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, sql)
    if ok then return q end
    return nil
end
local function exec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end

------------------------------------------------------------------------------------------------
-- tables (characters database)
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

------------------------------------------------------------------------------------------------
-- catalog lookups
------------------------------------------------------------------------------------------------
local byId, byKey = {}, {}
local function index()
    for k in pairs(byId) do byId[k] = nil end
    for k in pairs(byKey) do byKey[k] = nil end
    for _, c in ipairs(CATALOG) do byId[c.id] = c; byKey[c.key] = c end
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
local roles = {}       -- [guid] = name (lower case kept in .lname)
local props = {}       -- [id] = { id, owner, ownerName, area, entry, map, x, y, z, o }
local live = {}        -- [id] = object guid of the spawned prop
local selected = {}    -- [guid] = prop id
local nearList = {}    -- [guid] = { ids from the last .build near }
local undo = {}        -- [guid] = { actions }
local lastSpawn, lastLoad, moves = {}, {}, {}
local builds = {}      -- cache: [owner] = { [name] = { props = text, code = code } }
local byCode = {}      -- cache: [code] = { owner, name, props }
local lastCode = {}    -- [guid] = the code .build share printed last (for the window)
local nextId = 0

local function loadState()
    local q = query("SELECT guid, name FROM mod_builder_roles")
    if q then repeat roles[q:GetUInt32(0)] = { name = q:GetString(1), lname = q:GetString(1):lower() } until not q:NextRow() end
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
end
loadState()

local function isBuilder(player)
    return isGM(player) or roles[player:GetGUIDLow()] ~= nil
end

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

local function countOwner(guid)
    local n = 0
    for _, p in pairs(props) do if p.owner == guid then n = n + 1 end end
    return n
end
local function countArea(key)
    local n = 0
    for _, p in pairs(props) do if p.area == key then n = n + 1 end end
    return n
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
        if p.map == map and dist2(p.x, p.y, x, y) <= SYNC_RANGE and not liveObject(p, player) then
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

local function addProp(owner, ownerName, area, entry, map, x, y, z, o, id)
    if not id then nextId = nextId + 1; id = nextId end
    local p = { id = id, owner = owner, ownerName = ownerName, area = area, entry = entry, map = map,
        x = x, y = y, z = z, o = normO(o) }
    props[id] = p
    exec(sqlProp(p))
    spawn(p)
    return p
end

local function removeProp(p, player)
    despawn(p, player)
    props[p.id] = nil
    exec(string.format("DELETE FROM mod_builder_props WHERE id = %d", p.id))
end

local function placeProp(p, x, y, z, o, player)
    despawn(p, player)
    p.x, p.y, p.z, p.o = x, y, z, normO(o)
    exec(string.format("UPDATE mod_builder_props SET x = %.3f, y = %.3f, z = %.3f, o = %.4f WHERE id = %d", p.x, p.y, p.z, p.o, p.id))
    spawn(p)
end

local function pushUndo(guid, action)
    local stack = undo[guid] or {}
    undo[guid] = stack
    stack[#stack + 1] = action
    if #stack > UNDO_DEPTH then table.remove(stack, 1) end
end

local function copyProp(p)
    return { id = p.id, owner = p.owner, ownerName = p.ownerName, area = p.area, entry = p.entry, map = p.map,
        x = p.x, y = p.y, z = p.z, o = p.o }
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

local function catalogText()
    local out = {}
    for _, c in ipairs(CATALOG) do out[#out + 1] = c.id .. "," .. c.key .. "," .. c.cat .. "," .. c.name:gsub("[,;]", "") end
    return table.concat(out, ";")
end

local function sendState(player)
    if not OVMod then return end
    local guid = player:GetGUIDLow()
    local p = props[selected[guid] or 0]
    local sel = "-"
    if p then sel = p.id .. "," .. p.entry .. "," .. ((byId[p.entry] and byId[p.entry].name) or ("#" .. p.entry)):gsub("[,;=]", "") end
    local key = buildArea(player)
    local data = string.format("sel=%s;mine=%d/%d;area=%s;code=%s", sel, countOwner(guid), perPlayer(),
        (areaName(key)):gsub("[;=]", ""), lastCode[guid] or "-")
    pcall(OVMod.Send, player, MOD, "state", data)
end

------------------------------------------------------------------------------------------------
-- commands
------------------------------------------------------------------------------------------------
local function selection(player)
    local guid = player:GetGUIDLow()
    local p = props[selected[guid] or 0]
    if not p then say(player, "Nothing selected: |cffffff00.build spawn|r a prop, or |cffffff00.build near|r then |cffffff00.build select <n>|r."); return nil end
    if p.owner ~= guid and not isGM(player) then say(player, "That prop isn't yours."); return nil end
    if p.map ~= player:GetMapId() or dist2(p.x, p.y, player:GetX(), player:GetY()) > SYNC_RANGE then
        say(player, "Your selection is too far away."); return nil
    end
    return p
end

local function propName(p) return (byId[p.entry] and byId[p.entry].name) or ("prop " .. p.entry) end

local function spawnCommand(player, word)
    local c, count = findProp(word)
    if not c then
        if count and count > 1 then return say(player, "More than one prop matches '" .. word .. "'; use its id (|cffffff00.build catalog " .. word .. "|r).") end
        return say(player, "No prop called '" .. tostring(word or "") .. "' (|cffffff00.build catalog|r lists them).")
    end
    local key, why = buildArea(player)
    if not key then return say(player, why) end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastSpawn[guid] == now then return say(player, "One prop a second.") end
    if countOwner(guid) >= perPlayer() then return say(player, string.format("You have %s, the most allowed (|cffffff00.build delete|r or |cffffff00.build clear|r).", plural(countOwner(guid), "prop"))) end
    if countArea(key) >= perArea() then return say(player, string.format("This area is full (%d props).", perArea())) end
    lastSpawn[guid] = now
    local p = addProp(guid, player:GetName(), key, c.id, player:GetMapId(), player:GetX(), player:GetY(), player:GetZ(), player:GetO())
    if not live[p.id] then
        props[p.id] = nil
        exec(string.format("DELETE FROM mod_builder_props WHERE id = %d", p.id))
        return say(player, "The realm couldn't place that prop here.")
    end
    selected[guid] = p.id
    pushUndo(guid, { kind = "spawn", id = p.id })
    say(player, string.format("%s placed (%d/%d). Nudge it with |cffffff00.build move|r and |cffffff00.build turn|r.", c.name, countOwner(guid), perPlayer()))
end

local function nearCommand(player)
    local guid, map, x, y = player:GetGUIDLow(), player:GetMapId(), player:GetX(), player:GetY()
    local gm = isGM(player)
    local list = {}
    for _, p in pairs(props) do
        if p.map == map and (p.owner == guid or gm) then
            local d = dist2(p.x, p.y, x, y)
            if d <= NEAR_RANGE then list[#list + 1] = { p = p, d = d } end
        end
    end
    table.sort(list, function(a, b) if a.d ~= b.d then return a.d < b.d end return a.p.id < b.p.id end)
    nearList[guid] = {}
    if #list == 0 then return say(player, "None of your props within " .. NEAR_RANGE .. " yards.") end
    say(player, string.format("Props within %d yards (|cffffff00.build select <n>|r):", NEAR_RANGE))
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
    selected[guid] = id
    say(player, propName(props[id]) .. " selected.")
end

local function rateMove(guid)
    local now = os.time()
    local m = moves[guid]
    if not m or m.sec ~= now then moves[guid] = { sec = now, n = 1 }; return true end
    m.n = m.n + 1
    return m.n <= MOVES_PER_SECOND
end

local function moveCommand(player, axis, amount)
    local d = tonumber(amount or "")
    if not (axis == "x" or axis == "y" or axis == "z") or not d then return say(player, "Usage: |cffffff00.build move x|y|z <yards>|r  (e.g. .build move z 0.5)") end
    if d ~= d or math.abs(d) > MAX_STEP then return say(player, "Up to " .. MAX_STEP .. " yards a step.") end
    local p = selection(player)
    if not p then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    local x, y, z = p.x, p.y, p.z
    if axis == "x" then x = x + d elseif axis == "y" then y = y + d else z = z + d end
    if not insideArea(p.area, p.map, x, y, z) then return say(player, "That would take it out of the build area.") end
    pushUndo(player:GetGUIDLow(), { kind = "place", id = p.id, x = p.x, y = p.y, z = p.z, o = p.o })
    placeProp(p, x, y, z, p.o, player)
    say(player, string.format("%s moved %+.2f on %s.", propName(p), d, axis))
end

local function turnCommand(player, amount)
    local deg = tonumber(amount or "")
    if not deg or deg ~= deg then return say(player, "Usage: |cffffff00.build turn <degrees>|r  (e.g. .build turn 15, .build turn -90)") end
    if math.abs(deg) > MAX_TURN then return say(player, "Up to " .. MAX_TURN .. " degrees a turn.") end
    local p = selection(player)
    if not p then return end
    if not rateMove(player:GetGUIDLow()) then return say(player, "Slow down a little.") end
    pushUndo(player:GetGUIDLow(), { kind = "place", id = p.id, x = p.x, y = p.y, z = p.z, o = p.o })
    placeProp(p, p.x, p.y, p.z, p.o + math.rad(deg), player)
    say(player, string.format("%s turned %+d degrees.", propName(p), math.floor(deg + 0.5)))
end

local function deleteCommand(player)
    local p = selection(player)
    if not p then return end
    local guid = player:GetGUIDLow()
    pushUndo(guid, { kind = "restore", list = { copyProp(p) } })
    removeProp(p, player)
    selected[guid] = nil
    say(player, propName(p) .. " removed (|cffffff00.build undo|r brings it back).")
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
    selected[guid] = nil
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
        if selected[guid] == a.id then selected[guid] = nil end
        return say(player, "Undone: the prop you placed is gone.")
    elseif a.kind == "place" then
        local p = props[a.id]
        if not p then return say(player, "That prop is gone already.") end
        placeProp(p, a.x, a.y, a.z, a.o, player)
        selected[guid] = p.id
        return say(player, "Undone: " .. propName(p) .. " is back where it was.")
    elseif a.kind == "restore" then
        local room = perPlayer() - countOwner(guid)
        local n = 0
        for _, c in ipairs(a.list) do
            if n >= room then break end
            if not props[c.id] then
                addProp(c.owner, c.ownerName, c.area, c.entry, c.map, c.x, c.y, c.z, c.o, c.id)
                n = n + 1
            end
        end
        if #a.list == 1 and props[a.list[1].id] then selected[guid] = a.list[1].id end
        return say(player, "Undone: " .. plural(n, "prop") .. " back.")
    elseif a.kind == "load" then
        local n = 0
        for _, id in ipairs(a.ids) do
            if props[id] then removeProp(props[id], player); n = n + 1 end
        end
        selected[guid] = nil
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

local function saveCommand(player, arg)
    local name = cleanBuild(arg)
    if not name then return say(player, "Usage: |cffffff00.build save <name>|r  (letters, digits, - and _, up to " .. BUILD_NAME_MAX .. ")") end
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
        for i = 1, CODE_LEN do
            local k = math.random(#CODE_ALPHABET)
            t[i] = CODE_ALPHABET:sub(k, k)
        end
        local code = table.concat(t)
        if not getByCode(code) then return code end
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

local function loadCommand(player, arg)
    if not arg or arg == "" then return say(player, "Usage: |cffffff00.build load <name|code>|r") end
    local key, why = buildArea(player)
    if not key then return say(player, why) end
    local guid, now = player:GetGUIDLow(), os.time()
    local name = cleanBuild(arg)
    local b = name and getBuild(guid, name)
    local label = name
    if not b and isCode(arg) then
        local c = getByCode(arg)
        if c then b = c; label = arg:upper() end
    end
    if not b then return say(player, "No build '" .. tostring(arg) .. "': one of your names (|cffffff00.build saved|r) or a 6-letter code.") end
    if lastLoad[guid] and now - lastLoad[guid] < LOAD_COOLDOWN then return say(player, "One paste every " .. LOAD_COOLDOWN .. " seconds.") end
    local list = decode(b.props)
    local placeable, skipped = {}, 0
    local ax, ay, az, ao, map = player:GetX(), player:GetY(), player:GetZ(), player:GetO(), player:GetMapId()
    local c, s = math.cos(ao), math.sin(ao)
    for _, e in ipairs(list) do
        if byId[e.entry] then
            local x, y, z = ax + e.dx * c - e.dy * s, ay + e.dx * s + e.dy * c, az + e.dz
            if insideArea(key, map, x, y, z) then placeable[#placeable + 1] = { e = e, x = x, y = y, z = z } else skipped = skipped + 1 end
        else
            skipped = skipped + 1
        end
    end
    if #placeable == 0 then return say(player, "None of that build fits here (step further into the area).") end
    if countOwner(guid) + #placeable > perPlayer() then
        return say(player, string.format("That build has %s; you have room for %d (|cffffff00.build clear|r makes room).",
            plural(#placeable, "prop"), perPlayer() - countOwner(guid)))
    end
    if countArea(key) + #placeable > perArea() then return say(player, "This area hasn't room for that build.") end
    lastLoad[guid] = now
    local ids = {}
    for _, pl in ipairs(placeable) do
        local p = addProp(guid, player:GetName(), key, pl.e.entry, map, pl.x, pl.y, pl.z, ao + pl.e.o)
        ids[#ids + 1] = p.id
    end
    pushUndo(guid, { kind = "load", ids = ids })
    say(player, string.format("Pasted '%s': %s%s.", label, plural(#ids, "prop"),
        skipped > 0 and string.format(" (%d didn't fit here)", skipped) or ""))
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

-- GM only -------------------------------------------------------------------------------------
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

local function showHelp(player)
    say(player, "Builder: place props in build areas and share builds as codes. /builder opens the window.")
    say(player, "  |cffffff00.build catalog [word]|r  |cffffff00.build spawn <id|name>|r  |cffffff00.build near|r  |cffffff00.build select <n>|r")
    say(player, "  |cffffff00.build move x|y|z <yards>|r  |cffffff00.build turn <deg>|r  |cffffff00.build undo|r  |cffffff00.build delete|r  |cffffff00.build clear|r")
    say(player, "  |cffffff00.build save <name>|r  |cffffff00.build load <name|code>|r  |cffffff00.build share <name>|r  |cffffff00.build saved|r  |cffffff00.build where|r")
    say(player, string.format("  Limits: %d props per player, %d per area, one spawn a second.", perPlayer(), perArea()))
    if isGM(player) then say(player, "  GM: |cffffff00.build grant <name>|r  |cffffff00.build revoke <name>|r  |cffffff00.build purge <name>|r") end
    if not isBuilder(player) then say(player, "  You don't have the builder role yet: ask a GM.") end
end

local GM_ONLY = { grant = grantCommand, revoke = revokeCommand, purge = purgeCommand }
local OPEN = { help = true, where = true, catalog = true, saved = true }

-- Runs ".build <text>" for the player (the dot command and the window both come here).
local function run(player, text)
    local words = {}
    for w in tostring(text or ""):gmatch("%S+") do words[#words + 1] = w end
    local sub = (words[1] or "help"):lower()
    if sub == "help" or sub == "?" then return showHelp(player) end
    if not onSwitch() then return say(player, "The Builder is off on this realm.") end
    if GM_ONLY[sub] then
        if not isGM(player) then return say(player, "Only GMs can do that.") end
        return GM_ONLY[sub](player, words[2])
    end
    if not OPEN[sub] and not isBuilder(player) then return say(player, "You don't have the builder role yet: ask a GM.") end
    if sub ~= "help" then sync(player) end
    if sub == "catalog" or sub == "props" then catalogCommand(player, words[2])
    elseif sub == "where" or sub == "areas" then whereCommand(player)
    elseif sub == "saved" or sub == "builds" then savedCommand(player)
    elseif sub == "spawn" or sub == "place" then spawnCommand(player, table.concat(words, " ", 2))
    elseif sub == "near" or sub == "list" then nearCommand(player)
    elseif sub == "select" or sub == "sel" then selectCommand(player, words[2])
    elseif sub == "move" then moveCommand(player, (words[2] or ""):lower(), words[3])
    elseif sub == "turn" or sub == "rotate" then turnCommand(player, words[2])
    elseif sub == "undo" then undoCommand(player)
    elseif sub == "delete" or sub == "remove" then deleteCommand(player)
    elseif sub == "clear" then clearCommand(player)
    elseif sub == "save" then saveCommand(player, words[2])
    elseif sub == "load" or sub == "paste" then loadCommand(player, words[2])
    elseif sub == "share" or sub == "code" then shareCommand(player, words[2])
    else showHelp(player) end
end

local function onCommand(event, player, command)
    if not player then return end
    local text = (command or ""):gsub("^[%.!]", "")
    local verb, rest = text:match("^(%S+)%s*(.*)$")
    verb = (verb or ""):lower()
    if verb ~= "build" and verb ~= "builder" then return end
    run(player, rest)
    sendState(player)
    return false
end

if OVMod then
    OVMod.On(MOD, "cmd", function(player, data)
        if #data > 120 then return end
        run(player, data)
        sendState(player)
    end)
    OVMod.On(MOD, "catalog", function(player)
        OVMod.Send(player, MOD, "catalog", catalogText())
        sendState(player)
    end)
end

local function onArrive(event, player) if player then sync(player, true) end end

local function onLogout(event, player)
    if not player then return end
    local guid = player:GetGUIDLow()
    selected[guid], nearList[guid], undo[guid], lastSpawn[guid], lastLoad[guid], moves[guid], lastSync[guid] =
        nil, nil, nil, nil, nil, nil, nil
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
if CreateLuaEvent then CreateLuaEvent(syncAll, SYNC_EVERY_MS, 0) end

-- for stream/tests/test_ov_build.lua (read only)
OV_BUILD_TEST = { props = props, live = live, roles = roles, selected = selected, undo = undo, builds = builds,
    byCode = byCode, CATALOG = function() return CATALOG end, BUILD_AREAS = BUILD_AREAS, run = run, sync = sync,
    syncAll = syncAll, encode = encode, decode = decode, catalogText = catalogText, areaAt = areaAt }
