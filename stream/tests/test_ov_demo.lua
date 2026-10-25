-- Test ov_demo.lua (the Goldshire Inn guest pass) under a fake mod-ale:
--   lua5.1 tests/test_ov_demo.lua ../realm/custom/lua_scripts/ov_demo.lua
-- (tests/test_demo.py runs it.)
local script = assert(arg[1], "usage: lua5.1 test_ov_demo.lua <ov_demo.lua>")

local clock = 1000000
os.time = function() return clock end

local accounts = { [10] = "LYDEMO01", [11] = "LYDEMO02", [20] = "WR000123", [21] = "WR000456" }
local sql = {}
local function query(rows)
    if not rows then return nil end
    local i = 1
    return {
        GetUInt32 = function(_, c) return rows[i][c + 1] end,
        GetInt32 = function(_, c) return rows[i][c + 1] end,
        GetString = function(_, c) return tostring(rows[i][c + 1]) end,
        NextRow = function() i = i + 1; return rows[i] ~= nil end,
    }
end
function AuthDBExecute(s) sql[#sql + 1] = s end
function AuthDBQuery(s)
    sql[#sql + 1] = s
    local id = s:match("FROM account WHERE id = (%d+)")
    if id then return accounts[tonumber(id)] and query({ { accounts[tonumber(id)] } }) end
    local name = s:match("FROM account WHERE username = '(%w+)'")
    if name then
        for i, n in pairs(accounts) do if n == name then return query({ { i } }) end end
        return nil
    end
    return nil
end

local events = {}
function RegisterPlayerEvent(e, f) events[e] = events[e] or {}; table.insert(events[e], f) end
local function fire(e, ...)
    local result
    for _, f in ipairs(events[e] or {}) do
        local r = f(e, ...)
        if r ~= nil then result = r end
    end
    return result
end

local online = {}
function GetPlayersInWorld() return online end
function GetPlayerByName(n) for _, p in ipairs(online) do if p.name == n then return p end end end

local timers = {}
local nextId = 0
local P = {}
P.__index = P
function P:GetAccountId() return self.acct end
function P:IsGM() return self.gm end
function P:GetGUIDLow() return self.guid end
function P:GetGUID() return self.guid end
function P:GetName() return self.name end
function P:GetMapId() return self.map end
function P:GetX() return self.x end
function P:GetY() return self.y end
function P:GetZ() return self.z end
function P:Teleport(m, x, y, z, o) self.map, self.x, self.y, self.z = m, x, y, z; self.tp = self.tp + 1 end
function P:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
function P:SendAreaTriggerMessage(m) self.center[#self.center + 1] = m end
function P:KickPlayer() self.kicked = true end
function P:IsDead() return self.dead end
function P:ResurrectPlayer() self.dead = false end
function P:GetHealth() return self.hp end
function P:GetMaxHealth() return 100 end
function P:SetHealth(h) self.hp = h end
function P:GetGroup() return self.group end
function P:RegisterEvent(fn, delay, repeats)
    nextId = nextId + 1
    timers[#timers + 1] = { id = nextId, fn = fn, rep = repeats, p = self, alive = true }
    return nextId
end
function P:RemoveEventById(id) for _, t in ipairs(timers) do if t.id == id then t.alive = false end end end

local guidN = 0
local function player(acct, name, x, y, opts)
    opts = opts or {}
    guidN = guidN + 1
    local p = setmetatable({ acct = acct, name = name, guid = guidN, gm = opts.gm or false, map = opts.map or 0,
        x = x or 0, y = y or 0, z = opts.z or 57, msgs = {}, center = {}, tp = 0, hp = 40, dead = false }, P)
    online[#online + 1] = p
    return p
end

-- Run every live timer once (repeating ones stay; one-shots go).
local function runTimers()
    local list = timers
    timers = {}
    for _, t in ipairs(list) do
        if t.alive and not t.p.kicked then
            t.fn(t.id, 0, 0, t.p)
            if t.rep == 0 and t.alive then timers[#timers + 1] = t end
        end
    end
end

local replies
local handler = { SendSysMessage = function(_, m) replies[#replies + 1] = m end }
local function console(cmd)
    replies = {}
    local r = fire(42, nil, cmd, handler)
    return r, table.concat(replies, "\n")
end

local passed, failed = 0, 0
local function check(name, ok, extra)
    if ok then passed = passed + 1; print("PASS " .. name)
    else failed = failed + 1; print("FAIL " .. name .. " " .. tostring(extra or "")) end
end
local function has(list, pat) for _, m in ipairs(list) do if m:find(pat, 1, true) then return true end end return false end

dofile(script)
local T = OV_DEMO_TEST
check("loads and creates its table", sql[1] and sql[1]:find("CREATE TABLE IF NOT EXISTS ov_demo_passes", 1, true))

-- console
local r, out = console("ovdemo begin LYDEMO01 1200")
check("begin answers ok", r == false and out:find("ovdemo ok", 1, true), out)
check("begin stores the pass", sql[#sql]:find("REPLACE INTO ov_demo_passes", 1, true) and sql[#sql]:find("(10, UNIX_TIMESTAMP() + 1200)", 1, true), sql[#sql])
_, out = console("ovdemo begin WR000123 1200")
check("begin refuses a normal account", out:find("usage", 1, true), out)
_, out = console("ovdemo begin LYDEMO01 99999")
check("begin refuses a long pass", out:find("usage", 1, true), out)
_, out = console("ovdemo begin LYDEMO77 600")
check("begin: unknown account", out:find("no such account", 1, true), out)
check("other console commands pass through", console("server info") == nil)

-- login of a guest with an open pass
local g = player(10, "Visitoraa", -9000, 300)
fire(3, g)
runTimers()
check("guest brought to the inn", g.tp == 1 and g.map == 0 and g.x == T.INN[2] and g.y == T.INN[3], g.x .. "," .. g.y)
check("guest healed", g.hp == 100)
runTimers()
check("welcome banner", has(g.center, "Welcome to Leyline") and has(g.msgs, "Goldshire Inn"))
check("free-account line with the link", has(g.msgs, "Make a free account to keep playing: " .. T.SIGNUP_URL))
check("signup link is the website", T.SIGNUP_URL == "https://play.openvanilla.app/login?next=%2Fwrath")
check("inside the inn", T.inInn(g))

-- leaving the radius
g.x = g.x - 80
runTimers()   -- the watch sees it and queues the trip back
runTimers()
check("walked out: brought back", g.tp == 2 and T.inInn(g), g.tp)
check("told why", has(g.center, "stays in the Goldshire Inn"))
g.map, g.x, g.y = 571, 5800, 600
fire(28, g)
runTimers()
check("another map (a boost, a hearthstone): brought back", g.map == 0 and T.inInn(g))

-- trade, mail, groups, chat
local n = player(20, "Normal", -9460, 20)
local n2 = player(21, "Other", -9460, 20)
check("guest can't trade", fire(48, g, n) == false)
check("nobody can trade a guest", fire(48, n, g) == false)
check("normal players still trade", fire(48, n, n2) == true)
check("guest can't mail", fire(49, g, 1) == false)
check("normal players still mail", fire(49, n, 1) == true)
check("guest can't invite", fire(51, g, "Normal") == false)
check("nobody can invite a guest", fire(51, n, "Visitoraa") == false)
check("normal players still invite", fire(51, n, "Other") == true)
check("guest can't whisper", fire(19, g, "hi", 7, 0, n) == false)
check("whispers to a guest are dropped", fire(19, n, "hi", 7, 0, g) == false)
check("normal whispers untouched", fire(19, n, "hi", 7, 0, n2) == nil)
check("guest can't use channels", fire(22, g, "hi", 17, 0, 1) == false)
check("guest can't guild or party chat", fire(21, g, "hi") == false and fire(20, g, "hi") == false)
check("guest can't yell", fire(18, g, "HI", 6, 0) == false)
check("guest can say", fire(18, g, "hello", 1, 0) == nil)
check("normal players can yell", fire(18, n, "HI", 6, 0) == nil)
check("refusals point at a free account", has(g.msgs, "are off on guest passes. Make a free account"))

-- normal players are never touched
n.msgs = {}
fire(3, n)
runTimers()
check("normal player not moved", n.tp == 0 and #n.msgs == 0 and not n.kicked)

-- a GM on a guest account is not held
local gm = player(11, "Gmtest", -9000, 300, { gm = true })
console("ovdemo begin LYDEMO02 600")
fire(3, gm)
runTimers()
check("GM not held", gm.tp == 0 and not gm.kicked)

-- the pass's end
clock = clock + 1200 - 100
runTimers()
check("two-minute warning", has(g.center, "Two minutes left"))
clock = clock + 200
runTimers()
runTimers()
check("pass over: logged out", g.kicked)
check("thanks and the link", has(g.msgs, "Your guest pass has ended") and has(g.msgs, T.SIGNUP_URL))

-- a guest account with no open pass
local late = player(11, "Visitorab", -9460, 20)
_, out = console("ovdemo end LYDEMO02")
check("end logs the guest account out", gm.kicked and out:find("logged out", 1, true), out)
late.kicked = false
fire(3, late)
runTimers()
check("no pass: logged out at once", late.kicked)
check("end deletes the row", sql[#sql - 0] and table.concat(sql, "\n"):find("DELETE FROM ov_demo_passes WHERE account_id = 11", 1, true))

-- logout forgets the guest: a new login starts clean
fire(4, g)
console("ovdemo begin LYDEMO01 600")
g.kicked, g.tp, g.x = false, 0, -9000
fire(3, g)
runTimers()
check("after logout, a new visit starts in the inn", g.tp == 1 and not g.kicked)

-- no game-brand names in anything a player sees
local all = {}
for _, p in ipairs(online) do
    for _, m in ipairs(p.msgs) do all[#all + 1] = m end
    for _, m in ipairs(p.center) do all[#all + 1] = m end
end
local bad = {}
for _, m in ipairs(all) do
    local l = m:lower()
    for _, w in ipairs({ "world of warcraft", "warcraft", "lich king", "blizzard", "openvanilla", "open vanilla", "openwow" }) do
        if l:find(w, 1, true) and not l:find("play.openvanilla.app", 1, true) then bad[#bad + 1] = m end
    end
    if (" " .. l .. " "):find("[^%a]wow[^%a]") then bad[#bad + 1] = m end
end
check("no game-brand or old names in player messages", #bad == 0, table.concat(bad, " | "))

print(string.format("\n%d/%d passed", passed, passed + failed))
os.exit(failed == 0 and 0 or 1)
