-- lua5.1 stream/tests/test_ov_build.lua [ov_build.lua] [ov_modapi.lua]
-- ov_build.lua under a fake mod-ale: roles, build areas, the catalog check, spawn / move / turn / undo / delete /
-- clear, the limits and rates, save / share / load codes, the GM-only commands, props coming back after a grid
-- unload and a restart, the OVMOD channel, and no game-brand names in anything players saw. M3: plots and their
-- roles and GM tools, budgets and trust tiers, multi-select and group ops, copy and paste, exact numbers and size,
-- prefabs and the OVBuild functions, the op log and GM rollback, and a restart reading all of it back.
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
    function go:SetScale(sc) self.scale = sc end
    objects[go.guid] = go
    return go
end
function GetGUIDLow(g) return g end
local function liveCount() local n = 0; for _ in pairs(objects) do n = n + 1 end; return n end

-- the fake characters database: the statements, and the builds table for real
local sqlLog, buildsDb, propRows, roleRows = {}, {}, nil, nil
local extraRows = {}   -- [table name] = rows a restart reads back (plots, members, prefabs, trust, sizes)
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
    local t = sql:match("FROM (mod_builder_[%w_]+)$")
    if t and extraRows[t] then return result(extraRows[t]) end
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
check("tables: plots, plot members, prefabs, op log, trust, sizes", sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_plots ")
    and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_plot_members") and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_prefabs")
    and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_oplog") and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_trust")
    and sqlHas("^CREATE TABLE IF NOT EXISTS mod_builder_prop_scale"))
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
    -- The catalog may come in several parts (i/n): join their data in order.
    local i, n, data = a[2]:match("^wubuild\tcatalog\t(%d+)/(%d+)\t(.*)$")
    if i then catMsg = (i == "1" and "" or (catMsg or "")) .. data end
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

-- edit mode: pick, spawnat, placeat, dup -------------------------------------------------------------------------
do
    local ed = player({ guid = 40, name = "Edda", x = AREA.x + 2, y = AREA.y + 2 })
    cmd(gm, "build grant Edda")
    clock = clock + 5
    cmd(ed, string.format("build spawnat chair %.2f %.2f %.2f", AREA.x + 6, AREA.y - 3, AREA.z + 0.5))
    local e1 = only(40)
    check("spawnat: a prop at the exact point", e1 and math.abs(e1.x - (AREA.x + 6)) < 0.01 and math.abs(e1.y - (AREA.y - 3)) < 0.01
        and math.abs(e1.z - (AREA.z + 0.5)) < 0.01 and liveOf(e1) ~= nil)
    clock = clock + 5
    cmd(ed, string.format("build spawnat chair %.2f %.2f %.2f", AREA.x + 70, AREA.y, AREA.z))
    check("spawnat: outside the build area refused", last(ed):find("outside the build area") and propsOf(40) == 1)
    clock = clock + 5
    cmd(ed, string.format("build spawnat chair %.2f %.2f %.2f", AREA.x + 400, AREA.y, AREA.z))
    check("spawnat: too far from the character refused", last(ed):find("too far") and propsOf(40) == 1)
    cmd(ed, "build spawnat chair 1 2")
    check("spawnat: bad numbers get the usage", last(ed):find("Usage"))

    T.selected[40] = nil
    cmd(ed, "build pick " .. T.live[e1.id])
    check("pick: the clicked prop becomes the selection", T.selected[40] == e1.id and last(ed):find("selected"))
    local annProp = only(2)
    if annProp and T.live[annProp.id] then
        cmd(ed, "build pick " .. T.live[annProp.id])
        check("pick: someone else's prop is refused", last(ed):find("Ann's") and T.selected[40] == e1.id)
    end
    cmd(ed, "build pick 99999999")
    check("pick: not a Builder prop", last(ed):find("isn't a Builder prop"))

    clock = clock + 5
    local oldO = e1.o
    cmd(ed, string.format("build placeat %.2f %.2f %.2f 90", AREA.x - 4, AREA.y + 4, AREA.z + 1))
    check("placeat: moved to the exact point and turned 90 degrees", math.abs(e1.x - (AREA.x - 4)) < 0.01 and math.abs(e1.z - (AREA.z + 1)) < 0.01
        and math.abs(((e1.o - oldO) % (2 * math.pi)) - math.pi / 2) < 1e-6 and liveOf(e1) and math.abs(liveOf(e1).x - e1.x) < 0.01)
    cmd(ed, "build undo")
    check("placeat: undo puts it back", math.abs(e1.z - AREA.z - 0.5) < 0.01)
    clock = clock + 5
    cmd(ed, string.format("build placeat %.2f %.2f %.2f 0", AREA.x + 80, AREA.y, AREA.z))
    check("placeat: outside the area refused", last(ed):find("too far") or last(ed):find("out of the build area"))

    clock = clock + 5
    cmd(ed, "build dup")
    check("dup: a copy beside it becomes the selection", propsOf(40) == 2 and T.selected[40] ~= e1.id
        and T.props[T.selected[40]].entry == e1.entry and liveOf(T.props[T.selected[40]]) ~= nil)
    cmd(ed, "build dup")
    check("dup: one a second", last(ed):find("One prop a second") and propsOf(40) == 2)
    clock = clock + 5
    cmd(ed, "build undo")
    check("dup: undo removes the copy", propsOf(40) == 1)
