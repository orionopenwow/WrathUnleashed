-- lua5.1 stream/tests/test_ov_build.lua [ov_build.lua] [ov_modapi.lua]
-- ov_build.lua under a fake mod-ale: roles, build areas, the catalog check, spawn / move / turn / undo / delete /
-- clear, the limits and rates, save / share / load codes, the GM-only commands, props coming back after a grid
-- unload and a restart, the OVMOD channel, and no game-brand names in anything players saw.
local file = arg[1] or "realm/custom/lua_scripts/ov_build.lua"
local modapi = arg[2] or file:gsub("ov_build%.lua$", "ov_modapi.lua")

local pass, fail = 0, 0
local realPrint = print
local lastSeen = {}
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name)
        if os.getenv and lastSeen[1] then for _, p in ipairs(lastSeen) do realPrint("   " .. p.name .. ": " .. tostring(p.msgs[#p.msgs])) end end
    end
end
print = function() end

local clock = 1000000
os.time = function() return clock end
local env = {}
os.getenv = function(k) return env[k] end
math.randomseed(3)

-- ---------------------------------------------------------------- fake world
local events, luaEvents, serverEvents = {}, {}, {}
function RegisterPlayerEvent(id, fn) events[id] = fn end
function RegisterServerEvent(id, fn) serverEvents[id] = fn end
function CreateLuaEvent(fn, delay, rep) luaEvents[#luaEvents + 1] = { fn = fn, delay = delay, rep = rep } end

local objects, nextGuid, spawns = {}, 5000, {}
local maps = {}
local function mapObj(id)
    maps[id] = maps[id] or { id = id, GetWorldObject = function(self, g) local o = objects[g]; if o and o.map == self.id then return o end end,
        IsDungeon = function() return false end }
    return maps[id]
end
function GetMapById(id) return mapObj(id) end
function PerformIngameSpawn(kind, entry, map, inst, x, y, z, o, save, dur, phase)
    spawns[#spawns + 1] = { kind = kind, entry = entry, save = save }
    if kind ~= 2 or save then return nil end
    nextGuid = nextGuid + 1
    local go = { guid = nextGuid, entry = entry, map = map, x = x, y = y, z = z, o = o }
    function go:GetGUID() return self.guid end
    function go:RemoveFromWorld(del) objects[self.guid] = nil; self.removed = true end
    objects[go.guid] = go
    return go
end
local function liveCount() local n = 0; for _ in pairs(objects) do n = n + 1 end; return n end

-- the fake characters database: the statements, and the builds table for real
local sqlLog, buildsDb, propRows, roleRows = {}, {}, nil, nil
function CharDBExecute(sql)
    sqlLog[#sqlLog + 1] = sql
    local owner, oname, name, props = sql:match("^INSERT INTO mod_builder_builds %(owner, owner_name, name, props, created_at%) VALUES %((%d+), '(%w*)', '([%w_%-]+)', '([^']*)'")
    if owner then
        local key = owner .. "/" .. name
        buildsDb[key] = buildsDb[key] or { owner = tonumber(owner), name = name }
        buildsDb[key].props = props
    end
    local code, o2, n2 = sql:match("^UPDATE mod_builder_builds SET code = '(%w+)' WHERE owner = (%d+) AND name = '([%w_%-]+)'")
    if code then buildsDb[o2 .. "/" .. n2].code = code end
end
local function result(rows)
    if not rows or #rows == 0 then return nil end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetFloat(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetString(c) return tostring(self.rows[self.i][c + 1] or "") end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end
function CharDBQuery(sql)
    if sql:match("FROM mod_builder_props$") then return result(propRows) end
    if sql:match("FROM mod_builder_roles$") then return result(roleRows) end
    local o, n = sql:match("SELECT props, code FROM mod_builder_builds WHERE owner = (%d+) AND name = '([%w_%-]+)'")
    if o then local b = buildsDb[o .. "/" .. n]; return b and result({ { b.props, b.code or "" } }) end
    local c = sql:match("SELECT owner, name, props FROM mod_builder_builds WHERE code = '(%w+)'")
    if c then for _, b in pairs(buildsDb) do if b.code == c then return result({ { b.owner, b.name, b.props } }) end end; return nil end
    local ow = sql:match("SELECT name, code FROM mod_builder_builds WHERE owner = (%d+)")
    if ow then
        local rows = {}
        for _, b in pairs(buildsDb) do if b.owner == tonumber(ow) then rows[#rows + 1] = { b.name, b.code or "" } end end
        table.sort(rows, function(a, b) return a[1] < b[1] end)
        return result(rows)
    end
    return nil
end
local MISSING = 19664   -- this realm's world database lacks one catalog entry
local worldSql
function WorldDBQuery(sql)
    worldSql = sql
    local rows = {}
    for id in sql:match("IN %(([%d,]+)%)"):gmatch("%d+") do if tonumber(id) ~= MISSING then rows[#rows + 1] = { id } end end
    return result(rows)
end

-- players
local online = {}
function GetPlayerByName(n) for _, p in pairs(online) do if p.name:lower() == n:lower() then return p end end end
function GetPlayersInWorld() local t = {}; for _, p in pairs(online) do t[#t + 1] = p end; return t end
local allMsgs = {}
local AREA = { x = -9448.55, y = 68.24, z = 56.32 }
local function player(over)
    local p = { msgs = {}, addon = {}, gm = 0, map = 0, x = AREA.x, y = AREA.y, z = AREA.z, o = 0 }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m; allMsgs[#allMsgs + 1] = m end
    function p:SendAddonMessage(prefix, msg) self.addon[#self.addon + 1] = { prefix, msg } end
    function p:GetGUIDLow() return self.guid end
    function p:GetName() return self.name end
    function p:GetGMRank() return self.gm end
    function p:GetMapId() return self.map end
    function p:GetMap() return mapObj(self.map) end
    function p:GetX() return self.x end
    function p:GetY() return self.y end
    function p:GetZ() return self.z end
    function p:GetO() return self.o end
    online[p.guid] = p
    lastSeen[#lastSeen + 1] = p
    return p
end
local function last(p) return p.msgs[#p.msgs] or "" end
local function cmd(p, text) return events[42](42, p, text) end
local function said(p, pat) for _, m in ipairs(p.msgs) do if m:find(pat) then return true end end end
local function sqlHas(pat) for _, s in ipairs(sqlLog) do if s:find(pat) then return true end end end

-- ov_modapi.lua through require, as on the realm
package.preload["ov_modapi"] = function() return dofile(modapi) end

dofile(file)
local T = assert(OV_BUILD_TEST)
local function propsOf(guid) local n = 0; for _, p in pairs(T.props) do if p.owner == guid then n = n + 1 end end; return n end
local function only(guid) for _, p in pairs(T.props) do if p.owner == guid then return p end end end
local function liveOf(p) return objects[T.live[p.id]] end

check("events: login, logout, zone, map, command; a sync timer", events[3] and events[4] and events[27] and events[28] and events[42]
    and #luaEvents == 1 and luaEvents[1].delay == 15000 and luaEvents[1].rep == 0)
check("tables: mod_builder_roles, _props, _builds with CREATE TABLE IF NOT EXISTS",
    sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_roles") and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_props")
    and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_builds"))
check("catalog checked against the world database", worldSql:find("FROM gameobject_template WHERE entry IN"))
local cat = T.CATALOG()
check("an entry this world lacks is dropped", (function() for _, c in ipairs(cat) do if c.id == MISSING then return false end end; return #cat >= 30 end)())
check("every category has props", (function()
    local seen = {}; for _, c in ipairs(cat) do seen[c.cat] = true end
    for _, k in ipairs({ "seating", "tables", "barrels", "crates", "lights", "banners", "tents", "fires", "fences" }) do if not seen[k] then return false end end
    return true end)())
check("the default build area is Goldshire's game_tele spot", #T.BUILD_AREAS == 1 and T.BUILD_AREAS[1].map == 0 and T.BUILD_AREAS[1].r == 45)

-- roles ------------------------------------------------------------------------------------------------
local gm = player({ guid = 1, name = "Keeper", gm = 3 })
local ann = player({ guid = 2, name = "Ann", x = AREA.x + 5 })
local bob = player({ guid = 3, name = "Bob", x = AREA.x - 5 })

check(".build handled", cmd(ann, "build") == false and said(ann, "build spawn") and said(ann, "50 props per player, 500 per area"))
check("other commands untouched", cmd(ann, "buildings") == nil and cmd(ann, "tele goldshire") == nil)
cmd(ann, "build spawn chair")
check("no role: refused", last(ann):find("builder role") and propsOf(2) == 0)
cmd(ann, "build where")
check(".build where works without the role", said(ann, "Goldshire green") and said(ann, "you are here"))
cmd(ann, "build grant Bob")
check("grant is GM only", last(ann):find("Only GMs") and not T.roles[3])
cmd(ann, "build purge Keeper"); cmd(ann, "build revoke Bob")
check("purge and revoke are GM only", #ann.msgs >= 2 and ann.msgs[#ann.msgs]:find("Only GMs") and ann.msgs[#ann.msgs - 1]:find("Only GMs"))
cmd(gm, "build grant ann")
check("GM grants Ann (stored in mod_builder_roles)", T.roles[2] and sqlHas("^REPLACE INTO mod_builder_roles %(guid, name, granted_by, granted_at%) VALUES %(2, 'Ann', 'Keeper'")
    and last(ann):find("You can build now"))
cmd(gm, "build grant Nobody")
check("grant needs the player online", last(gm):find("isn't online"))
cmd(gm, "build grant Bob")

-- spawn -------------------------------------------------------------------------------------------------
ann.o = 1.0
cmd(ann, "build spawn chair")
local p1 = only(2)
check("spawn by key, at your position and facing", p1 and p1.entry == 2413 and p1.x == ann.x and p1.z == ann.z and math.abs(p1.o - 1.0) < 1e-9)
check("spawned unsaved through PerformIngameSpawn (gameobject)", spawns[#spawns].kind == 2 and spawns[#spawns].save == false and liveOf(p1))
check("stored in mod_builder_props", sqlHas("^INSERT INTO mod_builder_props %(id, owner, owner_name, area, entry, map, x, y, z, o, created_at%) VALUES %(%d+, 2, 'Ann', '1', 2413, 0,"))
check("selected after spawn", T.selected[2] == p1.id and last(ann):find("Wooden Chair placed %(1/50%)"))
cmd(ann, "build spawn 181075")
check("one spawn a second", propsOf(2) == 1 and last(ann):find("One prop a second"))
clock = clock + 1
cmd(ann, "build spawn 181075")
check("spawn by id", propsOf(2) == 2 and T.props[T.selected[2]].entry == 181075)
clock = clock + 1
cmd(ann, "build spawn 999999"); cmd(ann, "build spawn barrel 01 no")
check("unknown props refused", propsOf(2) == 2 and last(ann):find("No prop called"))
cmd(ann, "build spawn crate")
check("names: a key wins", T.props[T.selected[2]].entry == 179969)
clock = clock + 1
cmd(ann, "build spawn " .. MISSING)
check("a dropped entry can't be spawned", propsOf(2) == 3)

-- outside the area
local far = player({ guid = 4, name = "Far", gm = 0, x = AREA.x + 200 })
cmd(gm, "build grant Far")
cmd(far, "build spawn chair")
check("outside the build areas: refused", propsOf(4) == 0 and last(far):find("only in a build area"))
gm.x = AREA.x + 300
cmd(gm, "build spawn chair")
check("GMs too, by default", propsOf(1) == 0 and last(gm):find("only in a build area"))
env.OV_BUILD_ANYWHERE = "1"
cmd(gm, "build spawn chair")
check("OV_BUILD_ANYWHERE=1: GMs anywhere in the open world", propsOf(1) == 1 and only(1).area == "m0")
clock = clock + 1
cmd(far, "build spawn chair")
check("OV_BUILD_ANYWHERE=1 is for GMs only", propsOf(4) == 0)
env.OV_BUILD_ANYWHERE = nil
gm.x = AREA.x

-- near / select / move / turn -----------------------------------------------------------------------------
cmd(ann, "build near")
check(".build near lists your props, nearest first", said(ann, "1%. ") and said(ann, "3%. ") and not said(ann, "4%. "))
cmd(ann, "build select 9")
check("select out of range explains", last(ann):find("build near"))
local list = {}
for _, p in pairs(T.props) do if p.owner == 2 then list[#list + 1] = p end end
cmd(ann, "build select 1")
local sel = T.props[T.selected[2]]
check("select picks one", sel and sel.owner == 2 and last(ann):find("selected"))
local oldGo, oldZ = liveOf(sel), sel.z
cmd(ann, "build move z 0.5")
check("move: despawn and respawn higher", math.abs(sel.z - (oldZ + 0.5)) < 1e-9 and oldGo.removed and liveOf(sel).z == sel.z
    and sqlHas(string.format("^UPDATE mod_builder_props SET x = [%%-%%d%%.]+, y = [%%-%%d%%.]+, z = [%%-%%d%%.]+, o = [%%d%%.]+ WHERE id = %d", sel.id)))
cmd(ann, "build move x 11")
check("move: 10 yards a step at most", last(ann):find("Up to 10 yards"))
cmd(ann, "build move q 1")
check("move: usage", last(ann):find("Usage"))
local x0 = sel.x
clock = clock + 1
for _ = 1, 5 do cmd(ann, "build move x 9") end
check("move: never out of the build area", sel.x - x0 < 45 and said(ann, "out of the build area"))
clock = clock + 1
local o0 = sel.o
cmd(ann, "build turn 90")
check("turn: +90 degrees", math.abs(sel.o - (o0 + math.pi / 2)) < 1e-6 and liveOf(sel).o == sel.o)
cmd(ann, "build turn 400")
check("turn: 180 at most", last(ann):find("Up to 180"))
cmd(ann, "build undo")
check("undo a turn", math.abs(sel.o - o0) < 1e-6 and last(ann):find("back where it was"))
clock = clock + 1
for _ = 1, 6 do cmd(ann, "build turn 1") end
check("five moves or turns a second", last(ann):find("Slow down"))
clock = clock + 1

-- someone else's prop
T.selected[3] = sel.id
cmd(bob, "build move z 1")
check("can't move another builder's prop", last(bob):find("isn't yours"))
T.selected[3] = nil

-- delete / undo
local n0, live0 = propsOf(2), liveCount()
cmd(ann, "build delete")
check("delete: gone from the world and the table", propsOf(2) == n0 - 1 and liveCount() == live0 - 1
    and sqlHas(string.format("^DELETE FROM mod_builder_props WHERE id = %d$", sel.id)) and T.selected[2] == nil)
cmd(ann, "build delete")
check("delete with nothing selected explains", last(ann):find("Nothing selected"))
cmd(ann, "build undo")
check("undo a delete brings it back", propsOf(2) == n0 and T.props[sel.id] and liveOf(T.props[sel.id]))
clock = clock + 1
cmd(ann, "build spawn lantern")
local lan = T.selected[2]
cmd(ann, "build undo")
check("undo a spawn removes it", T.props[lan] == nil and propsOf(2) == n0)
local depth = #T.undo[2]
T.undo[2] = {}
cmd(ann, "build undo")
check("undo runs out (the stack holds 30 at most)", depth <= 30 and last(ann):find("Nothing to undo"))

-- limits --------------------------------------------------------------------------------------------------
env.OV_BUILD_PER_PLAYER = "4"
clock = clock + 1; cmd(ann, "build spawn stool")
clock = clock + 1; cmd(ann, "build spawn stool")
check("per-player limit", propsOf(2) == 4 and last(ann):find("the most allowed"))
env.OV_BUILD_PER_PLAYER = nil
local inArea = 0; for _, p in pairs(T.props) do if p.area == "1" then inArea = inArea + 1 end end
env.OV_BUILD_PER_AREA = tostring(inArea)
clock = clock + 1; cmd(bob, "build spawn stool")
check("per-area limit", propsOf(3) == 0 and last(bob):find("This area is full"))
env.OV_BUILD_PER_AREA = nil
clock = clock + 1; cmd(bob, "build spawn bonfire")
check("Bob builds too", propsOf(3) == 1)

-- clear ----------------------------------------------------------------------------------------------------
cmd(ann, "build clear")
check("clear: all of yours in this area, nobody else's", propsOf(2) == 0 and propsOf(3) == 1 and last(ann):find("Cleared 4 props"))
cmd(ann, "build undo")
check("undo a clear", propsOf(2) == 4)

-- save / share / load ---------------------------------------------------------------------------------------
ann.o = 0
cmd(ann, "build save camp!")
check("save: name checked", last(ann):find("Usage"))
cmd(ann, "build save Camp")
check("save: stored relative to you", buildsDb["2/camp"] and #T.decode(buildsDb["2/camp"].props) == 4 and last(ann):find("Saved 'camp': 4 props"))
cmd(ann, "build share nope")
check("share: unknown build", last(ann):find("no build called"))
cmd(ann, "build share camp")
local code = buildsDb["2/camp"].code
check("share: a 6-letter code, stored", code and #code == 6 and code:match("^[A-HJ-NP-Z2-9]+$") and last(ann):find(code, 1, true))
cmd(ann, "build share camp")
check("share again: the same code", buildsDb["2/camp"].code == code and last(ann):find(code, 1, true))
cmd(ann, "build save camp")
check("re-saving keeps the code", buildsDb["2/camp"].code == code)
cmd(ann, "build saved")
check(".build saved lists it with the code", last(ann):find("camp %(" .. code .. "%)"))

-- Bob pastes Ann's code somewhere else in the area, facing north (pi/2)
bob.x, bob.y, bob.o = AREA.x, AREA.y - 10, math.pi / 2
local enc = T.decode(buildsDb["2/camp"].props)
clock = clock + 1
cmd(bob, "build load " .. code:lower())
check("load a code: pasted for Bob", propsOf(3) == 5 and last(bob):find("Pasted '" .. code .. "': 4 props"))
check("pasted relative to Bob and turned with him", (function()
    local mine = {}
    for _, p in pairs(T.props) do if p.owner == 3 and p.entry ~= 50910 then mine[#mine + 1] = p end end
    local e = enc[1]
    for _, p in ipairs(mine) do
        local ex, ey = bob.x - e.dy, bob.y + e.dx   -- (dx, dy) turned by 90 degrees
        if p.entry == e.entry and math.abs(p.x - ex) < 0.02 and math.abs(p.y - ey) < 0.02 and math.abs(p.z - (bob.z + e.dz)) < 0.02 then return true end
    end
    return false end)())
cmd(bob, "build load " .. code)
check("one paste every 5 s", propsOf(3) == 5 and last(bob):find("One paste every 5"))
cmd(bob, "build undo")
check("undo a paste", propsOf(3) == 1 and last(bob):find("pasted build %(4 props%)"))
clock = clock + 10
env.OV_BUILD_PER_PLAYER = "3"
cmd(bob, "build load " .. code)
check("a paste over your limit is refused whole", propsOf(3) == 1 and last(bob):find("room for 2"))
env.OV_BUILD_PER_PLAYER = nil
bob.x, bob.y, bob.o = AREA.x - 40, AREA.y, math.pi
clock = clock + 10
local nb = propsOf(3)
cmd(bob, "build load " .. code)
check("props that would land outside the area are left out", last(bob):find("didn't fit here") or last(bob):find("None of that build fits"))
if propsOf(3) > nb then cmd(bob, "build undo") end
bob.x, bob.y, bob.o = AREA.x, AREA.y - 10, math.pi / 2
cmd(bob, "build load ZZZZZZ")
check("unknown code", last(bob):find("No build"))
-- a code made before a restart: from the table
for k in pairs(T.byCode) do T.byCode[k] = nil end
for k in pairs(T.builds) do T.builds[k] = nil end
clock = clock + 10
cmd(bob, "build load " .. code)
check("load a code from mod_builder_builds", propsOf(3) == 5)
cmd(bob, "build undo")
clock = clock + 10
cmd(ann, "build load camp")
check("load your own build by name", propsOf(2) == 8)
cmd(ann, "build undo")

-- grid unload, restart -------------------------------------------------------------------------------------
for g, o in pairs(objects) do objects[g] = nil end
check("grid unloaded: nothing in the world", liveCount() == 0)
luaEvents[1].fn()
local total = 0; for _ in pairs(T.props) do total = total + 1 end
local nearAny = 0
for _, p in pairs(T.props) do if p.map == 0 and math.abs(p.x - AREA.x) < 150 then nearAny = nearAny + 1 end end
check("the sync timer puts the props back near players", liveCount() == total and nearAny > 0)
-- restart: a fresh script reads mod_builder_props
propRows = {}
for _, p in pairs(T.props) do propRows[#propRows + 1] = { p.id, p.owner, p.ownerName, p.area, p.entry, p.map, p.x, p.y, p.z, p.o } end
roleRows = {}
for g, r in pairs(T.roles) do roleRows[#roleRows + 1] = { g, r.name } end
for g in pairs(objects) do objects[g] = nil end
dofile(file)
local T2 = OV_BUILD_TEST
check("restart: every prop read back", (function() local n = 0; for _ in pairs(T2.props) do n = n + 1 end; return n == total end)())
events[3](3, ann)
check("restart: they appear when a player logs in nearby", liveCount() == nearAny)
check("restart: roles come back from mod_builder_roles", T2.roles[2] and T2.roles[3] and T2.roles[2].name == "Ann")
check("restart: new ids continue after the highest", (function()
    clock = clock + 1; cmd(bob, "build spawn chair")
    local id = T2.selected[3]
    for _, r in ipairs(propRows) do if r[1] >= id then return false end end
    cmd(bob, "build undo")
    return id ~= nil end)())
T = T2
propRows, roleRows = nil, nil

-- GM: revoke, purge -------------------------------------------------------------------------------------------
cmd(gm, "build revoke ann")
check("revoke: gone, props stay", T.roles[2] == nil and sqlHas("^DELETE FROM mod_builder_roles WHERE guid = 2$") and propsOf(2) == 4)
clock = clock + 1
cmd(ann, "build spawn chair")
check("revoked: can't build", last(ann):find("builder role"))
local before = liveCount()
cmd(gm, "build purge ann")
check("purge: every prop of that player, from the world and the table", propsOf(2) == 0 and liveCount() == before - 4
    and sqlHas("^DELETE FROM mod_builder_props WHERE owner = 2$") and last(gm):find("Purged 4 props"))
cmd(gm, "build purge ann")
check("purge with nothing left", last(gm):find("has no props"))

-- the window's channel (OVMOD) ---------------------------------------------------------------------------------
local onAddon = serverEvents[30]
check("ov_modapi loaded through require", onAddon ~= nil and OVMod and OVMod._loaded)
bob.addon = {}
onAddon(30, bob, 7, "OVMOD", "wubuild\tcatalog\t1/1\t", bob)
local catMsg, stateMsg
for _, a in ipairs(bob.addon) do
    if a[2]:find("^wubuild\tcatalog\t") then catMsg = a[2] end
    if a[2]:find("^wubuild\tstate\t") then stateMsg = a[2] end
end
check("catalog over OVMOD", catMsg and catMsg:find("2413,chair,seating,Wooden Chair", 1, true) and not catMsg:find(tostring(MISSING)))
check("state over OVMOD", stateMsg and stateMsg:find("mine=1/50;area=Goldshire green;", 1, true))
clock = clock + 1
local n3 = propsOf(3)
onAddon(30, bob, 7, "OVMOD", "wubuild\tcmd\t1/1\tspawn keg", bob)
check("a command over OVMOD runs as the dot command", propsOf(3) == n3 + 1 and bob.addon[#bob.addon][2]:find("sel=%d+,180575,Keg;mine=2/50"))
onAddon(30, far, 7, "OVMOD", "wubuild\tcmd\t1/1\tpurge Bob", far)
check("GM-only stays GM-only over OVMOD", propsOf(3) == n3 + 1 and last(far):find("Only GMs"))

-- switch off ------------------------------------------------------------------------------------------------
env.OV_BUILD = "0"
clock = clock + 1
cmd(bob, "build spawn chair")
check("OV_BUILD=0: off", last(bob):find("off on this realm"))
env.OV_BUILD = nil

-- every SQL statement stays on mod_builder_ tables ---------------------------------------------------------------
check("SQL only on mod_builder_ tables", (function()
    for _, s in ipairs(sqlLog) do
        local t = s:match("INTO%s+(%S+)") or s:match("^UPDATE%s+(%S+)") or s:match("FROM%s+(%S+)") or s:match("EXISTS%s+(%S+)")
        if not t or not t:match("^mod_builder_") then return false end
    end
    return true end)())
check("no saved world spawns", (function() for _, s in ipairs(spawns) do if s.save then return false end end; return true end)())

local BANNED = { "world of warcraft", "warcraft", "lich king", "blizzard", "openvanilla", "open vanilla", "openwow" }
check("no game-brand names in anything players saw", (function()
    for _, m in ipairs(allMsgs) do
        local l = m:lower()
        for _, w in ipairs(BANNED) do if l:find(w, 1, true) then return false end end
        if l:find("%f[%a]wow%f[%A]") then return false end
    end
    for _, c in ipairs(T.CATALOG()) do if c.name:lower():find("darkmoon") or c.name:lower():find("wotlk") then return false end end
    return true end)())

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
