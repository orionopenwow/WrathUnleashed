-- lua5.1 stream/tests/test_wuui_collections.lua [addon dir]
-- Fake 3.3.5a API: loads WrathUnleashedUI.lua and Collections.lua, opens the window, lists fake companions,
-- searches, previews and summons, and checks the Shift-P binding and the Forever UI micro button.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets
local frames, created = {}, {}
local Frame = {}
Frame.__index = function(self, k)
    local v = rawget(Frame, k)
    if v ~= nil then return v end
    if type(k) == "string" and k:match("^%u") then return function() end end -- other widget methods: no-ops
    return nil
end
function Frame:SetScript(n, fn) self.scripts[n] = fn end
function Frame:GetScript(n) return self.scripts[n] end
function Frame:Fire(n, ...) local fn = self.scripts[n]; if fn then return fn(self, ...) end end
function Frame:Show()
    local was = self:IsVisible(); self.shown = true
    if not was and self:IsVisible() then self:Fire("OnShow") end
end
function Frame:Hide()
    local was = self:IsVisible(); self.shown = false
    if was then self:Fire("OnHide") end
end
function Frame:IsShown() return self.shown end
function Frame:IsVisible()
    if not self.shown then return false end
    return self.parent == nil or self.parent.top or self.parent:IsVisible()
