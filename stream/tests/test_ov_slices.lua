-- Test ov_slices.lua under a fake mod-ale:
--   lua5.1 tests/test_ov_slices.lua lua/ov_slices.lua <ov_slices_tiers.lua> [ov_main.lua]
-- (tests/test_lua.py makes the tiers file from slices/mini.json with lua/tiers_lua.py and finds
-- ov_main.lua in ..\realm\custom\lua_scripts or $OV_MAIN_LUA.)
local script = assert(arg[1], "usage: lua5.1 test_ov_slices.lua <ov_slices.lua> <ov_slices_tiers.lua> [ov_main.lua]")
local tiersFile, mainFile = arg[2], arg[3]

-- ---- fake ALE ---------------------------------------------------------------------------------
local events, gossip, sql, accounts, rows = {}, {}, {}, { WR000123 = 42, OTHER = 7, LOWBIE = 50, HORDIE = 51, DEEKAY = 52 }, {}
local timers, nextTimer = {}, 0
local clock = 1000000
os.time = function() return clock end
local realGetenv = os.getenv
-- the realm's environment (the profile): tests switch OV_SAMPLER on and off through this table
local ENV = { OV_MAIN = "1" }
os.getenv = function(k) if ENV[k] ~= nil then return ENV[k] or nil end return realGetenv(k) end

local function query(result)
    if not result then return nil end
    local i = 1
    return {
        GetUInt32 = function(_, c) return result[i][c + 1] end,
        GetInt32 = function(_, c) return result[i][c + 1] end,
        GetString = function(_, c) return tostring(result[i][c + 1]) end,
        NextRow = function() i = i + 1; return result[i] ~= nil end,
    }
end

