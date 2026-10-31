-- lua5.1 stream/tests/test_ov_main_bars.lua realm/custom/lua_scripts/ov_main.lua
-- The boost's bars and mounts (ov_main.lua) under a fake mod-ale. Owner 2026-10-30: "fix mounts in Dalaran, they dont
-- work right now, and bars are broken sometimes".
--   * the layout's flying-mount button is the Celestial Steed (SMART_MOUNT, a ground mount where flying is not allowed,
--     e.g. Dalaran, a flying one where it is); the Albino Drake only without it;
--   * a character boosted before keeps its bars, but the drake on that button becomes the Celestial Steed at login
--     (both specs, shown at once), once; a button the player changed is left alone;
--   * the addon's "wubars ask" is answered "boost" (the realm lays the bars out) or "none".
local mainFile = assert(arg[1], "usage: lua5.1 test_ov_main_bars.lua <ov_main.lua>")

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok, extra)
    if ok then pass = pass + 1; realPrint("PASS " .. name)
    else fail = fail + 1; realPrint("FAIL " .. name .. (extra ~= nil and ("  " .. tostring(extra)) or "")) end
end
print = function() end

-- ---- fake mod-ale --------------------------------------------------------------------------------
local realGetenv = os.getenv
os.getenv = function(k) if k == "OV_MAIN" then return "1" end if k == "OV_START_KIT" then return "0" end return realGetenv(k) end
local events = {}
function RegisterPlayerEvent(e, f) events[e] = events[e] or {}; table.insert(events[e], f) end
function RegisterPlayerGossipEvent() end
function WorldDBQuery() return nil end

-- characters DB: character_action[guid][spec][button] = { action, type }; ov_boost_bars[guid] = row
local actions, boostBars = {}, {}
local function rowsOf(list)
    if #list == 0 then return nil end
    local i = 1
    return { GetUInt32 = function(_, c) return tonumber(list[i][c + 1]) or 0 end,
             GetString = function(_, c) return tostring(list[i][c + 1]) end,
             NextRow = function() i = i + 1; return list[i] ~= nil end }
