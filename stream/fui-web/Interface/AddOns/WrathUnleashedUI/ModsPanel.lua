-- Esc > Mods & Workshop (3.3.5a API): the in-game front door of the WrathUnleashed mod workshop.
--   Interface: UI size slider (modern size by default), action bars on, fill my bars.
--   Installed:  every addon in this client with an on/off switch (takes effect after Reload UI).
--   Mods:       the Workshop mods this realm runs (WU_MOD_CATALOG, from the generated WUModCatalog addon),
--               with on/off for their addons, and the links (the Workshop site, the repos), to copy.
--   Workshop:   what players made (courses, modes, builds), to rate and play in one click (Workshop.lua).
-- The button is named GameMenuButtonAddOns: Forever UI's game menu keeps a place for that name
-- (after Ratings), skins it and lays it out with the other buttons.

local W = WrathUnleashedUI
local PANEL_W, PANEL_H, ROW_H, ROWS = 460, 470, 22, 12

local WORKSHOP = {
    { "Every mod", "https://play.openvanilla.app/wrath/mods" },
    { "Make a mod", "https://github.com/orionopenwow/WrathUnleashed/tree/main/mods" },
    { "This realm's code", "https://github.com/orionopenwow/WrathUnleashed" },
    { "Forever UI (GPL-2)", "https://github.com/Adrestie/mod-forever-ui" },
}

local panel

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

local function showTab(n)
    for i, page in ipairs(panel.pages) do
        if i == n then page:Show() else page:Hide() end
        panel.tabs[i]:SetAlpha(i == n and 1 or 0.6)
    end
    if n == 2 then panel.RefreshAddons() end
    if n == 3 and panel.RefreshWorkshop then panel.RefreshWorkshop() end
    if n == 4 and W.RefreshWorkshopItems then W.RefreshWorkshopItems() end
end

local function buildInterface(page)
    label(page, "UI size", "GameFontNormal", "TOPLEFT", 16, -14)
    local s = CreateFrame("Slider", "WrathUnleashedUIScaleSlider", page, "OptionsSliderTemplate")
    s:SetWidth(300); s:SetHeight(17)
    s:SetPoint("TOPLEFT", 20, -44)
    s:SetMinMaxValues(W.SCALE_MIN, W.SCALE_MAX)
    s:SetValueStep(0.01)
    _G[s:GetName() .. "Low"]:SetText("Smaller")
    _G[s:GetName() .. "High"]:SetText("Bigger")
    local value = label(page, "", "GameFontHighlightSmall", "LEFT", s, "RIGHT", 12, 0)
    local dragging = false
    s:SetScript("OnValueChanged", function(self, v)
        v = math.floor(v * 100 + 0.5) / 100
        value:SetText(string.format("%d%%", v * 100))
        if dragging then return end
        W.ApplyScale(v)
    end)
    s:SetScript("OnMouseDown", function() dragging = true end)
    s:SetScript("OnMouseUp", function(self) dragging = false; W.ApplyScale(self:GetValue()) end)
    page.slider = s
    button(page, "Modern size", 120, function()
        local k = W.ModernScale()
        W.ApplyScale(k); s:SetValue(k)
    end, "TOPLEFT", 20, -78)
    label(page, "Modern size matches today's games: the UI is the same share of the screen at any window size.",
        "GameFontHighlightSmall", "TOPLEFT", 20, -106):SetWidth(PANEL_W - 60)

    label(page, "Action bars", "GameFontNormal", "TOPLEFT", 16, -150)
    button(page, "Show every bar", 140, function() W.BarsOn() end, "TOPLEFT", 20, -174)
    button(page, "Fill my bars", 140, function() W.BarsOn(); W.FillBars(false) end, "LEFT", page, "TOPLEFT", 170, -185)
    label(page, "Fill my bars puts every spell you know that isn't on a bar into the empty buttons. Nothing is moved.",
        "GameFontHighlightSmall", "TOPLEFT", 20, -204):SetWidth(PANEL_W - 60)
    local qa = CreateFrame("CheckButton", nil, page, "UICheckButtonTemplate")
    qa:SetPoint("TOPLEFT", 16, -336)
    label(page, "Instant quests: accept and hand in for me (hold Shift to read; a reward choice always waits for you)",
        "GameFontHighlightSmall", "LEFT", qa, "RIGHT", 2, 0):SetWidth(PANEL_W - 80)
    qa:SetScript("OnShow", function(self) self:SetChecked(not (WrathUnleashedUIDB and WrathUnleashedUIDB.questsOff)) end)
    qa:SetScript("OnClick", function(self)
        WrathUnleashedUIDB = WrathUnleashedUIDB or {}
        WrathUnleashedUIDB.questsOff = not self:GetChecked() or nil
    end)
    label(page, "Keys", "GameFontNormal", "TOPLEFT", 16, -248)
    button(page, "Default keys", 140, function() W.DefaultKeys(false) end, "TOPLEFT", 20, -272)
    label(page, "Main bar 1-7 and F G T Z X (8 9 0 - = are left free). The bar above it: Shift + those keys. "
        .. "The next bar: Ctrl +. The right bar: Alt +.", "GameFontHighlightSmall", "TOPLEFT", 20, -300):SetWidth(PANEL_W - 60)
    page:SetScript("OnShow", function()
        s:SetValue((WrathUnleashedUIDB and WrathUnleashedUIDB.uiScale) or tonumber(GetCVar and GetCVar("uiScale") or "") or 1)
    end)
