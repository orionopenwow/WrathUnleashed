-- lua5.1 tests/test_ov_companions.lua ../realm/custom/lua_scripts/ov_companions.lua
local file = assert(arg[1], "ov_companions.lua")
local events, printed = {}, {}
local clock = 1000000
os.time = function() return clock end
local env = {}
os.getenv = function(k) return env[k] end
function RegisterPlayerEvent(id, fn) events[id] = fn end
local realPrint = print
print = function(s) printed[#printed + 1] = tostring(s) end
math.randomseed(7)

dofile(file)
local T = assert(OV_COMPANIONS_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end

local BANNED = { "world of warcraft", "wow", "warcraft", "lich king", "blizzard", "openvanilla", "open vanilla", "openwow" }
local allMsgs = {}

local function player(over)
    local p = { msgs = {}, cmds = {}, whispers = {}, queue = {}, teleports = {}, combat = false, dead = false }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m; allMsgs[#allMsgs + 1] = m end
    function p:GetGUIDLow() return self.guid end
    function p:GetGUID() return self.guid end
    function p:GetAccountId() return self.account or 42 end
    function p:GetAccountName() return self.accName or "PLAYER" end
    function p:GetName() return self.name or "Tester" end
    function p:GetLevel() return self.level or 20 end
    function p:GetClass() return self.class or 1 end
    function p:IsInCombat() return self.combat end
    function p:IsDead() return self.dead end
    function p:InBattleground() return false end
    function p:InArena() return false end
    function p:GetMap() local s = self; return { IsDungeon = function() return s.dungeon or false end, IsRaid = function() return false end } end
    function p:GetMapId() return self.map or 0 end
    function p:GetX() return 1 end
    function p:GetY() return 2 end
    function p:GetZ() return 3 end
    function p:GetO() return 4 end
    function p:GetDistance() return self.dist or 5 end
    function p:GetGroup() return self.group end
    function p:Teleport(...) self.teleports[#self.teleports + 1] = { ... } end
    function p:RegisterEvent(fn, delay, rep) self.queue[#self.queue + 1] = { fn = fn, delay = delay, rep = rep } end
    function p:Whisper(text, lang, to) self.whispers[#self.whispers + 1] = { text = text, to = to } end
    if not (over and over.built == false) then
        function p:IsPlayerbot() return self.bot == true end
        function p:IsAddclassBot() return self.addclass == true end
        function p:RunCommand(c) self.cmds[#self.cmds + 1] = c end
    end
    return p
end

-- A group the fake mod-playerbots adds bots to.
local function group(leader, members)
    local g = { members = members or { leader } }
    function g:GetMembers() return self.members end
    function g:GetMembersCount() return #self.members end
    function g:IsLeader(guid) return guid == leader.guid end
    leader.group = g
    for _, m in ipairs(g.members) do m.group = g end
    return g
end

local nextBot = 1000
-- What mod-playerbots does for each "addclass <class>" the player ran: a bot of that class joins the group.
local CLS = { warrior = 1, paladin = 2, hunter = 3, rogue = 4, priest = 5, dk = 6, shaman = 7, mage = 8, warlock = 9, druid = 11 }
local function serveAddclass(p, opts)
    opts = opts or {}
    local made = {}
    for i, c in ipairs(p.cmds) do
        local cls = c:match("^playerbots bot addclass (%a+)$")
        if cls and not p.served then p.served = {} end
        if cls and not p.served[i] and not (opts.skip and opts.skip[cls]) then
            p.served[i] = true
            nextBot = nextBot + 1
            local b = player({ guid = nextBot, account = 900, accName = "RNDBOT" .. nextBot, bot = true, addclass = true,
                class = CLS[cls], level = opts.level or p:GetLevel(), name = "Bot" .. string.char(64 + (nextBot % 26) + 1) .. "x",
                map = opts.map or 0, dist = opts.dist })
            if not p.group then group(p) end
            table.insert(p.group.members, b); b.group = p.group
            made[#made + 1] = b
        end
    end
    return made
end

local function run(p, n)
    local ticks = 0
    while #p.queue > 0 and (not n or ticks < n) do
        local e = table.remove(p.queue, 1)
        for k = 1, e.rep do ticks = ticks + 1; e.fn(ticks, e.delay, e.rep - k, p) end
    end
    return ticks
end
local function last(p) return p.msgs[#p.msgs] or "" end
local function cmd(p, c) return events[42](42, p, c) end
local function count(p, pat) local n = 0; for _, c in ipairs(p.cmds) do if c:match(pat) then n = n + 1 end end; return n end
local function whispered(p, to, pat)
    for _, w in ipairs(p.whispers) do if w.to == to and w.text:match(pat) then return true end end
    return false
end

check("events registered (logout, level, command)", events[4] and events[13] and events[42])

-- help -----------------------------------------------------------------------------------------------------
local h = player({ guid = 1 })
check(".companions handled", cmd(h, ".companions") == false)
local help = table.concat(h.msgs, "\n")
check("help lists .recruit, .buddy, .dismiss and the limits",
    help:match("%.recruit tank") and help:match("%.buddy") and help:match("%.dismiss") and help:match("4 companions per player")
    and help:match("groups up to 5") and help:match("every 30 s"))
check("other commands untouched", cmd(h, "summon") == nil and cmd(h, "qol") == nil and cmd(h, "playerbots bot list") == nil)

-- recruit a tank ---------------------------------------------------------------------------------------------
local a = player({ guid = 10, level = 30 })
check(".recruit handled", cmd(a, "recruit tank") == false)
check("one addclass of a tank class", #a.cmds == 1 and (a.cmds[1]:match("addclass warrior$") or a.cmds[1]:match("addclass paladin$")
    or a.cmds[1]:match("addclass druid$") or a.cmds[1]:match("addclass dk$")))
check("no dk below 55", count(a, "addclass dk") == 0)
check("pending, says a few seconds", #T.pending[10] == 1 and last(a):match("Recruiting 1 tank"))
check("arrival timer queued", #a.queue == 1 and a.queue[1].delay == 2000)
local bots = serveAddclass(a)
run(a)
local tank = bots[1]
check("claimed into companions", T.companions[10] and T.companions[10][tank.guid] ~= nil and #T.pending[10] == 0)
check("tank spec whispered", whispered(a, tank, "^talents spec %a+ pve$") and (whispered(a, tank, "prot pve") or whispered(a, tank, "bear pve")))
check("follow whispered", whispered(a, tank, "^follow$"))
check("same level: no init", count(a, "init=auto") == 0)
check("joins message", a.msgs[#a.msgs]:match("joins you as your tank"))

-- cooldown
cmd(a, "recruit healer")
check("cooldown", count(a, "addclass") == 1 and last(a):match("recruit again in 30 s"))
clock = clock + 31

-- three dps, two healers asked: group of 5 -> room for 3
cmd(a, "recruit dps 5")
check("capped at the party: 3 more (you + tank + 3 = 5)", count(a, "addclass") == 4 and last(a):match("3 of the 5 asked"))
check("dps classes vary", (function()
    local seen = {}; for i = 2, 4 do seen[a.cmds[i]] = true end; local n = 0; for _ in pairs(seen) do n = n + 1 end; return n == 3 end)())
check("realm count includes pending", T.realmCount() == 4)
local dps = serveAddclass(a, { level = 25, map = 1 })
run(a)
check("all four claimed", (function() local n = 0; for _ in pairs(T.companions[10]) do n = n + 1 end; return n == 4 end)())
check("other-map arrival teleported to the player", #dps[1].teleports == 1 and dps[1].teleports[1][2] == 1)
check("level mismatch: init=auto by name", count(a, "^playerbots bot init=auto Bot%a+$") == 3)
clock = clock + 31
cmd(a, "recruit healer")
check("per-player cap: 4", count(a, "addclass") == 4 and last(a):match("the most allowed"))

-- dismiss
local before = #a.cmds
cmd(a, "dismiss")
check(".dismiss alone with several: asks which", #a.cmds == before and last(a):match("Dismiss which"))
cmd(a, "dismiss " .. tank.name:lower())
check(".dismiss <name> removes that one", a.cmds[#a.cmds] == "playerbots bot remove " .. tank.name and T.companions[10][tank.guid] == nil)
cmd(a, "dismiss all")
check(".dismiss all removes the rest", count(a, "^playerbots bot remove ") == 4 and next(T.companions[10]) == nil and last(a):match("home"))
cmd(a, "dismiss")
check(".dismiss with none", last(a):match("no companions"))

-- a recruit that never arrives
clock = clock + 31
local n0 = player({ guid = 11, level = 30 })
cmd(n0, "recruit healer priest")
check("class pick inside the role", n0.cmds[1] == "playerbots bot addclass priest")
check("wrong class for the role explains", (function() clock = clock + 31; cmd(n0, "recruit tank mage"); return last(n0):match("can be:") end)())
clock = clock + 20
run(n0)
check("never arrived: expires with a message", #T.pending[11] == 0 and last(n0):match("didn't arrive"))

-- refusals
local c = player({ guid = 12, combat = true })
cmd(c, "recruit dps")
check("refused in combat", #c.cmds == 0 and last(c):match("Not in combat"))
local d = player({ guid = 13, dungeon = true })
cmd(d, "recruit dps")
check("refused inside an instance", #d.cmds == 0 and last(d):match("open world"))
local lead = player({ guid = 14 }); local follower = player({ guid = 15 })
group(lead, { lead, follower })
cmd(follower, "recruit dps")
check("only the group leader", #follower.cmds == 0 and last(follower):match("leader"))
cmd(lead, "recruit")
check("usage without a role", last(lead):match("Usage"))

-- realm cap
env.OV_COMPANIONS_REALM_MAX = "2"
local r1 = player({ guid = 16 }); cmd(r1, "recruit dps 2")
local r2 = player({ guid = 17 }); cmd(r2, "recruit dps")
check("realm cap", count(r1, "addclass") == 2 and #r2.cmds == 0 and last(r2):match("out with someone"))
env.OV_COMPANIONS_REALM_MAX = nil
events[4](4, r1)
check("logout frees the slots", T.pending[16] == nil and T.realmCount() == 0 + #(T.pending[11] or {}))

-- buddy
local b = player({ guid = 20, level = 12 })
check(".buddy handled", cmd(b, "buddy") == false)
check(".buddy addclass, never a dk at 12", count(b, "addclass") == 1 and count(b, "addclass dk") == 0 and last(b):match("on the way"))
cmd(b, "buddy")
check(".buddy while on the way", last(b):match("on the way") and count(b, "addclass") == 1)
local bb = serveAddclass(b)[1]
run(b)
check("buddy claimed, follow, no spec forced", T.companions[20][bb.guid].buddy and whispered(b, bb, "^follow$")
    and not whispered(b, bb, "talents"))
cmd(b, "buddy")
check(".buddy shows the buddy", last(b):match(bb.name) and last(b):match("keep to your level"))
b.level = 13
events[13](13, b, 12)
check("level up queues the catch-up", #b.queue == 1)
run(b)
check("buddy re-levelled with init=auto", b.cmds[#b.cmds] == "playerbots bot init=auto " .. bb.name and last(b):match("level 13"))
bb.level = 13
b.level = 14; bb.combat = true
events[13](13, b, 13); run(b)
check("in combat: catches up later", last(b):match("after the fight"))
clock = clock + 31
cmd(b, "buddy warrior")
check("one buddy only", count(b, "addclass") == 1)
cmd(b, "buddy off")
check(".buddy off dismisses", b.cmds[#b.cmds] == "playerbots bot remove " .. bb.name and T.companions[20][bb.guid] == nil)
local bl = player({ guid = 21, level = 10 }); cmd(bl, "buddy dk")
check(".buddy dk below 55 refused", #bl.cmds == 0 and last(bl):match("from level 55"))
local bq = player({ guid = 22, level = 60 }); cmd(bq, "buddy dk")
check(".buddy dk at 60", bq.cmds[1] == "playerbots bot addclass dk")

-- a kicked companion is forgotten
clock = clock + 31
local k = player({ guid = 30 })
cmd(k, "recruit dps")
local kb = serveAddclass(k)[1]; run(k)
table.remove(k.group.members)   -- the player kicked it
cmd(k, "dismiss")
check("left the group: pruned", last(k):match("no companions"))

-- switches
env.OV_COMPANIONS = "0"
local o = player({ guid = 40 }); cmd(o, "recruit dps")
check("OV_COMPANIONS=0: off", #o.cmds == 0 and last(o):match("off on this realm"))
env.OV_COMPANIONS = nil
env.OV_COMPANIONS_BUDDY = "0"
local ob = player({ guid = 41 }); cmd(ob, "buddy")
check("OV_COMPANIONS_BUDDY=0: off", #ob.cmds == 0 and last(ob):match("off"))
env.OV_COMPANIONS_BUDDY = nil
env.OV_COMPANIONS_GROUP_MAX = "10"; env.OV_COMPANIONS_PER_PLAYER = "9"
local big = player({ guid = 42 }); cmd(big, "recruit dps 9")
check("raid-size settings honoured", count(big, "addclass") == 9)
env.OV_COMPANIONS_GROUP_MAX, env.OV_COMPANIONS_PER_PLAYER = nil, nil

-- bots never drive this
local botp = player({ guid = 50, bot = true, accName = "RNDBOT50" })
check("bots: handled silently", cmd(botp, "recruit dps") == false and #botp.cmds == 0 and #botp.msgs == 0)

-- no mod-playerbots in the build: coming soon
local stock = player({ guid = 60, built = false })
stock.IsPlayerbot, stock.RunCommand = nil, nil
check("no bot module: handled", cmd(stock, "recruit tank") == false)
check("no bot module: coming soon, on Leyline", last(stock):match("Companions are coming soon to Wrath on Leyline"))
cmd(stock, "companions"); cmd(stock, "buddy"); cmd(stock, "dismiss all")
check("no bot module: every command says so", #stock.msgs == 4)

-- names
check("no forbidden names in anything players saw", (function()
    for _, m in ipairs(allMsgs) do
        local l = m:lower()
        for _, w in ipairs(BANNED) do
            if l:find(w, 1, true) and not (w == "wow" and not l:find("%f[%a]wow%f[%A]")) then return false end
        end
    end
    return true end)())

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
