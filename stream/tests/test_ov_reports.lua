-- lua5.1 tests/test_ov_reports.lua ov_reports.lua
local file = assert(arg[1], "ov_reports.lua")
local sql, events = {}, {}
local clock = 1000000
os.time = function() return clock end
function CharDBExecute(q) sql[#sql + 1] = q end
function RegisterPlayerEvent(id, fn) events[id] = fn end

-- fake world DB: mount items as (spellid_1, spellid_2); 483/55884 are the generic learn spells
local worldQueries = {}
local MOUNT_ROWS = { { 483, 458 }, { 55884, 59569 }, { 23509, 0 }, { 483, 458 }, { 0, 0 }, { 483, 0 }, { 32244, 0 } }
for i = 1, 90 do MOUNT_ROWS[#MOUNT_ROWS + 1] = { 55884, 70000 + i } end
local function fakeQuery(rows)
    if #rows == 0 then return nil end
    local r = 1
    return { GetUInt32 = function(_, c) return rows[r][c + 1] end, NextRow = function() r = r + 1; return r <= #rows end }
end
function WorldDBQuery(q) worldQueries[#worldQueries + 1] = q; return fakeQuery(MOUNT_ROWS) end
local charQueries, unlocked = {}, {}
function CharDBQuery(q)
    charQueries[#charQueries + 1] = q
    local guid = tonumber(q:match("ov_unlocks WHERE guid = (%d+) AND kind = 'mounts'") or "")
    if guid and unlocked[guid] then return fakeQuery({ { 1 } }) end
    return nil
end
dofile(file)
local T = assert(OV_REPORTS_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local function player(over)
    local p = { msgs = {}, casts = {}, combat = false, dead = false }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    function p:GetAccountId() return self.account or 42 end
    function p:GetGUIDLow() return self.guid or 5 end
    function p:GetName() return self.name or "Smokepally" end
    function p:GetLevel() return self.level or 12 end
    function p:GetClass() return 2 end
    function p:GetMapId() return 0 end
    function p:GetZoneId() return 12 end
    function p:GetAreaId() return 9 end
    function p:GetX() return -8949.95 end
    function p:GetY() return -132.49 end
    function p:GetZ() return 83.53 end
    function p:IsInCombat() return self.combat end
    function p:IsDead() return self.dead end
    function p:CastSpell(t, s, trig) self.casts[#self.casts + 1] = { s, trig } end
    function p:RegisterEvent(fn, delay, rep)
        self.timers = self.timers or {}; self.timers[#self.timers + 1] = fn
        self.queue = self.queue or {}; self.queue[#self.queue + 1] = { fn = fn, delay = delay, rep = rep }
    end
    p.spells, p.learned = p.spells or {}, {}
    function p:HasSpell(id) return self.spells[id] == true end
    function p:LearnSpell(id) self.spells[id] = true; self.learned[#self.learned + 1] = id end
    return p
end

check("table created on load", sql[1]:match("CREATE TABLE IF NOT EXISTS ov_bug_reports"))
check("events registered", events[42] and events[3])

local p = player()
local n0 = #sql
check(".bug handled", events[42](42, p, ".bug the vendor's window doesn't open") == false)
check("one insert", #sql == n0 + 1 and sql[#sql]:match("^INSERT INTO ov_bug_reports"))
check("text escaped", sql[#sql]:match("vendor''s window"))
check("position stored", sql[#sql]:match("%-8949%.95, %-132%.49, 83%.53"))
check("thanked", p.msgs[#p.msgs]:match("Bug report sent"))

local q = player({ name = "Ev'il" })
events[42](42, q, "report x'); DROP TABLE characters; -- \\")
local last = sql[#sql]
check("injection stays inside the literal", last:match("x''%); DROP TABLE characters; %-%- \\\\'%)$") ~= nil)
check("name escaped", last:match("'Ev''il'"))

local e = player({ account = 9 })
local before = #sql
events[42](42, e, "bug")
check("empty report explained, not stored", #sql == before and e.msgs[#e.msgs]:match("Type .bug"))

local r = player({ account = 77 })
for i = 1, 6 do events[42](42, r, "bug report number " .. i) end
local c = #sql
events[42](42, r, "bug seventh")
check("rate limit at 6 per hour", #sql == c and r.msgs[#r.msgs]:match("6 reports this hour"))
clock = clock + 3601
events[42](42, r, "bug after an hour")
check("rate limit resets after an hour", #sql == c + 1)

local long = player({ account = 78 })
events[42](42, long, "bug " .. string.rep("a", 900))
check("text capped at 500", #sql[#sql]:match("'(a+)'%)$") == 500)

local s = player({ guid = 11 })
check(".stuck handled", events[42](42, s, "stuck") == false)
check(".stuck hearths (triggered)", s.casts[1] and s.casts[1][1] == 8690 and s.casts[1][2] == true)
events[42](42, s, "stuck")
check(".stuck cooldown", #s.casts == 1 and s.msgs[#s.msgs]:match("ready again in 10 min"))
clock = clock + 601
events[42](42, s, "unstuck")
check(".stuck after the cooldown", #s.casts == 2)
local f = player({ guid = 12, combat = true })
events[42](42, f, "stuck")
check(".stuck refused in combat", #f.casts == 0 and f.msgs[1]:match("in combat"))
local d = player({ guid = 13, dead = true })
events[42](42, d, "stuck")
check(".stuck refused when dead", #d.casts == 0 and d.msgs[1]:match("release your spirit"))

local w = player()
check(".wu lists commands", events[42](42, w, "wu") == false and w.msgs[1]:match("%.bug"))
check("other commands untouched", events[42](42, w, "boost") == nil and events[42](42, w, "gm on") == nil)
local l = player()
events[3](3, l)
check("login tip", l.msgs[1]:match("%.bug"))

-- the level 80 guide
local g = player()
check(".guide handled", events[42](42, g, "guide") == false)
check(".guide shows every line", #g.msgs == #OV_REPORTS_TEST.GUIDE and g.msgs[2]:match("Dungeon Finder"))
check(".wu mentions .guide", (function() local x = player(); events[42](42, x, "wu"); return x.msgs[1]:match("%.guide") end)())
check("level event registered", events[13] ~= nil)
local up = player({ level = 80 })
events[13](13, up, 79)
check("reaching 80 queues the guide", up.timers and #up.timers >= 1)
up.timers[1](1, 4000, 1, up)
check("...and shows it", #up.msgs == #OV_REPORTS_TEST.GUIDE)
local mid = player({ level = 45 })
events[13](13, mid, 44)
check("below 80: no guide", not mid.timers)
local again = player({ level = 80 })
events[13](13, again, 80)
check("already 80 (a level event at 80): no repeat", not again.timers)
local l80 = player({ level = 80 })
events[3](3, l80)
check("an 80's login points to .guide", l80.msgs[2] and l80.msgs[2]:match("%.guide"))
local l12 = player()
events[3](3, l12)
check("a level 12's login doesn't", #l12.msgs == 1)

-- every mount for level 80s
-- fire queued timers like ALE: each event runs `rep` times; returns the number of ticks run
local function run(p)
    local n = 0
    while p.queue and #p.queue > 0 do
        local e = table.remove(p.queue, 1)
        for k = 1, e.rep do n = n + 1; e.fn(n, e.delay, e.rep - k, p) end
    end
    return n
end
local function count(t, x) local c = 0; for _, v in ipairs(t) do if v == x then c = c + 1 end end; return c end
local function has(t, x) return count(t, x) > 0 end
local function lastMsg(p) return p.msgs[#p.msgs] or "" end

check("ov_unlocks created on load", (function()
    for _, q in ipairs(sql) do if q:match("CREATE TABLE IF NOT EXISTS ov_unlocks %(guid") then return true end end end)())
check("one world query at load", #worldQueries == 1 and worldQueries[1]:match("class = 15 AND subclass = 5"))
local M = OV_REPORTS_TEST.MOUNT_SPELLS
check("learn spell 483 -> spellid_2", has(M, 458) and not has(M, 483))
check("learn spell 55884 -> spellid_2", has(M, 59569) and not has(M, 55884))
check("direct spellid_1 kept", has(M, 23509) and has(M, 32244))
check("0 ignored, duplicates once", not has(M, 0) and count(M, 458) == 1)
check("flying carpets added", has(M, 61451) and has(M, 61309) and has(M, 75596))
check("94 + 3 carpets = 97 spells", #M == 97)

-- reaching 80 learns every mount, spread over ticks
local m = player({ guid = 100, level = 80, spells = { [34091] = true, [54197] = true, [458] = true } })
events[13](13, m, 79)
local n80 = #sql
local ticks = run(m)
check("learning is spread over ticks", ticks >= 3 and ticks <= math.ceil(#M / OV_REPORTS_TEST.MOUNTS_PER_TICK) + 2)
check("every mount learned", (function() for _, id in ipairs(M) do if not m.spells[id] then return false end end return true end)())
check("known mounts skipped (HasSpell)", not has(m.learned, 458) and #m.learned == #M - 1)
check("riding already known: not relearned", not has(m.learned, 34091) and not has(m.learned, 54197))
check("marked done once", #sql == n80 + 1 and sql[#sql]:match("INSERT INTO ov_unlocks %(guid, kind%) VALUES %(100, 'mounts'%)"))
check("one line to the player", lastMsg(m) == "|cff66ccff[WrathUnleashed]|r Every mount is in your spellbook (Mounts tab).")
check("the guide still shows", #m.msgs == #OV_REPORTS_TEST.GUIDE + 1)

-- missing riding: Artisan and Cold Weather Flying first
local nr = player({ guid = 101, level = 80 })
events[13](13, nr, 79); run(nr)
check("riding learned first", nr.learned[1] == 34091 and nr.learned[2] == 54197)

-- login at 80, once
local lo = player({ guid = 102, level = 80 })
events[3](3, lo); run(lo)
check("first login at 80 unlocks", lo.spells[59569] and lastMsg(lo):match("Every mount"))
local lo2 = player({ guid = 102, level = 80 })
local cq = #charQueries
events[3](3, lo2)
check("second login: no repeat, no query (cached)", not lo2.queue and #charQueries == cq)
unlocked[103] = true
local lo3 = player({ guid = 103, level = 80 })
events[3](3, lo3)
check("marked in ov_unlocks (after a restart): no repeat", not lo3.queue)
local low = player({ guid = 104, level = 70 })
events[3](3, low); events[13](13, low, 69)
check("below 80: nothing", not low.queue and #charQueries == cq + 1)
local lv = player({ guid = 100, level = 80 })
events[13](13, lv, 79)
check("reaching 80 again (done): only the guide", #lv.queue == 1)

-- .mounts re-runs it, once per 10 minutes
local rc = player({ guid = 100, level = 80 })
check(".mounts handled", events[42](42, rc, "mounts") == false)
run(rc)
check(".mounts re-runs even when done", rc.spells[59569] and lastMsg(rc):match("Every mount"))
events[42](42, rc, ".mounts")
check(".mounts cooldown", not rc.queue[1] and lastMsg(rc):match("%.mounts is ready again in 10 min"))
clock = clock + 601
events[42](42, rc, "mounts")
check(".mounts after the cooldown", #rc.queue == 1)
local busy = player({ guid = 105, level = 80 })
events[42](42, busy, "mounts")
clock = clock + 601
events[42](42, busy, "mounts")
check(".mounts while running: not doubled", #busy.queue == 1 and lastMsg(busy):match("Already learning"))
local lowc = player({ guid = 106, level = 30 })
events[42](42, lowc, "mounts")
check(".mounts below 80 explained", not lowc.queue and lastMsg(lowc):match("at level 80"))
check(".wu mentions .mounts", (function() local x = player(); events[42](42, x, "wu"); return x.msgs[1]:match("%.mounts") end)())

-- the Leyline brand switch: the chat tag (OVMod.Brand from ov_modapi.lua; off: the old one)
local t0 = player(); events[42](42, t0, "wu")
check("brand off: the old chat tag", t0.msgs[1]:find("|cff66ccff[WrathUnleashed]|r ", 1, true) == 1)
_G.OVMod = { Brand = function() return { on = true, name = "Leyline", realm = "Wrath Unleashed", home = "Wrath Unleashed" } end }
local t1 = player(); events[42](42, t1, "wu")
check("brand on: [Leyline]", t1.msgs[1]:find("|cff66ccff[Leyline]|r ", 1, true) == 1 and not t1.msgs[1]:find("WrathUnleashed", 1, true))
_G.OVMod = nil

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