end

local function buildInstalled(page)
    label(page, "Addons in this client. Changes take effect after Reload UI.", "GameFontHighlightSmall", "TOPLEFT", 16, -12)
    local rows, offset = {}, 0
    for i = 1, ROWS do
        local cb = CreateFrame("CheckButton", nil, page, "UICheckButtonTemplate")
        cb:SetWidth(22); cb:SetHeight(22)
        cb:SetPoint("TOPLEFT", 14, -30 - (i - 1) * ROW_H)
        cb.text = label(page, "", "GameFontHighlight", "LEFT", cb, "RIGHT", 4, 0)
        cb.text:SetWidth(PANEL_W - 90)
        cb:SetScript("OnClick", function(self)
            if not self.index then return end
            if self:GetChecked() then pcall(EnableAddOn, self.index) else pcall(DisableAddOn, self.index) end
        end)
        rows[i] = cb
    end
    local function refresh()
        local n = GetNumAddOns and GetNumAddOns() or 0
        if offset > math.max(0, n - ROWS) then offset = math.max(0, n - ROWS) end
        for i, cb in ipairs(rows) do
            local idx = offset + i
            if idx <= n then
                local name, title, _, enabled = GetAddOnInfo(idx)
                cb.index = idx
                cb.text:SetText((title and title ~= "" and title or name) or ("Addon " .. idx))
                cb:SetChecked(enabled and true or false)
                cb:Show(); cb.text:Show()
            else
                cb.index = nil
                cb:Hide(); cb.text:Hide()
            end
        end
        page.count:SetText(n == 0 and "No addons found." or string.format("%d-%d of %d", offset + 1, math.min(n, offset + ROWS), n))
    end
    page.count = label(page, "", "GameFontHighlightSmall", "BOTTOMLEFT", 16, 46)
    button(page, "Up", 60, function() offset = math.max(0, offset - ROWS); refresh() end, "BOTTOMLEFT", 150, 40)
    button(page, "Down", 60, function() offset = offset + ROWS; refresh() end, "BOTTOMLEFT", 214, 40)
    button(page, "Reload UI", 100, function() ReloadUI() end, "BOTTOMRIGHT", -16, 40)
    panel.RefreshAddons = refresh
end

-- The catalog mods this realm runs: WU_MOD_CATALOG, from the WUModCatalog addon that the "mods" step
-- (wu-mod.py catalog --lua) generates and streams with the mods' own addons.
local KIND_LABEL = { ui = "Addon", realm = "Realm", both = "Realm + addon" }

-- The rows for the Workshop list: { id, title, line, addons, kind } per mod, sorted by name.
function W.CatalogRows(catalog)
    local rows = {}
    for _, m in ipairs(type(catalog) == "table" and catalog or {}) do
        if type(m) == "table" and type(m.id) == "string" and type(m.name) == "string" then
            rows[#rows + 1] = {
                id = m.id, kind = m.kind, name = m.name,
                title = string.format("%s |cff9d9d9dv%s - %s|r", m.name, tostring(m.version or "?"), KIND_LABEL[m.kind] or "Mod"),
                line = tostring(m.description or ""),
                addons = type(m.addons) == "table" and m.addons or {},
            }
        end
    end
    table.sort(rows, function(a, b) return a.name:lower() < b.name:lower() end)
    return rows
