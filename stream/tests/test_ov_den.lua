-- lua5.1 stream/tests/test_ov_den.lua [ov_den.lua] [ov_build.lua] [ov_modapi.lua]
-- A Den (OV_DEN=1, realm/profiles/den.env): ov_build.lua's one build area on the island, and ov_den.lua under a fake
-- mod-ale: the room going up from catalog props owned by the Den (free, owner-only), new characters starting in it,
-- the edge putting people back, owner / builder / visitor, the room and yard budgets, the invite link (owner only,
-- read as data), the room's looks, the whole Den as a layout, and no game-brand names anywhere players see.
local denFile = arg[1] or "realm/custom/lua_scripts/ov_den.lua"
local buildFile = arg[2] or denFile:gsub("ov_den%.lua$", "ov_build.lua")
local modapi = arg[3] or denFile:gsub("ov_den%.lua$", "ov_modapi.lua")

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end
print = function() end

local clock = 2000000
os.time = function() return clock end
local env = { OV_DEN = "1" }
os.getenv = function(k) return env[k] end

-- ---------------------------------------------------------------- fake world
local events, luaEvents = {}, {}
function RegisterPlayerEvent(id, fn) events[id] = events[id] or {}; table.insert(events[id], fn) end
function RegisterServerEvent() end
function CreateLuaEvent(fn, delay, rep) luaEvents[#luaEvents + 1] = { fn = fn, delay = delay, rep = rep } end
local function fire(id, ...) local r; for _, fn in ipairs(events[id] or {}) do local x = fn(id, ...); if x ~= nil then r = x end end; return r end

local objects, nextGuid = {}, 9000
local maps = {}
local GROUND = 12.6
local function mapObj(id)
    maps[id] = maps[id] or { id = id, GetWorldObject = function(self, g) local o = objects[g]; if o and o.map == self.id then return o end end,
        IsDungeon = function() return false end, GetHeight = function() return GROUND end }
    return maps[id]
end
function GetMapById(id) return mapObj(id) end
function PerformIngameSpawn(kind, entry, map, inst, x, y, z, o, save)
    if kind ~= 2 or save then return nil end
    nextGuid = nextGuid + 1
    local go = { guid = nextGuid, entry = entry, map = map, x = x, y = y, z = z, o = o }
    function go:GetGUID() return self.guid end
    function go:RemoveFromWorld() objects[self.guid] = nil end
    function go:SetScale(s) self.scale = s end
    objects[go.guid] = go
    return go
end
function GetGUIDLow(g) return g end

local sqlLog = {}
function CharDBExecute(sql) sqlLog[#sqlLog + 1] = sql end
function CharDBQuery() return nil end
function WorldDBQuery(sql)
    local rows = {}
    for id in sql:match("IN %(([%d,]+)%)"):gmatch("%d+") do rows[#rows + 1] = { id } end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end

local online, allMsgs = {}, {}
function GetPlayerByName(n) for _, p in pairs(online) do if p.name:lower() == n:lower() then return p end end end
function GetPlayersInWorld() local t = {}; for _, p in pairs(online) do t[#t + 1] = p end; table.sort(t, function(a, b) return a.guid < b.guid end); return t end
local function player(over)
    local p = { msgs = {}, addon = {}, gm = 0, gmOn = false, map = 0, x = -8949, y = -132, z = 83, o = 0, teleports = 0 }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m; allMsgs[#allMsgs + 1] = m end
    function p:SendAddonMessage(prefix, msg) self.addon[#self.addon + 1] = msg end
    function p:GetGUIDLow() return self.guid end
    function p:GetName() return self.name end
    function p:GetGMRank() return self.gm end
    function p:IsGM() return self.gmOn end
    function p:GetMapId() return self.map end
    function p:GetMap() return mapObj(self.map) end
    function p:GetX() return self.x end
    function p:GetY() return self.y end
    function p:GetZ() return self.z end
    function p:GetO() return self.o end
    function p:Teleport(m, x, y, z, o) self.map, self.x, self.y, self.z, self.o = m, x, y, z, o; self.teleports = self.teleports + 1; return true end
    function p:SetBindPoint(x, y, z, m, a) self.bind = { x = x, y = y, z = z, map = m, area = a } end
    function p:RegisterEvent(fn) fn(1, 0, 1, self); return 1 end
    online[p.guid] = p
    return p
end
local function last(p) return p.msgs[#p.msgs] or "" end
local function cmd(p, text) return fire(42, p, text) end
local function said(p, pat) for _, m in ipairs(p.msgs) do if m:find(pat) then return true end end end
local function sqlHas(pat) for _, s in ipairs(sqlLog) do if s:find(pat) then return true end end end
local function addonHas(p, pat) for _, m in ipairs(p.addon) do if m:find(pat) then return true end end end

package.preload["ov_modapi"] = function() return dofile(modapi) end
dofile(buildFile)
local T = assert(OV_BUILD_TEST)
local buildEvents = {}
for id, list in pairs(events) do buildEvents[id] = { unpack(list) } end
-- a Lua reload of ov_den.lua replaces its handlers (mod-ale reloads every script): the same here
local function loadDen()
    for id in pairs(events) do events[id] = buildEvents[id] and { unpack(buildEvents[id]) } or nil end
    local keep = {}
    for _, e in ipairs(luaEvents) do if e.delay ~= 2000 then keep[#keep + 1] = e end end
    luaEvents = keep
    dofile(denFile)
end
loadDen()
local D = assert(OV_DEN_TEST, "ov_den.lua loads with OV_DEN=1")
local DEN = T.DEN

local function roomProps() local n = 0; for _, p in pairs(T.props) do if p.owner == 0 then n = n + 1 end end; return n end
local function tick() for _, e in ipairs(luaEvents) do if e.delay == 2000 then e.fn() end end end

-- ---------------------------------------------------------------- the Den's area
check("a Den: the realm's one build area, on the island (map 1, game_tele 424)", #T.BUILD_AREAS == 1 and DEN and DEN.map == 1
    and math.abs(DEN.x - 16226.2) < 0.01 and math.abs(DEN.y - 16257.0) < 0.01 and T.BUILD_AREAS[1].name == "Your Den")
check("the room (half 12) sits inside the Den's edge", DEN.half == 12 and DEN.r > DEN.half * math.sqrt(2))
check("an edge check every 2 seconds", (function() for _, e in ipairs(luaEvents) do if e.delay == 2000 and e.rep == 0 then return true end end end)())

-- ---------------------------------------------------------------- a new character: the owner
local own = player({ guid = 1, name = "Owner", gm = 3 })
fire(30, own)
check("first login: the hearth is set in the Den", own.bind and own.bind.map == 1 and math.abs(own.bind.x - DEN.x) < 0.01)
check("first login: into the room", own.map == 1 and math.abs(own.x - DEN.x) < 0.01 and said(own, "Welcome to the Den"))
fire(3, own)
check("the room goes up when someone is there", roomProps() > 40 and roomProps() == #D.plan(D.THEMES.white, GROUND))
check("the floor height is measured once and kept", D.settings.floor == string.format("%.2f", GROUND) and DEN.floorZ == GROUND
    and sqlHas("^REPLACE INTO mod_den_settings %(k, v%) VALUES %('floor'"))
check("the room's pieces: catalog props, inside the Den, owned by the Den", (function()
    local ids = {}
    for _, c in ipairs(T.CATALOG()) do ids[c.id] = true end
    for _, p in pairs(T.props) do
        if p.owner == 0 and not (ids[p.entry] and T.areaAt(p.map, p.x, p.y, p.z) == DEN.key and p.ownerName == "Den") then return false end
    end
    return true end)())
check("the south wall keeps a doorway", (function()
    for _, e in ipairs(D.plan(D.THEMES.white, GROUND)) do
        if math.abs(e.y - (DEN.y - DEN.half)) < 0.01 and math.abs(e.x - DEN.x) < 3 then return false end
    end
    return true end)())
fire(3, own)
check("only once", roomProps() == #D.plan(D.THEMES.white, GROUND))
check("the room is free: no one's budget, not the area's prop count", (function()
    local i = T.X.denUsage(); return i == 0 end)())

-- ---------------------------------------------------------------- roles
local bea = player({ guid = 2, name = "Bea", map = 1, x = DEN.x + 2, y = DEN.y + 2, z = GROUND })
local vic = player({ guid = 3, name = "Vic", map = 1, x = DEN.x - 2, y = DEN.y - 2, z = GROUND })
fire(3, bea); fire(3, vic)
cmd(vic, "den")
check(".den: visitors look around", said(vic, "You're visiting"))
cmd(vic, "build spawn chair")
check("visitors don't build", last(vic):find("builder role"))
cmd(bea, "den allow Vic build")
check("only the owner allows", last(bea):find("Only the Den's owner"))
cmd(own, "den allow Bea build")
check(".den allow <name> build: a builder (the builder role)", T.roles[2] and last(own):find("Bea can build here now") and said(bea, "You can build here now"))
check("the Den bar hears the builders", addonHas(own, "^wuden\tinfo\t1/1\trole=owner;theme=white;builders=Bea;invite=0$"))
cmd(own, "den builders")
check(".den builders", last(own):find("Bea"))
cmd(own, "den allow Nobody build")
check("a builder must be online to add", last(own):find("isn't online"))

clock = clock + 2
own.x, own.y = DEN.x + 4, DEN.y
cmd(own, "build spawn table")
local ownTable = T.props[T.selected[1]]
check("the owner builds", ownTable and ownTable.owner == 1)
check("state: den role and the two budgets", addonHas(own, ";den=owner;room=1/1000;yard=0/300"))
clock = clock + 2
cmd(bea, "build pick " .. T.live[ownTable.id])
cmd(bea, "build move z 1")
check("builders decorate together: Bea moves the owner's table", math.abs(ownTable.z - (GROUND + 1)) < 1e-6 or math.abs(ownTable.z - (own.z + 1)) < 1e-6)
-- a wall: the owner may, a builder may not
local wall
for _, p in pairs(T.props) do if p.owner == 0 and p.entry == 188142 and p.z > GROUND + 1 then wall = p; break end end
cmd(bea, "build pick " .. T.live[wall.id])
check("a builder can't pick the room's walls", last(bea):find("part of the room"))
cmd(own, "build pick " .. T.live[wall.id])
clock = clock + 2
local wz = wall.z
cmd(own, "build move z 0.5")
check("the owner can", math.abs(wall.z - wz - 0.5) < 1e-6)
cmd(own, "build undo")
cmd(own, "den allow Bea view")
check(".den allow <name> view: looking only", T.roles[2] == nil and said(bea, "not build any more"))
cmd(own, "den allow Bea build")

-- ---------------------------------------------------------------- budgets: room and yard
env.OV_DEN_INSIDE_POINTS = "3"
bea.x, bea.y = DEN.x - 6, DEN.y + 6
for i = 1, 3 do clock = clock + 2; cmd(bea, "build spawn chair") end
check("the room's budget: everyone's props together", last(bea):find("room's decor budget is full %(3 of 3"))
env.OV_DEN_OUTSIDE_POINTS = "1"
bea.x, bea.y = DEN.x, DEN.y + DEN.half + 6     -- out in the yard
clock = clock + 2; cmd(bea, "build spawn chair")
check("the yard has its own budget", T.props[T.selected[2]] and T.props[T.selected[2]].y > DEN.y + DEN.half)
clock = clock + 2; cmd(bea, "build spawn chair")
check("and it fills too", last(bea):find("yard's decor budget is full"))
env.OV_DEN_INSIDE_POINTS, env.OV_DEN_OUTSIDE_POINTS = nil, nil
cmd(own, "den budget")
check(".den budget", last(own):find("the room %d+ of 1000 points, the yard %d+ of 300"))

-- ---------------------------------------------------------------- the edge
vic.x = DEN.x + 200
tick()
check("out of the Den: back in the room", vic.map == 1 and math.abs(vic.x - DEN.x) < 0.01 and last(vic):find("edge of the Den"))
vic.map, vic.x = 0, -8949
tick()
check("another map: back in the room (after a short wait)", vic.map == 0)
clock = clock + 5
tick()
check("another map: back in the room", vic.map == 1)
clock = clock + 5
vic.z = GROUND - 30
tick()
check("fell through the floor: back", vic.z > GROUND)
own.gmOn, own.x = true, DEN.x + 500
clock = clock + 5
tick()
check("a GM with .gm on goes where they like", own.x == DEN.x + 500)
own.gmOn = false
tick()
check("and is back with .gm off", math.abs(own.x - DEN.x) < 0.01)
cmd(vic, "den home")
check(".den home", last(vic):find("Back in the room"))

-- ---------------------------------------------------------------- the invite link
cmd(vic, "den invite")
check("only the owner sees the invite link", last(vic):find("Only the Den's owner"))
cmd(own, "den invite")
check("no link file: where to find it", last(own):find("Host page") and last(own):find("invite.txt"))
local tmp = os.tmpname()
local link = "https://relay.example.app/join/abcdefghij234567#ABCDEFGH23456789XYZQ"
local f = io.open(tmp, "w"); f:write('return { invite = "' .. link .. '" }\n'); f:close()
env.OV_DEN_INVITE_FILE = tmp
loadDen()
D = OV_DEN_TEST
own.addon = {}
cmd(own, "den invite")
check(".den invite: the link, for the owner", said(own, link:gsub("%p", "%%%0")) and addonHas(own, "^wuden\tinvite\t1/1\t" .. link:gsub("%p", "%%%0") .. "$"))
check("the Den bar knows there is a link", addonHas(own, "invite=1$"))
f = io.open(tmp, "w"); f:write('os.execute("rm -rf /") return { invite = "javascript:alert(1)" }\n'); f:close()
own.msgs = {}
cmd(own, "den invite")
check("the file is data: anything but a join link is ignored", not said(own, "javascript") and last(own):find("Host page"))
os.remove(tmp)
env.OV_DEN_INVITE_FILE = nil

-- ---------------------------------------------------------------- the room's look
local before = roomProps()
cmd(bea, "den room stone")
check("only the owner changes the room", last(bea):find("Only the Den's owner"))
cmd(own, "den room stone")
check(".den room stone: rebuilt in another look", D.settings.theme == "stone" and roomProps() == #D.plan(D.THEMES.stone, GROUND)
    and (function() for _, p in pairs(T.props) do if p.owner == 0 and p.entry == 19444 then return true end end end)())
cmd(own, "den room clear")
check(".den room clear: down, decor stays", roomProps() == 0 and ownTable and T.props[ownTable.id])
fire(3, own); tick()
check("and it stays down until rebuilt", roomProps() == 0)
cmd(own, "den room rebuild")
check(".den room rebuild", roomProps() == #D.plan(D.THEMES.stone, GROUND) and D.settings.cleared == nil)
cmd(own, "den room white")
check("back to white", roomProps() == before)

-- ---------------------------------------------------------------- the whole Den as a layout
local function decor() local n = 0; for _, p in pairs(T.props) do if p.owner ~= 0 then n = n + 1 end end; return n end
local n0 = decor()
own.x, own.y, own.z = DEN.x, DEN.y, GROUND
cmd(own, "den save home")
check(".den save: everyone's decor, not the room", T.X.layouts[1].home and select(2, T.X.layouts[1].home:gsub("|", "")) + 1 == n0)
cmd(bea, "build selall 40")
clock = clock + 2; cmd(bea, "build delete")
clock = clock + 10
cmd(own, "den load home replace")
check(".den load <name> replace: the Den as saved (the owner's now)", decor() == n0 and roomProps() == before and last(own):find("Pasted 'layout home'"))
cmd(bea, "den load home replace")
check("replace is the owner's", last(bea):find("Only the owner"))
cmd(own, "den layouts")
check(".den layouts", last(own):find("home"))

-- ---------------------------------------------------------------- the addon hint, any object in a Den
do
    local desk = player({ guid = 8, name = "Desk", map = 1, x = DEN.x, y = DEN.y, z = GROUND })
    local web = player({ guid = 9, name = "Web", map = 1, x = DEN.x + 1, y = DEN.y, z = GROUND })
    fire(3, desk); fire(3, web)
    OVMod.Dispatch(web, "wuden", "info", "")      -- the addon asks for the Den's info when it loads
    tick()
    check("addon hint: not before a while", not said(desk, "Leyline UI addon"))
    clock = clock + D.ADDON_WAIT
    tick()
    check("addon hint: a player whose game has no addon hears where to get it", said(desk, "Leyline UI addon")
        and said(desk, "launcher") and said(desk, ".build help"))
    check("addon hint: not for a player with the addon", not said(web, "Leyline UI addon"))
    local n = #desk.msgs
    clock = clock + 60; tick()
    check("addon hint: once", #desk.msgs == n)
    check("a Den places any object and any model by default", T.X.anyOn() and T.X.modelsWanted())
    online[8], online[9] = nil, nil
end

-- ---------------------------------------------------------------- a seamless floor from the models' bounds
do
    local function u32(n) return string.char(n % 256, math.floor(n / 256) % 256, math.floor(n / 65536) % 256, math.floor(n / 16777216) % 256) end
    local function f32(v)
        if v == 0 then return u32(0) end
        local sign = v < 0 and 2147483648 or 0
        v = math.abs(v)
        local e = math.floor(math.log(v) / math.log(2))
        return u32(sign + (e + 127) * 8388608 + math.floor((v / 2 ^ e - 1) * 8388608 + 0.5))
    end
    -- display 777: a block 2 x 2 yards, 1 tall from its base
    local name = "World\\Generic\\Block.m2\0"
    local rec = u32(777) .. u32(1) .. string.rep(u32(0), 10) .. f32(-1) .. f32(-1) .. f32(0) .. f32(1) .. f32(1) .. f32(1) .. u32(0)
    local path = os.tmpname()
    local fh = io.open(path, "wb"); fh:write("WDBC" .. u32(1) .. u32(19) .. u32(76) .. u32(1 + #name) .. rec .. "\0" .. name); fh:close()
    env.OV_BUILD_DBC = path
    T.X.dbc = nil
    local floorItem = T.X.known(D.THEMES.white.floor)
    local before = floorItem.display
    floorItem.display = 777
    local plan = D.plan(D.THEMES.white, GROUND)
    local fl, wl = plan[1], nil
    for _, e in ipairs(plan) do if math.abs(e.y - (DEN.y + DEN.half)) < 0.01 then wl = e; break end end
    check("with the models' bounds: floor blocks sized to one tile (2 yards -> size 2 for 4-yard tiles)", fl.s == 2)
    check("with the models' bounds: the floor's top is level with the ground", math.abs(fl.z + 2 * 1 - GROUND) < 0.001)
    check("with the models' bounds: walls stand on the floor", wl and wl.s == 2 and math.abs(wl.z - GROUND) < 0.001)
    floorItem.display = before
    env.OV_BUILD_DBC = nil
    T.X.dbc = nil
    os.remove(path)
    check("without them: blocks at their own size on the ground", D.plan(D.THEMES.white, GROUND)[1].s == nil
        and D.plan(D.THEMES.white, GROUND)[1].z == GROUND)
end

-- ---------------------------------------------------------------- brand words, tables
local BANNED = { "world of warcraft", "warcraft", "lich king", "blizzard", "openvanilla", "open vanilla", "openwow" }
check("no game-brand names in anything players saw", (function()
    for _, m in ipairs(allMsgs) do
        local l = m:lower()
        for _, w in ipairs(BANNED) do if l:find(w, 1, true) then return false end end
        if l:find("%f[%a]wow%f[%A]") then return false end
    end
    return true end)())
check("SQL only on the scripts' own tables", (function()
    for _, s in ipairs(sqlLog) do
        local t = s:match("INTO%s+(%S+)") or s:match("^UPDATE%s+(%S+)") or s:match("FROM%s+(%S+)") or s:match("EXISTS%s+(%S+)")
        if not t or not (t:match("^mod_builder_") or t:match("^mod_den_")) then return false end
    end
    return true end)())

-- ---------------------------------------------------------------- not a Den
env.OV_DEN = nil
OV_DEN_TEST = nil
events = {}
dofile(buildFile)
dofile(denFile)
check("OV_DEN unset: ov_den.lua does nothing", OV_DEN_TEST == nil and events[30] == nil)
check("OV_DEN unset: the Builder's areas as before", OV_BUILD_TEST.DEN == nil and OV_BUILD_TEST.BUILD_AREAS[1].map == 0)

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
