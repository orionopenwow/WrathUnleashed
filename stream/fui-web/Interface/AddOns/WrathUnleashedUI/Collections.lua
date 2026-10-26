-- Collections (3.3.5a API), phase 1: one window for what a character has collected, as in today's WoW.
--   Mounts, Pets: the 3.3.5 companion lists (GetNumCompanions / GetCompanionInfo), with search, a 3D preview
--                 and Summon. Click a row to preview it; double-click or Summon to ride or call it; drag a row
--                 onto an action bar (PickupCompanion).
--   Toys, Appearances: coming.
-- Opened by Shift-P (set once per character; Esc > Mods & Workshop > Default keys sets it again), /collections,
-- and, with Forever UI, a Collections button on the micro menu.
-- The companion handling follows Forever UI's MountsTab.lua (github.com/Adrestie/mod-forever-ui, GPL-2):
-- GetCompanionInfo(kind, i) -> creatureID, name, spellID, icon, active; SetCreature(creatureID) for the
-- preview; CallCompanion / DismissCompanion; COMPANION_LEARNED / UNLEARNED / UPDATE to refresh. No art copied.
-- Anything the browser client might lack is called through pcall.

local W = WrathUnleashedUI
local WIN_W, WIN_H, ROW_H, ROWS, LIST_W = 680, 480, 26, 13, 300
local BINDING_KEY = "SHIFT-P"
local TOGGLE_NAME = "WrathUnleashedCollectionsToggle"

local TABS = {
    { name = "Mounts", kind = "MOUNT", noun = "mounts", none = "No mounts yet. Level 80s get every mount (type .mounts)." },
    { name = "Pets", kind = "CRITTER", noun = "pets", none = "No pets yet." },
    { name = "Toys", coming = "Coming: the toys you own (fun items with a use) in one place, used right from here." },
    { name = "Appearances", coming = "Coming: every look you've unlocked for transmog, by slot, with a preview, "
        .. "ready to apply at the transmogrifier." },
}

local win
local C = {}   -- state and the functions the tests reach (W.Collections)

local function try(fn, ...)
    if type(fn) ~= "function" then return nil end
    local ok, a, b, c, d, e = pcall(fn, ...)
    if ok then return a, b, c, d, e end
    return nil
end

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end

local function button(parent, text, w, onClick, ...)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(22)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end

-- ---------------------------------------------------------------- Data

local function count(kind)
    return tonumber(try(GetNumCompanions, kind)) or 0
end

local function info(kind, index)
    return try(GetCompanionInfo, kind, index) -- creatureID, name, spellID, icon, active
end

