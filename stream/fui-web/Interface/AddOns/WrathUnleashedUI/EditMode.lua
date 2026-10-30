-- EditMode (3.3.5a API): Leyline's edit mode, the building view. F7, /edit or "Edit mode" in the Builder steps
-- out of your character into a free-flying camera (the browser client does the camera: CVar leylineEditMode).
-- While it is on, the normal UI is hidden and this addon shows the edit HUD instead:
--   * a banner with the controls, and a line under it saying what the tool is doing (and what the realm answered);
--   * a selection card: the selected prop (or how many), your props and build points, the plot or area;
--   * a tool bar: Props, Duplicate, Undo, Delete, Snap (grid), Turn (angle step), Keys, Done;
--   * a second bar: Spawn menu (Q), Select mine, Box select, Copy, Paste, Clear, Properties.
-- Your character stays where it stood; the realm checks every change, exactly as for the .build commands.
--
-- Keys (the browser client reads them and calls back here):
--   click a prop       select it (the realm says if it isn't yours); Shift-click adds it to the selection
--                      (or takes it out); move, turn, delete, duplicate and carry then work on the group
--   Props > Spawn      then click the ground: the prop goes exactly there (on the grid when Snap is on)
--   hold Q             the spawn menu (when nothing is carried); pick a prop, then click the ground
--   Box select         click two corners on the ground: every prop you may select inside the box
--   Copy / Paste       Paste, then click the ground: the copied props go there, around the point
--   G                  carry the selection on the cursor; wheel lifts it, Q / E or Shift+wheel turn it,
--                      a click or G drops it (".build placeat x y z turn"), Backspace puts it back
--   V                  duplicate the selection          Delete  remove it          Ctrl+Z  undo
--   the handles        drag an arrow (move along it) or the ring (turn): the prop moves on your screen while
--                      the button is held, and one change goes to the realm when you let go
--   WASD / Space / C   fly; Ctrl faster; hold the right mouse button to look; F7 back to your character
--
-- Hooks the browser client calls (all optional beyond Clicked and Drop):
--   E.Clicked(x, y, z, objectId, shift)  a click in the world (shift: Shift was held; else IsShiftKeyDown())
--   E.Drop(x, y, z, turn)                the carried selection was dropped
--   E.GizmoCommit(objectId, dx, dy, dz, turn, x, y, z)   a handle was let go after a drag (client 20261026a):
--                                        one prop -> ".build move <id> x y z yaw [pitch roll]" (its tilt kept);
--                                        a group -> ".build placeat", the whole selection by the same move
--   E.GizmoStart(kind)                   a handle drag began: "x", "y", "z" or "ring"
--   E.SpawnMenu(down)                    Q pressed (true) or released (false) while nothing is carried
--   E.BoxSelect(x1, y1, x2, y2, add)     a drag box's two ground corners, if the client draws one

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
local ALLOWED = { dup = true, delete = true, undo = true, near = true, copy = true, selall = true, selclear = true }
function E.Cmd(name)
    if not ALLOWED[name] then return end
    cmd(name)
end

-- A short line under the banner: what the tool is doing now.
function E.Note(text)
    E.note = text or ""
    if hud and hud.note then hud.note:SetText(E.note) end
end

-- What the next ground click does: place a prop, paste the copy, paste a prefab, or a box corner.
local function pend(kind, data, note)
    E.placing = (kind == "prop") and data or nil
    E.pending = kind and { kind = kind, data = data } or nil
    if note then E.Note(note) end
end

-- From the Builder's Spawn button (or the spawn menu) while editing: the next ground click places this prop.
function E.StartPlacing(prop)
    if not prop then return end
    pend("prop", prop, "Click the ground where the " .. prop.name .. " goes.")
end

function E.StartPasting() pend("paste", nil, "Click the ground where the copy goes.") end
function E.StartPrefab(name) if name then pend("prefab", name, "Click the ground where '" .. name .. "' goes.") end end
function E.StartBox() pend("box", nil, "Box select: click one corner on the ground, then the other.") end
function E.Cancel() pend(nil) end

local function shiftDown(flag)
    if flag ~= nil then return flag and true or false end
    return (IsShiftKeyDown and IsShiftKeyDown()) and true or false
end

-- The client, if it draws a drag box: its two corners on the ground.
function E.BoxSelect(x1, y1, x2, y2, add)
    if not (x1 and y1 and x2 and y2) then return end
    cmd(string.format("selbox %.2f %.2f %.2f %.2f%s", x1, y1, x2, y2, add and " add" or ""))
    E.Note("Box selected. G carries the group, Q / E turn it, Delete removes it.")
end

-- The client: Q held (true) or let go (false) while nothing is carried.
function E.SpawnMenu(down)
    local B = builder()
    if not (B and B.ShowMenu) then return end
    if down then B.ShowMenu(true) elseif not E.menuPinned then B.ShowMenu(false) end
end

-- The client: a click in the world, with the ground point under the cursor (WoW coordinates, already on the
-- grid when Snap is on) and the clicked object's id; either may be nil.
function E.Clicked(x, y, z, objectId, shift)
    local p = E.pending
    if p and x then
        if p.kind == "prop" then
            pend(nil)
            cmd(string.format("spawnat %d %.2f %.2f %.2f", p.data.id, x, y, z))
            E.Note(p.data.name .. " placed. G to carry it, V to duplicate it, or hold Q for another.")
        elseif p.kind == "paste" then
            pend(nil)
            cmd(string.format("pasteat %.2f %.2f %.2f", x, y, z))
            E.Note("Pasted. G carries the group, Ctrl+Z takes it back.")
        elseif p.kind == "prefab" then
            pend(nil)
            cmd(string.format("prefab pasteat %s %.2f %.2f %.2f", p.data, x, y, z))
            E.Note("Prefab pasted. G carries the group, Ctrl+Z takes it back.")
        elseif p.kind == "box" then
            if not p.data then
                p.data = { x = x, y = y }
                E.Note("Now click the other corner.")
            else
                pend(nil)
                E.BoxSelect(p.data.x, p.data.y, x, y, shiftDown(shift))
            end
        end
        return
    end
    if objectId then
        if shiftDown(shift) then
            cmd("pick " .. math.floor(objectId) .. " add")
            E.Note("Shift-click adds a prop, or takes it out. The group moves, turns and copies together.")
        else
            cmd("pick " .. math.floor(objectId))
            E.Note("Selected. G to carry it, V to duplicate, Delete to remove. Shift-click adds more.")
        end
    end
end

-- The client: the carried prop was dropped at x, y, z and turned by turn degrees.
function E.Drop(x, y, z, turn)
    cmd(string.format("placeat %.2f %.2f %.2f %.0f", x, y, z, turn or 0))
    E.Note("Dropped. G to carry it again.")
end

local GIZMO_NOTE = { x = "Moving along x", y = "Moving along y", z = "Moving up and down", ring = "Turning" }

-- The client: a handle drag began (the prop moves on this screen only until you let go).
function E.GizmoStart(kind)
    E.Note((GIZMO_NOTE[kind] or "Moving") .. ". Let go to place it; Esc puts it back.")
end

-- The client: a handle was let go. objectId is the dragged object's id (GUID counter); dx, dy, dz and turn are
-- the change, x, y, z where it is now. The preview happened on this client; this is the one change the realm gets.
function E.GizmoCommit(objectId, dx, dy, dz, turn, x, y, z)
    if not (x and y and z) then return end
    turn = tonumber(turn) or 0
    local B = builder()
    local s = (B and B.state) or {}
    local pid = B and B.PropForObject and B.PropForObject(objectId)
    if pid and (s.count or 1) <= 1 and s.selId == pid and s.p then
        -- one prop: exact place and rotation, its tilt kept
        B.MoveTo(pid, x, y, z, (s.p.yaw or s.p.turn or 0) + turn, s.p.pitch, s.p.roll)
        E.Note("Placed. Drag a handle again, or G to carry it.")
    elseif pid and s.p and pid ~= s.selId and math.abs(turn) < 0.05 and dx and dy and dz then
        -- a group dragged by another member: the same move for the last-picked prop, the rest keep their places
        cmd(string.format("placeat %.2f %.2f %.2f 0", s.p.x + dx, s.p.y + dy, s.p.z + dz))
        E.Note("Group placed.")
    else
        E.Drop(x, y, z, turn)
    end
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
    B.Dock(win, toWorld)
    if toWorld then
        win:ClearAllPoints()
        win:SetPoint("RIGHT", WorldFrame, "RIGHT", -24, 0)
        if show then win:Show() end
    end
end

local KEYS = {
    "Click a prop: select it.  Shift-click: add it to the selection (or take it out)",
    "Hold Q (or Spawn menu): pick a prop, then click the ground. Right-click a prop: favourite",
    "Box select: click two corners.  Select mine: all yours nearby.  Copy, then Paste and click",
    "Drag an arrow to move it along, the ring to turn it; it is placed when you let go",
    "G: carry the selection (the whole group). Mouse moves it, wheel lifts it,",
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
    help:SetText("Click select - Shift-click add - Q props - G carry - V duplicate - Del remove - Ctrl+Z undo - F7 back")
    hud.note = banner:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
    hud.note:SetPoint("TOP", banner, "BOTTOM", 0, -6)
    hud.note:SetText(E.note or "Click a prop to select it, G to carry it. Props to place new ones.")

    -- selection card
    local card = panel(hud, 300, 88)
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
    hud.info:SetWidth(276); hud.info:SetJustifyH("LEFT")
    hud.budget = card:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    hud.budget:SetPoint("TOPLEFT", 12, -66)
    hud.budget:SetWidth(276); hud.budget:SetJustifyH("LEFT")

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

    -- second bar: selection and the spawn menu
    local tools2 = panel(hud, 840, 40)
    tools2:SetScale(scale)
    tools2:SetPoint("BOTTOM", tools, "TOP", 0, 4)
    x = 10
    local function add2(text, w, fn) local b = bar(tools2, text, w, fn, "LEFT", x, 0); x = x + w + 4; return b end
    add2("Spawn menu (Q)", 120, function()
        local B = builder()
        if not B then return end
        E.menuPinned = not (B.Menu() and B.Menu():IsShown())
        B.ShowMenu(E.menuPinned)
    end)
    add2("Select mine", 96, function() E.Cmd("selall") end)
    add2("Box select", 92, function() E.StartBox() end)
    add2("Copy", 64, function() E.Cmd("copy") end)
    add2("Paste", 64, function() E.StartPasting() end)
    add2("Clear selection", 120, function() E.Cmd("selclear") end)
    add2("Properties", 96, function() local B = builder(); if B then B.ToggleProps() end end)
    add2("Save prefab", 100, function() moveBuilder(true, true) E.Note("Type a name in the Builder's Prefab box and press Save.") end)

    -- keys card
    hud.keys = panel(hud, 520, 22 + #KEYS * 16)
    hud.keys:SetScale(scale)
    hud.keys:SetPoint("BOTTOM", tools2, "TOP", 0, 8)
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
    if s.count and s.count > 1 then
        hud.sel:SetText(s.count .. " props selected")
    else
        hud.sel:SetText(s.selName and s.selName ~= "" and s.selName or "Nothing selected")
    end
    local p = s.plotInfo
    if p then
        hud.info:SetText(string.format("%s's plot: %d/%d props", p.owner, p.n, p.ncap))
    else
        hud.info:SetText((s.area and s.area ~= "-") and s.area or "Not in a build area")
    end
    hud.budget:SetText(B and B.Meter and (B.Meter()) or "")
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
        if B and B.Panel and B.Panel() then B.Dock(B.Panel(), true) end
        if B and B.RequestCatalog and (not B.catalog or #B.catalog == 0) then B.RequestCatalog() end
        refreshCard()
    else
        hud:Hide()
        pend(nil)
        E.menuPinned = nil
        moveBuilder(false)
        local B = builder()
        if B and B.ShowMenu then
            if B.Menu() then B.ShowMenu(false) end
            if B.Panel() then B.Dock(B.Panel(), false) end
        end
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