end

-- M3: plots and permissions ------------------------------------------------------------------------------------
local function at(p, dx, dy, dz) return string.format("%.2f %.2f %.2f", AREA.x + dx, AREA.y + dy, AREA.z + (dz or 0)) end
local function count(fn) local n = 0; for _, p in pairs(T.props) do if fn(p) then n = n + 1 end end; return n end
local function near(a, b) return math.abs(a - b) < 0.02 end
local function step() clock = clock + 1 end
do
    local pia = player({ guid = 50, name = "Pia", x = AREA.x, y = AREA.y + 25 })
    local quin = player({ guid = 51, name = "Quin", x = AREA.x + 3, y = AREA.y + 25 })
    local vic = player({ guid = 52, name = "Vic", x = AREA.x - 3, y = AREA.y + 25 })
    local rex = player({ guid = 53, name = "Rex", x = AREA.x + 6, y = AREA.y + 20 })
    cmd(gm, "build grant Pia"); cmd(gm, "build grant Quin"); cmd(gm, "build grant Rex")

    cmd(vic, "build plot claim")
    check("plot: claiming needs the builder role", last(vic):find("builder role") and next(T.plots) == nil)
    cmd(pia, "build plot")
    check("plot: none yet says how to claim", last(pia):find("plot claim"))
    cmd(pia, "build plot claim")
    local plot = (function() for _, pl in pairs(T.plots) do if pl.owner == 50 then return pl end end end)()
    check("plot: claimed where you stand, stored", plot and near(plot.x, AREA.x) and plot.r == 12 and plot.area == "1"
        and sqlHas("^REPLACE INTO mod_builder_plots %(id, owner, owner_name, area, map, x, y, z, r, created_at%) VALUES %(%d+, 50, 'Pia', '1', 0,")
        and last(pia):find("Plot claimed: 24 yards across"))
    cmd(pia, "build plot claim")
    check("plot: one each", last(pia):find("You have a plot already"))
    rex.x, rex.y = AREA.x + 20, AREA.y + 25
    cmd(rex, "build plot claim")
    check("plot: not over someone else's", last(rex):find("Too close to Pia's plot"))
    rex.x, rex.y = AREA.x + 40, AREA.y
    cmd(rex, "build plot claim")
    check("plot: inside the build area", last(rex):find("edge of the build area"))
    rex.x, rex.y = AREA.x + 5, AREA.y
    cmd(rex, "build plot claim")
    check("plot: not over other builders' props", last(rex):find("Someone else's props are here"))
    rex.x, rex.y = AREA.x + 6, AREA.y + 20

    -- Pia builds on her plot; Rex (a builder, not a member) can't
    step(); cmd(pia, "build spawnat chair " .. at(pia, 2, 26))
    local pc = T.props[T.selected[50]]
    check("plot: the owner builds on it", pc and pc.owner == 50)
    step(); cmd(rex, "build spawnat chair " .. at(rex, -2, 26))
    check("plot: a non-member can't build on it", last(rex):find("That's Pia's plot") and count(function(p) return p.owner == 53 end) == 0)
    T.selected[53] = pc.id
    cmd(rex, "build move z 1")
    check("plot: a non-member can't move its props", last(rex):find("Pia's plot") and near(pc.z, AREA.z))
    cmd(rex, "build pick " .. T.live[pc.id])
    check("plot: nor select them", last(rex):find("Pia's plot"))
    T.selected[53] = nil
    -- moving your own prop from the commons into her plot is refused too
    step(); cmd(rex, "build spawnat chair " .. at(rex, 6, 12))
    local rp = T.props[T.selected[53]]
    step(); cmd(rex, "build placeat " .. at(rex, 4, 26) .. " 0")
    check("plot: can't carry a prop into someone else's plot", rp and near(rp.y, AREA.y + 12) and last(rex):find("Pia's plot"))

    -- co-builders
    cmd(quin, "build plot add Pia")
    check("plot: only an owner adds people", last(quin):find("You have no plot"))
    cmd(pia, "build plot add Vic")
    check("plot: a builder needs the builder role", last(pia):find("Vic needs the builder role"))
    cmd(pia, "build plot add Quin")
    check("plot: add a builder by name (stored)", plot.members[51] and plot.members[51].role == "builder"
        and sqlHas("^REPLACE INTO mod_builder_plot_members %(plot, guid, name, role%) VALUES %(%d+, 51, 'Quin', 'builder'%)")
        and last(quin):find("You're a builder on Pia's plot"))
    step(); cmd(quin, "build spawnat stool " .. at(quin, 4, 27))
    local qp = T.props[T.selected[51]]
    check("plot: a builder builds there", qp and qp.owner == 51)
    T.selected[51] = pc.id
    step(); cmd(quin, "build move z 0.5")
    check("plot: a builder moves the owner's props there", near(pc.z, AREA.z + 0.5))
    cmd(pia, "build plot add Vic visitor")
    check("plot: add a visitor", plot.members[52] and plot.members[52].role == "visitor")
    cmd(gm, "build grant Vic")
    step(); cmd(vic, "build spawnat stool " .. at(vic, -4, 27))
    check("plot: visitors can't build", last(vic):find("visitor on Pia's plot") and count(function(p) return p.owner == 52 end) == 0)
    cmd(vic, "build pick " .. T.live[pc.id])
    check("plot: visitors may select", T.selected[52] == pc.id)
    step(); cmd(vic, "build move z 1")
    check("plot: visitors can't edit", last(vic):find("visitor") and near(pc.z, AREA.z + 0.5))
    cmd(vic, "build delete")
    check("plot: visitors can't delete", T.props[pc.id] ~= nil)
    cmd(vic, "build copy")
    check("plot: visitors may copy", T.clip[52] and #T.clip[52].rel == 1)
    cmd(quin, "build plot")
    check("plot: info lists builders and visitors", said(quin, "Builders: Quin") and said(quin, "Visitors: Vic") and last(quin):find("You: builder"))
    cmd(pia, "build plot remove quin")
    check("plot: remove a co-builder by name", plot.members[51] == nil and sqlHas("^DELETE FROM mod_builder_plot_members WHERE plot = %d+ AND guid = 51$"))
    step(); cmd(quin, "build spawnat stool " .. at(quin, 5, 28))
    check("plot: removed, can't build there any more", last(quin):find("That's Pia's plot"))

    -- the plot's budget
    env.OV_BUILD_PLOT_PROPS = "2"
    step(); cmd(pia, "build spawnat stool " .. at(pia, -3, 22))
    check("plot: its own prop limit", last(pia):find("Pia's plot is full") and count(function(p) return p.owner == 50 end) == 1)
    env.OV_BUILD_PLOT_PROPS = nil

    -- state over OVMOD carries the plot and the budget
    pia.addon = {}
    serverEvents[30](30, pia, 7, "OVMOD", "wubuild\tcmd\t1/1\tplot", pia)
    local st = pia.addon[#pia.addon][2]
    check("state: plot, your role, its use; points and tier", st:find("plot=%d+,Pia,owner,2/150,2/300") and st:find("pts=1/100;tier=builder"))

    -- GM tools
    cmd(pia, "build plot list")
    check("plot list is GM only", last(pia):find("Only GMs"))
    cmd(gm, "build plot list")
    check("GM: plot list", said(gm, "#" .. plot.id .. " Pia, Goldshire green"))
    cmd(gm, "build plot transfer " .. plot.id .. " Quin")
    check("GM: transfer a plot", plot.owner == 51 and plot.ownerName == "Quin" and last(gm):find("is Quin's now"))
    step(); cmd(pia, "build spawnat stool " .. at(pia, -3, 22))
    check("the old owner can't build there now", last(pia):find("That's Quin's plot"))
    cmd(gm, "build plot transfer " .. plot.id .. " Pia")
    cmd(gm, "build plot remove " .. plot.id)
    check("GM: remove a plot (props stay)", T.plots[plot.id] == nil and T.props[pc.id] ~= nil
        and sqlHas("^DELETE FROM mod_builder_plots WHERE id = " .. plot.id .. "$"))
    pia.x, pia.y = AREA.x + 20, AREA.y + 20
    cmd(pia, "build plot claim")
    plot = (function() for _, pl in pairs(T.plots) do if pl.owner == 50 then return pl end end end)()
    cmd(pia, "build plot abandon")
    check("abandon your plot", plot and T.plots[plot.id] == nil and last(pia):find("Your plot is gone"))

    -- plots only
    env.OV_BUILD_PLOTS_ONLY = "1"
    step(); cmd(rex, "build spawnat chair " .. at(rex, 6, 14))
    check("OV_BUILD_PLOTS_ONLY=1: no building in the commons", last(rex):find("Claim a plot first"))
    env.OV_BUILD_PLOTS_ONLY = nil
end

-- M3: budgets and trust tiers ------------------------------------------------------------------------------------
do
    local nia = player({ guid = 54, name = "Nia", x = AREA.x - 20, y = AREA.y - 5, played = 600 })
    function nia:GetTotalPlayedTime() return self.played end
    cmd(gm, "build grant Nia")
    local b = T.budgetOf(nia)
    check("tiers: a new character gets less (40%)", b.tier == "new" and b.props == 20 and b.points == 40)
    nia.played = 3 * 3600
    check("tiers: after 2 hours played, builder", T.budgetOf(nia).tier == "builder" and T.budgetOf(nia).props == 50)
    nia.played = 600
    cmd(nia, "build trust Nia master")
    check("trust is GM only", last(nia):find("Only GMs"))
    cmd(gm, "build trust Nia trusted")
    b = T.budgetOf(nia)
    check("GM sets a tier (stored)", b.tier == "trusted" and b.props == 150 and b.points == 300
        and sqlHas("^REPLACE INTO mod_builder_trust %(guid, name, tier, set_by, set_at%) VALUES %(54, 'Nia', 3, 'Keeper'")
        and last(nia):find("150 props and 300 points"))
    cmd(gm, "build trust Nia auto")
    check("trust auto: back to the played-time rule", T.budgetOf(nia).tier == "new" and sqlHas("^DELETE FROM mod_builder_trust WHERE guid = 54$"))
    cmd(gm, "build trust Nia boss")
    check("trust: unknown tier gets the usage", last(gm):find("Usage"))

    check("points: lights 2, tents 3, a chair 1, the Great Forge 6", T.costOf(180043) == 2 and T.costOf(184592) == 3
        and T.costOf(2413) == 1 and T.costOf(32372) == 6)
    env.OV_BUILD_POINTS = "10"     -- new tier: 4 points
    step(); cmd(nia, "build spawnat tent " .. at(nia, -20, -5))
    check("points: a 3-point tent fits in 4", count(function(p) return p.owner == 54 end) == 1)
    step(); cmd(nia, "build spawnat bigtent " .. at(nia, -22, -5))
    check("points: the next 3 don't, with a plain message", count(function(p) return p.owner == 54 end) == 1
        and last(nia):find("needs 3 build points; you have 1 of 4 left"))
    step(); cmd(nia, "build spawnat chair " .. at(nia, -22, -6))
    check("points: a 1-point chair still fits", count(function(p) return p.owner == 54 end) == 2)
    step(); cmd(nia, "build dup")
    check("points: dup is checked too", last(nia):find("build points") and count(function(p) return p.owner == 54 end) == 2)
    env.OV_BUILD_POINTS = nil
    cmd(nia, "build clear")
end

-- M3: multi-select, group ops, copy and paste ----------------------------------------------------------------------
do
    local gus = player({ guid = 60, name = "Gus", x = AREA.x - 15, y = AREA.y + 5 })
    cmd(gm, "build grant Gus")
    local ids = {}
    for i, dx in ipairs({ -2, 2, 0 }) do
        step(); cmd(gus, "build spawnat " .. (i == 3 and "barrel" or "chair") .. " " .. at(gus, -15 + dx, 5 + (i == 3 and 2 or 0)))
        ids[i] = T.selected[60]
    end
    local A, Bp, Cp = T.props[ids[1]], T.props[ids[2]], T.props[ids[3]]
    check("group: three props to work with", A and Bp and Cp)
    cmd(gus, "build pick " .. T.live[A.id])
    cmd(gus, "build pick " .. T.live[Bp.id] .. " add")
    check("Shift-click: adds to the selection", T.group[60] and #T.group[60] == 2 and last(gus):find("added %(2 selected%)"))
    cmd(gus, "build pick " .. T.live[Cp.id] .. " add")
    cmd(gus, "build pick " .. T.live[Cp.id] .. " add")
    check("Shift-click again: takes it out", #T.group[60] == 2 and last(gus):find("taken out"))
    cmd(gus, "build pick " .. T.live[A.id])
    check("a plain click: just that one", T.group[60] == nil and T.selected[60] == A.id)
    cmd(gus, "build selall")
    check("select all of mine in range", T.group[60] and #T.group[60] == 3 and last(gus):find("3 props selected"))
    cmd(gus, "build selclear")
    check("clear the selection", T.group[60] == nil and T.selected[60] == nil)
    cmd(gus, string.format("build selbox %.2f %.2f %.2f %.2f", AREA.x - 18, AREA.y + 4, AREA.x - 14.5, AREA.y + 8))
    check("box select: what's inside the box", T.group[60] and #T.group[60] == 2)
    cmd(gus, string.format("build selbox %.2f %.2f %.2f %.2f add", AREA.x - 13.5, AREA.y + 4, AREA.x - 12, AREA.y + 6))
    check("box select add: keeps the old ones", #T.group[60] == 3)
    cmd(gus, string.format("build selbox %.2f %.2f %.2f %.2f", AREA.x + 300, AREA.y, AREA.x + 310, AREA.y + 10))
    check("box select: too far", last(gus):find("too far"))
    cmd(gus, "build selall")

    local undo0 = #(T.undo[60] or {})
    step(); cmd(gus, "build move z 1")
    check("group move: all three, one undo entry", near(A.z, AREA.z + 1) and near(Bp.z, AREA.z + 1) and near(Cp.z, AREA.z + 1)
        and #T.undo[60] == undo0 + 1 and last(gus):find("3 props moved"))
    cmd(gus, "build undo")
    check("group undo: all back at once", near(A.z, AREA.z) and near(Bp.z, AREA.z) and near(Cp.z, AREA.z) and #T.undo[60] == undo0)
    local cx, cy = (A.x + Bp.x + Cp.x) / 3, (A.y + Bp.y + Cp.y) / 3
    local ax, ay, ao = A.x - cx, A.y - cy, A.o
    step(); cmd(gus, "build turn 90")
    check("group turn: around the middle, each prop turns too", near(A.x - cx, -ay) and near(A.y - cy, ax)
        and math.abs(A.o - (ao + math.pi / 2)) < 1e-6)
    cmd(gus, "build undo")
    check("group turn undo", near(A.x - cx, ax) and near(A.y - cy, ay))
    step(); cmd(gus, "build move x 9"); cmd(gus, "build move x 9"); step(); cmd(gus, "build move x 9"); cmd(gus, "build move x 9")
    cmd(gus, "build move x 9"); step(); cmd(gus, "build move x 9"); cmd(gus, "build move x 9")
    check("group move: all or none at the area's edge", math.abs((A.x - Bp.x) + 4) < 0.05 and said(gus, "out of the build area"))
    for _ = 1, 10 do if #T.undo[60] > undo0 then cmd(gus, "build undo") else break end end
    -- placeat with a group: the last-picked goes to the point, the rest keep their place around it
    cmd(gus, "build selall")
    local pp = T.props[T.selected[60]]
    local offs = {}
    for _, id in ipairs(T.group[60]) do offs[id] = { T.props[id].x - pp.x, T.props[id].y - pp.y } end
    step(); cmd(gus, "build placeat " .. at(gus, -10, 0, 0.5) .. " 0")
    check("group drop: the group keeps its shape", near(pp.x, AREA.x - 10) and near(pp.z, AREA.z + 0.5) and (function()
        for id, o in pairs(offs) do local p = T.props[id]; if not (near(p.x - pp.x, o[1]) and near(p.y - pp.y, o[2])) then return false end end
        return true end)())
    cmd(gus, "build undo")
    -- exact numbers: setpos, setturn, setscale
    cmd(gus, "build pick " .. T.live[A.id])
    step(); cmd(gus, "build setpos " .. at(gus, -16, 9, 0.25))
    check("setpos: exactly there", near(A.x, AREA.x - 16) and near(A.y, AREA.y + 9) and near(A.z, AREA.z + 0.25))
    cmd(gus, "build setturn 90")
    check("setturn: facing 90 degrees", math.abs(A.o - math.pi / 2) < 1e-4)
    cmd(gus, "build setscale 1.5")
    check("setscale: size on the object, stored", A.s == 1.5 and objects[T.live[A.id]].scale == 1.5
        and sqlHas(string.format("^REPLACE INTO mod_builder_prop_scale %%(id, scale%%) VALUES %%(%d, 1%%.50%%)", A.id)))
    local real = objects[T.live[A.id]]
    objects[T.live[A.id]] = { guid = real.guid, map = real.map, GetGUID = real.GetGUID, RemoveFromWorld = real.RemoveFromWorld }
    step(); cmd(gus, "build setscale 2")
    check("setscale: a realm without object sizes says so", last(gus):find("isn't supported") and A.s == 1.5)
    objects[T.live[A.id]] = real
    step(); cmd(gus, "build setscale 9")
    check("setscale: within limits", last(gus):find("Size goes from") and A.s == 1.5)
    cmd(gus, "build undo")
    check("undo a size", A.s == nil and sqlHas(string.format("^DELETE FROM mod_builder_prop_scale WHERE id = %d$", A.id)))
    gus.addon = {}
    serverEvents[30](30, gus, 7, "OVMOD", "wubuild\tcmd\t1/1\tnear", gus)
    check("state: exact numbers for the properties panel", gus.addon[#gus.addon][2]:find(string.format("pos=%.2f,%.2f,%.2f,90,1.00", A.x, A.y, A.z), 1, true))
    cmd(gus, "build undo"); cmd(gus, "build undo")

    -- dup and delete a group
    cmd(gus, "build selall")
    step(); cmd(gus, "build dup")
    check("group dup: copies of all three, selected", count(function(p) return p.owner == 60 end) == 6 and #T.group[60] == 3
        and T.group[60][1] ~= A.id)
    cmd(gus, "build undo")
    check("group dup undo", count(function(p) return p.owner == 60 end) == 3)
    cmd(gus, "build selall")
    cmd(gus, "build delete")
    check("group delete", count(function(p) return p.owner == 60 end) == 0 and last(gus):find("3 props removed"))
    cmd(gus, "build undo")
    check("group delete undo", count(function(p) return p.owner == 60 end) == 3 and T.props[A.id] and T.live[A.id])

    -- copy and paste around a point
    cmd(gus, "build selall")
    cmd(gus, "build copy")
    check("copy: the selection on the clipboard", T.clip[60] and #T.clip[60].rel == 3 and last(gus):find("Copied 3 props"))
    step(); cmd(gus, "build pasteat " .. at(gus, -10, -10) .. " 0")
    local pasted = T.group[60]
    check("paste at a point: three new props around it", count(function(p) return p.owner == 60 end) == 6 and pasted and #pasted == 3
        and (function()
            local sx, sy, mz = 0, 0, math.huge
            for _, id in ipairs(pasted) do local p = T.props[id]; sx = sx + p.x; sy = sy + p.y; mz = math.min(mz, p.z) end
            return near(sx / 3, AREA.x - 10) and near(sy / 3, AREA.y - 10) and near(mz, AREA.z) end)())
    cmd(gus, "build undo")
    check("paste undo: one entry", count(function(p) return p.owner == 60 end) == 3)
    clock = clock + 10
    cmd(gus, "build paste")
    check("paste with no name: at your feet", count(function(p) return p.owner == 60 end) == 6)
    cmd(gus, "build undo")
    clock = clock + 10
    T.clip[60] = nil
    cmd(gus, "build pasteat " .. at(gus, -10, -10))
    check("paste with nothing copied", last(gus):find("Nothing copied yet"))
end

-- M3: prefabs ------------------------------------------------------------------------------------------------------
do
    local gus = online[60]
    local hal = player({ guid = 61, name = "Hal", x = AREA.x + 15, y = AREA.y - 15 })
    cmd(gm, "build grant Hal")
    cmd(gus, "build selall")
    cmd(gus, "build prefab save Bad!")
    check("prefab: the name is checked", last(gus):find("Usage"))
    cmd(gus, "build prefab save Camp")
    local f = (function() for _, x in pairs(T.prefabs) do if x.owner == 60 then return x end end end)()
    local data = f and T.jsonDecode(f.data)
    check("prefab: saved from the selection as JSON", f and f.name == "camp" and data and data.v == 1 and data.name == "camp"
        and #data.props == 3 and data.props[1].e and sqlHas("^REPLACE INTO mod_builder_prefabs %(id, owner, owner_name, name, code, data, created_at%) VALUES %(%d+, 60, 'Gus', 'camp', NULL, '{\"v\":1"))
    check("prefab: offsets around its centre", (function()
        local sx, sy = 0, 0
        for _, e in ipairs(data.props) do sx = sx + e.x; sy = sy + e.y end
        return math.abs(sx) < 0.05 and math.abs(sy) < 0.05 end)())
    cmd(gus, "build prefab list")
    check("prefab: list", last(gus):find("camp %(3%)"))
    gus.addon = {}
    serverEvents[30](30, gus, 7, "OVMOD", "wubuild\tcmd\t1/1\tprefab list", gus)
    local pmsg
    for _, a in ipairs(gus.addon) do if a[2]:find("^wubuild\tprefabs\t") then pmsg = a[2] end end
    check("prefab: the window gets the list", pmsg and pmsg:find(f.id .. ",camp,%-,3$"))
    cmd(gus, "build prefab share camp")
    check("prefab: share gives a code", f.code and #f.code == 6 and last(gus):find(f.code, 1, true)
        and sqlHas("^UPDATE mod_builder_prefabs SET code = '" .. f.code .. "' WHERE id = " .. f.id .. "$"))
    step(); cmd(hal, "build prefab paste " .. f.code:lower())
    check("prefab: someone else pastes the code", count(function(p) return p.owner == 61 end) == 3 and last(hal):find("Pasted '" .. f.code .. "': 3 props"))
    cmd(hal, "build undo")
    clock = clock + 10
    cmd(hal, "build load " .. f.code)
    check("prefab: its code works in .build load too", count(function(p) return p.owner == 61 end) == 3)
    cmd(hal, "build undo")
    clock = clock + 10
    cmd(hal, "build prefab paste camp")
    check("prefab: names are per player", last(hal):find("No prefab 'camp'"))
    clock = clock + 10
    cmd(gus, "build prefab pasteat camp " .. at(gus, -12, -14) .. " 90")
    check("prefab: paste at a point, turned", count(function(p) return p.owner == 60 end) == 6 and #T.group[60] == 3)
    cmd(gus, "build undo")

    -- for other scripts (ov_workshop.lua)
    check("OVBuild is global", type(OVBuild) == "table" and type(OVBuild.ExportPrefab) == "function" and type(OVBuild.ImportPrefab) == "function")
    local json, info = OVBuild.ExportPrefab(f.id)
    check("ExportPrefab(id): JSON and info", json and json:find('^{"v":1,"name":"camp","props":%[') and info.count == 3
        and info.name == "camp" and info.ownerName == "Gus" and info.points == 3)
    check("ExportPrefab(code) works too; unknown is nil", OVBuild.ExportPrefab(f.code) == json and OVBuild.ExportPrefab(999999) == nil)
    clock = clock + 10
    local ok, newIds = OVBuild.ImportPrefab(json, hal, AREA.x + 12, AREA.y - 12, AREA.z, math.pi)
    check("ImportPrefab: pasted for the player, with an undo", ok == true and #newIds == 3 and count(function(p) return p.owner == 61 end) == 3
        and T.undo[61][#T.undo[61]].kind == "load")
    cmd(hal, "build undo")
    clock = clock + 10
    local okT = OVBuild.ImportPrefab(T.jsonDecode(json), hal)
    check("ImportPrefab: a table works, at your feet by default", okT == true and count(function(p) return p.owner == 61 end) == 3)
    cmd(hal, "build undo")
    clock = clock + 10
    local nobody = player({ guid = 63, name = "Ned", x = AREA.x, y = AREA.y })
    check("ImportPrefab: needs the builder role", OVBuild.ImportPrefab(json, nobody) == nil)
    check("ImportPrefab: rejects bad data", OVBuild.ImportPrefab("{\"props\":[{\"e\":2413,\"x\":1e999,\"y\":0,\"z\":0}]}", hal) == nil
        and OVBuild.ImportPrefab("not json", hal) == nil and OVBuild.ImportPrefab('{"props":[{"e":2413,"x":0,"y":0,"z":0}]} extra', hal) == nil
        and OVBuild.ImportPrefab('{"props":[{"e":2413,"x":90,"y":0,"z":0}]}', hal) == nil)
    local okU, whyU = OVBuild.ImportPrefab('{"props":[{"e":424242,"x":0,"y":0,"z":0}]}', hal)
    check("ImportPrefab: only props in this realm's catalog", okU == nil and whyU:find("on this realm"))
    local many = {}
    for i = 1, 61 do many[i] = '{"e":2413,"x":0,"y":0,"z":0}' end
    check("ImportPrefab: 60 props at most", OVBuild.ImportPrefab('{"props":[' .. table.concat(many, ",") .. ']}', hal) == nil)
    check("ImportPrefab: too far from the player", OVBuild.ImportPrefab(json, hal, AREA.x + 400, AREA.y, AREA.z) == nil)
    env.OV_BUILD_PER_PLAYER = "2"
    clock = clock + 10
    check("ImportPrefab: budgets apply", OVBuild.ImportPrefab(json, hal) == nil and last(hal):find("room for 2"))
    env.OV_BUILD_PER_PLAYER = nil
    check("ParsePrefab: counts without placing", OVBuild.ParsePrefab(json) == 3)
    local sid = OVBuild.SavePrefab(hal, "fromshop", json)
    check("SavePrefab: into the player's list", sid and T.prefabs[sid].owner == 61 and T.prefabs[sid].name == "fromshop"
        and #OVBuild.ListPrefabs(61) == 1 and OVBuild.ListPrefabs(61)[1].count == 3)
    check("the JSON reader: depth, nesting, escapes", T.jsonDecode('[[[[[[[[[1]]]]]]]]]') == nil
        and T.jsonDecode('{"a":"x\\"y","b":[1,2.5,-3e2],"c":true,"d":null}').a == 'x"y'
        and T.jsonDecode('{"b":[1,2.5,-3e2]}').b[3] == -300)
    cmd(hal, "build prefab delete fromshop")
    check("prefab delete", T.prefabs[sid] == nil and sqlHas("^DELETE FROM mod_builder_prefabs WHERE id = " .. sid .. "$"))
    local gus2 = online[60]
    step(); cmd(gus2, "build selall")
    for i = 1, 6 do cmd(gus2, "build prefab save spam" .. i) end
    check("plot and prefab changes: five a second", last(gus2):find("Slow down")
        and not (function() for _, x in pairs(T.prefabs) do if x.name == "spam6" then return true end end end)())
    step(); for i = 1, 5 do cmd(gus2, "build prefab delete spam" .. i) end
    check("(and the five are deleted again)", not (function() for _, x in pairs(T.prefabs) do if x.name:find("^spam") then return true end end end)())
end

-- M3: the op log and GM rollback ---------------------------------------------------------------------------------------
do
    local van = player({ guid = 62, name = "Van", x = AREA.x - 10, y = AREA.y - 25 })
    cmd(gm, "build grant Van")
    local ops0 = #T.oplog
    step(); cmd(van, "build spawnat chair " .. at(van, -10, -25))
    local v1 = T.selected[62]
    check("op log: a spawn is one op, stored", #T.oplog == ops0 + 1 and T.oplog[#T.oplog].op == "spawnat" and T.oplog[#T.oplog].name == "Van"
        and T.oplog[#T.oplog].rows[1].before == nil and T.oplog[#T.oplog].rows[1].after.entry == 2413
        and sqlHas("^INSERT INTO mod_builder_oplog %(op_id, guid, name, op, prop, before_state, after_state, at%) VALUES %(%d+, 62, 'Van', 'spawnat', " .. v1 .. ", '', '2413,0,"))
    step(); cmd(van, "build spawnat bench " .. at(van, -8, -25))
    local v2 = T.selected[62]
    step(); cmd(van, "build spawnat keg " .. at(van, -12, -25))
    local v3 = T.selected[62]
    cmd(van, "build selall")
    step(); cmd(van, "build move z 2")
    check("op log: a group move is one op with a row per prop", T.oplog[#T.oplog].op == "move" and #T.oplog[#T.oplog].rows == 3)
    cmd(van, "build pick " .. T.live[v1])
    cmd(van, "build delete")
    check("op log: deletes too", T.oplog[#T.oplog].op == "delete" and T.oplog[#T.oplog].rows[1].after == nil)
    cmd(van, "build rollback van 2")
    check("rollback is GM only", last(van):find("Only GMs"))
    cmd(gm, "build oplog van")
    check("GM: oplog lists the last changes", said(gm, "changes by van") and last(gm):find("spawnat, 1 prop"))
    cmd(gm, "build rollback van 2")
    check("GM rollback: the last 2 ops undone (delete, then the move)", T.props[v1] and T.live[v1] and near(T.props[v2].z, AREA.z)
        and near(T.props[v1].z, AREA.z) and last(gm):find("Rolled back 2 changes by van")
        and sqlHas("^UPDATE mod_builder_oplog SET undone = 1 WHERE op_id IN %(%d+,%d+%)$"))
    check("GM rollback: the restored prop keeps its owner", T.props[v1].owner == 62)
    check("GM rollback: the player's undo stack is cleared", T.undo[62] == nil)
    gm.x, gm.y = AREA.x + 300, AREA.y
    cmd(gm, "build rollback van 10")
    check("GM rollback: only near you", last(gm):find("No changes by van within 60 yards"))
    gm.x, gm.y = AREA.x, AREA.y
    cmd(gm, "build rollback van 10 120")
    check("GM rollback: the spawns undone too", not T.props[v1] and not T.props[v2] and not T.props[v3] and last(gm):find("Rolled back 3"))
    cmd(gm, "build rollback van 10")
    check("GM rollback: nothing left", last(gm):find("No changes by van"))
    check("rollback is logged as the GM's op", T.oplog[#T.oplog].op == "rollback" and T.oplog[#T.oplog].name == "Keeper")
end

-- M3: a restart reads plots, members, prefabs, tiers and sizes back ------------------------------------------------------
do
    local gus = online[60]
    cmd(gus, "build pick " .. T.live[(function() for _, p in pairs(T.props) do if p.owner == 60 then return p.id end end end)()])
    step(); cmd(gus, "build setscale 2")
    local scaled = T.selected[60]
    local pia = online[50]
    cmd(pia, "build plot claim")
    cmd(pia, "build plot add Vic visitor")
    cmd(gm, "build trust Nia master")
    local plotsBefore, prefabsBefore = {}, {}
    for id, pl in pairs(T.plots) do plotsBefore[#plotsBefore + 1] = { id, pl.owner, pl.ownerName, pl.area, pl.map, pl.x, pl.y, pl.z, pl.r } end
    local members = {}
    for id, pl in pairs(T.plots) do for g, m in pairs(pl.members) do members[#members + 1] = { id, g, m.name, m.role } end end
    for id, f in pairs(T.prefabs) do prefabsBefore[#prefabsBefore + 1] = { id, f.owner, f.ownerName, f.name, f.code or "", f.data } end
    propRows = {}
    for _, p in pairs(T.props) do propRows[#propRows + 1] = { p.id, p.owner, p.ownerName, p.area, p.entry, p.map, p.x, p.y, p.z, p.o } end
    roleRows = {}
    for g, r in pairs(T.roles) do roleRows[#roleRows + 1] = { g, r.name } end
    extraRows.mod_builder_plots = plotsBefore
    extraRows.mod_builder_plot_members = members
    extraRows.mod_builder_prefabs = prefabsBefore
    extraRows.mod_builder_trust = { { 54, 4 } }
    extraRows.mod_builder_prop_scale = { { scaled, 2 } }
    dofile(file)
    local T3 = OV_BUILD_TEST
    local plot3 = (function() for _, pl in pairs(T3.plots) do if pl.owner == 50 then return pl end end end)()
    check("restart: plots and their members", plot3 and plot3.members[52] and plot3.members[52].role == "visitor")
    check("restart: prefabs (with codes)", (function()
        for _, f in pairs(T3.prefabs) do if f.owner == 60 and f.name == "camp" and f.code then return true end end end)())
    check("restart: GM-set tiers", T3.trust[54] == 4 and T3.budgetOf(online[54]).tier == "master")
    check("restart: sizes", T3.props[scaled] and T3.props[scaled].s == 2)
    T = T3
    propRows, roleRows = nil, nil
    for k in pairs(extraRows) do extraRows[k] = nil end
end

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