end
function CharDBQuery(sql)
    local g, sp = sql:match("SELECT button, action, type FROM character_action WHERE guid = (%d+) AND spec = (%d+)")
    if g then
        local out = {}
        for button, b in pairs((actions[tonumber(g)] or {})[tonumber(sp)] or {}) do out[#out + 1] = { button, b[1], b[2] } end
        table.sort(out, function(a, b) return a[1] < b[1] end)
        return rowsOf(out)
    end
    g = sql:match("FROM ov_boost_bars WHERE guid = (%d+)")
    if g then local r = boostBars[tonumber(g)]; return r and rowsOf({ r }) or nil end
    return nil
end
function CharDBExecute(sql)
    local g, sp, list = sql:match("^DELETE FROM character_action WHERE guid = (%d+) AND spec = (%d+) AND button IN %(([%d,]+)%)")
    if g then
        local t = actions[tonumber(g)] and actions[tonumber(g)][tonumber(sp)]
        if t then for b in list:gmatch("%d+") do t[tonumber(b)] = nil end end
        return
    end
    if sql:find("^INSERT INTO character_action") then
        for gg, ss, b, a, ty in sql:gmatch("%((%d+), (%d+), (%d+), (%d+), (%d+)%)") do
            gg, ss = tonumber(gg), tonumber(ss)
            actions[gg] = actions[gg] or {}
            actions[gg][ss] = actions[gg][ss] or {}
            actions[gg][ss][tonumber(b)] = { tonumber(a), tonumber(ty) }
        end
    end
end
function CreatePacket(op, size)
    local p = { op = op, bytes = {}, longs = {} }
    function p:WriteUByte(v) self.bytes[#self.bytes + 1] = v end
    function p:WriteULong(v) self.longs[#self.longs + 1] = v end
    return p
end
-- ov_modapi as the realm has it: Send / On
local sent, handlers = {}, {}
package.preload["ov_modapi"] = function()
    return { On = function(mod, name, fn) handlers[mod .. "/" .. name] = fn end,
             Send = function(player, mod, name, data) sent[#sent + 1] = { player = player, what = mod .. "/" .. name, data = data } end }
end

local timers = {}
local function player(guid, class, spells, opts)
    opts = opts or {}
    local p = { guid = guid, class = class, spells = {}, msgs = {}, packets = {}, saves = 0, spec = opts.spec or 0 }
    for _, s in ipairs(spells or {}) do p.spells[s] = true end
    function p:GetGUIDLow() return self.guid end
    function p:GetClass() return self.class end
    function p:GetRace() return 1 end
    function p:GetLevel() return 80 end
    function p:GetName() return "P" .. self.guid end
    function p:GetAccountId() return 1 end
    function p:HasSpell(s) return self.spells[s] == true end
    function p:LearnSpell(s) if not opts.noLearn then self.spells[s] = true end end
    function p:GetActiveSpec() return self.spec end
    function p:GetSpecsCount() return 2 end
    function p:IsInWorld() return true end
    function p:IsBot() return false end
    function p:SaveToDB() self.saves = self.saves + 1 end
    function p:SendPacket(pkt) self.packets[#self.packets + 1] = pkt end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    function p:RegisterEvent(fn, delay) timers[#timers + 1] = { fn = fn, p = self } end
    return p
end
local function runTimers()
    local n = 0
    while #timers > 0 and n < 100 do
        local t = table.remove(timers, 1)
        t.fn(1, 0, 1, t.p)
        n = n + 1
    end
end
local function fire(e, ...) for _, f in ipairs(events[e] or {}) do f(e, ...) end end
local function packed(pkt, button) return pkt.longs[button + 1] end

dofile(mainFile)
local T = assert(OV_MAIN_TEST, "OV_MAIN_TEST")
local SMART, GROUND_ID, DRAKE = T.SMART_MOUNT, T.MOUNTS[1], T.MOUNTS[2]
check("the smart mount is the Celestial Steed", SMART == 75614)

-- ---- 1. the layout ----------------------------------------------------------------------------------
check("warrior arms: the mount buttons are 58 (ground) and 59 (smart)", (function()
    local l = T.flyButtons(player(1, 1), "arms")
    return #l == 1 and l[1] == 59
end)())
local w = player(2, 1, { GROUND_ID, DRAKE, SMART })
local buttons = T.resolveLayout(w, "arms", false)
check("layout: button 59 is the Celestial Steed", buttons[59] and buttons[59][1] == SMART, buttons[59] and buttons[59][1])
check("layout: button 58 stays the ground mount", buttons[58] and buttons[58][1] == GROUND_ID)
local old = player(3, 1, { GROUND_ID, DRAKE })
check("layout without the Celestial Steed: the drake as before", T.resolveLayout(old, "arms", false)[59][1] == DRAKE)
for cls, c in pairs(T.BARS) do
    local keys = {}
    for key in pairs(c) do if key ~= "base" then keys[#keys + 1] = key end end
    if #keys == 0 then keys[1] = "none" end   -- one layout for every tree (mage, warlock)
    for _, key in ipairs(keys) do
        local l = T.flyButtons(player(9, cls), key)
        check("class " .. cls .. " " .. key .. ": one smart mount button", #l == 1, #l)
    end
end

-- ---- 2. a character boosted before: the drake button becomes the Celestial Steed at login -------------
local G = 10
boostBars[G] = { "arms", 1, 1700000000, "", "" }
actions[G] = { [0] = { [0] = { 12294, 0 }, [58] = { GROUND_ID, 0 }, [59] = { DRAKE, 0 } },
               [1] = { [58] = { GROUND_ID, 0 }, [59] = { DRAKE, 0 } } }
local b = player(G, 1, { GROUND_ID, DRAKE })
fire(3, b); runTimers()
check("login: saved first", b.saves >= 1)
check("login: Celestial Steed learned", b:HasSpell(SMART))
check("login: spec 1 button 59 is the Celestial Steed", actions[G][0][59][1] == SMART and actions[G][0][59][2] == 0)
check("login: spec 2 button 59 too", actions[G][1][59][1] == SMART)
check("login: the other buttons untouched", actions[G][0][58][1] == GROUND_ID and actions[G][0][0][1] == 12294)
check("login: the client is shown the bars at once", #b.packets == 1 and packed(b.packets[1], 59) == SMART
    and packed(b.packets[1], 58) == GROUND_ID and packed(b.packets[1], 0) == 12294)
check("login: told what changed", b.msgs[#b.msgs] and b.msgs[#b.msgs]:find("Celestial Steed", 1, true) ~= nil, b.msgs[#b.msgs])
check("login: no word of the game's name", not table.concat(b.msgs, " "):find("Warcraft") and not table.concat(b.msgs, " "):find("WoW"))
local np = #b.packets
fire(3, b); runTimers()
check("login again this session: nothing more", #b.packets == np)

-- the player put something else on the button: left alone
local G2 = 11
boostBars[G2] = { "arms", 1, 1700000000, "", "" }
actions[G2] = { [0] = { [59] = { 1234, 0 } }, [1] = { [59] = { DRAKE, 0 } } }
local c2 = player(G2, 1, { GROUND_ID, DRAKE }, { spec = 0 })
fire(3, c2); runTimers()
check("changed button: the player's spell stays", actions[G2][0][59][1] == 1234)
check("changed button: the other spec's drake still becomes the steed", actions[G2][1][59][1] == SMART)
check("changed button: nothing to show for the active spec", #c2.packets == 0)

-- a core without the spell: the drake stays
local G3 = 12
boostBars[G3] = { "arms", 1, 1700000000, "", "" }
actions[G3] = { [0] = { [59] = { DRAKE, 0 } } }
local c3 = player(G3, 1, { DRAKE }, { noLearn = true })
fire(3, c3); runTimers()
check("no Celestial Steed on this core: the drake stays", actions[G3][0][59][1] == DRAKE and #c3.packets == 0)

-- not boosted: nothing
local c4 = player(13, 1, { DRAKE })
fire(3, c4); runTimers()
check("not boosted: no bars written", actions[13] == nil and #c4.packets == 0)

-- ---- 3. the addon's question ------------------------------------------------------------------------
local ask = handlers["wubars/ask"]
check("wubars ask is handled", type(ask) == "function")
if ask then
    ask(b, "")
    check("boosted: answered boost", sent[#sent] and sent[#sent].what == "wubars/layout" and sent[#sent].data == "boost")
    ask(c4, "")
    check("not boosted: answered none", sent[#sent].data == "none" and sent[#sent].player == c4)
end

print = realPrint
print(("\n%d/%d passed"):format(pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
