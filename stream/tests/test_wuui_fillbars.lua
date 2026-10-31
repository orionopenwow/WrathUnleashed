-- lua5.1 stream/tests/test_wuui_fillbars.lua stream/fui-web/Interface/AddOns/WrathUnleashedUI/WrathUnleashedUI.lua
-- A level 80's empty buttons filled from the spellbook (WrathUnleashedUI.lua), and the realm's own layout (the main
-- realm's boost, ov_main.lua) left alone. Owner 2026-10-30: "bars are broken sometimes": the fill ran 4 s after the
-- boost's PLAYER_LEVEL_UP, right while the realm wrote its layout on the same bars. Also: the page keys (Shift +
-- wheel / arrows) unbound, and the main bar brought back to page 1.
local file = assert(arg[1], "WrathUnleashedUI.lua")
local pass, fail = 0, 0
local function check(name, ok, extra) if ok then pass = pass + 1 else fail = fail + 1 end
  print((ok and "PASS " or "FAIL ") .. name .. (extra ~= nil and ("  " .. tostring(extra)) or "")) end

-- ---- fake 3.3.5a UI -----------------------------------------------------------------------------
local frames = {}
local function newFrame()
    local f = { events = {}, scripts = {} }
    function f:RegisterEvent(e) self.events[e] = true end
    function f:UnregisterEvent(e) self.events[e] = nil end
    function f:SetScript(k, fn) self.scripts[k] = fn end
    frames[#frames + 1] = f
    return f
end
function CreateFrame() return newFrame() end
UIParent = { GetScale = function() return 1 end, SetScale = function() end }
DEFAULT_CHAT_FRAME = { lines = {}, AddMessage = function(self, m) self.lines[#self.lines + 1] = m end }
local combat, level = false, 1
function InCombatLockdown() return combat end
function UnitLevel() return level end
function UnitName() return "Me" end
function UnitClass() return "Warrior", "WARRIOR" end
function SetCVar() end
function GetCVar() return nil end
function SetActionBarToggles() end
local asked = 0
function SendAddonMessage(prefix, msg) if prefix == "OVMOD" and msg:find("^wubars\task") then asked = asked + 1 end end
-- bindings
local binds = { ["SHIFT-MOUSEWHEELUP"] = "PREVIOUSACTIONPAGE", ["SHIFT-MOUSEWHEELDOWN"] = "NEXTACTIONPAGE",
    ["SHIFT-UP"] = "PREVIOUSACTIONPAGE", ["SHIFT-DOWN"] = "NEXTACTIONPAGE", ["1"] = "ACTIONBUTTON1" }
function SetBinding(key, cmd) binds[key] = cmd end
function GetBindingAction(key) return binds[key] or "" end
function SaveBindings() end
function GetCurrentBindingSet() return 2 end
-- bars and spellbook: 10 spells; placing sends what the server would get (CMSG_SET_ACTION_BUTTON)
local actions, placedLog, cursor = {}, {}, nil
function HasAction(slot) return actions[slot] ~= nil end
function GetActionInfo(slot) local a = actions[slot]; if a then return "spell", a end end
function GetSpellInfo(id) return "Spell" .. tostring(id) end
function GetNumSpellTabs() return 1 end
function GetSpellTabInfo() return "General", "", 0, 10 end
function GetSpellName(i) return "Spell" .. (1000 + i) end
function IsPassiveSpell() return nil end
function ClearCursor() cursor = nil end
function PickupSpell(i) cursor = 1000 + i end
function PlaceAction(slot) if cursor then actions[slot] = cursor; placedLog[#placedLog + 1] = slot end end
local page = 1
function GetActionBarPage() return page end
function ChangeActionBarPage(p) page = p end
SlashCmdList = {}

local function fire(event, ...)
    for _, f in ipairs(frames) do
        if f.events[event] and f.scripts.OnEvent then f.scripts.OnEvent(f, event, ...) end
    end
end
local function run(sec)
    for _ = 1, math.floor(sec * 10) do
        for _, f in ipairs(frames) do if f.scripts.OnUpdate then f.scripts.OnUpdate(f, 0.1) end end
    end
end
local function word(w) fire("CHAT_MSG_ADDON", "OVMOD", "wubars\tlayout\t1/1\t" .. w, "WHISPER", "Me") end
local function reset(lvl)
    WrathUnleashedUIChar, WrathUnleashedUIDB = nil, nil
    actions, placedLog, frames, asked, level, combat = {}, {}, {}, 0, lvl, false
    WrathUnleashedUI = nil
    dofile(file)
end

-- 1. a new character boosts: level 1 -> 80 in one jump, the realm lays the bars out; nothing is filled
reset(1)
fire("PLAYER_ENTERING_WORLD")
check("level 1: no ask", asked == 0)
level = 80
fire("PLAYER_LEVEL_UP", 80)
run(30)
check("boost (1 -> 80): nothing filled", #placedLog == 0, #placedLog)
check("boost: marked, never filled later", WrathUnleashedUIChar.filled80 == true)

-- 2. the realm's word arrives before the level-up (the boost says "boost" at once)
reset(1)
fire("PLAYER_ENTERING_WORLD")
word("boost")
level = 80
fire("PLAYER_LEVEL_UP", 80)
run(30)
check("realm says boost: nothing filled", #placedLog == 0)

-- 3. a natural 79 -> 80: filled 4 s later
reset(79)
fire("PLAYER_ENTERING_WORLD")
level = 80
fire("PLAYER_LEVEL_UP", 80)
run(3)
check("79 -> 80: not before 4 s", #placedLog == 0)
run(2)
check("79 -> 80: filled", #placedLog == 10, #placedLog)

-- 4. login at 80, boosted character (the realm answers boost): asked, nothing filled
reset(80)
fire("PLAYER_ENTERING_WORLD")
check("login at 80: the realm is asked", asked == 1)
run(1); word("boost"); run(30)
check("login, boosted: nothing filled", #placedLog == 0)

-- 5. login at 80, not boosted (none): filled 4 s after login
reset(80)
fire("PLAYER_ENTERING_WORLD")
run(1); word("none")
run(2)
check("login, none: not before 4 s", #placedLog == 0)
run(2)
check("login, none: filled", #placedLog == 10, #placedLog)

-- 6. login at 80, no answer (a realm without the boost): filled after 20 s, not at 4 s
reset(80)
fire("PLAYER_ENTERING_WORLD")
run(10)
check("no answer: not at 10 s", #placedLog == 0)
run(11)
check("no answer: filled after 20 s", #placedLog == 10, #placedLog)

-- 7. the fill falls in combat: after the fight, not skipped for good
reset(79)
fire("PLAYER_ENTERING_WORLD")
level = 80
fire("PLAYER_LEVEL_UP", 80)
combat = true
run(5)
check("combat: not filled", #placedLog == 0)
check("combat: not marked done", not WrathUnleashedUIChar.filled80)
combat = false
fire("PLAYER_REGEN_ENABLED")
check("after the fight: filled", #placedLog == 10, #placedLog)

-- 8. the page keys: new characters get none, older characters lose them once (only while they flip pages)
check("page keys unbound with the default keys", (binds["SHIFT-MOUSEWHEELUP"] or "") == "" and (binds["SHIFT-DOWN"] or "") == "")
check("the bar keys are set", binds["SHIFT-1"] == "MULTIACTIONBAR1BUTTON1" and binds["1"] == "ACTIONBUTTON1")
binds["SHIFT-MOUSEWHEELUP"], binds["SHIFT-MOUSEWHEELDOWN"], binds["SHIFT-UP"] = "PREVIOUSACTIONPAGE", "NEXTACTIONPAGE", "MYMACRO"
WrathUnleashedUIChar, frames = { keys = true, barsOn = true, defaults = true }, {}
local keep = WrathUnleashedUIChar
dofile(file)
WrathUnleashedUIChar = keep
fire("PLAYER_ENTERING_WORLD")
check("older character: page flips unbound", (binds["SHIFT-MOUSEWHEELUP"] or "") == "" and (binds["SHIFT-MOUSEWHEELDOWN"] or "") == "")
check("older character: a key the player bound to something else stays", binds["SHIFT-UP"] == "MYMACRO")
check("older character: done once", keep.pageKeys == true)

-- 9. the main bar back on page 1
page = 3
check("MainBarHome: page 3 -> 1", WrathUnleashedUI.MainBarHome() == true and page == 1)
page, combat = 2, true
check("MainBarHome: not in combat", WrathUnleashedUI.MainBarHome() == false and page == 2)
combat = false

print(("\n%d/%d passed"):format(pass, pass + fail)); os.exit(fail == 0 and 0 or 1)
