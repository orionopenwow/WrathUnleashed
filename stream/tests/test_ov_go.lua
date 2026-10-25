-- lua5.1 stream/tests/test_ov_go.lua realm/custom/lua_scripts/ov_go.lua
local file = assert(arg[1], "ov_go.lua")
local events = {}
local clock = 1000000
os.time = function() return clock end
function RegisterPlayerEvent(id, fn) events[id] = fn end

-- a fake auth / world database
local auth = { accounts = { PLAYER = 42, OTHER = 43 }, intents = {}, sql = {} }
local function rows(list)
    local i = 1
    if #list == 0 then return nil end
    local q = {}
    function q:GetString(c) return tostring(list[i][c + 1]) end
    function q:GetUInt32(c) return tonumber(list[i][c + 1]) end
    function q:GetInt32(c) return tonumber(list[i][c + 1]) end
    function q:GetFloat(c) return tonumber(list[i][c + 1]) end
    function q:NextRow() i = i + 1; return i <= #list end
    return q
end
function AuthDBExecute(sql)
    auth.sql[#auth.sql + 1] = sql
    local id, go, secs = sql:match("VALUES %((%d+), '([^']*)', UNIX_TIMESTAMP%(%) %+ (%d+)%)")
    if id then auth.intents[tonumber(id)] = { go = go, exp = clock + tonumber(secs) } end
    local del = sql:match("DELETE FROM ov_go_intents WHERE account_id = (%d+)")
    if del then auth.intents[tonumber(del)] = nil end
end
function AuthDBQuery(sql)
    local name = sql:match("FROM account WHERE username = '(%w+)'")
    if name then return auth.accounts[name] and rows({ { auth.accounts[name] } }) or nil end
    local id = sql:match("FROM ov_go_intents WHERE account_id = (%d+)")
    if id then
        local g = auth.intents[tonumber(id)]
        if g and g.exp > clock then return rows({ { g.go, g.exp - clock } }) end
        return nil
    end
    return nil
end
local worldAsked = {}
function WorldDBQuery(sql)
    worldAsked[#worldAsked + 1] = sql
    local map = tonumber(sql:match("target_map = (%d+)"))
    if map == 564 then return rows({ { 564, 96.4, 1002.35, -86.9, 6.1 } }) end
    return nil
end
local online = {}
function GetPlayersInWorld() return online end

dofile(file)
local T = assert(OV_GO_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local BANNED = { "world of warcraft", "wow", "warcraft", "lich king", "blizzard" }
local allMsgs = {}

local function player(over)
    local p = { msgs = {}, queue = {}, teleports = {}, combat = false, dead = false, guid = 1, account = 42, level = 80,
                gm = 0, teleportOk = true }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m; allMsgs[#allMsgs + 1] = m end
    function p:GetGUIDLow() return self.guid end
    function p:GetAccountId() return self.account end
    function p:GetLevel() return self.level end
    function p:GetGMRank() return self.gm end
    function p:IsInCombat() return self.combat end
    function p:IsDead() return self.dead end
    function p:InBattleground() return self.bg or false end
    function p:InArena() return false end
    function p:GetMap() local s = self; return { IsDungeon = function() return s.dungeon or false end,
        IsRaid = function() return false end, IsBattlegroundOrArena = function() return false end } end
    function p:GetGroup() return self.group end
    function p:Teleport(...) self.teleports[#self.teleports + 1] = { ... }; return self.teleportOk end
    function p:RegisterEvent(fn, delay, rep) self.queue[#self.queue + 1] = { fn = fn, delay = delay } end
    return p
end
local function run(p)
    while #p.queue > 0 do
        local e = table.remove(p.queue, 1)
        e.fn(1, e.delay, 0, p)
    end
end
local function console(cmd)
    local out = {}
    local h = { SendSysMessage = function(_, m) out[#out + 1] = m end }
    local r = events[42](42, nil, cmd, h)
    return r, table.concat(out, "\n")
end
local function cmd(p, c) return events[42](42, p, c, nil) end
local function last(p) return p.msgs[#p.msgs] or "" end
local function raidGroup() return { IsRaidGroup = function() return true end } end

check("events registered (login, level, first login, command)", events[3] and events[13] and events[30] and events[42])
check("table: every place has a name, a kind and a level", (function()
    local n = 0
    for k, v in pairs(T.PLACES) do
        n = n + 1
        if type(v.name) ~= "string" or not v.what or type(v.min) ~= "number" then return false end
        if v.what ~= "queue" and not v.map then return false end
    end
    return n > 80
end)())
check("table: the raids, wings, dungeons, queues and hangouts", T.PLACES["b:icecrown-citadel"] and T.PLACES["b:icc-frozen-throne"]
    and T.PLACES["b:naxx-arachnid"] and T.PLACES["q:deadmines"] and T.PLACES["q:262"] and T.PLACES["h:dalaran"]
    and T.PLACES["h:goldshire-inn"] and T.PLACES["h:duels"])
check("table: no brand words", (function()
    for k, v in pairs(T.PLACES) do
        local s = (v.name .. " " .. v.hint):lower()
        for _, b in ipairs(BANNED) do if s:find(b, 1, true) then return false end end
    end
    return true
end)())

-- console: set / clear ------------------------------------------------------------------------------------------
local r, out = console("ovgo set player q:deadmines")
check("console set: handled", r == false)
check("console set: confirmed with 'ovgo ok'", out:match("^ovgo ok: PLAYER %-> q:deadmines %(30 min%)"))
check("console set: stored in the auth DB for 30 min", auth.intents[42] and auth.intents[42].go == "q:deadmines"
    and auth.intents[42].exp == clock + 1800)
r, out = console("ovgo clear PLAYER")
check("console clear", r == false and out:match("^ovgo ok: PLAYER cleared") and auth.intents[42] == nil and T.pending[42] == nil)
for _, bad in ipairs({ "ovgo set PLAYER q:not-a-dungeon", "ovgo set PLAYER x:deadmines", "ovgo set PLAYER q:dead'mines",
                       "ovgo set PLAYER q:deadmines;drop", "ovgo set PLAY'ER q:deadmines", "ovgo set PLAYER",
                       "ovgo set " .. string.rep("A", 17) .. " q:deadmines", "ovgo set PLAYER m:better-bags",
                       "ovgo set PLAYER u:Arthas", "ovgo frob PLAYER" }) do
    local before = #auth.sql
    local rr, o = console(bad)
    check("console refuses " .. bad, rr == false and not o:match("ovgo ok") and #auth.sql == before and auth.intents[42] == nil)
end
r, out = console("ovgo set NOBODY q:deadmines")
check("console: unknown account", out:match("no such account NOBODY") and not out:match("ovgo ok"))
check("console: other commands untouched", console("ovstream mark X mini 1 60") == nil and console("server info") == nil)

-- players can never use the console command ------------------------------------------------------------------
local pl = player({ guid = 5 })
check("player .ovgo not handled (the core says no such command)", cmd(pl, ".ovgo set PLAYER h:dalaran") == nil
    and cmd(pl, "ovgo set PLAYER h:dalaran") == nil and auth.intents[42] == nil)
check("other player commands untouched", cmd(pl, ".boost") == nil and cmd(pl, ".play") == nil)
local gm = player({ guid = 6, gm = 3 })
check("a GM's own .go commands are not shadowed", cmd(gm, ".go xyz 1 2 3") == nil and cmd(gm, ".go") == nil
    and cmd(pl, ".go creature 12") == nil)

-- online: right away ------------------------------------------------------------------------------------------
local a = player({ guid = 10, level = 30 })
online = { a }
console("ovgo set PLAYER q:deadmines")
check("online: deferred, not inside the hook", #a.teleports == 0 and #a.queue == 1)
run(a)
check("online: teleported to the Deadmines door", a.teleports[1] and a.teleports[1][1] == 36 and a.teleports[1][2] == -16.4)
check("online: said where", last(a):match("The Deadmines"))
check("used once", auth.intents[42] == nil and T.pending[42] == nil)
cmd(a, ".go"); run(a)
check(".go with nothing waiting", #a.teleports == 1 and last(a):match("Nothing is waiting"))
online = {}

-- next login --------------------------------------------------------------------------------------------------
console("ovgo set PLAYER h:dalaran")
T.pending[42] = nil   -- a restart: only the auth DB remembers
local b = player({ guid = 11, level = 12 })
events[3](3, b)
check("login: waits a moment", #b.teleports == 0 and b.queue[1] and b.queue[1].delay >= 3000)
run(b)
check("login: Dalaran from the auth DB", b.teleports[1] and b.teleports[1][1] == 571)

-- refusals keep the intent ------------------------------------------------------------------------------------
console("ovgo set PLAYER q:deadmines")
local c = player({ guid = 12, level = 30, combat = true })
events[3](3, c); run(c)
check("combat: refused", #c.teleports == 0 and last(c):match("not in combat"))
check("combat: kept", auth.intents[42] ~= nil)
c.combat = false; c.dungeon = true
cmd(c, ".go"); run(c)
check("instance: refused", #c.teleports == 0 and last(c):match("not from inside an instance"))
c.dungeon = false; c.dead = true
cmd(c, ".go"); run(c)
check("dead: refused", #c.teleports == 0 and last(c):match("not while dead"))
c.dead = false; c.bg = true
cmd(c, ".go"); run(c)
check("battleground: refused", #c.teleports == 0 and last(c):match("battleground"))
c.bg = false
cmd(c, ".go"); run(c)
check(".go: then it goes", c.teleports[1] and c.teleports[1][1] == 36)

-- level ------------------------------------------------------------------------------------------------------
console("ovgo set PLAYER b:icc-plagueworks")
local d = player({ guid = 13, level = 30 })
events[3](3, d); run(d)
check("too low: says the level and .boost", #d.teleports == 0 and last(d):match("needs level 80") and last(d):match("%.boost"))
check("too low: kept for another character", auth.intents[42] ~= nil)
d.level = 80
events[13](13, d, 30)
check("level-up (the boost): tries again later", d.queue[1] and d.queue[1].delay >= 5000)
run(d)
check("raid without a raid group: refused, kept", #d.teleports == 0 and last(d):match("raid group") and auth.intents[42] ~= nil)
d.group = raidGroup()
cmd(d, ".wugo"); run(d)
check("wing: the raid's door", d.teleports[1] and d.teleports[1][1] == 631)
check("wing: how to reach it", last(d):match("teleporter"))

-- first login: never moved before the boost / level-1 choice ---------------------------------------------------
console("ovgo set PLAYER h:goldshire-inn")
local f = player({ guid = 14, level = 1 })
events[30](30, f); events[3](3, f); run(f)
check("first login: waits, says .go", #f.teleports == 0 and last(f):match("%.go"))
cmd(f, ".go"); run(f)
check("first login: .go then goes", f.teleports[1] and f.teleports[1][1] == 0 and f.teleports[1][2] == -9460.3)

-- expiry ------------------------------------------------------------------------------------------------------
console("ovgo set PLAYER q:deadmines")
clock = clock + 1801
local g = player({ guid = 15, level = 30 })
events[3](3, g); run(g)
check("expired after 30 min", #g.teleports == 0 and auth.intents[42] == nil)
clock = clock + 10

-- cancel ------------------------------------------------------------------------------------------------------
console("ovgo set PLAYER q:deadmines")
local h = player({ guid = 16, level = 30 })
cmd(h, ".go cancel")
check(".go cancel forgets", auth.intents[42] == nil and last(h):match("Forgotten"))

-- random queue: how to queue ----------------------------------------------------------------------------------
console("ovgo set PLAYER q:262")
local i = player({ guid = 17, level = 80 })
events[3](3, i); run(i)
check("random queue: how to queue, no teleport", #i.teleports == 0 and last(i):match("Dungeon Finder") and auth.intents[42] == nil)
console("ovgo set PLAYER q:262")
local i2 = player({ guid = 18, level = 40 })
events[3](3, i2); run(i2)
check("random queue: too low says so", last(i2):match("level 80"))

-- a raid with no entrance in the table: areatrigger_teleport ------------------------------------------------------
console("ovgo set PLAYER b:black-temple")
local j = player({ guid = 19, level = 80, group = raidGroup() })
events[3](3, j); run(j)
check("door from areatrigger_teleport", j.teleports[1] and j.teleports[1][1] == 564 and j.teleports[1][2] == 96.4
    and worldAsked[#worldAsked]:match("areatrigger_teleport WHERE target_map = 564"))
console("ovgo set PLAYER b:molten-core")
local k = player({ guid = 20, level = 80, group = raidGroup() })
events[3](3, k); run(k)
check("no door on file: says so, forgets", #k.teleports == 0 and last(k):match("no entrance") and auth.intents[42] == nil)

-- the core refuses the teleport ---------------------------------------------------------------------------------
console("ovgo set PLAYER q:deadmines")
local m = player({ guid = 21, level = 30, teleportOk = false })
events[3](3, m); run(m)
check("core refusal said plainly", last(m):match("can't enter"))

-- another account's intent is not this one's -----------------------------------------------------------------------
console("ovgo set OTHER q:deadmines")
local n = player({ guid = 22, level = 30, account = 42 })
events[3](3, n); run(n)
check("only the account's own intent", #n.teleports == 0)
console("ovgo clear OTHER")

-- messages ----------------------------------------------------------------------------------------------------
local joined = table.concat(allMsgs, "\n"):lower()
local clean = true
for _, w in ipairs(BANNED) do
    if joined:find(w, 1, true) then clean = false; print("  banned word: " .. w) end
end
check("no brand words in any message", clean)

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
