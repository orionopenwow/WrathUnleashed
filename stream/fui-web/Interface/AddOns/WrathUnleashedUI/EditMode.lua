-- EditMode (3.3.5a API): Leyline's edit mode, the building view. F7, or "Edit mode" in the Builder, steps out
-- of your character into a free-flying camera (the browser client does the camera: CVar leylineEditMode).
-- While it is on, the normal UI is hidden and this addon shows a slim edit HUD instead:
--   * a banner with the controls (WASD fly, Space / C up and down, Ctrl faster, hold the right button to look);
--   * a toolbar: Props (the Builder's catalog, to spawn), Near, Undo, Delete, and Done (back to your character).
-- Your character stays where it stood; the realm checks every change, exactly as for the .build commands.
--
-- Tools (the browser client sends the clicks and keys here):
--   click a prop          selects it (the realm says if it isn't yours)
--   Props > pick > Spawn  then click the ground: the prop goes exactly there
--   G                     carry the selected prop on the cursor; Q / E turn it; click or G drops it;
--                         Backspace puts it back. A drop is sent as ".build placeat x y z turn".

local W = WrathUnleashedUI
local CVAR = "leylineEditMode"

local hud, wasOn
local E = {}

local function on() return GetCVar and GetCVar(CVAR) == "1" end

function E.Set(want)
    if SetCVar then pcall(SetCVar, CVAR, want and "1" or "0") end
end

function E.Toggle() E.Set(not on()) end
function E.IsOn() return on() and true or false end

local function builder() return W.Builder end
local function cmd(text) local B = builder(); if B and B.Command then return B.Command(text) end end

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

-- The client: a click in the world, with the ground point under the cursor (WoW coordinates) and the
-- clicked object's id, either may be nil.
function E.Clicked(x, y, z, objectId)
    if E.placing and x then
        local p = E.placing
        E.placing = nil
        cmd(string.format("spawnat %d %.2f %.2f %.2f", p.id, x, y, z))
        E.Note(p.name .. " placed. Pick another in Props, or click a prop to select it.")
        return
    end
    if objectId then
        cmd("pick " .. math.floor(objectId))
        E.Note("Selected. G to carry it, Delete in the bar to remove it.")
    end
end

-- The client: the carried prop was dropped at x, y, z and turned by turn degrees.
function E.Drop(x, y, z, turn)
    cmd(string.format("placeat %.2f %.2f %.2f %.0f", x, y, z, turn or 0))
    E.Note("Dropped. G to carry it again.")
end

local function bar(parent, text, w, onClick, ...)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(24)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end

-- The Builder window follows the HUD: on the world frame while editing (the UI is hidden), back on UIParent after.
local function moveBuilder(toWorld)
    local B = W.Builder
    local win = B and B.Window and B.Window()
    if not win then
        if toWorld and W.ToggleBuilder then W.ToggleBuilder(); win = B and B.Window and B.Window() end
        if not win then return end
    end
    local parent = toWorld and WorldFrame or UIParent
    if win:GetParent() ~= parent then
        win:SetParent(parent)
        if toWorld and UIParent.GetEffectiveScale and WorldFrame.GetEffectiveScale then
            local s = UIParent:GetEffectiveScale() / math.max(0.01, WorldFrame:GetEffectiveScale())
            win:SetScale(s)
        else
            win:SetScale(1)
        end
        win:SetFrameStrata("DIALOG")
    end
    if toWorld then
        win:ClearAllPoints()
        win:SetPoint("RIGHT", WorldFrame, "RIGHT", -24, 0)
        win:Show()
    end
end

local function build()
    if hud or not WorldFrame then return end
    hud = CreateFrame("Frame", "LeylineEditModeHUD", WorldFrame)
    hud:SetAllPoints(WorldFrame)
    hud:SetFrameStrata("HIGH")
    local scale = (UIParent.GetEffectiveScale and WorldFrame.GetEffectiveScale)
        and UIParent:GetEffectiveScale() / math.max(0.01, WorldFrame:GetEffectiveScale()) or 1

    local banner = CreateFrame("Frame", nil, hud)
    banner:SetScale(scale)
    banner:SetWidth(760); banner:SetHeight(58)
    banner:SetPoint("TOP", hud, "TOP", 0, -10)
    banner:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    banner:SetBackdropColor(0.06, 0.07, 0.09, 0.88)
    banner:SetBackdropBorderColor(0.89, 0.72, 0.36, 1)
    local title = banner:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
    title:SetPoint("TOP", 0, -9)
    title:SetText("EDIT MODE")
    local help = banner:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    help:SetPoint("TOP", title, "BOTTOM", 0, -4)
    help:SetText("WASD fly - Space / C up, down - Ctrl faster - hold right mouse to look - click select - G carry - F7 back")

    hud.note = banner:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    hud.note:SetPoint("TOP", banner, "BOTTOM", 0, -6)
    hud.note:SetText(E.note or "Click a prop to select it, G to carry it. Props to place new ones.")

    local tools = CreateFrame("Frame", nil, hud)
    tools:SetScale(scale)
    tools:SetWidth(560); tools:SetHeight(40)
    tools:SetPoint("BOTTOM", hud, "BOTTOM", 0, 18)
    tools:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    tools:SetBackdropColor(0.06, 0.07, 0.09, 0.88)
    tools:SetBackdropBorderColor(0.36, 0.40, 0.45, 1)
    local B = function() return W.Builder end
    bar(tools, "Props", 90, function() moveBuilder(true) end, "LEFT", 10, 0)
    bar(tools, "Near", 80, function() if B() then B().Command("near") end end, "LEFT", 104, 0)
    bar(tools, "Undo", 80, function() if B() then B().Command("undo") end end, "LEFT", 188, 0)
    bar(tools, "Delete", 90, function() if B() then B().Command("delete") end end, "LEFT", 272, 0)
    bar(tools, "Done (F7)", 110, function() E.Set(false) end, "RIGHT", -10, 0)
    hud:Hide()
end

local function apply(nowOn)
    build()
    if not hud then return end
    if nowOn then
        if UIParent:IsShown() then E.hidUI = true; UIParent:Hide() end
        hud:Show()
        moveBuilder(true)
    else
        hud:Hide()
        E.placing = nil
        moveBuilder(false)
        if E.hidUI then E.hidUI = nil; UIParent:Show() end
    end
end

-- The watcher lives on the world frame, so it keeps running while UIParent is hidden.
local watcher = CreateFrame("Frame", nil, WorldFrame or UIParent)
watcher:SetScript("OnUpdate", function()
    local nowOn = on() and true or false
    if nowOn ~= wasOn then
        wasOn = nowOn
        apply(nowOn)
    end
end)

SLASH_LEYLINEEDIT1 = "/edit"
SlashCmdList["LEYLINEEDIT"] = function() E.Toggle() end

W.EditMode = E
