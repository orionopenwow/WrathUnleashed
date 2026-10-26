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

-- A fake characters database: characters and mod_companions_usual.
local sqlLog = {}
local chars = {}   -- { guid, account, name, level, class, online }
local usual = {}   -- [account] = { { slot, guid, name } }
local function result(rows)
    if not rows or #rows == 0 then return nil end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetString(c) return tostring(self.rows[self.i][c + 1] or "") end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end
function CharDBExecute(sql)
    sqlLog[#sqlLog + 1] = sql
    local acc = sql:match("^DELETE FROM mod_companions_usual WHERE account = (%d+)$")
    if acc then usual[tonumber(acc)] = nil end
    local a, s, g, n = sql:match("^INSERT INTO mod_companions_usual %(account, slot, guid, name, saved_at%) VALUES %((%d+), (%d+), (%d+), '([%a\128-\255]+)', %d+%)$")
    if a then
        a = tonumber(a); usual[a] = usual[a] or {}
        table.insert(usual[a], { slot = tonumber(s), guid = tonumber(g), name = n })
    end
end
function CharDBQuery(sql)
    sqlLog[#sqlLog + 1] = sql
    local acc, me = sql:match("^SELECT guid, name, level, class FROM characters WHERE account = (%d+) AND online = 0 AND guid <> (%d+)")
    if acc then
        local rows = {}
        for _, c in ipairs(chars) do
            if c.account == tonumber(acc) and c.online == 0 and c.guid ~= tonumber(me) then rows[#rows + 1] = { c.guid, c.name, c.level, c.class } end
        end
        return result(rows)
    end
    local acc2, nm = sql:match("^SELECT guid, name, level, class, online FROM characters WHERE account = (%d+) AND name = '([^']*)' LIMIT 1$")
    if acc2 then
        for _, c in ipairs(chars) do
            if c.account == tonumber(acc2) and c.name:lower() == nm:lower() then return result({ { c.guid, c.name, c.level, c.class, c.online } }) end
        end
        return nil
    end
    local acc3 = sql:match("FROM mod_companions_usual u JOIN characters c ON c.guid = u.guid AND c.account = u.account WHERE u.account = (%d+) ORDER BY u.slot$")
    if acc3 then
        local rows = {}
        for _, u in ipairs(usual[tonumber(acc3)] or {}) do
            for _, c in ipairs(chars) do
                if c.guid == u.guid and c.account == tonumber(acc3) then rows[#rows + 1] = { c.guid, c.name, c.level, c.class, c.online } end
            end
        end
        return result(rows)
    end
    return nil
end

local T_SRC = assert(io.open(file)):read("*a")
dofile(file)
local T = assert(OV_COMPANIONS_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end

check("usual-party table made at load, mod_ prefix",
    sqlLog[1] and sqlLog[1]:match("^CREATE TABLE IF NOT EXISTS mod_companions_usual") ~= nil)

local BANNED = { "world of warcraft", "wow", "warcraft", "lich king", "blizzard", "openvanilla", "open vanilla", "openwow",
    "leyline", "wrathunleashed", "playerbot", "azerothcore", "mod-ale", "eluna" }
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
    function p:InBattleground() return self.bg or false end
    function p:InArena() return false end
    function p:GetMap() local s = self; return { IsDungeon = function() return (s.dungeon or s.raidmap) or false end,
        IsRaid = function() return s.raidmap or false end } end
    function p:GetMapId() return self.map or 0 end
    function p:GetInstanceId() return self.inst or 0 end
    function p:GetX() return 1 end
    function p:GetY() return 2 end
    function p:GetZ() return 3 end
    function p:GetO() return 4 end
    function p:GetDistance() return self.dist or 5 end
    function p:GetGroup() return self.group end
    function p:Teleport(...) self.teleports[#self.teleports + 1] = { ... } end
    function p:RegisterEvent(fn, delay, rep) self.queue[#self.queue + 1] = { fn = fn, delay = delay, rep = rep } end
    function p:Whisper(text, lang, to)
        self.whispers[#self.whispers + 1] = { text = text, to = to }
        if text == "leave" and to and to.group then to.group:RemoveMember(to.guid) end
    end
    if not (over and over.built == false) then
        function p:IsPlayerbot() return self.bot == true end
        function p:IsAddclassBot() return self.addclass == true end
        function p:IsTank(bySpec) return bySpec == true and self.spec == "tank" end
        function p:IsHealer(bySpec) return bySpec == true and self.spec == "healer" end
        function p:RunCommand(c) self.cmds[#self.cmds + 1] = c end
    end
    return p
end

-- A group the fake mod-playerbots adds bots to.
local function group(leader, members)
    local g = { members = members or { leader }, raid = false, converted = 0 }
    function g:GetMembers() return self.members end
    function g:GetMembersCount() return #self.members end
    function g:IsLeader(guid) return guid == leader.guid end
    function g:IsRaidGroup() return self.raid end
    function g:ConvertToRaid() self.raid = true; self.converted = self.converted + 1 end
    function g:IsLFGGroup() return self.lfg or false end
    function g:IsBGGroup() return false end
    function g:RemoveMember(guid)
        for i, m in ipairs(self.members) do if m.guid == guid then table.remove(self.members, i); m.group = nil; return true end end
        return false
    end
    leader.group = g
    for _, m in ipairs(g.members) do m.group = g end
    return g
end

local nextBot = 1000
-- What mod-playerbots does for each "addclass <class>" / "add <name>" the player ran: the bot joins the group.
local CLS = { warrior = 1, paladin = 2, hunter = 3, rogue = 4, priest = 5, dk = 6, shaman = 7, mage = 8, warlock = 9, druid = 11 }
local function serve(p, opts)
    opts = opts or {}
    local made = {}
    p.served = p.served or {}
    for i, c in ipairs(p.cmds) do
        local cls = c:match("^playerbots bot addclass (%a+)$")
        local alt = c:match("^playerbots bot add (%S+)$")
        if (cls or alt) and not p.served[i] and not (opts.skip and opts.skip[cls or alt]) then
            p.served[i] = true
            local b
            if cls then
                nextBot = nextBot + 1
                b = player({ guid = nextBot, account = 900, accName = "RNDBOT" .. nextBot, bot = true, addclass = true,
                    class = CLS[cls], level = opts.level or p:GetLevel(), name = "Bot" .. string.char(64 + (nextBot % 26) + 1) .. "x",
                    map = opts.map or 0, inst = opts.inst or 0, dist = opts.dist })
            else
                local row
                for _, ch in ipairs(chars) do if ch.name == alt then row = ch end end
                b = player({ guid = row.guid, account = row.account, accName = "OWNER", bot = true, addclass = false,
                    class = row.class, level = row.level, name = row.name, spec = row.spec, map = opts.map or 0,
                    inst = opts.inst or 0, dist = opts.dist })
                row.online = 1
            end
            if not p.group then group(p) end
            table.insert(p.group.members, b); b.group = p.group
            if #p.group.members > 5 then p.group.raid = true end   -- the module converts at the 6th member
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
local function n(t) local k = 0; for _ in pairs(t or {}) do k = k + 1 end; return k end

check("events registered (logout, level, command)", events[4] and events[13] and events[42])

-- composition math ------------------------------------------------------------------------------------------
local P = T.planRoles
local function eq(a, t, h, d) return a.tank == t and a.healer == h and a.dps == d end
check("plan: solo damage player, raid of 10 -> 2 tanks, 3 healers, 4 damage", eq(P({ dps = 1 }, T.SHAPE[10], 9), 2, 3, 4))
check("plan: solo tank, raid of 10 -> 1 tank, 3 healers, 5 damage", eq(P({ tank = 1 }, T.SHAPE[10], 9), 1, 3, 5))
check("plan: solo healer, party of 5 -> 1 tank, 0 healers, 3 damage", eq(P({ healer = 1 }, T.SHAPE[5], 4), 1, 0, 3))
check("plan: tanks and healers first when slots are short", eq(P({ dps = 1 }, T.SHAPE[10], 4), 2, 2, 0))
check("plan: extra slots go to damage", eq(P({ tank = 3, dps = 1 }, T.SHAPE[10], 6), 0, 3, 3))
check("plan: never negative", eq(P({ tank = 5, healer = 5, dps = 9 }, T.SHAPE[10], 0), 0, 0, 0))

-- help -----------------------------------------------------------------------------------------------------
local h = player({ guid = 1 })
check(".companions handled", cmd(h, ".companions") == false)
local help = table.concat(h.msgs, "\n")
check("help lists party, raid, roles, alts, save, buddy, dismiss and the limits",
    help:match("%.recruit party") and help:match("%.recruit raid") and help:match("%.recruit tank")
    and help:match("%.recruit alt") and help:match("%.companions save") and help:match("%.recruit usual")
    and help:match("%.buddy") and help:match("%.dismiss") and help:match("4 bots in a party") and help:match("9 bots in a raid")
    and help:match("every 30 s") and help:match("pass on loot"))
check("other commands untouched", cmd(h, "summon") == nil and cmd(h, "qol") == nil and cmd(h, "playerbots bot list") == nil)

-- recruit a tank ---------------------------------------------------------------------------------------------
local a = player({ guid = 10, level = 30 })
check(".recruit handled", cmd(a, "recruit tank") == false)
check("one addclass of a tank class", #a.cmds == 1 and (a.cmds[1]:match("addclass warrior$") or a.cmds[1]:match("addclass paladin$")
    or a.cmds[1]:match("addclass druid$") or a.cmds[1]:match("addclass dk$")))
check("no dk below 55", count(a, "addclass dk") == 0)
check("pending, says a few seconds", #T.pending[10] == 1 and last(a):match("Recruiting 1 tank bot"))
check("arrival timer queued", #a.queue == 1 and a.queue[1].delay == 2000)
local bots = serve(a)
run(a)
local tank = bots[1]
check("claimed into companions", T.companions[10] and T.companions[10][tank.guid] ~= nil and #T.pending[10] == 0)
check("tank spec whispered", whispered(a, tank, "^talents spec %a+ pve$") and (whispered(a, tank, "prot pve") or whispered(a, tank, "bear pve")))
check("maintenance and autogear whispered", whispered(a, tank, "^maintenance$") and whispered(a, tank, "^autogear$"))
check("loot list reset whispered", whispered(a, tank, "^ll normal$"))
check("follow whispered", whispered(a, tank, "^follow$"))
check("same level: no init", count(a, "init=auto") == 0)
check("joins message calls it a bot", a.msgs[#a.msgs]:match("joins as a tank bot"))

-- cooldown
cmd(a, "recruit healer")
check("cooldown", count(a, "addclass") == 1 and last(a):match("recruit again in 30 s"))
clock = clock + 31

-- three dps, five asked: party of 5 -> room for 3
cmd(a, "recruit dps 5")
check("capped at the party: 3 more (you + tank + 3 = 5)", count(a, "addclass") == 4 and last(a):match("3 of the 5 asked"))
check("dps classes vary", (function()
    local seen = {}; for i = 2, 4 do seen[a.cmds[i]] = true end; return n(seen) == 3 end)())
check("realm count includes pending", T.realmCount() == 4)
local dps = serve(a, { level = 25, map = 1 })
run(a)
check("all four claimed", n(T.companions[10]) == 4)
check("open world, other map: moved to the player", #dps[1].teleports == 1 and dps[1].teleports[1][2] == 1)
check("level mismatch: init=auto by name", count(a, "^playerbots bot init=auto Bot%a+$") == 3)
clock = clock + 31
cmd(a, "recruit healer")
check("party cap: 4 bots", count(a, "addclass") == 4 and last(a):match("the most allowed in a party"))

-- dismiss
local before = #a.cmds
cmd(a, "dismiss"); run(a)
check(".dismiss alone with several: asks which", #a.cmds == before and last(a):match("Dismiss which"))
cmd(a, "dismiss " .. tank.name:lower()); run(a)
check(".dismiss <name> removes that one", a.cmds[#a.cmds] == "playerbots bot remove " .. tank.name and T.companions[10][tank.guid] == nil)
cmd(a, "dismiss all"); run(a)
check(".dismiss all removes the rest", count(a, "^playerbots bot remove ") == 4 and next(T.companions[10]) == nil and last(a):match("home"))
cmd(a, "dismiss"); run(a)
check(".dismiss with none", last(a):match("no bots"))

-- a recruit that never arrives
clock = clock + 31
local n0 = player({ guid = 11, level = 30 })
cmd(n0, "recruit healer priest")
check("class pick inside the role", n0.cmds[1] == "playerbots bot addclass priest")
check("wrong class for the role explains", (function() clock = clock + 31; cmd(n0, "recruit tank mage"); return last(n0):match("can be:") end)())
clock = clock + 20
run(n0)
check("never arrived: expires with a message", #T.pending[11] == 0 and last(n0):match("didn't arrive"))

-- party fill -------------------------------------------------------------------------------------------------
clock = clock + 31
local pf = player({ guid = 70, level = 40, spec = "healer" })
cmd(pf, "recruit party")
check(".recruit party: 4 bots for a healer (1 tank, 3 damage, no healer)", count(pf, "addclass") == 4
    and #T.pending[70] == 4 and (function() local t, hl = 0, 0
        for _, p in ipairs(T.pending[70]) do if p.role == "tank" then t = t + 1 elseif p.role == "healer" then hl = hl + 1 end end
        return t == 1 and hl == 0 end)())
check(".recruit party message", last(pf):match("Recruiting 4 bots for a 5%-player group: 1 tank, 3 damage"))
serve(pf); run(pf)
check("party fill: no raid", pf.group.raid == false and pf.group.converted == 0)
clock = clock + 31
cmd(pf, "recruit party")
check("party full", last(pf):match("full") or last(pf):match("most allowed"))

-- raid fill (10) ---------------------------------------------------------------------------------------------
clock = clock + 31
local rd = player({ guid = 80, level = 80 })
local mate = player({ guid = 81, level = 80, spec = "tank" })
group(rd, { rd, mate })
cmd(rd, "recruit raid")
local tanks, heals, dmg = 0, 0, 0
for _, p in ipairs(T.pending[80]) do
    if p.role == "tank" then tanks = tanks + 1 elseif p.role == "healer" then heals = heals + 1 else dmg = dmg + 1 end
end
check(".recruit raid: 8 bots fill to 10 (a real tank already there)", count(rd, "addclass") == 8 and tanks == 1 and heals == 3 and dmg == 4)
check(".recruit raid: party converted to a raid", rd.group.raid == true and rd.group.converted == 1)
check(".recruit raid message", last(rd):match("Recruiting 8 bots for a 10%-player raid: 1 tank, 3 healers, 4 damage"))
serve(rd); run(rd)
check("raid: all 8 claimed", n(T.companions[80]) == 8)
check("raid: specs, maintenance, autogear for each", (function()
    for bg in pairs(T.companions[80]) do
        local m; for _, x in ipairs(rd.group.members) do if x.guid == bg then m = x end end
        if not (whispered(rd, m, "^talents spec ") and whispered(rd, m, "^maintenance$") and whispered(rd, m, "^autogear$")
            and whispered(rd, m, "^follow$")) then return false end
    end
    return true end)())
clock = clock + 31
cmd(rd, "recruit dps")
check("raid full at 10", last(rd):match("full %(10 players%)") or last(rd):match("most allowed in a raid"))
cmd(rd, "dismiss all"); run(rd)
check("raid: dismiss all sends 8 home", count(rd, "^playerbots bot remove ") == 8)
check("raid: dismissed bots leave the group (no offline members filling it)", #rd.group.members == 2)
check("raid: dismiss never calls the group's RemoveMember from the script (crashed the realm 2026-10-26)",
    not T_SRC:find("RemoveMember%s*\""))

-- raid caps: solo raid gets 9 (per player in a raid), not 4
clock = clock + 31
local solo = player({ guid = 90, level = 80 })
cmd(solo, "recruit raid")
check("solo .recruit raid: 9 bots (2 tanks, 3 healers, 4 damage)", count(solo, "addclass") == 9
    and last(solo):match("2 tanks, 3 healers, 4 damage"))
serve(solo); run(solo)
check("solo raid: group became a raid", solo.group.raid == true)
clock = clock + 31
cmd(solo, "recruit healer")
check("raid cap: 9 bots", count(solo, "addclass") == 9 and last(solo):match("most allowed in a raid"))
cmd(solo, "dismiss all"); run(solo)

-- 25 behind the switch
clock = clock + 31
local r25 = player({ guid = 91, level = 80 })
cmd(r25, "recruit raid 25")
check("25-player off by default", #r25.cmds == 0 and last(r25):match("25%-player raids are off"))
env.OV_COMPANIONS_RAID25 = "1"; env.OV_COMPANIONS_GROUP_MAX = "25"; env.OV_COMPANIONS_PER_PLAYER_RAID = "24"
cmd(r25, "recruit raid 25")
check("OV_COMPANIONS_RAID25=1: fills 25", count(r25, "addclass") == 24)
env.OV_COMPANIONS_RAID25, env.OV_COMPANIONS_GROUP_MAX, env.OV_COMPANIONS_PER_PLAYER_RAID = nil, nil, nil
events[4](4, r25)
env.OV_COMPANIONS_PER_PLAYER_RAID = "30"
local r10 = player({ guid = 92, level = 80 })
cmd(r10, "recruit raid")
check("raid size capped at 10 without the switch, whatever the env", count(r10, "addclass") == 9)
env.OV_COMPANIONS_PER_PLAYER_RAID = nil
events[4](4, r10)
env.OV_COMPANIONS_GROUP_MAX = "5"
local nr = player({ guid = 93 }); cmd(nr, "recruit raid")
check("GROUP_MAX=5: raids off", #nr.cmds == 0 and last(nr):match("off"))
env.OV_COMPANIONS_GROUP_MAX = nil

-- refusals and the instance rules -----------------------------------------------------------------------------
local c = player({ guid = 12, combat = true })
cmd(c, "recruit dps")
check("refused in combat", #c.cmds == 0 and last(c):match("Not in combat"))
local dd = player({ guid = 120, dead = true })
cmd(dd, "recruit dps")
check("refused while dead", #dd.cmds == 0 and last(dd):match("dead"))
local bgp = player({ guid = 121, bg = true })
cmd(bgp, "recruit party")
check("refused in battlegrounds", #bgp.cmds == 0 and last(bgp):match("battlegrounds or arenas"))
local d = player({ guid = 13, dungeon = true, map = 36, inst = 5 })
cmd(d, "recruit dps")
check("allowed inside a dungeon out of combat", count(d, "addclass") == 1)
local inb = serve(d, { map = 36, inst = 5, dist = 80 })[1]
local outb = serve(d, {})   -- nothing more pending
run(d)
check("in instance, same map and instance, far: moved to the player", #inb.teleports == 1 and not whispered(d, inb, "^summon$"))
clock = clock + 31
cmd(d, "recruit dps")
local other = serve(d, { map = 0, inst = 0 })[1]
run(d)
check("in instance, bot elsewhere: playerbots summon, no teleport", #other.teleports == 0 and whispered(d, other, "^summon$"))
clock = clock + 31
cmd(d, "recruit dps")
local wrongInst = serve(d, { map = 36, inst = 9, dist = 80 })[1]
run(d)
check("in instance, same map other instance: summon, no teleport", #wrongInst.teleports == 0 and whispered(d, wrongInst, "^summon$"))
clock = clock + 31
other.combat = true
cmd(d, "recruit dps")
check("in instance, group member in combat: refused", last(d):match("out of combat") and count(d, "addclass") == 3)
other.combat = false
cmd(d, "recruit raid")
check("raid fill refused inside a 5-player dungeon", last(d):match("use %.recruit party"))
local rr = player({ guid = 14, raidmap = true, map = 533, inst = 7, level = 80 })
cmd(rr, "recruit raid")
check("raid fill allowed inside a raid instance", count(rr, "addclass") == 9)
events[4](4, rr)
local lead = player({ guid = 15 }); local follower = player({ guid = 16 })
group(lead, { lead, follower })
cmd(follower, "recruit dps")
check("only the group leader", #follower.cmds == 0 and last(follower):match("leader"))
cmd(lead, "recruit")
check("usage without a role", last(lead):match("Usage"))
local lfg = player({ guid = 17 }); group(lfg).lfg = true
cmd(lfg, "recruit raid")
check("no raid fill in a Dungeon Finder group", #lfg.cmds == 0 and last(lfg):match("Dungeon Finder"))

-- realm cap
clock = clock + 31
env.OV_COMPANIONS_REALM_MAX = tostring(T.realmCount() + 2)
local r1 = player({ guid = 18 }); cmd(r1, "recruit dps 2")
local r2 = player({ guid = 19 }); cmd(r2, "recruit dps")
check("realm cap", count(r1, "addclass") == 2 and #r2.cmds == 0 and last(r2):match("out with someone"))
env.OV_COMPANIONS_REALM_MAX = nil
local beforeLogout = T.realmCount()
events[4](4, r1)
check("logout frees the slots", T.pending[18] == nil and T.realmCount() == beforeLogout - 2)

-- alts ------------------------------------------------------------------------------------------------------
chars = {
    { guid = 500, account = 7, name = "Me", level = 70, class = 1, online = 1 },
    { guid = 501, account = 7, name = "Healie", level = 68, class = 5, online = 0, spec = "healer" },
    { guid = 502, account = 7, name = "Tanky", level = 70, class = 1, online = 0, spec = "tank" },
    { guid = 503, account = 7, name = "Busy", level = 60, class = 8, online = 1 },
    { guid = 600, account = 8, name = "Stranger", level = 80, class = 2, online = 0 },
}
clock = clock + 31
local me = player({ guid = 500, account = 7, name = "Me", level = 70 })
cmd(me, "companions alts")
check(".companions alts lists own offline characters only", (function()
    local all = table.concat(me.msgs, "\n")
    return all:match("Healie %(68 Priest%)") and all:match("Tanky %(70 Warrior%)") and not all:match("Busy")
        and not all:match("Stranger") and not all:match("Me %(") end)())
check(".companions alts query is by account id", (function()
    for _, s in ipairs(sqlLog) do if s:match("FROM characters WHERE account = 7 AND online = 0 AND guid <> 500") then return true end end
    return false end)())
cmd(me, "recruit alt Stranger")
check("another account's character refused", #me.cmds == 0 and last(me):match("no character called Stranger"))
cmd(me, "recruit alt Busy")
check("an online alt refused", #me.cmds == 0 and last(me):match("online already"))
cmd(me, "recruit alt Me")
check("yourself refused", #me.cmds == 0 and last(me):match("That's you"))
cmd(me, "recruit alt Ta'nky; drop")
check("odd names refused, no SQL", #me.cmds == 0 and last(me):match("Usage"))
cmd(me, "recruit alt tanky")
check(".recruit alt: playerbots bot add with the stored name, no addclass", me.cmds[1] == "playerbots bot add Tanky" and count(me, "addclass") == 0)
check(".recruit alt message", last(me):match("Bringing Tanky"))
local tk = serve(me)[1]
run(me)
check("alt claimed as a bot", T.companions[500][502] and T.companions[500][502].alt == true and last(me):match("Tanky %(your Warrior%) joins as a bot"))
check("alt: own gear, spec, level: no init, talents, maintenance or autogear",
    count(me, "init=auto") == 0 and not whispered(me, tk, "talents") and not whispered(me, tk, "maintenance")
    and not whispered(me, tk, "autogear"))
check("alt: loot reset and follow", whispered(me, tk, "^ll normal$") and whispered(me, tk, "^follow$"))
check("alt role from its spec", T.companions[500][502].role == "tank")
clock = clock + 31
cmd(me, "recruit alt Tanky")
check("alt already with you", last(me):match("already with you"))
cmd(me, "recruit alt Healie")
serve(me); run(me)
check("second alt in", T.companions[500][501] ~= nil)
-- alts count toward the cap
clock = clock + 31
cmd(me, "recruit dps 5")
check("alts count toward the party cap (2 alts + 2 more = 4)", count(me, "addclass") == 2)
serve(me); run(me)
cmd(me, "companions save")
check(".companions save stores the alts, not the class bots", usual[7] and #usual[7] == 2 and usual[7][1].name == "Healie"
    and usual[7][2].name == "Tanky" and last(me):match("Saved your usual party: Healie, Tanky"))
cmd(me, "dismiss all"); run(me)
check(".dismiss all handles alts", count(me, "^playerbots bot remove Tanky$") == 1 and count(me, "^playerbots bot remove Healie$") == 1)
for _, ch in ipairs(chars) do if ch.guid == 501 or ch.guid == 502 then ch.online = 0 end end
me.group.members = { me }   -- the module logs them out of the group
clock = clock + 31
local adds = count(me, "^playerbots bot add ")
cmd(me, "recruit usual")
check(".recruit usual re-adds the saved alts", count(me, "^playerbots bot add ") == adds + 2
    and last(me):match("Bringing your usual party: Healie, Tanky"))
serve(me); run(me)
cmd(me, "dismiss healie"); run(me)
check(".dismiss <alt name>", me.cmds[#me.cmds] == "playerbots bot remove Healie")
local other7 = player({ guid = 700, account = 9 })
cmd(other7, "recruit usual")
check(".recruit usual with nothing saved", #other7.cmds == 0 and last(other7):match("No usual party saved"))
local noalts = player({ guid = 701, account = 10 })
cmd(noalts, "companions save")
check(".companions save with no alts", last(noalts):match("No alts with you"))
check("the usual list is read by account, joined to characters on that account", (function()
    for _, s in ipairs(sqlLog) do if s:match("JOIN characters c ON c.guid = u.guid AND c.account = u.account WHERE u.account = 7") then return true end end
    return false end)())

-- buddy
clock = clock + 31
local b = player({ guid = 20, level = 12 })
check(".buddy handled", cmd(b, "buddy") == false)
check(".buddy addclass, never a dk at 12", count(b, "addclass") == 1 and count(b, "addclass dk") == 0 and last(b):match("on the way"))
cmd(b, "buddy")
check(".buddy while on the way", last(b):match("on the way") and count(b, "addclass") == 1)
local bb = serve(b)[1]
run(b)
check("buddy claimed, follow, no spec forced", T.companions[20][bb.guid].buddy and whispered(b, bb, "^follow$")
    and not whispered(b, bb, "talents"))
cmd(b, "buddy")
check(".buddy shows the buddy", last(b):match(bb.name) and last(b):match("keeps to your level"))
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
cmd(b, "buddy off"); run(b)
check(".buddy off dismisses", b.cmds[#b.cmds] == "playerbots bot remove " .. bb.name and T.companions[20][bb.guid] == nil)
local bl = player({ guid = 21, level = 10 }); cmd(bl, "buddy dk")
check(".buddy dk below 55 refused", #bl.cmds == 0 and last(bl):match("from level 55"))
local bq = player({ guid = 22, level = 60 }); cmd(bq, "buddy dk")
check(".buddy dk at 60", bq.cmds[1] == "playerbots bot addclass dk")

-- a kicked companion is forgotten
clock = clock + 31
local k = player({ guid = 30 })
cmd(k, "recruit dps")
serve(k); run(k)
table.remove(k.group.members)   -- the player kicked it
cmd(k, "dismiss"); run(k)
check("left the group: pruned", last(k):match("no bots"))

-- switches
env.OV_COMPANIONS = "0"
local o = player({ guid = 40 }); cmd(o, "recruit dps")
check("OV_COMPANIONS=0: off", #o.cmds == 0 and last(o):match("off on this realm"))
env.OV_COMPANIONS = nil
env.OV_COMPANIONS_BUDDY = "0"
local ob = player({ guid = 41 }); cmd(ob, "buddy")
check("OV_COMPANIONS_BUDDY=0: off", #ob.cmds == 0 and last(ob):match("off"))
env.OV_COMPANIONS_BUDDY = nil
env.OV_COMPANIONS_PER_PLAYER = "2"
local small = player({ guid = 42 }); cmd(small, "recruit party")
check("OV_COMPANIONS_PER_PLAYER honoured", count(small, "addclass") == 2)
env.OV_COMPANIONS_PER_PLAYER = nil
env.OV_COMPANIONS_COOLDOWN = "0"
local fast = player({ guid = 43 }); cmd(fast, "recruit dps"); cmd(fast, "recruit dps")
check("OV_COMPANIONS_COOLDOWN honoured", count(fast, "addclass") == 2)
env.OV_COMPANIONS_COOLDOWN = nil

-- bots never drive this
local botp = player({ guid = 50, bot = true, accName = "RNDBOT50" })
check("bots: handled silently", cmd(botp, "recruit dps") == false and #botp.cmds == 0 and #botp.msgs == 0)

-- no mod-playerbots in the build: coming soon
local stock = player({ guid = 60, built = false })
stock.IsPlayerbot, stock.RunCommand = nil, nil
check("no bot module: handled", cmd(stock, "recruit tank") == false)
check("no bot module: coming soon, no brand", last(stock):match("Bots are coming soon to this realm"))
cmd(stock, "companions"); cmd(stock, "buddy"); cmd(stock, "dismiss all")
check("no bot module: every command says so", #stock.msgs == 4)

-- loot: every arrival got the per-bot loot reset; the realm keys are checked in the profile test below
check("every claimed bot got 'll normal'", (function()
    for _, p in ipairs({ a, pf, rd, me }) do
        for _, w in ipairs(p.whispers) do
            if w.text == "follow" and not whispered(p, w.to, "^ll normal$") then return false end
        end
    end
    return true end)())

-- the realm profile and serverpass carry the always-pass loot keys and the caps
local function slurp(path) local f = io.open(path, "rb"); if not f then return nil end; local s = f:read("*a"); f:close(); return s end
local root = file:match("^(.*)realm/custom/lua_scripts/ov_companions%.lua$")
if root then
    local prof = slurp(root .. "realm/profiles/main.env") or ""
    local sp = slurp(root .. "realm/serverpass.sh") or ""
    local function both(kv) return prof:find("\n" .. kv .. "\n", 1, true) ~= nil and sp:find(kv, 1, true) ~= nil end
    check("loot: need -> pass", both("AC_PLAYERBOTS_LOOT_NEED_ROLL_LEVEL=0"))
    check("loot: greed -> pass", both("AC_PLAYERBOTS_LOOT_GREED_ROLL_LEVEL=0"))
    check("loot: no disenchant, no recipe rolls", both("AC_PLAYERBOTS_LOOT_ROLL_DISENCHANT=0") and both("AC_PLAYERBOTS_LOOT_ROLL_RECIPE=0"))
    check("loot: no looting under free-for-all", both("AC_PLAYERBOTS_FREE_METHOD_LOOT=0"))
    check("caps: module 9, realm 60, group 10, raid 9, 25 off", both("AC_PLAYERBOTS_MAX_ADDED_BOTS=9") and both("OV_COMPANIONS_REALM_MAX=60")
        and both("OV_COMPANIONS_GROUP_MAX=10") and both("OV_COMPANIONS_PER_PLAYER_RAID=9") and both("OV_COMPANIONS_RAID25=0"))
else
    realPrint("SKIP profile checks (run with the repo path to ov_companions.lua)")
end

-- names: no brand names, and companions are called bots
check("no brand names in anything players saw", (function()
    for _, m in ipairs(allMsgs) do
        local l = m:lower()
        for _, w in ipairs(BANNED) do
            if l:find(w, 1, true) and not (w == "wow" and not l:find("%f[%a]wow%f[%A]")) then return false end
        end
    end
    return true end)())
check("players only ever hear 'bots' (the .companions command aside)", (function()
    for _, m in ipairs(allMsgs) do
        if m:lower():gsub("%.companions?", ""):find("companion") then return false end
    end
    return true end)())
check("messages are short", (function()
    for _, m in ipairs(allMsgs) do if #m:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "") > 170 then realPrint("  long: " .. m); return false end end
    return true end)())

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