-- Indices of the companions whose name holds the search text (plain, any case).
local function filtered(kind, query)
    local list = {}
    query = (query or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
    for i = 1, count(kind) do
        local creatureID, name = info(kind, i)
        if creatureID and (query == "" or (name or ""):lower():find(query, 1, true)) then
            list[#list + 1] = i
        end
    end
    return list
end

-- ---------------------------------------------------------------- Companion page

local function buildCompanionPage(page, tab)
    local P = { tab = tab, kind = tab.kind, offset = 0, list = {}, rows = {} }
    page.state = P

    local search = CreateFrame("EditBox", nil, page, "InputBoxTemplate")
    search:SetWidth(LIST_W - 10); search:SetHeight(20)
    search:SetPoint("TOPLEFT", 22, -6)
    search:SetAutoFocus(false)
    search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    search:SetScript("OnEnterPressed", function(self) self:ClearFocus() end)
    local hint = label(search, "Search " .. tab.noun, "GameFontDisableSmall", "LEFT", 4, 0)
    P.search, P.hint = search, hint

    for i = 1, ROWS do
        local r = CreateFrame("Button", nil, page)
        r:SetWidth(LIST_W); r:SetHeight(ROW_H - 2)
        r:SetPoint("TOPLEFT", 14, -34 - (i - 1) * ROW_H)
        r.icon = r:CreateTexture(nil, "ARTWORK")
        r.icon:SetWidth(ROW_H - 4); r.icon:SetHeight(ROW_H - 4)
        r.icon:SetPoint("LEFT", 2, 0)
        r.text = label(r, "", "GameFontHighlight", "LEFT", r.icon, "RIGHT", 6, 0)
        r.text:SetWidth(LIST_W - ROW_H - 30)
        r.active = label(r, "", "GameFontNormalSmall", "RIGHT", -4, 0)
        r:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        r.sel = r:CreateTexture(nil, "BACKGROUND")
        r.sel:SetAllPoints(r)
        r.sel:SetTexture("Interface\\QuestFrame\\UI-QuestLogTitleHighlight")
        r.sel:SetVertexColor(1, 0.82, 0, 0.35)
        r.sel:Hide()
        r:RegisterForClicks("LeftButtonUp", "RightButtonUp")
        r:RegisterForDrag("LeftButton")
        r:SetScript("OnClick", function(self, mouse)
            if not self.index then return end
            P.selected = self.creatureID
            if mouse == "RightButton" then C.Summon(P) end
            P.Refresh()
        end)
        r:SetScript("OnDoubleClick", function(self)
            if not self.index then return end
            P.selected = self.creatureID
            C.Summon(P)
        end)
        r:SetScript("OnDragStart", function(self)
            if self.index then try(PickupCompanion, P.kind, self.index) end
        end)
        P.rows[i] = r
    end
    page:EnableMouseWheel(true)
    page:SetScript("OnMouseWheel", function(_, delta)
        P.offset = P.offset - delta * 3
        P.Refresh()
    end)
    P.count = label(page, "", "GameFontHighlightSmall", "BOTTOMLEFT", 16, 42)
    button(page, "Up", 50, function() P.offset = P.offset - ROWS; P.Refresh() end, "BOTTOMLEFT", 176, 38)
    button(page, "Down", 50, function() P.offset = P.offset + ROWS; P.Refresh() end, "BOTTOMLEFT", 230, 38)

    -- Preview: the creature in 3D, turned by dragging with the mouse.
    local box = CreateFrame("Frame", nil, page)
    box:SetPoint("TOPLEFT", LIST_W + 30, -6)
    box:SetPoint("BOTTOMRIGHT", -14, 70)
    box:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    box:SetBackdropColor(0, 0, 0, 0.6)
    local ok, model = pcall(CreateFrame, "PlayerModel", nil, box)
    if ok and model then
        model:SetPoint("TOPLEFT", 6, -6); model:SetPoint("BOTTOMRIGHT", -6, 6)
        model.rotation = 0
        model:EnableMouse(true)
        model:SetScript("OnMouseDown", function(self) self.dragX = try(GetCursorPosition) end)
        model:SetScript("OnMouseUp", function(self) self.dragX = nil end)
        model:SetScript("OnUpdate", function(self)
            if not self.dragX then return end
            local x = try(GetCursorPosition)
            if not x then return end
            self.rotation = (self.rotation or 0) + (x - self.dragX) * 0.02
            self.dragX = x
            try(self.SetRotation, self, self.rotation)
        end)
        -- A model hidden when its creature was set shows nothing: set it again on show (as Forever UI does).
        model:SetScript("OnShow", function(self) self.creature = nil; P.UpdatePreview() end)
        P.model = model
    end
    P.name = label(page, "", "GameFontNormalLarge", "TOPLEFT", box, "BOTTOMLEFT", 4, -8)
    P.name:SetWidth(WIN_W - LIST_W - 160)
    P.summon = button(page, "Summon", 120, function() C.Summon(P) end, "BOTTOMRIGHT", -16, 38)
    label(page, "Drag a row onto an action bar.", "GameFontDisableSmall", "BOTTOMLEFT", box, "BOTTOMLEFT", 4, -48)

    function P.UpdatePreview()
        local index = P.SelectedIndex()
        local creatureID, name, _, _, active = nil, nil, nil, nil, nil
        if index then creatureID, name, _, _, active = info(P.kind, index) end
        P.name:SetText(name or "")
        if creatureID then P.summon:Enable() else P.summon:Disable() end
        if P.kind == "MOUNT" then
            P.summon:SetText(active and "Dismount" or "Summon")
        else
            P.summon:SetText(active and "Dismiss" or "Summon")
        end
        local m = P.model
        if m and creatureID and m.creature ~= creatureID and m:IsVisible() then
            m.creature = creatureID
            try(m.SetCreature, m, creatureID)
            try(m.SetRotation, m, m.rotation or 0)
        end
    end

    -- The chosen one; with none chosen (or it's gone) the active one, else the first in the list.
    function P.SelectedIndex()
        local first, activeIdx
        for _, i in ipairs(P.list) do
            local creatureID, _, _, _, active = info(P.kind, i)
            if creatureID == P.selected then return i end
            first = first or i
            if active and not activeIdx then activeIdx = i end
        end
        local i = activeIdx or first
        P.selected = i and info(P.kind, i) or nil
        return i
    end

    function P.Refresh()
        local text = search:GetText() or ""
        if text == "" then hint:Show() else hint:Hide() end
        P.list = filtered(P.kind, text)
        local n = #P.list
        P.offset = math.max(0, math.min(P.offset, n - ROWS))
        local current = P.SelectedIndex()
        for i, r in ipairs(P.rows) do
            local index = P.list[P.offset + i]
            local creatureID, name, _, icon, active
            if index then creatureID, name, _, icon, active = info(P.kind, index) end
            if creatureID then
                r.index, r.creatureID = index, creatureID
                r.icon:SetTexture(icon)
                r.text:SetText(name or "")
                r.active:SetText(active and (P.kind == "MOUNT" and "riding" or "out") or "")
                if index == current then r.sel:Show() else r.sel:Hide() end
                r:Show()
            else
                r.index, r.creatureID = nil, nil
                r:Hide()
            end
        end
        local total = count(P.kind)
        if total == 0 then
            P.count:SetText(tab.none)
        elseif n == total then
            P.count:SetText(string.format("%d %s", total, tab.noun))
        else
            P.count:SetText(string.format("%d of %d %s", n, total, tab.noun))
        end
        P.UpdatePreview()
    end

    search:SetScript("OnTextChanged", function() P.offset = 0; P.Refresh() end)
    page:SetScript("OnShow", function() P.Refresh() end)
    return P
end

local function buildComingPage(page, tab)
    label(page, tab.name, "GameFontNormalLarge", "TOPLEFT", 24, -24)
    label(page, "Coming", "GameFontHighlight", "TOPLEFT", 24, -52)
    label(page, tab.coming, "GameFontHighlightSmall", "TOPLEFT", 24, -76):SetWidth(WIN_W - 80)
end

-- ---------------------------------------------------------------- Actions

-- Rides or calls the selected companion; dismounts / dismisses it when it is already out.
function C.Summon(P)
    local index = P.SelectedIndex()
    if not index then return false end
    local _, _, _, _, active = info(P.kind, index)
    if active then
        if P.kind == "MOUNT" and Dismount and IsMounted and try(IsMounted) then try(Dismount)
        else try(DismissCompanion, P.kind) end
    else
        try(CallCompanion, P.kind, index)
    end
    return true
end

local function showTab(n)
    for i, page in ipairs(win.pages) do
        if i == n then page:Show() else page:Hide() end
        win.tabs[i]:SetAlpha(i == n and 1 or 0.6)
    end
    win.current = n
    local P = win.pages[n].state
    if P then P.Refresh() end
end

local function build()
    win = CreateFrame("Frame", "WrathUnleashedCollectionsFrame", UIParent)
    win:SetWidth(WIN_W); win:SetHeight(WIN_H)
    win:SetPoint("CENTER")
    win:SetFrameStrata("DIALOG")
    win:EnableMouse(true)
    win:SetMovable(true)
    win:RegisterForDrag("LeftButton")
    win:SetScript("OnDragStart", win.StartMoving)
    win:SetScript("OnDragStop", win.StopMovingOrSizing)
    win:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    win:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    label(win, "Collections", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, win, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    button(win, "Done", 90, function() win:Hide() end, "BOTTOMRIGHT", -16, 14)
    if UISpecialFrames then tinsert(UISpecialFrames, "WrathUnleashedCollectionsFrame") end -- Esc closes it

    win.pages, win.tabs = {}, {}
    for i, tab in ipairs(TABS) do
        local page = CreateFrame("Frame", nil, win)
        page:SetPoint("TOPLEFT", 12, -70); page:SetPoint("BOTTOMRIGHT", -12, 12)
        page:Hide()
        win.pages[i] = page
        win.tabs[i] = button(win, tab.name, 130, function() showTab(i) end, "TOPLEFT", 24 + (i - 1) * 140, -42)
        if tab.kind then buildCompanionPage(page, tab) else buildComingPage(page, tab) end
    end
    win:SetScript("OnShow", function()
        try(PlaySound, "igCharacterInfoOpen")
        if W.UpdateCollectionsMicro then W.UpdateCollectionsMicro(true) end
    end)
    win:SetScript("OnHide", function()
        try(PlaySound, "igCharacterInfoClose")
        if W.UpdateCollectionsMicro then W.UpdateCollectionsMicro(false) end
    end)
    showTab(1)
    win:Hide()
end

-- tab: optional number or name ("mounts", "pets", "toys", "appearances").
function W.ToggleCollections(tab)
    if not win then build() end
    local n
    if type(tab) == "number" then n = tab
    elseif type(tab) == "string" and tab ~= "" then
        for i, t in ipairs(TABS) do if t.name:lower():find(tab:lower(), 1, true) == 1 then n = i end end
    end
    if n and TABS[n] then
        showTab(n)
        win:Show()
        return
    end
    if win:IsShown() then win:Hide() else win:Show() end
end

-- Learned, forgotten, mounted or dismounted: refresh the open page.
local listener = CreateFrame("Frame")
for _, event in ipairs({ "COMPANION_LEARNED", "COMPANION_UNLEARNED", "COMPANION_UPDATE", "PLAYER_ENTERING_WORLD" }) do
    listener:RegisterEvent(event)
end
listener:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_ENTERING_WORLD" then
        listener:UnregisterEvent("PLAYER_ENTERING_WORLD")
        WrathUnleashedUIChar = WrathUnleashedUIChar or {}
        if not WrathUnleashedUIChar.collectionsKey then
            WrathUnleashedUIChar.collectionsKey = W.CollectionsKey(true) and true or nil
        end
        return
    end
    if win and win:IsShown() and win.current then
        local P = win.pages[win.current].state
        if P then P.Refresh() end
    end
end)

-- Shift-P (as in today's WoW; in 3.3.5 it opened the pet spellbook) clicks a hidden button that toggles the window.
local toggle = CreateFrame("Button", TOGGLE_NAME, UIParent)
toggle:SetScript("OnClick", function() W.ToggleCollections() end)
function W.CollectionsKey(quiet)
    if not SetBindingClick then return false end
    if InCombatLockdown and InCombatLockdown() then return false end
    if not pcall(SetBindingClick, BINDING_KEY, TOGGLE_NAME) then return false end
    if SaveBindings then pcall(SaveBindings, (GetCurrentBindingSet and GetCurrentBindingSet()) or 2) end
    return true
end
-- Esc > Mods & Workshop > Default keys sets Shift-P again.
if W.DefaultKeys then
    local defaultKeys = W.DefaultKeys
    W.DefaultKeys = function(quiet)
        local done = defaultKeys(quiet)
        if done then W.CollectionsKey(quiet) end
        return done
    end
end

-- The micro menu button: Forever UI's strip has a place for other addons' buttons, after Group Finder as in
-- today's WoW, with its collections icon. Without Forever UI the stock 3.3.5 strip is full, so Shift-P and
-- /collections open it.
if ForeverUI and type(ForeverUI.AddMicroButton) == "function" then
    pcall(ForeverUI.AddMicroButton, {
        name = "WrathUnleashedCollectionsMicroButton",
        atlasSet = "collections",
        after = "LFDMicroButton",
        tooltip = "Collections (Shift-P)",
        onClick = function() W.ToggleCollections() end,
    })
    W.UpdateCollectionsMicro = function(isOpen)
        if ForeverUI.UpdateMicro then pcall(ForeverUI.UpdateMicro, "WrathUnleashedCollectionsMicroButton", isOpen) end
    end
end

SLASH_WUCOLLECTIONS1 = "/collections"
SlashCmdList["WUCOLLECTIONS"] = function(msg) W.ToggleCollections(msg) end

W.Collections = C
C.Filtered, C.Window, C.Tabs = filtered, function() return win end, TABS
