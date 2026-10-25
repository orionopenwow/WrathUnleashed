-- EditMode (3.3.5a API): Leyline's edit mode, the building view. F7, /edit or "Edit mode" in the Builder steps
-- out of your character into a free-flying camera (the browser client does the camera: CVar leylineEditMode).
-- While it is on, the normal UI is hidden and this addon shows the edit HUD instead:
--   * a banner with the controls, and a line under it saying what the tool is doing (and what the realm answered);
--   * a selection card: the selected prop, your prop count and limit, the build area;
--   * a tool bar: Props, Duplicate, Undo, Delete, Snap (grid), Turn (angle step), Keys, Done.
-- Your character stays where it stood; the realm checks every change, exactly as for the .build commands.
--
-- Keys (the browser client reads them and calls back here):
--   click a prop       select it (the realm says if it isn't yours)
--   Props > Spawn      then click the ground: the prop goes exactly there (on the grid when Snap is on)
--   G                  carry the selection on the cursor; wheel lifts it, Q / E or Shift+wheel turn it,
--                      a click or G drops it (".build placeat x y z turn"), Backspace puts it back
--   V                  duplicate the selection          Delete  remove it          Ctrl+Z  undo
--   WASD / Space / C   fly; Ctrl faster; hold the right mouse button to look; F7 back to your character

local W = WrathUnleashedUI
local CVAR, GRID, ANGLE = "leylineEditMode", "leylineEditGrid", "leylineEditAngle"
local GRIDS = { 0, 0.5, 1, 2 }
local ANGLES = { 15, 45, 90 }
local TAG_PATTERN = "%[Builder%]"

local hud, wasOn
local E = {}

local function on() return GetCVar and GetCVar(CVAR) == "1" end
local function cvarNum(name, default) return tonumber(GetCVar and GetCVar(name) or "") or default end

function E.Set(want)
    if SetCVar then pcall(SetCVar, CVAR, want and "1" or "0") end
end

function E.Toggle() E.Set(not on()) end
function E.IsOn() return on() and true or false end

local function builder() return W.Builder end
local function cmd(text) local B = builder(); if B and B.Command then return B.Command(text) end end

-- From the client's hotkeys (V, Delete, Ctrl+Z) and the tool bar.
local ALLOWED = { dup = true, delete = true, undo = true, near = true }
function E.Cmd(name)
    if not ALLOWED[name] then return end
    cmd(name)
end

-- A short line under the banner: what the tool is doing now.
function E.Note(text)
    E.note = text or ""
    if hud and hud.note then hud.note:SetText(E.note) end
end

-- From the Builder's Spawn button while editing: the next click on the ground places this prop.
function E.StartPlacing(prop)
    if not prop then return end
    E.placing = prop
    E.Note("Click the ground where the " .. prop.name .. " goes.")
end

-- The client: a click in the world, with the ground point under the cursor (WoW coordinates, already on the
-- grid when Snap is on) and the clicked object's id; either may be nil.
function E.Clicked(x, y, z, objectId)
    if E.placing and x then
        local p = E.placing
        E.placing = nil
        cmd(string.format("spawnat %d %.2f %.2f %.2f", p.id, x, y, z))
        E.Note(p.name .. " placed. G to carry it, V to duplicate it, or pick another in Props.")
        return
    end
    if objectId then
        cmd("pick " .. math.floor(objectId))
        E.Note("Selected. G to carry it, V to duplicate, Delete to remove.")
    end
end

-- The client: the carried prop was dropped at x, y, z and turned by turn degrees.
function E.Drop(x, y, z, turn)
    cmd(string.format("placeat %.2f %.2f %.2f %.0f", x, y, z, turn or 0))
    E.Note("Dropped. G to carry it again.")
end

local function cycle(list, current)
    for i, v in ipairs(list) do
        if math.abs(v - current) < 0.001 then return list[i % #list + 1] end
    end
    return list[1]
end

local function snapText()
    local g = cvarNum(GRID, 0)
    return g > 0 and ("Snap " .. g .. " yd") or "Snap off"
end
local function angleText() return "Turn " .. cvarNum(ANGLE, 15) .. " deg" end

local function bar(parent, text, w, onClick, ...)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(24)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end

local function panel(parent, w, h, border)
    local f = CreateFrame("Frame", nil, parent)
    f:SetWidth(w); f:SetHeight(h)
    f:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    f:SetBackdropColor(0.06, 0.07, 0.09, 0.88)
    f:SetBackdropBorderColor(unpack(border or { 0.36, 0.40, 0.45, 1 }))
    return f
end

-- The Builder window follows the HUD: on the world frame while editing (the UI is hidden), back on UIParent after.
local function moveBuilder(toWorld, show)
    local B = W.Builder
    local win = B and B.Window and B.Window()
    if not win then
        if toWorld and show and W.ToggleBuilder then W.ToggleBuilder(); win = B and B.Window and B.Window() end
        if not win then return end
    end
    local parent = toWorld and WorldFrame or UIParent
    if win:GetParent() ~= parent then
        win:SetParent(parent)
        if toWorld and UIParent.GetEffectiveScale and WorldFrame.GetEffectiveScale then
            win:SetScale(UIParent:GetEffectiveScale() / math.max(0.01, WorldFrame:GetEffectiveScale()))
        else
            win:SetScale(1)
        end
        win:SetFrameStrata("DIALOG")
    end
    if toWorld then
        win:ClearAllPoints()
        win:SetPoint("RIGHT", WorldFrame, "RIGHT", -24, 0)
        if show then win:Show() end
    end
end

local KEYS = {
    "Click a prop: select it",
    "Props, pick one, Spawn: then click the ground to place it",
    "G: carry the selection. Mouse moves it, wheel lifts it,",
    "     Q / E or Shift+wheel turn it, click or G drops it, Backspace puts it back",
    "V: duplicate     Delete: remove     Ctrl+Z: undo",
    "Snap: grid for placing and carrying     Turn: the angle step",
    "WASD fly, Space / C up and down, Ctrl faster, hold right mouse to look",
    "F7 or Done: back to your character",
}

local function build()
    if hud or not WorldFrame then return end
    hud = CreateFrame("Frame", "LeylineEditModeHUD", WorldFrame)
    hud:SetAllPoints(WorldFrame)
    hud:SetFrameStrata("HIGH")
    local scale = (UIParent.GetEffectiveScale and WorldFrame.GetEffectiveScale)
        and UIParent:GetEffectiveScale() / math.max(0.01, WorldFrame:GetEffectiveScale()) or 1

    -- banner
    local banner = panel(hud, 780, 58, { 0.89, 0.72, 0.36, 1 })
    banner:SetScale(scale)
    banner:SetPoint("TOP", hud, "TOP", 0, -10)
    local title = banner:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -9)
    title:SetText("EDIT MODE")
    local help = banner:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    help:SetPoint("TOP", title, "BOTTOM", 0, -4)
    help:SetText("Click select - G carry - V duplicate - Del remove - Ctrl+Z undo - WASD fly - right mouse look - F7 back")
    hud.note = banner:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    hud.note:SetPoint("TOP", banner, "BOTTOM", 0, -6)
    hud.note:SetText(E.note or "Click a prop to select it, G to carry it. Props to place new ones.")

    -- selection card
    local card = panel(hud, 280, 70)
    card:SetScale(scale)
    card:SetPoint("TOPLEFT", hud, "TOPLEFT", 16, -16)
    local cardTitle = card:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    cardTitle:SetPoint("TOPLEFT", 12, -10)
    cardTitle:SetText("Selection")
    hud.sel = card:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    hud.sel:SetPoint("TOPLEFT", 12, -28)
    hud.sel:SetWidth(256); hud.sel:SetJustifyH("LEFT")
    hud.info = card:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    hud.info:SetPoint("TOPLEFT", 12, -48)
    hud.info:SetWidth(256); hud.info:SetJustifyH("LEFT")

    -- tool bar
    local tools = panel(hud, 840, 40)
    tools:SetScale(scale)
    tools:SetPoint("BOTTOM", hud, "BOTTOM", 0, 18)
    local x = 10
    local function add(text, w, fn) local b = bar(tools, text, w, fn, "LEFT", x, 0); x = x + w + 4; return b end
    add("Props", 74, function() moveBuilder(true, true) end)
    add("Duplicate", 90, function() E.Cmd("dup") end)
    add("Undo", 70, function() E.Cmd("undo") end)
    add("Delete", 76, function() E.Cmd("delete") end)
    hud.snap = add(snapText(), 110, function(self)
        local g = cycle(GRIDS, cvarNum(GRID, 0))
        if SetCVar then pcall(SetCVar, GRID, tostring(g)) end
        self:SetText(snapText())
        E.Note(g > 0 and ("Placing and carrying snap to a " .. g .. " yard grid.") or "Snap off: props go exactly where you point.")
    end)
    hud.angle = add(angleText(), 104, function(self)
        local a = cycle(ANGLES, cvarNum(ANGLE, 15))
        if SetCVar then pcall(SetCVar, ANGLE, tostring(a)) end
        self:SetText(angleText())
        E.Note("Q / E turn by " .. a .. " degrees.")
    end)
    add("Save build", 96, function() moveBuilder(true, true) E.Note("Type a name in the Builder's Build box and press Save.") end)
    add("Keys", 64, function() if hud.keys:IsShown() then hud.keys:Hide() else hud.keys:Show() end end)
    bar(tools, "Done (F7)", 96, function() E.Set(false) end, "RIGHT", -10, 0)

    -- keys card
    hud.keys = panel(hud, 520, 22 + #KEYS * 16)
    hud.keys:SetScale(scale)
    hud.keys:SetPoint("BOTTOM", tools, "TOP", 0, 8)
    for i, line in ipairs(KEYS) do
        local fs = hud.keys:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        fs:SetPoint("TOPLEFT", 14, -10 - (i - 1) * 16)
        fs:SetJustifyH("LEFT")
        fs:SetText(line)
    end
    hud.keys:Hide()

    hud:Hide()
end

local function refreshCard()
    if not hud or not hud.sel then return end
    local B = builder()
    local s = (B and B.state) or {}
    hud.sel:SetText(s.selName and s.selName ~= "" and s.selName or "Nothing selected")
    local parts = {}
    if s.mine then parts[#parts + 1] = "Your props " .. s.mine end
    parts[#parts + 1] = (s.area and s.area ~= "-") and s.area or "Not in a build area"
    hud.info:SetText(table.concat(parts, "  -  "))
end

local function apply(nowOn)
    build()
    if not hud then return end
    if nowOn then
        if UIParent:IsShown() then E.hidUI = true; UIParent:Hide() end
        hud.snap:SetText(snapText()); hud.angle:SetText(angleText())
        hud:Show()
        moveBuilder(true, true)
        local B = builder()
        if B and B.RequestCatalog and (not B.catalog or #B.catalog == 0) then B.RequestCatalog() end
        refreshCard()
    else
        hud:Hide()
        E.placing = nil
        moveBuilder(false)
        if E.hidUI then E.hidUI = nil; UIParent:Show() end
    end
end

-- The watcher lives on the world frame, so it keeps running while UIParent is hidden; it also shows the
-- realm's Builder answers (normally in chat, which is hidden while editing) on the note line.
local watcher = CreateFrame("Frame", nil, WorldFrame or UIParent)
local since = 0
watcher:SetScript("OnUpdate", function(_, elapsed)
    local nowOn = on() and true or false
    if nowOn ~= wasOn then
        wasOn = nowOn
        apply(nowOn)
    end
    since = since + (elapsed or 0)
    if nowOn and since > 0.5 then since = 0; refreshCard() end
end)
watcher:RegisterEvent("CHAT_MSG_SYSTEM")
watcher:SetScript("OnEvent", function(_, _, msg)
    if not wasOn or type(msg) ~= "string" or not msg:find(TAG_PATTERN) then return end
    local text = msg:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub(TAG_PATTERN .. "%s*", "")
    E.Note(text)
end)

SLASH_LEYLINEEDIT1 = "/edit"
SlashCmdList["LEYLINEEDIT"] = function() E.Toggle() end

W.EditMode = E
