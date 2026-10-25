-- WrathUnleashed UI: the browser realm's defaults (3.3.5a API).
--  1. Every action bar on: bottom left, bottom right, right, right 2 (Esc > Interface > ActionBars).
--     Done once per character; turning a bar off afterwards is respected.
--  2. A level 80 gets its empty buttons on those bars filled from the spellbook: every active spell
--     not already on a bar, highest rank, in spellbook order. Once per character; /wubars does it again.
-- Nothing is removed or moved: only empty buttons are used.

local ADDON = "WrathUnleashedUI"
local BOOK = BOOKTYPE_SPELL or "spell"
-- Action slots (1-based) of the extra bars, in the order they fill: bottom left, bottom right, right, right 2.
local SLOTS = {}
for _, first in ipairs({ 61, 49, 25, 37 }) do
    for i = 0, 11 do SLOTS[#SLOTS + 1] = first + i end
end

WrathUnleashedUI = WrathUnleashedUI or {}
local W = WrathUnleashedUI

-- UI size. Retail's "pixel perfect" makes the UI 768 units tall whatever the window, so a 253-unit minimap
-- ring is about a quarter of the screen height. The browser client gives UIParent the window's own
-- height, so everything draws about 1.3x too big; this scale puts it back. The slider in Esc > Mods &
-- Workshop changes it (saved per account); "Modern size" goes back to this default.
W.SCALE_MIN, W.SCALE_MAX = 0.5, 1.2
function W.ModernScale()
    local h = (GetScreenHeight and GetScreenHeight() or 768) * (UIParent:GetScale() or 1)
    if not h or h <= 0 then return 1 end
    local k = 768 / h
    if k < W.SCALE_MIN then k = W.SCALE_MIN elseif k > W.SCALE_MAX then k = W.SCALE_MAX end
    return math.floor(k * 100 + 0.5) / 100
end
function W.ApplyScale(k)
    if InCombatLockdown and InCombatLockdown() then return false end
    if k < W.SCALE_MIN then k = W.SCALE_MIN elseif k > W.SCALE_MAX then k = W.SCALE_MAX end
    UIParent:SetScale(k)
    WrathUnleashedUIDB = WrathUnleashedUIDB or {}
    WrathUnleashedUIDB.scale = k
    return true
end

local function say(msg)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff4fc3f7[WrathUnleashed]|r " .. msg) end
end

local function barsOn()
    -- (also W.BarsOn for the Mods panel)
    if SetActionBarToggles then SetActionBarToggles(1, 1, 1, 1, 1) end
    SHOW_MULTI_ACTIONBAR_1, SHOW_MULTI_ACTIONBAR_2, SHOW_MULTI_ACTIONBAR_3, SHOW_MULTI_ACTIONBAR_4 = 1, 1, 1, 1
    ALWAYS_SHOW_MULTI_ACTIONBAR = 1
    if MultiActionBar_Update then MultiActionBar_Update() end
    if UIParent_ManageFramePositions then UIParent_ManageFramePositions() end
end

-- Names of the spells already on any of the 120 buttons.
local function placedNames()
    local names = {}
    for slot = 1, 120 do
        if HasAction(slot) then
            local kind, id = GetActionInfo(slot)
            if kind == "spell" and id then
                local name = GetSpellInfo(id)
                if name then names[name] = true end
            elseif kind == "macro" then
                names["macro:" .. tostring(id)] = true
            end
        end
    end
    return names
end

-- Active spells in spellbook order, one entry per name (the last listed = the highest rank).
local function bookSpells()
    local order, index = {}, {}
    local tabs = GetNumSpellTabs and GetNumSpellTabs() or 0
    for t = 1, tabs do
        local _, _, offset, count = GetSpellTabInfo(t)
        for i = offset + 1, offset + count do
            local name = GetSpellName(i, BOOK)
            if name and not IsPassiveSpell(i, BOOK) then
                if not index[name] then
                    order[#order + 1] = name
                end
                index[name] = i
            end
        end
    end
    return order, index
end

local function fillBars(quiet)
    if InCombatLockdown and InCombatLockdown() then
        if not quiet then say("Not in combat: try /wubars again after the fight.") end
        return 0
    end
    local have = placedNames()
    local order, index = bookSpells()
    local placed, s = 0, 1
    for _, name in ipairs(order) do
        if not have[name] then
            while SLOTS[s] and HasAction(SLOTS[s]) do s = s + 1 end
            local slot = SLOTS[s]
            if not slot then break end
            ClearCursor()
            PickupSpell(index[name], BOOK)
            PlaceAction(slot)
            ClearCursor()
            have[name] = true
            placed = placed + 1
            s = s + 1
        end
    end
    if not quiet then
        say(placed > 0 and (placed .. " more spells put on your action bars.") or "Your action bars already have every spell.")
    end
    return placed
end

-- Key bindings everyone knows: no reaching for 8 9 0 - =.
--   main bar         1-7, then F G T Z X for buttons 8-12
--   bottom left bar  Shift + the same keys (it sits on top of the main bar)
--   bottom right bar Ctrl + the same keys
--   right bar        Alt + the same keys
--   right bar 2      no keys (click it, or bind in Esc > Key Bindings)
-- 8 9 0 - = are cleared. Done once per character; Esc > Mods & Workshop > Default keys does it again.
local KEYS = { "1", "2", "3", "4", "5", "6", "7", "F", "G", "T", "Z", "X" }
local BAR_KEYS = {
    { "ACTIONBUTTON", "" },
    { "MULTIACTIONBAR1BUTTON", "SHIFT-" },
    { "MULTIACTIONBAR2BUTTON", "CTRL-" },
    { "MULTIACTIONBAR3BUTTON", "ALT-" },
}
local function defaultKeys(quiet)
    if not SetBinding then return false end
    if InCombatLockdown and InCombatLockdown() then
        if not quiet then say("Not in combat: try again after the fight.") end
        return false
    end
    for _, key in ipairs({ "8", "9", "0", "-", "=" }) do pcall(SetBinding, key) end
    for _, bar in ipairs(BAR_KEYS) do
        for i, key in ipairs(KEYS) do
            pcall(SetBinding, bar[2] .. key, bar[1] .. i)
        end
    end
    if SaveBindings then pcall(SaveBindings, (GetCurrentBindingSet and GetCurrentBindingSet()) or 2) end
    if not quiet then
        say("Keys set: main bar 1-7 and F G T Z X; the bar above it Shift + those keys; the next Ctrl +; the right bar Alt +.")
    end
    return true
end

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_ENTERING_WORLD")
f:RegisterEvent("PLAYER_LEVEL_UP")
f:SetScript("OnEvent", function(_, event, level)
    WrathUnleashedUIChar = WrathUnleashedUIChar or {}
    local c = WrathUnleashedUIChar
    if event == "PLAYER_ENTERING_WORLD" then
        f:UnregisterEvent("PLAYER_ENTERING_WORLD")
        WrathUnleashedUIDB = WrathUnleashedUIDB or {}
        -- Talent planner: 3.3.5's own preview mode (plan points, then Learn), on for everyone.
        if SetCVar then pcall(SetCVar, "previewTalents", "1"); pcall(SetCVar, "previewPetTalents", "1") end
        -- The first time on this account: the modern size. After that: the player's own choice.
        W.ApplyScale(WrathUnleashedUIDB.scale or W.ModernScale())
        if not c.barsOn then
            barsOn()
            c.barsOn = true
        end
        if not c.keys then
            c.keys = defaultKeys(true) and true or nil
            if c.keys then say("Every action bar is on, with keys: 1-7 and F G T Z X, plus Shift, Ctrl and Alt for the bars above. Esc > Mods & Workshop to change.") end
        end
    end
    local lvl = (event == "PLAYER_LEVEL_UP" and tonumber(level)) or UnitLevel("player")
    if lvl and lvl >= 80 and not c.filled80 then
        c.filled80 = true
        -- A moment after login, so the server's action buttons (the boost's layout) are in first.
        local wait = 0
        f:SetScript("OnUpdate", function(self, elapsed)
            wait = wait + elapsed
            if wait < 4 then return end
            self:SetScript("OnUpdate", nil)
            local n = fillBars(true)
            if n > 0 then say(n .. " more spells put on your action bars. /wubars fills new ones later.") end
        end)
    end
end)

W.BarsOn, W.FillBars, W.DefaultKeys = barsOn, fillBars, defaultKeys

SLASH_WUBARS1 = "/wubars"
SlashCmdList["WUBARS"] = function()
    barsOn()
    fillBars(false)
end
