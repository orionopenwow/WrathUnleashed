-- lua5.1 stream/tests/test_ov_main_choice.lua realm/custom/lua_scripts/ov_main.lua
-- The new character's choice menu ("Begin your adventure at level 1 / Boost to level 80", ov_main.lua) and the
-- client's answers (WrathUnleashedUI Modes.lua, "the start-choice window"): ".boost seen" stops the resends after
-- login, ".boost later" (Goodbye without a pick) keeps it closed for the character at the next login, a pick made
-- this session is never undone by a late ".boost later", and .boost still opens the boost. Smoke 2026-10-30: the
-- menu kept coming back after Goodbye.
local mainFile = assert(arg[1], "usage: lua5.1 test_ov_main_choice.lua <ov_main.lua>")

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok) if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end end
print = function() end

-- ---- fake mod-ale ------------------------------------------------------------------------------
local realGetenv = os.getenv
os.getenv = function(k) if k == "OV_MAIN" then return "1" end if k == "OV_START_KIT" then return "0" end return realGetenv(k) end
local events, gossip = {}, nil
function RegisterPlayerEvent(e, f) events[e] = events[e] or {}; table.insert(events[e], f) end
function RegisterPlayerGossipEvent(menu, e, f) gossip = f end
local choices = {}
function CharDBExecute(sql)
    local guid, choice = sql:match("^INSERT INTO ov_main_choice %(.-%) VALUES %((%d+), %d+, '(%w+)'")
    if guid then choices[tonumber(guid)] = choice end
end
local function row(v) return { GetUInt32 = function() return tonumber(v) or 0 end, GetString = function() return tostring(v) end,
    NextRow = function() return false end } end
function CharDBQuery(sql)
    local g = sql:match("SELECT choice FROM ov_main_choice WHERE guid = (%d+)")
    if g then return choices[tonumber(g)] and row(choices[tonumber(g)]) or nil end
    if sql:find("FROM ov_boosts", 1, true) then return row(0) end
    return nil
end
function WorldDBQuery() return nil end
function SendMail() end

local function newPlayer(guid)
    local p = { guid = guid, menus = 0, timers = {}, said = {}, items = {} }
    function p:GetGUIDLow() return self.guid end
    function p:GetAccountId() return 7 end
    function p:GetName() return "Newbie" end
    function p:GetClass() return 1 end
    function p:GetRace() return 1 end
    function p:GetLevel() return 1 end
    function p:GossipClearMenu() self.items = {} end
    function p:GossipMenuAddItem(_, text) self.items[#self.items + 1] = text end
    function p:GossipSendMenu() self.menus = self.menus + 1 end
    function p:GossipComplete() end
    function p:SendBroadcastMessage(t) self.said[#self.said + 1] = t end
    function p:RegisterEvent(fn, ms) self.timers[#self.timers + 1] = fn end
    function p:HasSkill() return false end
    function p:HasSpell() return true end
    function p:LearnSpell() end
    function p:GetEquippedItemBySlot() return nil end
    function p:HasItem() return true end
    return p
end
local function fire(e, ...) local r for _, f in ipairs(events[e] or {}) do r = f(e, ...) end return r end
local function runTimers(p) local t = p.timers; p.timers = {}; for _, fn in ipairs(t) do fn(nil, nil, nil, p) end end
local function command(p, text) return fire(42, p, text) end

OV_KITS = {}
dofile(mainFile)

-- 1. a new character: the menu, sent again after login while untouched
local a = newPlayer(101)
fire(30, a)
check("first login: the choice is pending", choices[101] == "pending")
runTimers(a)
check("untouched, the menu is sent again a few times", a.menus >= 3)

-- 2. the client says it arrived: no more resends this session
local b = newPlayer(102)
fire(30, b)
check(".boost seen is handled (no 'no such command')", command(b, "boost seen") == false)
runTimers(b)
check("after .boost seen, no resends", b.menus == 0)
check("and the choice is still open", choices[102] == "pending")

-- 3. Goodbye: .boost later keeps it closed at the next login, .boost still opens the boost
check(".boost later is handled", command(b, "boost later") == false)
check("Goodbye: the choice is 'later'", choices[102] == "later")
local b2 = newPlayer(102)
fire(3, b2)
runTimers(b2)
check("next login: no menu after Goodbye", b2.menus == 0)
command(b2, "boost")
-- (no kits in this fake: the spec menu step says so, which is past the "may this character boost" check)
check(".boost still opens the boost (the spec menu)", b2.menus == 1 or (b2.said[#b2.said] or ""):find("No boost kit", 1, true) ~= nil)

-- 4. a pick made this session is never undone by a late .boost later
local c = newPlayer(103)
fire(30, c)
gossip(2, c, c, 0, 1)          -- Begin your adventure at level 1
check("the level-1 pick is recorded", choices[103] == "level1")
command(c, "boost later")
check("a late .boost later doesn't change it", choices[103] == "level1")
local d = newPlayer(104)
fire(30, d)
gossip(2, d, d, 0, 2)          -- Boost: the spec menu (the choice still pending)
command(d, "boost later")
check("closing after opening the boost menu this session doesn't record Goodbye", choices[104] == "pending")

realPrint(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
