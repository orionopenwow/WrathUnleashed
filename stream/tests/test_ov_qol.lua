-- lua5.1 tests/test_ov_qol.lua ../realm/custom/lua_scripts/ov_qol.lua
local file = assert(arg[1], "ov_qol.lua")
local events, worldQueries, printed = {}, {}, {}
local clock = 1000000
os.time = function() return clock end
local env = {}

os.getenv = function(k) return env[k] end   -- only what a test sets
function RegisterPlayerEvent(id, fn) events[id] = fn end
local realPrint = print
print = function(s) printed[#printed + 1] = tostring(s) end

-- fake world DB --------------------------------------------------------------------------------------------
-- rows: cls, id, lvl, sk, r1, r2, r3, prev
local TRAINER_ROWS = {
    { 1, 78, 1, 0, 0, 0, 0, 0 },          -- warrior Heroic Strike r1
    { 1, 100, 4, 0, 0, 0, 0, 0 },         -- Charge
    { 1, 772, 4, 0, 0, 0, 0, 0 },         -- Rend
    { 1, 284, 8, 0, 78, 0, 0, 78 },       -- Heroic Strike r2 (ReqAbility + previous rank)
    { 1, 6546, 10, 0, 772, 0, 0, 772 },   -- Rend r2
    { 1, 285, 16, 0, 284, 0, 0, 284 },    -- Heroic Strike r3
    { 1, 21551, 48, 0, 12294, 0, 0, 12294 }, -- Mortal Strike r2: needs the talent
    { 1, 9999, 20, 0, 0, 0, 0, 9998 },    -- a rank whose previous rank (spell_ranks) is unknown
    { 1, 33391, 20, 0, 0, 0, 0, 0 },      -- riding: never
    { 1, 2580, 5, 186, 0, 0, 0, 0 },      -- a ReqSkillLine row (profession): never
    { 1, 7777, 5, 0, 0, 0, 0, 0 },        -- a teach spell with no mapping (HasEffect 36): never
    { 1, 8888, 5, 0, 0, 0, 0, 0 },        -- IsProfessionOrRiding: never
    { 2, 13820, 20, 0, 0, 0, 0, 0 },      -- paladin Warhorse (Alliance teach spell -> 13819)
    { 2, 34768, 20, 0, 0, 0, 0, 0 },      -- Thalassian Warhorse (Horde teach spell -> 34769)
    { 2, 23214, 40, 0, 13819, 33391, 0, 0 }, -- Charger
    { 2, 635, 1, 0, 0, 0, 0, 0 },         -- Holy Light
}
for i = 1, 60 do TRAINER_ROWS[#TRAINER_ROWS + 1] = { 8, 50000 + i, 10, 0, 0, 0, 0, 0 } end -- mage: 60 at level 10
for i = 1, 3 do TRAINER_ROWS[#TRAINER_ROWS + 1] = { 8, 3560 + i, 20, 0, 0, 0, 0, 0 } end   -- 3561-3563 teleports
local schemaMode = "trainer"
local function fakeQuery(rows)
    if not rows or #rows == 0 then return nil end
    local r = 1
    return { GetUInt32 = function(_, c) return rows[r][c + 1] end, NextRow = function() r = r + 1; return r <= #rows end }
end
function WorldDBQuery(q)
    worldQueries[#worldQueries + 1] = q
    local t = q:match("TABLES WHERE .- TABLE_NAME = '([%w_]+)'")
    if t then
        local have = schemaMode == "trainer" and (t == "trainer" or t == "trainer_spell")
            or schemaMode == "old" and t == "npc_trainer"
        return fakeQuery({ { have and 1 or 0 } })
    end
    if q:match("information_schema.COLUMNS") then return fakeQuery({ { schemaMode == "old" and 1 or 0 } }) end
    if q:match("FROM trainer t JOIN trainer_spell") or q:match("FROM npc_trainer s JOIN") then
        local sorted = {}
        for _, r in ipairs(TRAINER_ROWS) do sorted[#sorted + 1] = r end
        table.sort(sorted, function(a, b)
            if a[1] ~= b[1] then return a[1] < b[1] end
            if a[3] ~= b[3] then return a[3] < b[3] end
            return a[2] < b[2] end)
        return fakeQuery(sorted)
    end
    return nil
end
function GetSpellInfo(id)
    return { HasEffect = function(_, e) return e == 36 and (id == 7777 or id == 13820 or id == 34768) end,
             IsProfessionOrRiding = function() return id == 8888 or id == 33391 end }
end

dofile(file)
local T = assert(OV_QOL_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end

local function player(over)
    local p = { msgs = {}, combat = false, dead = false, flags = 0, queue = {}, learned = {}, cooldowns = {}, teleports = {} }
    for k, v in pairs(over or {}) do p[k] = v end
    p.spells = p.spells or {}
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    function p:GetAccountId() return self.account or 42 end
    function p:GetAccountName() return self.accName or "PLAYER" end
    function p:GetGUIDLow() return self.guid or 5 end
    function p:GetName() return self.name or "Tester" end
    function p:GetLevel() return self.level or 1 end
    function p:GetClass() return self.class or 1 end
    function p:GetTeam() return self.team or 0 end
    function p:GetGMRank() return self.gm or 0 end
    function p:IsInCombat() return self.combat end
    function p:IsDead() return self.dead end
    function p:InBattleground() return self.bg or false end
    function p:InArena() return false end
    function p:GetMap() local s = self; return { IsDungeon = function() return s.dungeon or false end, IsRaid = function() return false end } end
    function p:GetMapId() return 0 end
    function p:GetX() return 1 end
    function p:GetY() return 2 end
    function p:GetZ() return 3 end
    function p:GetO() return 4 end
    function p:HasSpell(id) return self.spells[id] == true end
    function p:LearnSpell(id) self.spells[id] = true; self.learned[#self.learned + 1] = id end
    function p:RegisterEvent(fn, delay, rep) self.queue[#self.queue + 1] = { fn = fn, delay = delay, rep = rep } end
    function p:ResetTalents(noCost) self.reset = noCost end
    function p:SetPlayerFlag(f) self.flags = self.flags + (self.flags % (2 * f) >= f and 0 or f) end
    function p:RemovePlayerFlag(f) if self.flags % (2 * f) >= f then self.flags = self.flags - f end end
    function p:HasFlag(i, f) return i == 150 and self.flags % (2 * f) >= f end
    function p:GetRestBonus() return self.rest or 0 end
    function p:HasSpellCooldown(id) return self.cooldowns[id] == true end
    function p:ResetSpellCooldown(id, upd) self.cooldowns[id] = nil; self.resetCd = { id, upd } end
    function p:GetGroup() return self.group end
    function p:Teleport(...) self.teleports[#self.teleports + 1] = { ... } end
    return p
end
-- runs queued timers like ALE (each event `rep` times); returns ticks run
local function run(p)
    local n = 0
    while #p.queue > 0 do
        local e = table.remove(p.queue, 1)
        for k = 1, e.rep do n = n + 1; e.fn(n, e.delay, e.rep - k, p) end
    end
    return n
end
local function has(t, x) for _, v in ipairs(t) do if v == x then return true end end return false end
local function last(p) return p.msgs[#p.msgs] or "" end
local function cmd(p, c) return events[42](42, p, c) end

-- load ---------------------------------------------------------------------------------------------------------
check("events registered (login, duel, level, command)", events[3] and events[11] and events[13] and events[42])
check("schema detected: trainer", T.schema() == "trainer")
local dataQueries = 0
for _, q in ipairs(worldQueries) do if q:match("FROM trainer t JOIN trainer_spell") then dataQueries = dataQueries + 1 end end
check("one data query at load", dataQueries == 1)
local dq; for _, q in ipairs(worldQueries) do if q:match("FROM trainer t") then dq = q end end
check("class trainers only (Type 0), every class at once", dq:match("t%.Type = 0") and dq:match("BETWEEN 1 AND 11")
    and not dq:match("Requirement = %d"))
check("previous rank from spell_ranks in the same query", dq:match("spell_ranks sp") and dq:match("sp%.`rank` = sr%.`rank` %- 1"))
check("cached per class", #T.classSpells[1] == 12 and #T.classSpells[8] == 63)
check("loaded line logged", printed[1]:match("trainer schema trainer, %d+ class spells"))

-- level up -----------------------------------------------------------------------------------------------------
local w = player({ guid = 10, level = 10, spells = { [78] = true } })
events[13](13, w, 9)
check("level up queues the learn", #w.queue == 1)
run(w)
check("level 10 spells learned", w.spells[100] and w.spells[772] and w.spells[284] and w.spells[6546])
check("nothing above the level", not w.spells[285])
check("one summary line", #w.msgs == 1 and last(w) == "|cff66ccff[QoL]|r You learned 4 new spells for level 10.")
check("riding / profession / teach / prof-or-riding rows never learned",
    not has(w.learned, 33391) and not has(w.learned, 2580) and not has(w.learned, 7777) and not has(w.learned, 8888))
check("unmapped teach spell logged once", (function()
    local n = 0; for _, s in ipairs(printed) do if s:match("trainer spell 7777 teaches") then n = n + 1 end end; return n == 1 end)())

local w2 = player({ guid = 11, level = 60 })
events[13](13, w2, 59); run(w2)
check("ranks chain in one run (r1 -> r2 -> r3)", w2.spells[78] and w2.spells[284] and w2.spells[285])
check("talent-gated rank skipped without the talent", not w2.spells[21551])
check("unknown previous rank (spell_ranks) blocks", not w2.spells[9999])
local w3 = player({ guid = 12, level = 60, spells = { [12294] = true } })
events[13](13, w3, 59); run(w3)
check("talent-gated rank learned with the talent", w3.spells[21551])
check("level down / same level: nothing", (function() local x = player({ guid = 13, level = 5 }); events[13](13, x, 5); return #x.queue == 0 end)())

-- faction and teach spells
local pa = player({ guid = 20, class = 2, level = 40, team = 0, spells = { [33391] = true } })
events[13](13, pa, 39); run(pa)
check("Alliance paladin: Warhorse teach spell -> 13819 learned", pa.spells[13819] and not pa.spells[13820])
check("Horde mount left out for the Alliance", not pa.spells[34769] and not pa.spells[34768])
check("Charger after the Warhorse it requires", pa.spells[23214])
local ph = player({ guid = 21, class = 2, level = 40, team = 1 })
events[13](13, ph, 39); run(ph)
check("Horde paladin: Thalassian Warhorse 34769, no Alliance mount", ph.spells[34769] and not ph.spells[13819])
check("Charger needs Journeyman Riding (ReqAbility2)", not ph.spells[23214])
local mg = player({ guid = 22, class = 8, level = 20, team = 1 })
events[13](13, mg, 19); run(mg)
check("Horde mage: Undercity teleport only", mg.spells[3563] and not mg.spells[3561] and not mg.spells[3562])

-- batches over ticks
local m = player({ guid = 23, class = 8, level = 10 })
events[13](13, m, 9)
local ticks = run(m)
check("60 spells over several ticks", ticks >= 3 and #m.learned == 60)
check("batch size respected", T.LEARN_BATCH < 60)
check("summary once", #m.msgs == 1 and last(m):match("60 new spells for level 10"))

-- a level during a run is caught after it
local r = player({ guid = 24, class = 8, level = 10 })
events[13](13, r, 9)
r.level = 20
events[13](13, r, 19)
check("second level while running: no second run yet", #r.queue == 1)
run(r)
check("...caught by the same run (level read each tick), one summary", r.spells[3561] and #r.msgs == 1)
events[13](13, r, 19)
check("...and the next level starts a run again", #r.queue == 1)
run(r)

-- login catch-up, quiet when nothing new
local lg = player({ guid = 25, level = 10 })
events[3](3, lg)
run(lg)
check("login catch-up learns", lg.spells[100] and last(lg):match("You learned"))
local lg2 = player({ guid = 25, level = 10, spells = lg.spells })
events[3](3, lg2); local before = #lg2.msgs; run(lg2)
check("login with nothing new: quiet", #lg2.msgs == before)

-- bots are skipped
local bot = player({ guid = 26, level = 10, accName = "RNDBOT0042" })
events[13](13, bot, 9); events[3](3, bot)
check("bots skipped", #bot.queue == 0 and #bot.msgs == 0)

-- .learnall with a 60 s guard
local la = player({ guid = 27, level = 10 })
check(".learnall handled", cmd(la, ".learnall") == false)
run(la)
check(".learnall learns", la.spells[100] and last(la):match("You learned"))
cmd(la, "learnall")
check(".learnall guard", #la.queue == 0 and last(la):match("ready again in 60 s"))
clock = clock + 61
cmd(la, "learnall"); run(la)
check(".learnall after the guard says so when nothing is new", last(la):match("already know every class spell for level 10"))
clock = clock + 61
local lq = player({ guid = 27, level = 10 })
cmd(lq, "qol learn")
check(".qol learn is the same", #lq.queue == 1)

-- off switch
env.OV_AUTOLEARN = "0"
local off = player({ guid = 28, level = 10 })
events[13](13, off, 9); events[3](3, off)
check("OV_AUTOLEARN=0: no learn on level or login", #off.queue == 0)
cmd(off, "learnall")
check("OV_AUTOLEARN=0: .learnall explains", last(off):match("off on this realm") and #off.queue == 0)
env.OV_AUTOLEARN = nil

-- .respec ------------------------------------------------------------------------------------------------------
local rs = player({ guid = 30, level = 40 })
check(".respec handled", cmd(rs, "respec") == false)
check(".respec alone only explains", rs.reset == nil and last(rs):match("%.respec confirm"))
cmd(rs, "respec confirm")
check(".respec confirm resets with noCost", rs.reset == true and last(rs):match("free"))
local rc = player({ guid = 31, combat = true })
cmd(rc, "respec confirm")
check(".respec refused in combat", rc.reset == nil)
local rd = player({ guid = 32, dungeon = true })
cmd(rd, "respec confirm")
check(".respec refused in an instance", rd.reset == nil)
env.OV_FREE_RESPEC = "0"
local ro = player({ guid = 33 })
cmd(ro, "respec confirm")
check("OV_FREE_RESPEC=0: off", ro.reset == nil and last(ro):match("off"))
env.OV_FREE_RESPEC = nil

-- .xp ----------------------------------------------------------------------------------------------------------
local x = player({ guid = 40, level = 19 })
check(".xp handled", cmd(x, "xp off") == false)
check(".xp off sets PLAYER_FLAGS_NO_XP_GAIN", x.flags == T.NO_XP and last(x):match("frozen at level 19"))
cmd(x, "xp")
check(".xp shows frozen", last(x):match("frozen"))
cmd(x, "xp on")
check(".xp on clears it", x.flags == 0 and last(x):match("on again"))
env.OV_XP_TOGGLE = "0"
local xo = player({ guid = 41 })
cmd(xo, "xp off")
check("OV_XP_TOGGLE=0: off", xo.flags == 0)
env.OV_XP_TOGGLE = nil

-- rested note --------------------------------------------------------------------------------------------------
env.OV_AUTOLEARN = "0"
local rn = player({ guid = 50, level = 30, rest = 12345 })
events[3](3, rn)
check("rested note at login", has(rn.msgs, "|cff66ccff[QoL]|r Rested: 12345 bonus XP banked; kills give double XP until it is used up."))
local rf = player({ guid = 51, level = 30, rest = 500, flags = T.NO_XP })
events[3](3, rf)
check("frozen XP reminder instead", last(rf):match("frozen") and not last(rf):match("Rested"))
local r80 = player({ guid = 52, level = 80, rest = 500 })
events[3](3, r80)
check("no rested note at 80", not last(r80):match("Rested"))
local r0 = player({ guid = 53, level = 30, rest = 0 })
events[3](3, r0)
check("no note with nothing banked", not last(r0):match("Rested"))
env.OV_RESTED_NOTE = "0"
local rno = player({ guid = 54, level = 30, rest = 500 })
events[3](3, rno)
check("OV_RESTED_NOTE=0: off", not last(rno):match("Rested"))
env.OV_RESTED_NOTE, env.OV_AUTOLEARN = nil, nil

-- .hearth ------------------------------------------------------------------------------------------------------
local h = player({ guid = 60, cooldowns = { [8690] = true } })
check(".hearth handled", cmd(h, "hearth") == false)
check(".hearth clears 8690 with an update", h.resetCd and h.resetCd[1] == 8690 and h.resetCd[2] == true)
h.cooldowns[8690] = true; h.resetCd = nil
cmd(h, "hearth")
check(".hearth once an hour", h.resetCd == nil and last(h):match("ready again in 60 min"))
clock = clock + 3601
cmd(h, "hearth")
check(".hearth after the hour", h.resetCd ~= nil)
local hr = player({ guid = 61 })
cmd(hr, "hearth")
check(".hearth when ready: says so, keeps the hour", last(hr):match("ready already") and hr.resetCd == nil)
local hc = player({ guid = 62, combat = true, cooldowns = { [8690] = true } })
cmd(hc, "hearth")
check(".hearth refused in combat", hc.resetCd == nil)
env.OV_HEARTH_RESET = "0"
local ho = player({ guid = 63, cooldowns = { [8690] = true } })
cmd(ho, "hearth")
check("OV_HEARTH_RESET=0: off", ho.resetCd == nil)
env.OV_HEARTH_RESET = nil

-- .summon ------------------------------------------------------------------------------------------------------
local owner = player({ guid = 70, account = 7 })
local rb = player({ guid = 71, account = 900, accName = "RNDBOT1" })
local alt = player({ guid = 72, account = 7 })
local human = player({ guid = 73, account = 8 })
local busyBot = player({ guid = 74, account = 901, accName = "RNDBOT2", combat = true })
local members = { owner, rb, alt, human, busyBot }
owner.group = { GetMembers = function() return members end }
check(".summon handled", cmd(owner, "summon") == false)
check("random bot and own alt-bot summoned", #rb.teleports == 1 and #alt.teleports == 1 and rb.teleports[1][2] == 1)
check("real players and bots in combat stay", #human.teleports == 0 and #busyBot.teleports == 0 and #owner.teleports == 0)
check("summary", last(owner):match("Summoned 2 bots"))
cmd(owner, "summon")
check(".summon cooldown", #rb.teleports == 1 and last(owner):match("ready again"))
local solo = player({ guid = 75 })
cmd(solo, "summon")
check(".summon without a group explains", last(solo):match("not in a group"))
local gm = player({ guid = 76, gm = 3 })
check("GM .summon <name> left to the core", cmd(gm, "summon Bob") == nil and cmd(gm, "summon") == nil)
gm.group = { GetMembers = function() return {} end }
check("GM .summon bots is ours", cmd(gm, "summon bots") == false)
local ind = player({ guid = 77, dungeon = true }); ind.group = owner.group
clock = clock + 31
cmd(ind, "summon")
check(".summon refused in an instance", last(ind):match("open world"))
env.OV_BOT_SUMMON = "0"
local so = player({ guid = 78 }); so.group = owner.group
clock = clock + 31
cmd(so, "summon")
check("OV_BOT_SUMMON=0: off", last(so):match("off"))
env.OV_BOT_SUMMON = nil

-- the rest stays as it was --------------------------------------------------------------------------------------
local q = player()
check(".qol help lists the new commands", cmd(q, "qol") == false and (function()
    local all = table.concat(q.msgs, "\n"); return all:match("%.learnall") and all:match("%.respec") and all:match("%.xp")
        and all:match("%.hearth") and all:match("%.summon") end)())
check("other commands untouched", cmd(q, "boost") == nil and cmd(q, "gm on") == nil and cmd(q, "bug x") == nil)

-- the old npc_trainer schema -----------------------------------------------------------------------------------
schemaMode = "old"; worldQueries = {}; events = {}
dofile(file)
check("old schema detected: npc_trainer", OV_QOL_TEST.schema() == "npc_trainer")
local oq; for _, s in ipairs(worldQueries) do if s:match("FROM npc_trainer s JOIN") then oq = s end end
check("old schema query follows negative SpellID references", oq and oq:match("%-t%.SpellID AS tid") and oq:match("trainer_type = 0"))
check("old schema: ReqLevel 0 rows left out, ReqSpell used", oq:match("s%.ReqLevel > 0") and oq:match("MAX%(s%.ReqSpell%) AS r1"))
local op = player({ guid = 80, class = 2, level = 20, team = 0 })
events[13](13, op, 19); run(op)
check("old schema: teach spell mapped too", op.spells[13819] and not op.spells[13820])
schemaMode = "none"; events = {}
dofile(file)
check("no trainer tables: schema none", OV_QOL_TEST.schema() == "none")
local np = player({ guid = 81, level = 10 })
events[13](13, np, 9)
check("no data: nothing queued", #np.queue == 0)
cmd(np, "learnall")
check("no data: .learnall explains", last(np):match("no trainer data"))

-- the Leyline brand switch: the realm's name in .qol is "Dalaran Hangout" while it is on (OVMod.Brand, or the env alone)
local bq = player()
cmd(bq, "qol")
check("brand off: .qol names the realm as before", bq.msgs[1]:find("WrathUnleashed quality of life:", 1, true) ~= nil)
env.OV_LEYLINE_BRAND = "1"
local bq2 = player()
cmd(bq2, "qol")
check("brand on (env): .qol names Dalaran Hangout", bq2.msgs[1]:find("Dalaran Hangout quality of life:", 1, true) ~= nil)
env.OV_LEYLINE_BRAND = nil
_G.OVMod = { Brand = function() return { on = true, name = "Leyline", realm = "Dalaran Hangout", home = "Dalaran Hangout" } end }
local bq3 = player()
cmd(bq3, "qol")
check("brand on (OVMod.Brand): .qol names Dalaran Hangout", bq3.msgs[1]:find("Dalaran Hangout quality of life:", 1, true) ~= nil)
_G.OVMod = nil

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
