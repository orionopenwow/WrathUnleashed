-- lua5.1 tests/test_ov_reports.lua ov_reports.lua
local file = assert(arg[1], "ov_reports.lua")
local sql, events = {}, {}
local clock = 1000000
os.time = function() return clock end
function CharDBExecute(q) sql[#sql + 1] = q end
function RegisterPlayerEvent(id, fn) events[id] = fn end
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
    function p:RegisterEvent(fn, delay, rep) self.timers = self.timers or {}; self.timers[#self.timers + 1] = fn end
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
check("reaching 80 queues the guide", up.timers and #up.timers == 1)
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

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