end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text end
function Frame:SetTexture(t) self.texture = t end
function Frame:Enable() self.enabled = true end
function Frame:Disable() self.enabled = false end
function Frame:RegisterEvent(e) self.events[e] = true end
function Frame:UnregisterEvent(e) self.events[e] = nil end
function Frame:GetName() return self.name end
function Frame:GetParent() return self.parent end
function Frame:SetCreature(id) self.creature_set = id end
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    created[#created + 1] = f
    return f
end
function Frame:CreateFontString() return new("FontString", nil, self) end
function Frame:CreateTexture() return new("Texture", nil, self) end
function CreateFrame(kind, name, parent) local f = new(kind, name, parent); frames[#frames + 1] = f; return f end

UIParent = new("Frame", "UIParent"); UIParent.top = true
UIParent.s = 1
function UIParent:SetScale(k) self.s = k end
function UIParent:GetScale() return self.s end
UISpecialFrames = {}
function tinsert(t, v) table.insert(t, v) end
SlashCmdList = {}
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
function GetScreenHeight() return 981 end
function InCombatLockdown() return false end
local binds, clicks = {}, {}
function SetBinding(k, a) binds[k] = a or false; return 1 end
function SetBindingClick(k, b) clicks[k] = b; return 1 end
local saved = 0
function SaveBindings() saved = saved + 1 end
function GetCurrentBindingSet() return 2 end
function SetCVar() end
function SetActionBarToggles() end
function HasAction() return false end
function UnitLevel() return 12 end
function PlaySound() end

-- ---------------------------------------------------------------- fake companions
local companions = {
    MOUNT = {
        { 14332, "Black War Steed", 22717, "icon-steed", false },
        { 28531, "Albino Drake", 60025, "icon-drake", false },
        { 32158, "Swift Zhevra", 49322, "icon-zhevra", false },
        { 31702, "Blue Drake", 59568, "icon-bluedrake", false },
    },
    CRITTER = {
        { 7385, "Bombay Cat", 10673, "icon-cat", false },
        { 7553, "Great Horned Owl", 10707, "icon-owl", false },
    },
}
for i = 1, 20 do companions.MOUNT[#companions.MOUNT + 1] = { 40000 + i, "Test Ram " .. i, 50000 + i, "icon-ram", false } end
local calls, dismissed, picked = {}, {}, {}
function GetNumCompanions(kind) return #companions[kind] end
function GetCompanionInfo(kind, i) local c = companions[kind][i]; if c then return c[1], c[2], c[3], c[4], c[5] end end
function CallCompanion(kind, i)
    calls[#calls + 1] = { kind, i }
    for j, c in ipairs(companions[kind]) do c[5] = (j == i) end
end
function DismissCompanion(kind) dismissed[#dismissed + 1] = kind; for _, c in ipairs(companions[kind]) do c[5] = false end end
function PickupCompanion(kind, i) picked[#picked + 1] = { kind, i } end

-- Forever UI's micro menu hook
local micro
ForeverUI = { AddMicroButton = function(def) micro = def; return new("Button", def.name) end, UpdateMicro = function() end }

-- ---------------------------------------------------------------- load
dofile(dir .. "/WrathUnleashedUI.lua")
local n0 = #frames
dofile(dir .. "/Collections.lua")
local W = assert(WrathUnleashedUI)
local C = assert(W.Collections, "W.Collections")
check("loads, builds nothing until opened", C.Window() == nil and #frames - n0 <= 3)
check("/collections registered", SLASH_WUCOLLECTIONS1 == "/collections" and SlashCmdList.WUCOLLECTIONS)
check("micro button after Group Finder, collections icon", micro and micro.after == "LFDMicroButton"
    and micro.atlasSet == "collections" and type(micro.onClick) == "function")

-- the first login sets Shift-P once per character, on a Leyline realm only (its hello, WrathUnleashedUI.lua W.WhenLeyline)
for _, f in ipairs(frames) do if f.events.PLAYER_ENTERING_WORLD then f:Fire("OnEvent", "PLAYER_ENTERING_WORLD") end end
check("another server (no hello yet): Shift-P left alone", clicks["SHIFT-P"] == nil)
WrathUnleashedUI.SetLeyline()
check("Shift-P clicks the toggle button", clicks["SHIFT-P"] == "WrathUnleashedCollectionsToggle" and saved > 0)
check("...once per character", WrathUnleashedUIChar.collectionsKey == true)
clicks["SHIFT-P"] = nil
W.DefaultKeys(true)
check("Default keys sets Shift-P again", clicks["SHIFT-P"] == "WrathUnleashedCollectionsToggle")

-- open it (Shift-P)
_G.WrathUnleashedCollectionsToggle:Fire("OnClick")
local win = C.Window()
check("window opens", win and win:IsShown() and win.current == 1)
check("Esc closes it", UISpecialFrames[1] == "WrathUnleashedCollectionsFrame")
local P = win.pages[1].state
local function visibleRows(P)
    local out = {}
    for _, r in ipairs(P.rows) do if r:IsShown() then out[#out + 1] = r.text:GetText() end end
    return out
end
local rows = visibleRows(P)
check("lists fake mounts (a page of 13)", #rows == 13 and rows[1] == "Black War Steed" and rows[2] == "Albino Drake")
check("count line", P.count:GetText() == "24 mounts")
check("first one selected and previewed", P.name:GetText() == "Black War Steed" and P.model.creature_set == 14332)

-- scroll
P.rows[1]:GetParent():Fire("OnMouseWheel", -1)
check("mouse wheel scrolls", visibleRows(P)[1] == "Blue Drake")
win.pages[1]:Fire("OnMouseWheel", 10)

-- search
P.search:SetText("drake"); P.search:Fire("OnTextChanged")
rows = visibleRows(P)
check("search filters (any case)", #rows == 2 and rows[1] == "Albino Drake" and rows[2] == "Blue Drake")
check("search count", P.count:GetText() == "2 of 24 mounts")
check("search hint hidden while typing", not P.hint:IsShown())
check("selection follows the filter", P.name:GetText() == "Albino Drake")
P.rows[2]:Fire("OnClick", "LeftButton")
check("click previews", P.name:GetText() == "Blue Drake" and P.model.creature_set == 31702)

-- summon
P.summon:Fire("OnClick")
check("Summon calls the companion", calls[1] and calls[1][1] == "MOUNT" and calls[1][2] == 4)
P.Refresh()
check("Summon becomes Dismount", P.summon:GetText() == "Dismount" and P.rows[2].active:GetText() == "riding")
P.summon:Fire("OnClick")
check("Dismount dismisses", dismissed[1] == "MOUNT")
P.rows[1]:Fire("OnDoubleClick")
check("double-click summons", calls[2] and calls[2][2] == 2)
P.rows[1]:Fire("OnDragStart")
check("drag picks it up for an action bar", picked[1] and picked[1][1] == "MOUNT" and picked[1][2] == 2)
P.search:SetText("zzz"); P.search:Fire("OnTextChanged")
check("no match: empty list, Summon off", #visibleRows(P) == 0 and P.summon.enabled == false)
P.search:SetText(""); P.search:Fire("OnTextChanged")
check("clearing the search lists all again", #visibleRows(P) == 13 and P.hint:IsShown())

-- pets
win.tabs[2]:Fire("OnClick")
local Q = win.pages[2].state
rows = visibleRows(Q)
check("Pets tab lists pets", win.current == 2 and #rows == 2 and rows[2] == "Great Horned Owl"
    and not win.pages[1]:IsShown())
Q.rows[2]:Fire("OnClick", "RightButton")
check("right-click summons a pet", calls[3] and calls[3][1] == "CRITTER" and calls[3][2] == 2)
Q.Refresh()
check("Summon becomes Dismiss for pets", Q.summon:GetText() == "Dismiss")

-- placeholders
win.tabs[3]:Fire("OnClick")
check("Toys: coming", win.current == 3 and win.pages[3].state == nil)
local function pageSays(page, pat)
    for _, f in ipairs(created) do
        if f.parent == page and f.kind == "FontString" and (f.text or ""):find(pat) then return true end
    end
end
check("Toys says what's coming", pageSays(win.pages[3], "^Coming$") and pageSays(win.pages[3], "toys you own"))
win.tabs[4]:Fire("OnClick")
check("Appearances says what's coming", pageSays(win.pages[4], "^Coming$") and pageSays(win.pages[4], "transmog"))

-- toggle, slash with a tab name, events
_G.WrathUnleashedCollectionsToggle:Fire("OnClick")
check("Shift-P again closes it", not win:IsShown())
SlashCmdList.WUCOLLECTIONS("pets")
check("/collections pets opens on Pets", win:IsShown() and win.current == 2)
companions.CRITTER[3] = { 7380, "Siamese Cat", 10677, "icon-cat2", false }
for _, f in ipairs(frames) do if f.events.COMPANION_LEARNED then f:Fire("OnEvent", "COMPANION_LEARNED") end end
check("a new pet shows on COMPANION_LEARNED", #visibleRows(Q) == 3)

-- a client without the companion API: no errors, empty lists
GetNumCompanions, GetCompanionInfo = nil, nil
local ok = pcall(function() win.tabs[1]:Fire("OnClick") end)
check("missing companion API: no error", ok and #visibleRows(P) == 0 and P.count:GetText():match("No mounts yet"))

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
