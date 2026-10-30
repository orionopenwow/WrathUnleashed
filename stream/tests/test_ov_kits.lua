-- ov_main.lua's starting-kit fill under a fake mod-ale:
--   lua5.1 tests/test_ov_kits.lua <ov_main.lua>
-- (tests/test_lua.py runs it with the same ov_main.lua it finds for the boost tests.)
local mainFile = assert(arg[1], "usage: lua5.1 test_ov_kits.lua <ov_main.lua>")

-- ---- fake ALE ---------------------------------------------------------------------------------
local events = {}
local realGetenv = os.getenv
os.getenv = function(k) if k == "OV_MAIN" or k == "OV_START_KIT" then return nil end return realGetenv(k) end
function RegisterPlayerEvent(e, f) events[e] = events[e] or {}; table.insert(events[e], f) end
function RegisterPlayerGossipEvent() end
function CharDBExecute() end
function CharDBQuery() end
function SendMail() end
local printed = {}
local realPrint = print
print = function(...) local t = {} for i = 1, select("#", ...) do t[#t + 1] = tostring(select(i, ...)) end
    printed[#printed + 1] = table.concat(t, " ") end

-- item_template as far as these tests need it: class (2 weapon, 4 armour, 6 ammo, 11 quiver), subclass, InventoryType
local ITEMS = {
    [6948] = { 15, 0, 0 }, [117] = { 0, 5, 0 }, [159] = { 0, 5, 0 },
    [38] = { 4, 0, 4 }, [39] = { 4, 1, 7 }, [40] = { 4, 0, 8 }, [49778] = { 2, 8, 17 },
    [45] = { 4, 0, 4 }, [44] = { 4, 1, 7 }, [43] = { 4, 0, 8 }, [23346] = { 2, 8, 17 },
    [148] = { 4, 0, 4 }, [147] = { 4, 1, 7 }, [129] = { 4, 0, 8 }, [12282] = { 2, 1, 17 },
    [2504] = { 2, 2, 15 }, [2508] = { 2, 3, 26 }, [2512] = { 6, 2, 24 }, [2516] = { 6, 3, 24 },
    [2101] = { 11, 2, 18 }, [2102] = { 11, 3, 18 },
    [49] = { 4, 0, 4 }, [48] = { 4, 1, 7 }, [47] = { 4, 0, 8 }, [2092] = { 2, 15, 13 }, [50055] = { 2, 15, 22 },
    [28979] = { 2, 16, 25 }, [25861] = { 2, 16, 25 },
    [53] = { 4, 0, 4 }, [6098] = { 4, 1, 20 }, [52] = { 4, 1, 7 }, [51] = { 4, 0, 8 }, [35] = { 2, 10, 17 },
    [154] = { 4, 0, 4 }, [153] = { 4, 2, 7 }, [36] = { 2, 4, 21 }, [2362] = { 4, 6, 14 },
    [6096] = { 4, 0, 4 }, [56] = { 4, 1, 20 }, [1395] = { 4, 1, 7 }, [55] = { 4, 0, 8 },
    [6097] = { 4, 0, 4 }, [57] = { 4, 1, 20 }, [1396] = { 4, 1, 7 }, [59] = { 4, 0, 8 },
    [6123] = { 4, 1, 20 }, [6124] = { 4, 1, 7 },
    -- 23347 Weathered Crossbow left out: the load check must drop it
}
local queries = {}
function WorldDBQuery(sql)
    queries[#queries + 1] = sql
    local list = sql:match("FROM item_template WHERE entry IN %(([%d,]+)%)")
    if not list then return nil end
    local rows = {}
    for id in list:gmatch("%d+") do if ITEMS[tonumber(id)] then rows[#rows + 1] = tonumber(id) end end
    local i = 1
    return #rows > 0 and { GetUInt32 = function() return rows[i] end,
                           NextRow = function() i = i + 1; return rows[i] ~= nil end } or nil
end

local WEAPON_SKILL = { [1] = 172, [2] = 45, [3] = 46, [4] = 54, [8] = 55, [10] = 136, [15] = 173, [16] = 176, [18] = 226 }
local SPELL_SKILL = { [202] = 55, [197] = 172, [198] = 54, [227] = 136, [1180] = 173, [2567] = 176, [264] = 45,
    [266] = 46, [5011] = 226 }
local SLOT_OK = { [4] = { [3] = true }, [20] = { [4] = true }, [7] = { [6] = true }, [8] = { [7] = true },
    [17] = { [15] = true }, [21] = { [15] = true }, [13] = { [15] = true, [16] = true }, [22] = { [16] = true },
    [14] = { [16] = true }, [15] = { [17] = true }, [25] = { [17] = true }, [26] = { [17] = true },
    [18] = { [19] = true, [20] = true, [21] = true, [22] = true } }

local function item(entry)
    local d = ITEMS[entry]
    local it = { entry = entry, cls = d[1], sub = d[2], inv = d[3] }
    function it:GetEntry() return self.entry end
    function it:GetSubClass() return self.sub end
    function it:GetItemTemplate() local s = self; return { GetInventoryType = function() return s.inv end } end
    return it
end

local function player(race, class, level, opts)
    opts = opts or {}
    local p = { race = race, class = class, level = level, worn = {}, bags = {}, skills = {}, spells = {},
                calls = { equip = 0, add = {} }, ammo = nil }
    for _, s in ipairs(opts.skills or {}) do p.skills[s] = true end
    for slot, e in pairs(opts.worn or {}) do p.worn[slot] = item(e) end
    for _, e in ipairs(opts.bags or {}) do p.bags[#p.bags + 1] = item(e) end
    function p:GetClass() return self.class end
    function p:GetRace() return self.race end
    function p:GetLevel() return self.level end
    function p:GetName() return "Kit" .. self.race .. "_" .. self.class end
    function p:GetEquippedItemBySlot(slot) return self.worn[slot] end
    function p:HasSkill(s) return self.skills[s] == true end
    function p:HasSpell(s) return self.spells[s] == true end
    function p:LearnSpell(s) self.spells[s] = true; if SPELL_SKILL[s] then self.skills[SPELL_SKILL[s]] = true end end
    function p:count(entry)
        local n = 0
        for _, it in pairs(self.worn) do if it.entry == entry then n = n + (it.n or 1) end end
        for _, it in ipairs(self.bags) do if it.entry == entry then n = n + (it.n or 1) end end
        return n
    end
    function p:HasItem(entry, c) return self:count(entry) >= (c or 1) end
    function p:GetItemByEntry(entry)
        for _, it in pairs(self.worn) do if it.entry == entry then return it end end
        for _, it in ipairs(self.bags) do if it.entry == entry then return it end end
    end
    function p:AddItem(entry, n)
        assert(ITEMS[entry], "AddItem of an unknown item " .. tostring(entry))
        self.calls.add[entry] = (self.calls.add[entry] or 0) + (n or 1)
        local it = item(entry); it.n = n or 1
        self.bags[#self.bags + 1] = it
        return newproxy(false)
    end
    -- CanEquipItem: empty slot, a slot of its InventoryType, weapon proficiency, no off hand beside a two-hander
    function p:EquipItem(src, slot)
        local it = type(src) == "table" and src or (ITEMS[src] and item(src))
        assert(it, "EquipItem of an unknown item " .. tostring(src))
        if self.worn[slot] or not (SLOT_OK[it.inv] or {})[slot] then return slot end
        if it.cls == 2 and not self.skills[WEAPON_SKILL[it.sub]] then return slot end
        if slot == 16 and self.worn[15] and self.worn[15].inv == 17 then return slot end
        if type(src) == "table" then
            for i, b in ipairs(self.bags) do if b == src then table.remove(self.bags, i); break end end
        end
        self.calls.equip = self.calls.equip + 1
        self.worn[slot] = it
        return newproxy(false)
    end
    function p:SetAmmo(e) self.ammo = e end
    return p
end
local function fire(e, ...) for _, f in ipairs(events[e] or {}) do f(e, ...) end end

-- ---- tests -----------------------------------------------------------------------------------
local pass, fail = 0, 0
local function check(name, cond, extra)
    if cond then pass = pass + 1; realPrint("PASS " .. name)
    else fail = fail + 1; realPrint("FAIL " .. name .. (extra and ("  " .. tostring(extra)) or "")) end
end
local function wornId(p, slot) return p.worn[slot] and p.worn[slot].entry end

OV_KITS = {}
dofile(mainFile)
local T = OV_MAIN_TEST
check("ov_main.lua registers FIRST_LOGIN (30)", events[30] ~= nil)
check("load: the kit ids are checked in item_template once", #queries == 1 and queries[1]:match("item_template") ~= nil)
local crossbow = false
for _, r in ipairs(T.START_KITS[3].ranged) do if r.weapon == 23347 then crossbow = true end end
check("load: an id item_template lacks is dropped", not crossbow and #T.START_KITS[3].ranged == 2)
check("load: the drop is logged", (printed[#printed] or ""):match("23347") ~= nil, printed[#printed])
local allKnown = true
for class, k in pairs(T.START_KITS) do
    for _, g in ipairs(k.gear) do if not ITEMS[g[1]] then allKnown = false end end
end
check("load: every remaining kit id exists", allKnown)
check("no Death Knight kit", T.START_KITS[6] == nil)

-- Tauren rogue (6/4), nothing worn, no Daggers skill (stock Daggers raceMask 735 has no Tauren)
local tr = player(6, 4, 1, { skills = { 176, 118 } })
fire(30, tr)
check("tauren rogue: Daggers learnt", tr.skills[173] == true and tr.spells[1180] == true)
check("tauren rogue: Worn Dagger in the main hand, Worn Dirk in the off hand", wornId(tr, 15) == 2092 and wornId(tr, 16) == 50055)
check("tauren rogue: a thrown weapon", wornId(tr, 17) == 28979)
check("tauren rogue: shirt, pants, shoes", wornId(tr, 3) == 49 and wornId(tr, 6) == 48 and wornId(tr, 7) == 47)
check("tauren rogue: hearthstone and food", tr:count(6948) == 1 and tr:count(117) == 4)

-- Gnome hunter (7/3), nothing worn, no ranged skill at all
local gh = player(7, 3, 1, { skills = { 172 } })
fire(30, gh)
check("gnome hunter: a gun (Guns learnt)", wornId(gh, 17) == 2508 and gh.skills[46] == true)
check("gnome hunter: 200 Light Shot, selected", gh:count(2516) == 200 and gh.ammo == 2516)
check("gnome hunter: Small Ammo Pouch in a bag slot", wornId(gh, 19) == 2102)
check("gnome hunter: Worn Battleaxe", wornId(gh, 15) == 12282)
check("gnome hunter: shirt, pants, boots", wornId(gh, 3) == 148 and wornId(gh, 6) == 147 and wornId(gh, 7) == 129)
check("gnome hunter: hearthstone and food", gh:count(6948) == 1 and gh:count(117) == 4)

-- Orc-like hunter with Bows: bow and arrows, not a gun
local bh = player(10, 3, 1, { skills = { 172, 45 } })
fire(30, bh)
check("hunter with Bows: Worn Shortbow, Rough Arrow, Light Quiver", wornId(bh, 17) == 2504 and bh:count(2512) == 200
    and bh.ammo == 2512 and bh:count(2101) == 1 and not bh.spells[266])

-- Human warrior with the stock kit: nothing twice
local hw = player(1, 1, 1, { skills = { 55 }, worn = { [3] = 38, [6] = 39, [7] = 40, [15] = 49778 }, bags = { 6948 } })
fire(30, hw)
check("stock human warrior: nothing equipped", hw.calls.equip == 0)
local dup = {}
for e, n in pairs(hw.calls.add) do if e ~= 117 then dup[#dup + 1] = e .. "x" .. n end end
check("stock human warrior: no gear or hearthstone added", #dup == 0, table.concat(dup, ","))
check("stock human warrior: one of each piece", hw:count(38) == 1 and hw:count(49778) == 1 and hw:count(6948) == 1)

-- A weapon left in the bags (no skill for it at creation) goes on; no second copy
local bagged = player(11, 4, 1, { skills = { 176, 118 }, bags = { 2092, 6948 }, worn = { [17] = 25861 } })
fire(30, bagged)
check("weapon in the bags: worn, one copy", wornId(bagged, 15) == 2092 and bagged:count(2092) == 1)
check("thrown slot already taken: left alone", wornId(bagged, 17) == 25861 and bagged:count(28979) == 0)

-- Shaman: shield in the off hand; a two-hander already worn: no shield
local sh = player(3, 7, 1, { skills = { 54, 433 } })
fire(30, sh)
check("shaman: Worn Mace and Worn Wooden Shield, water", wornId(sh, 15) == 36 and wornId(sh, 16) == 2362 and sh:count(159) == 2)
local sh2 = player(3, 7, 1, { skills = { 54, 433, 136 }, worn = { [15] = 35 } })
fire(30, sh2)
check("shaman with a staff: no shield beside it", wornId(sh2, 16) == nil and sh2:count(2362) == 0)

-- Death Knight (55) and a level 2 character: nothing
local dk = player(1, 6, 55)
fire(30, dk)
local dkAdds = 0
for _ in pairs(dk.calls.add) do dkAdds = dkAdds + 1 end
check("death knight: nothing", dk.calls.equip == 0 and dkAdds == 0 and next(dk.spells) == nil)
local l1dk = player(1, 6, 1)
fire(30, l1dk)
check("death knight at level 1 (GM .level): still nothing", l1dk.calls.equip == 0 and next(l1dk.calls.add) == nil)
local old = player(6, 4, 2)
fire(30, old)
check("not level 1: nothing", old.calls.equip == 0 and next(old.calls.add) == nil)

-- the same login twice: nothing new
local again = player(7, 3, 1, { skills = { 172 } })
fire(30, again); local first = again.calls.equip
fire(30, again)
check("second run: nothing more", again.calls.equip == first and again:count(2516) == 200 and again:count(6948) == 1)

-- every class with nothing worn gets a main-hand weapon and its armour (all skills present)
local allSkills = { 55, 172, 54, 136, 173, 176, 45, 46, 226, 118, 433 }
for _, class in ipairs({ 1, 2, 3, 4, 5, 7, 8, 9, 11 }) do
    local p = player(6, class, 1, { skills = allSkills })
    fire(30, p)
    check("class " .. class .. ": main-hand weapon, legs, hearthstone", wornId(p, 15) ~= nil and wornId(p, 6) ~= nil
        and p:count(6948) == 1)
end

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