function AuthDBExecute(s) sql[#sql + 1] = s end
function AuthDBQuery(s)
    sql[#sql + 1] = s
    local name = s:match("username = '(%w+)'")
    if name then return accounts[name] and query({ { accounts[name] } }) end
    local id = s:match("account_id = (%d+) AND")
    if id then
        local r = rows[tonumber(id)]
        return r and query({ { r.slice, r.tier, r.left } })
    end
    if s:match("^SELECT account_id") then
        local all = {}
        for id, r in pairs(rows) do all[#all + 1] = { id, r.slice, r.tier, r.left } end
        return #all > 0 and query(all) or nil
    end
end
local charSql = {}
function CharDBExecute(s) charSql[#charSql + 1] = s end
function CharDBQuery(s) charSql[#charSql + 1] = s end
function WorldDBQuery(s) end
local mails = {}
function SendMail(...) mails[#mails + 1] = { ... } end
-- mod-ale keeps every handler registered for an event; a COMMAND returning false = handled.
function RegisterPlayerEvent(e, f) events[e] = events[e] or {}; table.insert(events[e], f) end
-- mod-ale's "can" hooks (50 CAN_JOIN_LFG) use CallAllFunctionsBool with its default false: a handler must
-- return true to allow; nothing (nil) or false refuses. Other events: nil unless a handler returns false.
local CAN_HOOKS = { [50] = true }
local function fire(e, ...)
    local result
    if CAN_HOOKS[e] and events[e] then result = false end
    for _, f in ipairs(events[e] or {}) do
        local r = f(e, ...)
        if CAN_HOOKS[e] then
            if r == true then result = true end
        elseif r == false then result = false end
    end
    return result
end
function RegisterPlayerGossipEvent(m, e, f) gossip[m] = f end
local online = {}
function GetPlayersInWorld() return online end

-- Where a fake position is (enough of the world for these tests).
local function zoneAt(map, x, y)
    if map == 571 then return 4395 end
    if map == 0 then
        if x >= -9150 and x <= -8250 and y >= 150 and y <= 1450 then return 1519 end
        if x >= -6500 and x <= -6000 then return 1 end   -- Dun Morogh (Coldridge Valley)
        return 12                                          -- Elwynn Forest
    end
    if map == 1 then
        if x >= 1300 and x <= 2100 and y >= -4850 and y <= -4050 then return 1637 end
        return 14                                          -- Durotar
    end
    if map == 609 then return 4298 end
    return 0
end

local function player(acct, map, x, y, opts)
    opts = opts or {}
    local p = { acct = acct, map = map, x = x or 0, y = y or 0, msgs = {}, center = {}, tp = {}, gm = false,
                dead = false, menu = {}, group = nil, canEnter = true, level = opts.level or 80,
                class = opts.class or 1, team = opts.team or 0, spells = {}, skills = {} }
    p.zone = opts.zone or zoneAt(map, p.x, p.y)
    function p:GetAccountId() return self.acct end
    function p:GetMapId() return self.map end
    function p:GetZoneId() return self.zone end
    function p:GetX() return self.x end
    function p:GetY() return self.y end
    function p:GetZ() return self.z or 660 end
    function p:GetGUIDLow() return self.acct * 10 end
    function p:GetLevel() return self.level end
    function p:SetLevel(l) local old = self.level; self.level = l; fire(13, self, old) end
    function p:GetClass() return self.class end
    function p:GetRace() return self.race or (self.team == 1 and 2 or 1) end
    function p:GetTeam() return self.team end
    function p:GetName() return "Tester" .. self.acct end
    function p:IsGM() return self.gm end
    function p:IsDead() return self.dead end
    function p:IsInCombat() return false end
    function p:ResurrectPlayer(pct) self.dead = false; self.res = pct end
    function p:Teleport(m, tx, ty, tz, o)
        if not self.canEnter then return false end
        self.tp[#self.tp + 1] = { m, tx, ty, tz, o }; self.map, self.x, self.y, self.z = m, tx, ty, tz
        self.zone = zoneAt(m, tx, ty)
        return true
    end
    function p:SendBroadcastMessage(s) self.msgs[#self.msgs + 1] = s end
    function p:SendAreaTriggerMessage(s) self.center[#self.center + 1] = s end
    function p:RegisterEvent(f, delay, rep)
        nextTimer = nextTimer + 1
        timers[#timers + 1] = { f = f, p = self, id = nextTimer, delay = delay, rep = rep or 1 }
        return nextTimer
    end
    function p:RemoveEventById(id)
        for i, t in ipairs(timers) do if t.id == id then table.remove(timers, i); return end end
    end
    function p:GossipClearMenu() self.menu = {} end
    function p:GossipMenuAddItem(icon, text, sender, intid) self.menu[#self.menu + 1] = { text, intid } end
    function p:GossipSendMenu(text, sender, id) self.menuId = id end
    function p:GossipComplete() self.menuId = nil end
    function p:GetGroup() return self.group end
    -- for ov_main.lua's boost
    function p:HasSpell(id) return self.spells[id] == true end
    function p:LearnSpell(id) self.spells[id] = true end
    function p:HasSkill(id) return self.skills[id] ~= nil end
    function p:SetSkill(id, step, cur, max) self.skills[id] = cur end
    function p:AdvanceSkillsToMax() end
    function p:CastSpell() end
    function p:AddItem() return newproxy(false) end
    function p:EquipItem() return newproxy(false) end
    function p:SetBindPoint(x, y, z, m, zone) self.bind = { m, x, y, z, zone } end
    function p:SaveToDB() end
    function p:ModifyMoney() end
    return p
end
-- One-shot events (sendHome, ov_main's menu) run; repeating ones (the box check) stay.
local function runTimers()
    for _ = 1, 4 do
        local due = {}
        for i = #timers, 1, -1 do
            if timers[i].rep == 1 then due[#due + 1] = table.remove(timers, i) end
        end
        if #due == 0 then return end
        for j = #due, 1, -1 do local e = due[j]; e.f(e.id, e.delay, 1, e.p) end
    end
end
local function tick()
    local reps = {}
    for _, t in ipairs(timers) do if t.rep == 0 then reps[#reps + 1] = t end end
    for _, t in ipairs(reps) do t.f(t.id, t.delay, 0, t.p) end
    runTimers()
end
local function repeating(p)
    local n = 0
    for _, t in ipairs(timers) do if t.rep == 0 and t.p == p then n = n + 1 end end
    return n
end
-- Logging out ends a player's timed events (mod-ale removes them with the object).
local function logout(p)
    for i = #timers, 1, -1 do if timers[i].p == p then table.remove(timers, i) end end
end
local handlerOut = {}
local handler = { SendSysMessage = function(_, s) handlerOut[#handlerOut + 1] = s end }

-- ---- tests -----------------------------------------------------------------------------------
local pass, fail = 0, 0
local function check(name, cond, extra)
    if cond then pass = pass + 1; print("PASS " .. name)
    else fail = fail + 1; print("FAIL " .. name .. (extra and ("  " .. tostring(extra)) or "")) end
end
local function menuText(p)
    local t = {}
    for _, it in ipairs(p.menu) do t[#t + 1] = it[1] end
    return table.concat(t, "|")
end
local function menuId(p, pattern)
    for _, it in ipairs(p.menu) do if it[1]:match(pattern) then return it[2] end end
end

rows[99] = { slice = "mini", tier = 3, left = 600 } -- a mark from before a restart
dofile(script)
local T = OV_SLICES_TEST
check("creates the table on load", sql[1]:match("CREATE TABLE IF NOT EXISTS ov_stream_accounts") ~= nil)
check("loads existing marks on load", T.flagged[99] and T.flagged[99].tier == 3 and T.flagged[99].exp == clock + 600)

-- Without ov_slices_tiers.lua: base + Dalaran only
check("no tiers file: the fallback (base + Dalaran)", T.tiers() == T.FALLBACK and T.tiers()[1].maps[1].id == 571)
local fb = player(42, 571, 5807, 588)
check("fallback: Dalaran is inside", T.inSlice({ tier = 9 }, fb, 571, 4395, 5807, 588))
check("fallback: Stormwind is outside", not T.inSlice({ tier = 9 }, fb, 0, 1519, -8833, 628))

-- Load the generated tiers (the global is read lazily, as on the realm where ov_slices.lua loads first)
dofile(assert(tiersFile, "the tiers file (tiers_lua.py output) is the second argument"))
local TT = OV_STREAM_TIERS
local K = {}
for n = 0, TT.count - 1 do K[TT[n].key] = n end
check("tiers file read after load", T.tiers() == TT and K.dalaran == 1 and K.base == 0)
local ALL = TT.count - 1
-- Every check looks tiers up by key, never by position, so any "order" in mini.json works. MID is a
-- mark that reaches every tier the checks below need open; LATER is a whole-map instance tier above
-- it (refused at MID).
local function maxOf(...)
    local m = 1
    for _, k in ipairs({ ... }) do m = math.max(m, (assert(K[k], "no tier " .. k))) end
    return m
end
local MID = maxOf("arenas", "ragefire-chasm", "deadmines", "stormwind", "northshire")
local LATER
for n = TT.count - 1, MID + 1, -1 do
    local t, m = TT[n], TT[n].maps[1]
    if t.play and m and not m.zone and not m.box then LATER = n; break end
end
assert(LATER, "this order leaves no instance tier above the test mark (tier " .. MID .. ")")
local LATER_MAP = TT[LATER].maps[1].id

-- the console command (SOAP): player nil
local r = fire(42, nil, "ovstream mark WR000123 mini " .. MID .. " 43200", handler)
check("mark: handled (returns false)", r == false)
check("mark: replies ovstream ok", handlerOut[#handlerOut]:match("^ovstream ok") ~= nil, handlerOut[#handlerOut])
check("mark: REPLACE INTO with the account id", sql[#sql]:match("REPLACE INTO ov_stream_accounts .-VALUES %(42, 'mini', " .. MID .. ", UNIX_TIMESTAMP%(%) %+ 43200%)") ~= nil, sql[#sql])
check("mark: cached", T.flagged[42].tier == MID)
fire(42, nil, "ovstream mark NOBODY mini 2 60", handler)
check("mark: unknown account refused", handlerOut[#handlerOut]:match("no such account") ~= nil)
local before = #sql
fire(42, nil, "ovstream mark WR000123 mini 2 60'; DROP TABLE account; --", handler)
check("mark: injection refused by the parser", handlerOut[#handlerOut]:match("usage") ~= nil and #sql == before)
fire(42, nil, "ovstream mark WR000123 mini 300 60", handler)
check("mark: a tier above 255 refused (TINYINT)", handlerOut[#handlerOut]:match("usage") ~= nil and T.flagged[42].tier == MID)
check("other console commands pass through", fire(42, nil, "server info", handler) == nil)

-- a level-80 character: in the slice nothing happens
local p = player(42, 571, 5807, 588)
fire(3, p); runTimers()
check("login in Dalaran: stays", #p.tp == 0)
check("login of a marked player: the position check runs", repeating(p) == 1)
p.map, p.zone = 572, 0; fire(28, p); runTimers()
check("arena allowed when the mark reaches the arenas tier", #p.tp == 0)
p.map, p.zone = 389, 0; fire(28, p); runTimers()
check("Ragefire Chasm (inside the mark) allowed at 80", #p.tp == 0)

-- outside: sent home with both messages
p.map, p.zone = LATER_MAP, 0; fire(28, p); runTimers()
check("an instance in a tier above the mark refused: sent to Dalaran", #p.tp == 1 and p.tp[1][1] == 571, LATER_MAP)
check("whisper says drop your game folder + the help page + Discord", p.msgs[#p.msgs]:match("Drop your own 3.3.5a game folder on the game page")
    and p.msgs[#p.msgs]:match("Use my game folder") and p.msgs[#p.msgs]:match("nothing is uploaded")
    and p.msgs[#p.msgs]:match("play.openvanilla.app/wrath/docs/play") and p.msgs[#p.msgs]:match("discord.gg/hVeUxYwbkr"))
check("centre text too: drop the game folder", #p.center == 1 and p.center[1]:match("drop your 3.3.5a game folder on the page"))
do
    local bad = false
    for _, t in ipairs({ p.msgs[#p.msgs], p.center[1] }) do
        local l = t:lower()
        if l:find("world of warcraft", 1, true) or l:find("warcraft", 1, true) or l:find("blizzard", 1, true)
            or l:find("lich king", 1, true) or l:find("%f[%a]wow%f[%A]") then bad = true end
    end
    check("zone-edge text has no game-brand words", not bad)
end
p.map, p.zone = 571, 4395
-- Standing in Dalaran while the core reports Crystalsong Forest (2817): the city floats above it, and the core
-- has no WMO area for it. Live 2026-10-24: this looped "sent home" every 5 s. Inside the city box it stays.
fire(27, p, 2817, 2817); p.zone = 2817; runTimers()
check("in Dalaran reported as Crystalsong Forest: stays (no loop)", #p.tp == 1)
for _ = 1, 3 do runTimers() end
check("...and the 5 s watch doesn't send it home either", #p.tp == 1)
-- Fell through Dalaran before its floor loaded (live 2026-10-24): same x/y, Crystalsong's ground below, dead.
local faller = player(42, 571, 5807, 588)
faller.zone, faller.z, faller.dead = 2817, 150, true
fire(27, faller, 2817, 2817); runTimers()
check("fell under Dalaran: resurrected and brought back up", faller.res == 100 and #faller.tp == 1 and faller.z > 450)
check("fell under Dalaran: told it fell, not \"not streamed\"", faller.msgs[#faller.msgs]:match("brought back up") and #faller.center == 0, faller.msgs[#faller.msgs])
faller.dead = false
for _ = 1, 3 do runTimers() end
check("...and stays once back up (no loop)", #faller.tp == 1)
p.x, p.y = 5300, -300                 -- flew out, down to Crystalsong Forest's ground
fire(27, p, 2817, 2817); runTimers()
check("Northrend outside Dalaran: sent home", #p.tp == 2)
check("messages are not spammed within a minute", #p.center == 1)
clock = clock + 10
p.map, p.zone, p.x, p.y, p.dead = 0, 40, -10500, 1000, true
logout(p); fire(3, p); runTimers()
check("dead outside: resurrected then home", p.res == 100 and p.tp[3][1] == 571)
check("login check reads the account row", sql[#sql]:match("account_id = 42 AND") ~= nil)
check("a new session gets one position check again", repeating(p) == 1)
-- Stormwind is open to an 80 too, but home stays Dalaran
p.map, p.x, p.y = 0, -8833, 628; p.zone = 1519; fire(28, p); runTimers()
check("level 80 in Stormwind: allowed", #p.tp == 3)

-- GMs in GM mode are left alone; unmarked players too
local gm = player(42, 0, -10500, 1000); gm.gm = true
fire(28, gm); runTimers()
check("GM mode: not moved", #gm.tp == 0)
local free = player(7, 0, -10500, 1000)
fire(28, free); runTimers()
check("unmarked account: not moved", #free.tp == 0)
fire(3, free)
check("unmarked login: no position check", repeating(free) == 0)

-- tier 0 still has Dalaran as home
fire(42, nil, "ovstream mark OTHER mini 0 60", handler)
local low = player(7, 571, 5807, 588)
fire(28, low); runTimers()
check("tier 0: Dalaran is still allowed (home)", #low.tp == 0)
local sw0 = player(7, 0, -8833, 628)
fire(28, sw0); runTimers()
check("tier 0: Stormwind is not (not streamed): Dalaran", sw0.tp[1] and sw0.tp[1][1] == 571)

-- expiry
clock = clock + 61
local exp = player(7, 0, -10500, 1000)
fire(28, exp); runTimers()
check("expired mark: free again", T.flagged[7] == nil and #exp.tp == 0)

-- ---- level-1 streamed characters -------------------------------------------------------------
fire(42, nil, "ovstream mark LOWBIE mini " .. ALL .. " 43200", handler)
local h1 = player(50, 0, -8949.95, -132.49, { level = 1, class = 1, team = 0 })   -- human warrior in Northshire
fire(3, h1); runTimers()
check("level 1 human in Northshire: stays", #h1.tp == 0)
check("level 1 login: told where it lives", h1.msgs[#h1.msgs]:match("Northshire Valley and Stormwind City") ~= nil, h1.msgs[#h1.msgs])
h1.x, h1.y = -9300, -100; h1.zone = 12          -- walked out of the box, still in Elwynn (no zone change)
tick()
check("left the Northshire box (no zone change): the position check sends it back", h1.tp[1] and h1.tp[1][1] == 0 and math.abs(h1.tp[1][2] + 8949.95) < 0.01)
check("sent back with the game-folder + Discord message", h1.msgs[#h1.msgs]:match("own 3.3.5a game folder") ~= nil)
h1.x, h1.y, h1.zone = -8833, 628, 1519; fire(27, h1, 1519, 1519); runTimers()
check("level 1 in Stormwind City: allowed", #h1.tp == 1)
clock = clock + 10
h1.x, h1.y, h1.zone = -10500, 1000, 40; fire(27, h1, 40, 40); runTimers()
check("level 1 in Westfall: back to Northshire", #h1.tp == 2 and h1.tp[2][1] == 0)
h1.map, h1.zone = 389, 0; fire(28, h1); runTimers()
check("level 1 in Ragefire Chasm: back to Northshire (dungeons open at 10)", #h1.tp == 3 and h1.tp[3][1] == 0)
h1.map, h1.x, h1.y = 1, 1629, -4373; h1.zone = 1637; fire(28, h1); runTimers()
check("level 1 Alliance in Orgrimmar: not its capital, back to Northshire", #h1.tp == 4 and h1.tp[4][1] == 0)
h1.map, h1.x, h1.y, h1.z, h1.zone = 571, 5807, 588, 660, 4395; fire(28, h1); runTimers()
check("level 1 in Dalaran: still home, allowed", #h1.tp == 4)

local dw = player(50, 0, -6240.32, 331.03, { level = 1, class = 1, team = 0 })  -- dwarf in Coldridge Valley
fire(3, dw); runTimers()
check("level 1 dwarf (Coldridge, not streamed): moved to Northshire on login", dw.tp[1] and dw.tp[1][1] == 0 and math.abs(dw.tp[1][3] + 132.493) < 0.01)

fire(42, nil, "ovstream mark HORDIE mini " .. ALL .. " 43200", handler)
local orc = player(51, 1, -618.5, -4251.7, { level = 3, class = 1, team = 1 })
fire(3, orc); runTimers()
check("level 3 orc in the Valley of Trials: stays", #orc.tp == 0)
orc.x, orc.y = 300, -4700; tick()
check("orc walked to Razor Hill: back to the Valley of Trials", orc.tp[1] and orc.tp[1][1] == 1 and math.abs(orc.tp[1][2] + 618.518) < 0.01)
local ud = player(51, 0, 1676.71, 1678.31, { level = 1, class = 4, team = 1 })   -- undead, Deathknell
fire(3, ud); runTimers()
check("level 1 undead (Deathknell): moved to the Valley of Trials", ud.tp[1] and ud.tp[1][1] == 1)
orc.x, orc.y, orc.zone = 1629, -4373, 1637; fire(27, orc, 1637, 1637); runTimers()
check("level 3 orc in Orgrimmar: allowed", #orc.tp == 1)
orc.map, orc.x, orc.y, orc.zone = 0, -8949, -132, 12; fire(28, orc); runTimers()
check("level 3 Horde in Northshire: not its starter area", #orc.tp == 2 and orc.tp[2][1] == 1)

-- a slice without the starter tiers: home falls back to the capital, then Dalaran (the tier list is
-- swapped for one with those tiers emptied, so this does not depend on where they sit in the order)
local function without(kinds)
    local c = {}
    for k, v in pairs(TT) do c[k] = v end
    for n = 0, TT.count - 1 do
        if kinds[TT[n].kind] then c[n] = { key = TT[n].key, name = TT[n].name, kind = "base", maps = {} } end
    end
    return c
end
OV_STREAM_TIERS = without({ starter = true })
local orc2 = player(51, 1, 300, -4700, { level = 3, class = 1, team = 1 })
fire(28, orc2); runTimers()
check("starter area not streamed: a level 3 orc goes to Orgrimmar", orc2.tp[1] and orc2.tp[1][1] == 1 and math.abs(orc2.tp[1][2] - 1629.85) < 0.01)
OV_STREAM_TIERS = without({ starter = true, city = true })
local orc4 = player(51, 1, 300, -4700, { level = 3, class = 1, team = 1 })
fire(28, orc4); runTimers()
check("neither starter area nor capital streamed: a level 3 orc goes to Dalaran", orc4.tp[1] and orc4.tp[1][1] == 571)
OV_STREAM_TIERS = TT
fire(42, nil, "ovstream mark HORDIE mini 1 43200", handler)
local orc3 = player(51, 1, 300, -4700, { level = 3, class = 1, team = 1 })
fire(28, orc3); runTimers()
check("only Dalaran streamed: a level 3 orc goes to Dalaran", orc3.tp[1] and orc3.tp[1][1] == 571)
fire(42, nil, "ovstream mark HORDIE mini " .. ALL .. " 43200", handler)

-- level 10+: Dungeon Finder and .play open; home is the capital
local mid = player(51, 389, 0, 0, { level = 16, team = 1 })
fire(28, mid); runTimers()
check("level 16 in Ragefire Chasm: allowed", #mid.tp == 0)
mid.map, mid.x, mid.y, mid.zone = 0, -10500, 1000, 40; fire(28, mid); runTimers()
check("level 16 Horde outside the slice: home is Orgrimmar", mid.tp[1] and mid.tp[1][1] == 1 and math.abs(mid.tp[1][2] - 1629.85) < 0.01)
check("home of a level 70: Dalaran", T.homeOf(T.flagged[51], player(51, 0, 0, 0, { level = 70, team = 1 }))[1] == 571)

-- Death Knights: Ebon Hold
fire(42, nil, "ovstream mark DEEKAY mini " .. ALL .. " 43200", handler)
local dk = player(52, 609, 2355.84, -5664.77, { level = 55, class = 6, team = 0 })
fire(3, dk); runTimers()
check("new Death Knight in Ebon Hold: stays", #dk.tp == 0)
dk.map, dk.x, dk.y, dk.zone = 0, 2280, -5300, 139; fire(28, dk); runTimers()   -- Light's Hope (Eastern Plaguelands)
check("Death Knight at Light's Hope (not streamed): to Stormwind", dk.tp[1] and dk.tp[1][1] == 0 and math.abs(dk.tp[1][2] + 8833.38) < 0.01)
fire(42, dk, ".play", nil)
gossip[61700](2, dk, dk, 0, menuId(dk, "^Your capital"), nil, 61700)
check(".play for a Death Knight lists Ebon Hold", menuText(dk):match("Ebon Hold") ~= nil, menuText(dk))

-- .play menu
fire(42, nil, "ovstream mark WR000123 mini " .. MID .. " 43200", handler)
local mp = player(42, 571, 5807, 588)
check(".play handled", fire(42, mp, ".play", nil) == false)
local top = menuText(mp)
check(".play top menu: groups", top:match("Dalaran") and top:match("Your capital") and top:match("Dungeons: Azeroth") and top:match("Arenas and battlegrounds"), top)
local firstRaid = TT.count
for n = 1, TT.count - 1 do if TT[n].kind == "raid" then firstRaid = math.min(firstRaid, n) end end
check(".play: a raid group once the mark reaches a raid tier", (top:match("Raids") ~= nil) == (MID >= firstRaid), top)
T.flagged[42].tier = firstRaid - 1
fire(42, mp, ".play", nil)
check(".play: no raid group when the mark stops before the raids", menuText(mp):match("Raids") == nil, menuText(mp))
T.flagged[42].tier = MID
fire(42, mp, ".play", nil)
check(".play: under 32 items", #mp.menu <= 32)
gossip[61700](2, mp, mp, 0, menuId(mp, "^Your capital"), nil, 61700)
local places = menuText(mp)
check(".play places: own capital and starter, not the Horde's", places:match("Stormwind City") and places:match("Northshire") and not places:match("Orgrimmar") and not places:match("Valley of Trials"), places)
check(".play places: Ebon Hold only for Death Knights", not places:match("Ebon Hold"), places)
gossip[61700](2, mp, mp, 0, menuId(mp, "Trade District"), nil, 61700)
check("menu: teleport to Stormwind", mp.tp[#mp.tp][1] == 0 and math.abs(mp.tp[#mp.tp][2] + 8833.38) < 0.01)
T.flagged[42].tier = ALL     -- every classic dungeon, wherever the order puts them
fire(42, mp, "play", nil)
gossip[61700](2, mp, mp, 0, menuId(mp, "^Dungeons: Azeroth"), nil, 61700)
local dz = menuText(mp)
check(".play classic dungeons listed by level, whatever the order", dz:find("Ragefire Chasm") and dz:find("Ragefire Chasm") < dz:find("Shadowfang Keep") and dz:find("Shadowfang Keep") < dz:find("Stratholme"), dz)
check(".play: Dungeons: Azeroth holds no Outland or Northrend dungeon", not dz:find("Hellfire") and not dz:find("Utgarde"), dz)
check(".play: Scarlet Monastery is one entry", select(2, dz:gsub("Scarlet Monastery", "")) == 1, dz)
gossip[61700](2, mp, mp, 0, menuId(mp, "Deadmines"), nil, 61700)
check("menu: teleport to the Deadmines entrance", mp.tp[#mp.tp][1] == 36)
T.flagged[42].tier = MID
fire(42, mp, "play", nil)
gossip[61700](2, mp, mp, 0, menuId(mp, "^Arenas"), nil, 61700)
local pvp = menuText(mp)
check(".play arenas info at the arenas tier", pvp:match("how to play") ~= nil, pvp)
gossip[61700](2, mp, mp, 0, menuId(mp, "^" .. TT[K.arenas].name .. ": how to play"), nil, 61700)
check("menu: the arena text is whispered", mp.msgs[#mp.msgs]:match("Arena Battlemaster") ~= nil)
check("menu: a tier above the mark is refused", (function()
    local n = #mp.tp
    gossip[61700](2, mp, mp, 0, 10000 + LATER * 100 + 1, nil, 61700)
    return #mp.tp == n
end)())
T.flagged[42].tier = ALL
fire(42, mp, "play", nil)
gossip[61700](2, mp, mp, 0, menuId(mp, "^Raids"), nil, 61700)
local raids = menuText(mp)
check(".play raids at the top tier", raids:match("Raid: Naxxramas") and raids:match("Raid: Icecrown Citadel"), raids)
gossip[61700](2, mp, mp, 0, menuId(mp, "Naxxramas"), nil, 61700)
check("menu: raid without a raid group refused", mp.tp[#mp.tp][1] ~= 533 and mp.msgs[#mp.msgs]:match("raid group"))
mp.group = { IsRaidGroup = function() return true end }
gossip[61700](2, mp, mp, 0, 10000 + K["naxx-os-voa"] * 100 + 1, nil, 61700)
check("menu: raid with a raid group", mp.tp[#mp.tp][1] == 533)
mp.canEnter = false
gossip[61700](2, mp, mp, 0, 10000 + K["violet-hold-toc"] * 100 + 2, nil, 61700)
check("menu: entry refused by the server is explained", mp.msgs[#mp.msgs]:match("can't enter"))
fire(42, mp, "play", nil)
gossip[61700](2, mp, mp, 0, menuId(mp, "Dungeons: Northrend"), nil, 61700)
check("menu: every submenu stays under 32 items", #mp.menu <= 32, #mp.menu)

-- .play below 10: the starter area and capital, no Dalaran, no dungeons
local lp = player(50, 0, -8949.95, -132.49, { level = 5, team = 0 })
fire(42, lp, ".play", nil)
local lt = menuText(lp)
check(".play below 10: places only", lt:match("Your capital") and not lt:match("Dungeons") and not lt:match("^Dalaran") and not lt:match("|Dalaran|"), lt)
check(".play below 10: says what level 10 brings", lt:match("At level 10") ~= nil, lt)
local np = player(7, 0, -10500, 1000)
fire(42, np, ".play", nil)
check(".play for an unmarked player: explained, no menu", #np.menu == 0 and np.msgs[1]:match("browser"))

-- Dungeon Finder
local lf = player(42, 571, 5807, 588)
check("LFG without the id table: refused", fire(50, lf, 0, { 241 }, "") == false)
OV_STREAM_LFG = { [241] = 575, [215] = 608, [4] = 389, [6] = 36, [300] = 4242 }
OV_STREAM_LFG_LEVEL = { [241] = { 80, 80 }, [215] = { 75, 80 }, [4] = { 15, 21 }, [6] = { 15, 23 } }
check("LFG: Utgarde Pinnacle allowed at the top tier, level 80", fire(50, lf, 0, { 241, 215 }, "") == true)
local keep42 = T.flagged[42].tier
T.flagged[42].tier = ALL
check("LFG: Random Lich King Dungeon allowed when every Wrath dungeon is streamed", fire(50, lf, 0, { 261 }, "") == true)
check("LFG: Random Lich King Heroic too", fire(50, lf, 0, { 262 }, "") == true)
T.flagged[42].tier = 0
check("LFG: random refused when the mark doesn't reach all its dungeons", fire(50, lf, 0, { 261 }, "") == false)
T.flagged[42].tier = keep42
check("LFG: an unknown random id refused", fire(50, lf, 0, { 9999 }, "") == false)
check("LFG: a non-streamed dungeon refused", fire(50, lf, 0, { 241, 300 }, "") == false)
check("LFG: allowed means an explicit true (mod-ale reads nothing as no)", fire(50, lf, 0, { 241 }, "") == true)
check("LFG: a set keyed by id is read too", fire(50, lf, 0, { [241] = true }, "") == true)
check("LFG: unmarked players untouched", fire(50, player(7, 0, 0, 0), 0, { 300 }, "") == true)
local l16 = player(50, 0, -8833, 628, { level = 16 })
check("LFG: level 16, Ragefire Chasm and the Deadmines allowed", fire(50, l16, 0, { 4, 6 }, "") == true)
check("LFG: level 16 refused for a level 75 dungeon", fire(50, l16, 0, { 215 }, "") == false and l16.msgs[#l16.msgs]:match("levels 75 to 80"))
local l9 = player(50, 0, -8949, -132, { level = 9 })
check("LFG: below 10 refused", fire(50, l9, 0, { 4 }, "") == false and l9.msgs[#l9.msgs]:match("opens at level 10"))
local l11 = player(50, 0, -8833, 628, { level = 11 })
check("LFG: level 11, Ragefire Chasm and the Deadmines allowed (realm minimum 10 under the DBC's 15)",
    fire(50, l11, 0, { 4, 6 }, "") == true)
OV_STREAM_LFG[7] = 48; OV_STREAM_LFG_LEVEL[7] = { 20, 30 }
check("LFG: level 11 still refused for Blackfathom Deeps (20), with the right range",
    fire(50, l11, 0, { 7 }, "") == false and l11.msgs[#l11.msgs]:match("levels 20 to 30"))
T.flagged[50].tier = K.deadmines - 1
check("LFG: a dungeon in a tier above the mark refused", fire(50, l16, 0, { 6 }, "") == false)
T.flagged[50].tier = ALL

-- reaching 10 (the slice's lowLevel)
local up = player(50, 0, -8949, -132, { level = 9 })
up:SetLevel(10)
check("level 10 reached: told the Dungeon Finder is open", up.msgs[#up.msgs]:match("Dungeon Finder") ~= nil)

-- clear
fire(42, nil, "ovstream clear WR000123", handler)
check("clear: DELETE + uncached", sql[#sql]:match("DELETE FROM ov_stream_accounts WHERE account_id = 42") and T.flagged[42] == nil)
check("clear: replies ok", handlerOut[#handlerOut]:match("^ovstream ok"))
tick()
check("clear: the position check stops itself", repeating(p) == 0)

-- ---- the main realm's boost (ov_main.lua) on a streamed level-1 character ----------------------
if mainFile then
    OV_KITS = { order = { [1] = { "arms" } }, [1] = { arms = { name = "Arms", pve = { 1 }, pvp = { 2 } } } }
    dofile(mainFile)
    check("ov_main.lua loads beside ov_slices.lua", events[30] ~= nil and gossip[61010] ~= nil)
    fire(42, nil, "ovstream mark LOWBIE mini " .. ALL .. " 43200", handler)
    local nb = player(50, 0, -6240.32, 331.03, { level = 1, class = 1, team = 0 })   -- a new dwarf
    fire(3, nb); fire(30, nb); runTimers()
    check("boost: the new character was moved to Northshire first", nb.tp[1] and nb.tp[1][1] == 0)
    check("new character: Apprentice Riding and its race mount at level 1", nb.spells[33388] == true and nb.spells[({[1]=458,[3]=6899})[nb:GetRace()]] == true)
    check("boost: the choice menu opened", nb.menuId == 61010 and menuText(nb):match("Boost to level 80"), menuText(nb))
    gossip[61010](2, nb, nb, 0, 2, nil, 61010)     -- Boost -> spec menu
    gossip[61010](2, nb, nb, 0, 11, nil, 61010)    -- Arms -> professions
    gossip[61010](2, nb, nb, 0, 999, nil, 61010)   -- boost now
    check("boost: level 80", nb.level == 80)
    local last = nb.tp[#nb.tp]
    check("boost: sent to Dalaran", last[1] == 571 and math.abs(last[2] - 5804.15) < 0.01)
    fire(28, nb); fire(27, nb, 4395, 4395); runTimers(); tick()
    check("boost: the streamed character stays in Dalaran", nb.tp[#nb.tp] == last and nb.map == 571)
    fire(42, nb, ".play", nil)
    check("boost: .play now has dungeons and Dalaran", menuText(nb):match("Dungeons") and menuText(nb):match("Dalaran"))
else
    print("SKIP ov_main.lua boost tests (no ov_main.lua given)")
end

-- .reload ale drops every timed event: the reloaded script re-arms players already online.
local stuck = player(42, 571, 5807, 588)
stuck.zone, stuck.z, stuck.dead = 2817, 150, true
online[#online + 1] = stuck
logout(stuck)
rows[42] = { slice = "mini", tier = MID, left = 43200 } -- the mark as the database has it
for k in pairs(events) do events[k] = nil end
dofile(script); runTimers()
check("reload: an online player under Dalaran is rescued", stuck.res == 100 and #stuck.tp == 1 and stuck.z > 450)
check("reload: the watch is re-armed", repeating(stuck) == 1, repeating(stuck))
dofile(script); runTimers()
check("reload twice: still one watch", repeating(stuck) <= 2)
table.remove(online)

-- A marked account on its own 3.3.5a client (Discord, 2026-10-26): a public address is a desktop
-- session, never fenced; the stream relay's private address still is.
fire(42, nil, "ovstream mark WR000123 mini " .. MID .. " 43200", handler)
do
    local desk = player(42, 571, 5807, 588)
    function desk:GetPlayerIP() return "203.0.113.7" end
    fire(3, desk); runTimers()
    desk.map, desk.zone = LATER_MAP, 0; fire(28, desk); runTimers()
    check("desktop client (public address): a marked account goes anywhere", #desk.tp == 0, #desk.tp)
    check("desktop client: no position watch", repeating(desk) == 0, repeating(desk))
    local web = player(42, 571, 5807, 588)
    function web:GetPlayerIP() return "172.18.0.1" end
    fire(3, web); runTimers()
    web.map, web.zone = LATER_MAP, 0; fire(28, web); runTimers()
    check("browser session (relay's private address): still fenced", #web.tp == 1 and web.tp[1][1] == 571, #web.tp)
    local mapped = player(42, 571, 5807, 588)
    function mapped:GetPlayerIP() return "::ffff:10.0.0.5" end
    mapped.map, mapped.zone = LATER_MAP, 0; fire(28, mapped); runTimers()
    check("an IPv4-mapped private address counts as the relay", #mapped.tp == 1, #mapped.tp)
    local ok100 = player(42, 571, 5807, 588)
    function ok100:GetPlayerIP() return "100.20.1.1" end
    ok100.map, ok100.zone = LATER_MAP, 0; fire(28, ok100); runTimers()
    check("100.20.x is public (only 100.64/10 is shared space)", #ok100.tp == 0, #ok100.tp)
end

-- ---- the Leyline Sample Hangout (OV_SAMPLER=1, realm/profiles/sampler.env) --------------------------
-- Streamed browser sessions: Dalaran, the starting areas and every streamed instance; no capitals.
-- Sessions with their own files (desktop, or the browser after "Use my game folder") keep the whole world.
ENV.OV_SAMPLER = "1"
local function noBrand(t)
    local l = (t or ""):lower()
    return not (l:find("world of warcraft", 1, true) or l:find("warcraft", 1, true) or l:find("blizzard", 1, true)
        or l:find("lich king", 1, true) or l:find("%f[%a]wow%f[%A]"))
end
local function web(acct, map, x, y, opts)
    local q = player(acct, map, x, y, opts)
    function q:GetPlayerIP() return "172.18.0.9" end
    return q
end
local function desk(acct, map, x, y, opts)
    local q = player(acct, map, x, y, opts)
    function q:GetPlayerIP() return "198.51.100.20" end
    return q
end
clock = clock + 120
-- a mark as the console makes it, also in the fake auth database (a login reads the row back)
local function markAll(name, id)
    fire(42, nil, "ovstream mark " .. name .. " mini " .. ALL .. " 43200", handler)
    rows[id] = { slice = "mini", tier = ALL, left = 43200 }
end
markAll("WR000123", 42)
markAll("HORDIE", 51)
markAll("LOWBIE", 50)
do
    local s80 = web(42, 0, -8833, 628, { level = 80 })   -- Stormwind City, browser session
    fire(3, s80); runTimers()
    check("sampler: welcome line at login names the Sample Hangout and says temporary",
        s80.msgs[1] and s80.msgs[1]:match("Leyline Sample Hangout") and s80.msgs[1]:match("temporary"), s80.msgs[1])
    check("sampler, browser: a capital is closed (level 80 in Stormwind goes to Dalaran)",
        #s80.tp == 1 and s80.tp[1][1] == 571, #s80.tp)
    local m = s80.msgs[#s80.msgs]
    check("sampler message: add your own game folder to explore the whole world",
        m:match("Add your own 3.3.5a game folder to explore the whole world") and m:match("Use my game folder")
        and m:match("nothing is uploaded") and m:match("play.openvanilla.app/wrath/docs/play"), m)
    check("sampler message: points to community realms on Leyline", m:match("community realm from Leyline") ~= nil, m)
    check("sampler centre text: add your own game folder", s80.center[1] == "Add your own game folder to explore the whole world", s80.center[1])
    check("sampler messages: no game-brand words", noBrand(m) and noBrand(s80.center[1]) and noBrand(s80.msgs[1]))
    s80.map, s80.zone, s80.x, s80.y = 571, 4395, 5807, 588; fire(28, s80); runTimers()
    check("sampler, browser: Dalaran stays open", #s80.tp == 1)
    s80.map, s80.zone = 36, 0; fire(28, s80); runTimers()
    check("sampler, browser: a dungeon (the Deadmines) stays open", #s80.tp == 1)
    s80.map, s80.zone = 533, 0; fire(28, s80); runTimers()
    check("sampler, browser: a raid (Naxxramas) stays open", #s80.tp == 1)
    s80.map, s80.zone = 617, 0; fire(28, s80); runTimers()
    check("sampler, browser: the Dalaran arena stays open", #s80.tp == 1)
    clock = clock + 61
    s80.map, s80.x, s80.y, s80.zone = 0, -10500, 1000, 40; fire(28, s80); runTimers()
    check("sampler, browser: the open world (Westfall) goes back to Dalaran", #s80.tp == 2 and s80.tp[2][1] == 571)
    -- the boost spot / Hearthstone into a capital: same rule, wherever the character was bound
    clock = clock + 61
    local h = web(42, 1, 1629, -4373, { level = 80, team = 1 })  -- hearthed to Orgrimmar
    fire(28, h); runTimers()
    check("sampler, browser: a Hearthstone into Orgrimmar lands back in Dalaran", #h.tp == 1 and h.tp[1][1] == 571)
    -- a portal or the Deeprun Tram out of a capital: map 369 is not streamed
    local tram = web(42, 369, 0, 0, { level = 80 })
    fire(28, tram); runTimers()
    check("sampler, browser: a portal to an unstreamed map lands back in Dalaran", #tram.tp == 1 and tram.tp[1][1] == 571)

    -- level 1-9: their starting area, not the capital
    local h1s = web(50, 0, -8949.95, -132.49, { level = 1, team = 0 })
    fire(3, h1s); runTimers()
    check("sampler, browser: a new human starts in Northshire and stays", #h1s.tp == 0)
    check("sampler, browser: the level-1 line names the starting area only",
        h1s.msgs[#h1s.msgs]:match("Northshire Valley until level") and not h1s.msgs[#h1s.msgs]:match("Stormwind"), h1s.msgs[#h1s.msgs])
    h1s.x, h1s.y, h1s.zone = -8833, 628, 1519; fire(27, h1s, 1519, 1519); runTimers()
    check("sampler, browser: level 1 in Stormwind goes back to Northshire", #h1s.tp == 1 and h1s.tp[1][1] == 0
        and math.abs(h1s.tp[1][2] + 8949.95) < 0.01)
    local o1 = web(51, 1, -618.5, -4251.7, { level = 1, team = 1 })
    fire(3, o1); runTimers()
    check("sampler, browser: a new orc starts in the Valley of Trials and stays", #o1.tp == 0)
    o1.x, o1.y, o1.zone = 1629, -4373, 1637; fire(27, o1, 1637, 1637); runTimers()
    check("sampler, browser: level 1 in Orgrimmar goes back to the Valley of Trials", #o1.tp == 1 and o1.tp[1][1] == 1
        and math.abs(o1.tp[1][2] + 618.518) < 0.01)
    local dk2 = web(52, 609, 2355.84, -5664.77, { level = 55, class = 6 })
    markAll("DEEKAY", 52)
    fire(3, dk2); runTimers()
    check("sampler, browser: a new Death Knight stays in Ebon Hold", #dk2.tp == 0)
    -- level 10 to 67: home is Dalaran (no capital)
    local m16 = web(51, 0, -10500, 1000, { level = 16, team = 1 })
    fire(28, m16); runTimers()
    check("sampler, browser: level 16 outside goes to Dalaran, not Orgrimmar", m16.tp[1] and m16.tp[1][1] == 571)
    -- .play: no capitals
    local pm = web(42, 571, 5807, 588, { level = 80 })
    fire(42, pm, ".play", nil)
    local topS = menuText(pm)
    check(".play under the sampler: \"Your starting area\", dungeons, raids and Dalaran",
        topS:match("Your starting area") and not topS:match("Your capital") and topS:match("Dungeons")
        and topS:match("Raids") and topS:match("Dalaran"), topS)
    gossip[61700](2, pm, pm, 0, menuId(pm, "^Your starting area"), nil, 61700)
    check(".play under the sampler: no capital in the places menu", not menuText(pm):match("Stormwind")
        and menuText(pm):match("Northshire"), menuText(pm))
    -- the Dungeon Finder stays on
    check("sampler: the Dungeon Finder still queues a streamed dungeon", fire(50, pm, 0, { 241 }, "") == true)

    -- own files: a desktop client, or the browser after "Use my game folder" (the mark is cleared)
    local d80 = desk(42, 0, -10500, 1000, { level = 80 })
    fire(3, d80); runTimers()
    check("sampler, desktop client: the whole world (Westfall stays)", #d80.tp == 0, #d80.tp)
    check("sampler, desktop client: welcome line too", d80.msgs[1]:match("Leyline Sample Hangout") ~= nil)
    check("sampler, desktop client: no position watch", repeating(d80) == 0)
    d80.map, d80.x, d80.y, d80.zone = 0, -8833, 628, 1519; fire(28, d80); runTimers()
    check("sampler, desktop client: capitals open", #d80.tp == 0)
    fire(42, nil, "ovstream clear WR000123", handler); rows[42] = nil   -- the DELETE, in the fake database
    local own = web(42, 0, -10500, 1000, { level = 80 })
    fire(3, own); runTimers()
    check("sampler, browser with its own game folder (mark cleared): the whole world", #own.tp == 0)
    -- streaming switched off (stream-switch.sh off, or the data killswitch): every mark is deleted and
    -- "reload ale" reloads the script, so every browser session is an own-files session with the whole world
    rows = {}
    for k in pairs(events) do events[k] = nil end
    dofile(script); runTimers()
    local killed = web(51, 0, -10500, 1000, { level = 30, team = 1 })
    fire(3, killed); runTimers()
    check("sampler, streaming off (no marks): a browser session keeps the whole world", #killed.tp == 0 and repeating(killed) == 0)
    markAll("WR000123", 42)

    -- OV_SAMPLER_CITIES=1 opens the capitals again; OV_SAMPLER off is the main realm's rule
    ENV.OV_SAMPLER_CITIES = "1"
    local sc = web(42, 0, -8833, 628, { level = 80 })
    fire(28, sc); runTimers()
    check("sampler with OV_SAMPLER_CITIES=1: Stormwind open", #sc.tp == 0)
    ENV.OV_SAMPLER_CITIES = nil
    ENV.OV_SAMPLER = false
    local mainP = web(42, 0, -8833, 628, { level = 80 })
    fire(3, mainP); runTimers()
    check("OV_SAMPLER off: Stormwind open again (the main realm's rule)", #mainP.tp == 0)
    check("OV_SAMPLER off: no Sample Hangout welcome", not (mainP.msgs[1] or ""):match("Sample Hangout"))
    clock = clock + 61
    mainP.map, mainP.x, mainP.y, mainP.zone = 0, -10500, 1000, 40; fire(28, mainP); runTimers()
    check("OV_SAMPLER off: the old message (drop your game folder)", mainP.msgs[#mainP.msgs]:match("Drop your own 3.3.5a game folder") ~= nil)
    ENV.OV_SAMPLER = nil
end

-- tiers in the script, as text for the JSON cross-check (tests/test_lua.py)
local parts = {}
for t = 0, TT.count - 1 do
    local ids = {}
    for _, m in ipairs(T.tiers()[t].maps) do ids[#ids + 1] = m.id end
    parts[#parts + 1] = t .. "=" .. table.concat(ids, ",")
end
print("TIERS " .. table.concat(parts, ";"))
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
