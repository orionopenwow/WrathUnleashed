-- WrathUnleashed UI: the browser realm's defaults (3.3.5a API).
--  1. Every action bar on: bottom left, bottom right, right, right 2 (Esc > Interface > ActionBars).
--     Done once per character; turning a bar off afterwards is respected.
--  2. A level 80 gets its empty buttons on those bars filled from the spellbook: every active spell
--     not already on a bar, highest rank, in spellbook order. Once per character; /wubars does it again.
--     Not for a character the realm lays out itself (the main realm's boost, ov_main.lua): see "the realm's layout".
-- Nothing is removed or moved: only empty buttons are used.
-- Leyline realms only (owner 2026-10-30): every one-time default (camera, auto loot, talent preview, the bars, the
-- keys and the page keys, the level 80 fill, Shift-P in Collections.lua) and the instant quests wait for our realm's
-- answer at login (W.WhenLeyline, "the realm's hello" below). The Leyline launcher installs this addon into players'
-- own game folders too, so on any other server the windows load but nothing is rebound or changed.

local ADDON = "WrathUnleashedUI"
local BOOK = BOOKTYPE_SPELL or "spell"
-- Action slots (1-based) of the extra bars, in the order they fill: bottom left, bottom right, right, right 2.
local SLOTS = {}
for _, first in ipairs({ 61, 49, 25, 37 }) do
    for i = 0, 11 do SLOTS[#SLOTS + 1] = first + i end
end

WrathUnleashedUI = WrathUnleashedUI or {}
local W = WrathUnleashedUI

-- The Leyline brand switch (owner 2026-10-30): while the realm has it on (ov_modapi.lua OVMod.Brand, realm/brand.sh)
-- it tells this addon at login over OVMOD (mod "wubrand", name "brand", data "leyline\t<realm name>"), and the
-- windows say "Leyline" and call the main realm by the name it sends (W.OFFICIAL_NAME when it sends none). No word
-- from the realm = off: every text is the
-- old one. Only what players read changes: the addon's folder, saved variables, frame names and prefixes stay.
-- Kept in memory only (never saved), so a realm that turns it off is off at the next login.
W.Brand = { on = false, name = "WrathUnleashed", home = "Wrath", back = "Back to Wrath" }
-- The official realm's name (owner 2026-10-30 23:32: "Wrath Unleashed" for now; the realm's own copy is
-- ov_modapi.lua OVMod.OFFICIAL_NAME). Leyline.lua reads it from here.
W.OFFICIAL_NAME = "Wrath Unleashed"
local brandWatchers = {}
function W.OnBrand(fn) brandWatchers[#brandWatchers + 1] = fn end
function W.SetBrand(realm)
    realm = type(realm) == "string" and realm:gsub("|", ""):gsub("[%c]", ""):sub(1, 32) or ""
    if realm == "" then realm = W.OFFICIAL_NAME end
    W.Brand = { on = true, name = "Leyline", home = realm, back = "Back to " .. realm }
    for _, fn in ipairs(brandWatchers) do pcall(fn, W.Brand) end
end

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
-- Through the game's own setting (Esc > Interface > Use UI Scale), never UIParent:SetScale: the browser
-- client draws a SetScale on UIParent only partly (sizes, not positions), which pushed the left edge off
-- screen (live 2026-10-25 01:10). The client applies the uiScale CVar itself.
function W.ApplyScale(k)
    if InCombatLockdown and InCombatLockdown() then return false end
    if k < W.SCALE_MIN then k = W.SCALE_MIN elseif k > W.SCALE_MAX then k = W.SCALE_MAX end
    if SetCVar then pcall(SetCVar, "useUiScale", "1"); pcall(SetCVar, "uiScale", string.format("%.2f", k)) end
    WrathUnleashedUIDB = WrathUnleashedUIDB or {}
    WrathUnleashedUIDB.uiScale = k
    return true
end

-- Chat lines wait a few seconds after login for the realm's brand word (W.SettleBrand), so the tag is the right one.
local held, settled = {}, false
local function say(msg)
    if not settled then held[#held + 1] = msg; return end
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff4fc3f7[" .. W.Brand.name .. "]|r " .. msg) end
end
function W.SettleBrand()
    if settled then return end
    settled = true
    local list = held
    held = {}
    for _, m in ipairs(list) do say(m) end
end
W.Say = say

-- The realm's hello: the addon asks at login (OVMOD "wuhello" "ask"); a Leyline realm answers "wuhello" "hi"
-- (ov_modapi.lua). Its other answers prove it too: the brand ("wubrand" "brand") and the bars word ("wubars"
-- "layout", ov_main.lua). Only answers count, never the ask (a whisper to oneself comes back on any server). Kept for
-- this session only: the next login asks again.
W.LeylineRealm = false
local leylineWaiting = {}
-- fn now on a Leyline realm, else once its hello arrives (never on another server).
function W.WhenLeyline(fn)
    if W.LeylineRealm then pcall(fn) else leylineWaiting[#leylineWaiting + 1] = fn end
end
function W.SetLeyline()
    if W.LeylineRealm then return end
    W.LeylineRealm = true
    local list = leylineWaiting
    leylineWaiting = {}
    for _, fn in ipairs(list) do pcall(fn) end
end
local function isHello(msg)
    return msg:find("^wuhello\thi\t%d+/%d+\t") or msg:find("^wubrand\tbrand\t%d+/%d+\t") or msg:find("^wubars\tlayout\t%d+/%d+\t")
end

local BRAND_WAIT = 3   -- seconds after entering the world: no word from the realm by then = off (the ask is answered at once)
local brandFrame = CreateFrame("Frame")
brandFrame:RegisterEvent("CHAT_MSG_ADDON")
brandFrame:RegisterEvent("PLAYER_ENTERING_WORLD")
brandFrame:SetScript("OnEvent", function(self, event, prefix, msg, channel)
    if event == "PLAYER_ENTERING_WORLD" then
        self:UnregisterEvent("PLAYER_ENTERING_WORLD")
        if SendAddonMessage and UnitName then
            pcall(SendAddonMessage, "OVMOD", "wuhello\task\t1/1\t", "WHISPER", UnitName("player"))
            pcall(SendAddonMessage, "OVMOD", "wubrand\task\t1/1\t", "WHISPER", UnitName("player"))
        end
        local wait = 0
        self:SetScript("OnUpdate", function(f, elapsed)
            wait = wait + elapsed
            if wait < BRAND_WAIT then return end
            f:SetScript("OnUpdate", nil)
            W.SettleBrand()
        end)
        return
    end
    if prefix ~= "OVMOD" or channel ~= "WHISPER" or type(msg) ~= "string" then return end
    if isHello(msg) then W.SetLeyline() end
    local data = msg:match("^wubrand\tbrand\t1/1\t(.*)$")
    if not data then return end
    local kind, realm = data:match("^(%a+)\t?(.*)$")
    if kind == "leyline" then
        W.SetBrand(realm)
        W.SettleBrand()
    end
end)

local function barsOn()
    -- (also W.BarsOn for the Mods panel)
    if SetActionBarToggles then SetActionBarToggles(1, 1, 1, 1, nil) end
    SHOW_MULTI_ACTIONBAR_1, SHOW_MULTI_ACTIONBAR_2, SHOW_MULTI_ACTIONBAR_3, SHOW_MULTI_ACTIONBAR_4 = 1, 1, 1, 1
    ALWAYS_SHOW_MULTI_ACTIONBAR = nil   -- empty buttons stay hidden (shown while dragging a spell)
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
-- The stock keys that turn the main bar to its next / previous page. Shift is the bottom left bar's key here, and
-- Shift + wheel turns a carried prop in edit mode, so a Shift held while scrolling (zooming, building) flipped the
-- main bar to an empty or other page and it looked broken ("bars are broken sometimes", 2026-10-30). Unbound with
-- the default keys, and once for characters that had them already (only while they still flip pages).
local PAGE_KEYS = { "SHIFT-UP", "SHIFT-DOWN", "SHIFT-MOUSEWHEELUP", "SHIFT-MOUSEWHEELDOWN" }
local PAGE_FLIPS = { NEXTACTIONPAGE = true, PREVIOUSACTIONPAGE = true }
local function unbindPageFlips()
    if not SetBinding or not GetBindingAction then return false end
    if InCombatLockdown and InCombatLockdown() then return false end
    local n = 0
    for _, key in ipairs(PAGE_KEYS) do
        if PAGE_FLIPS[GetBindingAction(key) or ""] then pcall(SetBinding, key); n = n + 1 end
    end
    if n > 0 and SaveBindings then pcall(SaveBindings, (GetCurrentBindingSet and GetCurrentBindingSet()) or 2) end
    return true
end

-- The main bar back on its first page (after edit mode, a mode or minigolf, which take the keys and the wheel).
-- Stance, form, vehicle and possess bars are the client's own state, not a page: untouched.
function W.MainBarHome()
    if InCombatLockdown and InCombatLockdown() then return false end
    if type(GetActionBarPage) ~= "function" or type(ChangeActionBarPage) ~= "function" then return false end
    local page = GetActionBarPage()
    if page and page ~= 1 then pcall(ChangeActionBarPage, 1); return true end
    return false
end
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
    for _, key in ipairs(PAGE_KEYS) do pcall(SetBinding, key) end
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

-- The realm's layout (2026-10-30, "bars are broken sometimes"). The main realm's boost (ov_main.lua) writes a layout for
-- the class and spec a few seconds after the boost, or after the login while it is still pending, and then syncs the
-- server's copy with a talent spec switch. This addon used to fill a level 80's empty buttons 4 s after
-- PLAYER_LEVEL_UP, which the boost fires: right in that window, on the very bars the layout writes (bottom left,
-- bottom right, right), so the bars came out as the layout, a mix or spellbook order (the mount buttons gone)
-- depending on the timing, and the buttons the layout keeps free for talents were taken. Now:
--   * a jump of more than one level (a boost) never fills: the realm lays the bars out;
--   * the realm says "boost" (whisper, OVMOD "wubars" "layout") when it boosts, and answers "boost" or "none" to
--     the ask sent at login; "boost" stops any fill for the character, "none" fills (at least 4 s after login);
--   * no answer in ASK_WAIT seconds (a realm without the boost) fills as before;
--   * a fill that falls in combat waits for the end of the fight (it used to be skipped for good).
local FILL_DELAY, ASK_WAIT = 4, 20
local fill = { at = nil, since = 0, word = nil, waitCombat = false }
local lastLevel

local function char()
    WrathUnleashedUIChar = WrathUnleashedUIChar or {}
    return WrathUnleashedUIChar
end

local filler = CreateFrame("Frame")
local function runFill()
    local c = char()
    fill.at = nil
    if c.filled80 then return end
    if InCombatLockdown and InCombatLockdown() then fill.waitCombat = true; return end
    fill.waitCombat = false
    c.filled80 = true
    local n = fillBars(true)
    if n > 0 then say(n .. " more spells put on your action bars. /wubars fills new ones later.") end
end
-- in `seconds` (from now, or sooner if one is already due earlier)
local function fillIn(seconds)
    if char().filled80 then return end
    local due = fill.since + seconds
    if not fill.at or due < fill.at then fill.at = due end
end
local function leaveToRealm()
    char().filled80 = true
    fill.at, fill.waitCombat = nil, false
end
filler:SetScript("OnUpdate", function(_, elapsed)
    fill.since = fill.since + (elapsed or 0)
    if fill.at and fill.since >= fill.at then runFill() end
end)

function W.OnBarsWord(word)
    fill.word = word
    if word == "boost" then
        leaveToRealm()
    elseif word == "none" and fill.at then
        fillIn(math.max(0, FILL_DELAY - fill.since))
    end
end

local f = CreateFrame("Frame")
f:RegisterEvent("PLAYER_ENTERING_WORLD")
f:RegisterEvent("PLAYER_LEVEL_UP")
f:RegisterEvent("PLAYER_REGEN_ENABLED")
f:RegisterEvent("CHAT_MSG_ADDON")
f:SetScript("OnEvent", function(_, event, level, msg, channel)
    local c = char()
    if event == "CHAT_MSG_ADDON" then
        if level ~= "OVMOD" or channel ~= "WHISPER" or type(msg) ~= "string" then return end
        local word = msg:match("^wubars\tlayout\t1/1\t(%a+)$")
        if word then W.OnBarsWord(word) end
        return
    end
    if event == "PLAYER_REGEN_ENABLED" then
        if fill.waitCombat then runFill() end
        return
    end
    if event == "PLAYER_ENTERING_WORLD" then
        f:UnregisterEvent("PLAYER_ENTERING_WORLD")
        lastLevel = UnitLevel("player")
        W.WhenLeyline(function() W.LeylineDefaults() end)
        return
    end
    -- PLAYER_LEVEL_UP
    local lvl = tonumber(level) or UnitLevel("player")
    local jump = lastLevel and lvl and lvl - lastLevel > 1
    lastLevel = lvl
    if not W.LeylineRealm then return end   -- another server: no fill
    if not lvl or lvl < 80 or c.filled80 then return end
    if jump or fill.word == "boost" then leaveToRealm(); return end   -- a boost: the realm lays the bars out
    fillIn(FILL_DELAY)
end)

-- The one-time defaults, on a Leyline realm only (W.WhenLeyline at login).
function W.LeylineDefaults()
    local c = char()
    WrathUnleashedUIDB = WrathUnleashedUIDB or {}
    -- Defaults everyone wants (once per character, so a player's own change sticks):
    -- the farthest camera (and start zoomed out), auto loot.
    if not c.defaults then
        c.defaults = true
        if SetCVar then
            pcall(SetCVar, "cameraDistanceMax", "50")
            pcall(SetCVar, "cameraDistanceMaxFactor", "4")
            pcall(SetCVar, "autoLootDefault", "1")
        end
        if CameraZoomOut then pcall(CameraZoomOut, 50) end
    end
    -- Talent planner: 3.3.5's own preview mode (plan points, then Learn), on for everyone.
    if SetCVar then pcall(SetCVar, "previewTalents", "1"); pcall(SetCVar, "previewPetTalents", "1") end
    -- Undo the first version's UIParent:SetScale (it cut off the left edge); the default size now
    -- comes from the client, and the slider sets the game's own UI scale.
    if UIParent:GetScale() ~= 1 and not WrathUnleashedUIDB.uiScale then UIParent:SetScale(1) end
    WrathUnleashedUIDB.scale = nil
    if not c.barsOn then
        barsOn()
        c.barsOn = true
    end
    if not c.keys then
        c.keys = defaultKeys(true) and true or nil
        if c.keys then c.pageKeys = true; say("Every action bar is on, with keys: 1-7 and F G T Z X, plus Shift, Ctrl and Alt for the bars above. Esc > Mods & Workshop to change.") end
    end
    if c.keys and not c.pageKeys then c.pageKeys = unbindPageFlips() or nil end
    lastLevel = UnitLevel("player")
    if lastLevel and lastLevel >= 80 and not c.filled80 then
        if SendAddonMessage and UnitName then
            pcall(SendAddonMessage, "OVMOD", "wubars\task\t1/1\t", "WHISPER", UnitName("player"))
        end
        if fill.word == "boost" then leaveToRealm()
        elseif fill.word == "none" then fillIn(FILL_DELAY)
        else fillIn(ASK_WAIT) end
    end
end

W.BarsOn, W.FillBars, W.DefaultKeys = barsOn, fillBars, defaultKeys

-- Instant quests: accept, hand in and take the reward when there is nothing to choose. Shift skips it
-- (to read the text); a reward choice and a quest that needs gold or items handed over always wait.
local q = CreateFrame("Frame")
for _, e in ipairs({ "QUEST_DETAIL", "QUEST_PROGRESS", "QUEST_COMPLETE", "QUEST_ACCEPT_CONFIRM" }) do q:RegisterEvent(e) end
q:SetScript("OnEvent", function(_, event)
    if not W.LeylineRealm then return end   -- never on another server
    if (WrathUnleashedUIDB and WrathUnleashedUIDB.questsOff) or (IsShiftKeyDown and IsShiftKeyDown()) then return end
    if event == "QUEST_DETAIL" then
        if AcceptQuest then AcceptQuest() end
    elseif event == "QUEST_ACCEPT_CONFIRM" then
        if ConfirmAcceptQuest then ConfirmAcceptQuest() end
        if StaticPopup_Hide then StaticPopup_Hide("QUEST_ACCEPT") end
    elseif event == "QUEST_PROGRESS" then
        if IsQuestCompletable and IsQuestCompletable() and (not GetQuestMoneyToGet or GetQuestMoneyToGet() == 0) then
            CompleteQuest()
        end
    elseif event == "QUEST_COMPLETE" then
        if (GetNumQuestChoices and GetNumQuestChoices() or 0) <= 1 and GetQuestReward then GetQuestReward(1) end
    end
end)

SLASH_WUBARS1 = "/wubars"
SlashCmdList["WUBARS"] = function()
    barsOn()
    fillBars(false)
end
