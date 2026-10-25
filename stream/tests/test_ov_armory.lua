-- lua5.1 tests/test_ov_armory.lua ../realm/custom/lua_scripts/ov_armory.lua
-- The web armory opt-out (.armory off / on / privacy) under a fake mod-ale, plus the item search still working.
local file = assert(arg[1], "ov_armory.lua")
local events, server = {}, {}
local clock = 1000000
os.time = function() return clock end
local env = {}
os.getenv = function(k) return env[k] end

-- a fake characters database: the privacy rows, and every statement seen
local privacy, executed, worldQueries = {}, {}, {}
function CharDBExecute(sql)
    executed[#executed + 1] = sql
    local g, h, t = sql:match("^REPLACE INTO ov_armory_privacy %(guid, hidden, changed_at%) VALUES %((%d+), (%d+), (%d+)%)$")
    if g then privacy[tonumber(g)] = { hidden = tonumber(h), at = tonumber(t) } end
end
local function result(rows)
    if #rows == 0 then return nil end
    local i = 1
    return { GetUInt32 = function(_, c) return rows[i][c + 1] end, GetString = function(_, c) return tostring(rows[i][c + 1]) end,
             NextRow = function() i = i + 1; return i <= #rows end }
end
function CharDBQuery(sql)
    local g = sql:match("^SELECT hidden FROM ov_armory_privacy WHERE guid = (%d+)$")
    if g then
        local r = privacy[tonumber(g)]
        return r and result({ { r.hidden } }) or nil
    end
    return result({ { 0 } })
end
function WorldDBQuery(sql)
    worldQueries[#worldQueries + 1] = sql
    return result({ { 40343, "Armageddon", 4, 264 } })
end
function RegisterPlayerEvent(id, fn) events[id] = fn end
function RegisterServerEvent(id, fn) server[id] = fn end

dofile(file)
local T = assert(OV_ARMORY_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local BANNED = { "world of warcraft", "wow", "warcraft", "lich king", "blizzard", "openvanilla", "open vanilla", "openwow" }
local allMsgs = {}

local function player(over)
    local p = { msgs = {}, addon = {} }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m; allMsgs[#allMsgs + 1] = m end
    function p:SendAddonMessage(prefix, m) self.addon[#self.addon + 1] = m end
    function p:GetGUIDLow() return self.guid end
    function p:GetAccountName() return self.accName or "PLAYER" end
    function p:GetLevel() return self.level or 80 end
    function p:GetZoneId() return self.zone or 4395 end
    function p:GetMap() return { IsArena = function() return false end, IsBattleground = function() return false end } end
    if p.bot then function p:IsPlayerbot() return true end end
    return p
end
local function cmd(p, c) return events[42](42, p, c) end
local function last(p) return p.msgs[#p.msgs] or "" end

check("registers the command hook", type(events[42]) == "function")
local made = false
for _, s in ipairs(executed) do if s:find("CREATE TABLE IF NOT EXISTS ov_armory_privacy", 1, true) then made = true end end
check("creates the privacy table on load", made)

-- off
local a = player({ guid = 7 })
check(".armory off: handled", cmd(a, ".armory off") == false)
check(".armory off: stored hidden", privacy[7] and privacy[7].hidden == 1 and privacy[7].at == clock)
check(".armory off: says so, and how to undo", last(a):find("hidden from the web armory", 1, true) and last(a):find(".armory on", 1, true))
check(".armory off: no item search", #worldQueries == 0)
check("webHidden: true after off", T.webHidden(a) == true)

-- privacy readout
cmd(a, "armory privacy")
check(".armory privacy: says hidden", last(a):find("hidden", 1, true) ~= nil)

-- rate: one change per 5 s
cmd(a, ".armory on")
check("a second change within 5 s waits", privacy[7].hidden == 1 and last(a):find("5 seconds", 1, true))
clock = clock + 5
cmd(a, ".ARMORY ON")
check(".armory on (any case): shown again", privacy[7].hidden == 0)
check(".armory on: says so", last(a):find("back on the web armory", 1, true) ~= nil)
check("webHidden: false after on", T.webHidden(a) == false)
cmd(a, "armory privacy")
check(".armory privacy: says shown", last(a):find("shown", 1, true) ~= nil)

-- never set: shown (the default), no row
local b = player({ guid = 8 })
check("no row: shown by default", T.webHidden(b) == false and privacy[8] == nil)

-- the guid is a number from the core, the SQL holds nothing typed by the player
clock = clock + 10
local c = player({ guid = 9 })
cmd(c, ".armory off'; DROP TABLE characters; --")
check("odd text after off is not an opt-out (and not SQL)", privacy[9] == nil)
local injected = false
for _, q in ipairs(executed) do if q:find("DROP", 1, true) then injected = true end end
for _, q in ipairs(worldQueries) do if q:find(";", 1, true) or q:find("off' ", 1, true) then injected = true end end
check("no injected SQL anywhere (the search doubles quotes, drops semicolons)", not injected)

-- bots: nothing happens, nothing is said
local rb = player({ guid = 20, accName = "RNDBOT0042" })
cmd(rb, ".armory off")
check("RNDBOT account: ignored", privacy[20] == nil and #rb.msgs == 0)
local pb = player({ guid = 21, bot = true })
cmd(pb, ".armory off")
check("IsPlayerbot: ignored", privacy[21] == nil and #pb.msgs == 0)
check("isBot", T.isBot(rb) and T.isBot(pb) and not T.isBot(a))

-- the item search still works, and the help names the new commands
clock = clock + 10
local s = player({ guid = 30 })
local before = #worldQueries
cmd(s, ".armory armageddon")
check("item search still runs", #worldQueries == before + 1 and last(s):find("Armageddon", 1, true))
cmd(s, ".armory")
check("help lists .armory off / on", last(s):find(".armory off", 1, true) and last(s):find(".armory on", 1, true))
check("other commands pass by", events[42](42, s, ".help") == nil)

check("no forbidden names in anything players saw", (function()
    for _, m in ipairs(allMsgs) do
        local l = m:lower()
        for _, w in ipairs(BANNED) do
            if l:find(w, 1, true) and not (w == "wow" and not l:find("%f[%a]wow%f[%A]")) then return false end
        end
    end
    return true end)())

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