end

-- On when every addon of the mod is enabled (GetAddOnInfo's 4th value); nil when it has none.
function W.ModAddonsOn(row)
    if #row.addons == 0 then return nil end
    for _, name in ipairs(row.addons) do
        local _, _, _, enabled = GetAddOnInfo(name)
        if not enabled then return false end
    end
    return true
end

function W.SetModAddons(row, on)
    for _, name in ipairs(row.addons) do
        if on then pcall(EnableAddOn, name) else pcall(DisableAddOn, name) end
    end
end

local function buildWorkshop(page)
    local MOD_ROWS, MOD_H = 4, 42
    label(page, "Mods on this realm. Untick an addon to turn it off (after Reload UI).", "GameFontHighlightSmall", "TOPLEFT", 16, -12)
    local box = CreateFrame("EditBox", nil, page, "InputBoxTemplate")
    box:SetWidth(PANEL_W - 50); box:SetHeight(20)
    box:SetPoint("BOTTOMLEFT", 22, 46)
    box:SetAutoFocus(false)
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    box:SetScript("OnTextChanged", function(self) if self.fixed and self:GetText() ~= self.fixed then self:SetText(self.fixed) end end)
    label(page, "Ctrl+C copies the address above.", "GameFontDisableSmall", "BOTTOMLEFT", 22, 30)
    local function copy(url)
        if url == "" then return end
        box.fixed = url; box:SetText(url); box:SetFocus(); box:HighlightText()
    end

    local rows, offset = {}, 0
    for i = 1, MOD_ROWS do
        local y = -30 - (i - 1) * MOD_H
        local cb = CreateFrame("CheckButton", nil, page, "UICheckButtonTemplate")
        cb:SetWidth(22); cb:SetHeight(22)
        cb:SetPoint("TOPLEFT", 14, y)
        cb:SetScript("OnClick", function(self)
            if self.row then W.SetModAddons(self.row, self:GetChecked() and true or false) end
        end)
        cb.title = label(page, "", "GameFontNormal", "TOPLEFT", 40, y - 2)
        cb.title:SetWidth(PANEL_W - 70)
        cb.line = label(page, "", "GameFontHighlightSmall", "TOPLEFT", 40, y - 18)
        cb.line:SetWidth(PANEL_W - 70); cb.line:SetHeight(20)
        cb.realm = label(page, "realm", "GameFontDisableSmall", "TOPLEFT", 12, y - 6)
        rows[i] = cb
    end
    local by = -30 - MOD_ROWS * MOD_H
    local count = label(page, "", "GameFontHighlightSmall", "TOPLEFT", 16, by - 6)
    local function refresh()
        local list = W.CatalogRows(WU_MOD_CATALOG)
        if offset > math.max(0, #list - MOD_ROWS) then offset = math.max(0, #list - MOD_ROWS) end
        for i, cb in ipairs(rows) do
            local row = list[offset + i]
            cb.row = row
            if row then
                cb.title:SetText(row.title); cb.line:SetText(row.line)
                cb.title:Show(); cb.line:Show()
                local on = W.ModAddonsOn(row)
                if on == nil then cb:Hide(); cb.realm:Show() else cb:SetChecked(on); cb:Show(); cb.realm:Hide() end
            else
                cb:Hide(); cb.title:Hide(); cb.line:Hide(); cb.realm:Hide()
            end
        end
        count:SetText(#list == 0 and "No Workshop mods on this realm yet."
            or string.format("%d-%d of %d", offset + 1, math.min(#list, offset + MOD_ROWS), #list))
        page.rows, page.list = rows, list
    end
    button(page, "Up", 50, function() offset = math.max(0, offset - MOD_ROWS); refresh() end, "TOPLEFT", 150, by)
    button(page, "Down", 60, function() offset = offset + MOD_ROWS; refresh() end, "TOPLEFT", 204, by)
    button(page, "Reload UI", 90, function() ReloadUI() end, "TOPLEFT", 270, by)
    for i, e in ipairs(WORKSHOP) do
        local b = CreateFrame("Button", nil, page)
        b:SetWidth(PANEL_W - 40); b:SetHeight(16)
        b:SetPoint("TOPLEFT", 16, by - 30 - (i - 1) * 17)
        b.label = label(b, e[1] .. ": |cff9d9d9d" .. e[2] .. "|r", "GameFontHighlightSmall", "LEFT", 0, 0)
        b:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        b:SetScript("OnClick", function() copy(e[2]) end)
    end
    page.copyBox = box
    panel.RefreshWorkshop = refresh
end

local function build()
    panel = CreateFrame("Frame", "WrathUnleashedModsFrame", UIParent)
    panel:SetWidth(PANEL_W); panel:SetHeight(PANEL_H)
    panel:SetPoint("CENTER")
    panel:SetFrameStrata("DIALOG")
    panel:EnableMouse(true)
    panel:SetMovable(true)
    panel:RegisterForDrag("LeftButton")
    panel:SetScript("OnDragStart", panel.StartMoving)
    panel:SetScript("OnDragStop", panel.StopMovingOrSizing)
    panel:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    panel:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    label(panel, "Mods & Workshop", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    button(panel, "Done", 90, function() panel:Hide() end, "BOTTOMRIGHT", -16, 14)
    if W.ToggleLeyline then   -- Leyline.lua: the realms of the Leyline network
        button(panel, "Leyline realms", 130, function() panel:Hide(); W.ToggleLeyline() end, "BOTTOMLEFT", 16, 14)
    end
    if W.ToggleBuilder then   -- Builder.lua: place and share props in build areas
        button(panel, "Builder", 90, function() panel:Hide(); W.ToggleBuilder() end, "BOTTOMLEFT", 152, 14)
    end
    tinsert(UISpecialFrames, "WrathUnleashedModsFrame")   -- Esc closes it

    panel.pages, panel.tabs = {}, {}
    local names = { "Interface", "Installed", "Mods", "Workshop" }
    for i, name in ipairs(names) do
        local page = CreateFrame("Frame", nil, panel)
        page:SetPoint("TOPLEFT", 12, -70); page:SetPoint("BOTTOMRIGHT", -12, 12)
        page:Hide()
        panel.pages[i] = page
        panel.tabs[i] = button(panel, name, 98, function() showTab(i) end, "TOPLEFT", 22 + (i - 1) * 104, -42)
    end
    buildInterface(panel.pages[1])
    buildInstalled(panel.pages[2])
    buildWorkshop(panel.pages[3])
    if W.BuildWorkshopItems then W.BuildWorkshopItems(panel.pages[4]) end
    showTab(1)
    panel:Hide()
end

function W.ToggleMods()
    if not panel then build() end
    if panel:IsShown() then panel:Hide() else panel:Show() end
end

-- The Esc menu button (Forever UI lays it out; without Forever UI it goes under Macros).
if GameMenuFrame and not _G["GameMenuButtonAddOns"] then
    local b = CreateFrame("Button", "GameMenuButtonAddOns", GameMenuFrame, "GameMenuButtonTemplate")
    b:SetText("Mods & Workshop")
    b:SetScript("OnClick", function()
        PlaySound("igMainMenuOption")
        HideUIPanel(GameMenuFrame)
        W.ToggleMods()
    end)
    if not (ForeverUI and ForeverUI.GameMenu) then
        b:SetPoint("TOP", GameMenuButtonMacros, "BOTTOM", 0, -1)
        GameMenuFrame:SetHeight(GameMenuFrame:GetHeight() + 25)
        if GameMenuButtonLogout then
            GameMenuButtonLogout:ClearAllPoints()
            GameMenuButtonLogout:SetPoint("TOP", b, "BOTTOM", 0, -16)
        end
    end
    if ForeverUI and ForeverUI.GameMenu and ForeverUI.GameMenu.Layout then ForeverUI.GameMenu.Layout() end
end

-- Opens the panel on one tab (4: the Workshop).
function W.ShowModsTab(n)
    if not panel then build() end
    panel:Show()
    showTab(n)
end

SLASH_WUMODS1 = "/mods"
SlashCmdList["WUMODS"] = function() W.ToggleMods() end
SLASH_WUWORKSHOP1, SLASH_WUWORKSHOP2 = "/workshop", "/ws"
SlashCmdList["WUWORKSHOP"] = function() W.ShowModsTab(4) end
