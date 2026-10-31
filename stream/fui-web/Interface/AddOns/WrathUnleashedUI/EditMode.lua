-- EditMode (3.3.5a API): Leyline's edit mode, the building view. F7, /edit or "Edit mode" in the Builder steps
-- out of your character into a free-flying camera (the browser client does the camera: CVar leylineEditMode).
-- While it is on, the normal UI is hidden and this addon shows the edit HUD instead:
--   * a banner with the controls, and a line under it saying what the tool is doing (and what the realm answered);
--   * a selection card: the selected prop (or how many), your props and build points, the plot or area;
--   * a tool bar: Props, Duplicate, Undo, Delete, Snap (grid), Turn (angle step), Keys, Done;
--   * a second bar: Spawn menu (Q), Select mine, Box select, Copy, Paste, Clear, Properties;
--   * a third bar: Group, Ungroup, Put away (into storage), Storage, Floor, Redo's count, and in a Den the Den button;
--   * in a Den (the realm's ov_den.lua), the Den panel: Invite a friend (the link to copy, the owner only), who
--     builds (Can build / View only), the whole Den as a layout (Save, Load, Load replacing) and the room's look.
--     /den opens it outside edit mode too.
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
--   V                  duplicate the selection          Delete  remove it          Ctrl+Z  undo   Ctrl+Y  redo
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
--   E.Cmd("redo")                        Ctrl+Y (or Ctrl+Shift+Z): redo, as the Redo button (also "store", "group",
--                                        "ungroup", "floor" for the client's own keys, if it binds any)

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

-- On a player's own game (no browser client: no edit-mode camera, no LeylineEdit), F7 and /edit open the Builder
-- window and the properties panel instead: every tool is there, at your character's position and by exact numbers.
function E.Desktop()
    if LeylineEdit or not GetCVar then return false end
    local ok, v = pcall(GetCVar, CVAR)
    return ok and v == nil
end

function E.Toggle()
    if E.Desktop() then
        local B = W.Builder
        if W.ToggleBuilder then W.ToggleBuilder() end
        if B and B.ShowProps then B.ShowProps(true) end
        if DEFAULT_CHAT_FRAME then
            DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Builder]|r The free building camera is in the Leyline browser client. Here the Builder "
                .. "window and the Properties panel do everything: exact numbers, nudges, Every object and Models.")
        end
        return
    end
    E.Set(not on())
end
function E.IsOn() return on() and true or false end

local function builder() return W.Builder end
local function cmd(text) local B = builder(); if B and B.Command then return B.Command(text) end end

-- From the client's hotkeys (V, Delete, Ctrl+Z) and the tool bar.
local ALLOWED = { dup = true, delete = true, undo = true, near = true, copy = true, selall = true, selclear = true,
    redo = true, store = true, group = true, ungroup = true, floor = true, lock = true, unlock = true, hide = true,
    measure = true, stack = true }
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
function E.StartStack() pend("stack", nil, "Stack: click the prop the selection goes on top of.") end
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

-- The client: a click in the world, with the ground point under the cursor (game coordinates, already on the
-- grid when Snap is on) and the clicked object's id; either may be nil.
function E.Clicked(x, y, z, objectId, shift)
    local p = E.pending
    if p and p.kind == "stack" then
        if not objectId then E.Note("Click a prop: the selection goes on top of it."); return end
        pend(nil)
        cmd("stackon obj " .. math.floor(objectId))
        E.Note("Stacked. Ctrl+Z takes it back.")
        return
    end
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
    if W.Style then W.Style.Backdrop(f, W.Style.C.bg2) else f:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } }) end
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
    "V: duplicate     Delete: remove     Ctrl+Z: undo     Ctrl+Y: redo",
    "Group: a click on one selects them all.  Put away: into your storage.  Floor: down onto it",
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
    local tools = panel(hud, 900, 40)
    tools:SetScale(scale)
    tools:SetPoint("BOTTOM", hud, "BOTTOM", 0, 18)
    local x = 10
    local function add(text, w, fn) local b = bar(tools, text, w, fn, "LEFT", x, 0); x = x + w + 4; return b end
    add("Props", 74, function() moveBuilder(true, true) end)
    add("Duplicate", 90, function() E.Cmd("dup") end)
    add("Undo", 64, function() E.Cmd("undo") end)
    hud.redo = add("Redo", 64, function() E.Cmd("redo") end)
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
    local tools2 = panel(hud, 900, 40)
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

    -- third bar: groups, storage, the floor, the Den
    local tools3 = panel(hud, 900, 40)
    tools3:SetScale(scale)
    tools3:SetPoint("BOTTOM", tools2, "TOP", 0, 4)
    x = 10
    local function add3(text, w, fn) local b = bar(tools3, text, w, fn, "LEFT", x, 0); x = x + w + 4; return b end
    add3("Group", 70, function() E.Cmd("group") end)
    add3("Ungroup", 80, function() E.Cmd("ungroup") end)
    add3("Put away", 84, function() E.Cmd("store") end)
    add3("Storage", 80, function()
        local B = builder()
        if not B then return end
        B.menuTab, B.menuOffset = "storage", 0
        E.menuPinned = true
        B.ShowMenu(true)
        B.MenuRefresh()
    end)
    add3("Floor", 64, function() E.Cmd("floor") end)
    hud.den = bar(tools3, "Den", 80, function() E.ToggleDen() end, "RIGHT", -10, 0)
    hud.den:Hide()

    -- keys card
    hud.keys = panel(hud, 560, 22 + #KEYS * 16)
    hud.keys:SetScale(scale)
    hud.keys:SetPoint("BOTTOM", tools3, "TOP", 0, 8)
    for i, line in ipairs(KEYS) do
        local fs = hud.keys:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
        fs:SetPoint("TOPLEFT", 14, -10 - (i - 1) * 16)
        fs:SetJustifyH("LEFT")
        fs:SetText(line)
    end
    hud.keys:Hide()

    hud:Hide()
end

local DEN_ROLE = { owner = "your Den", builder = "you build here", visitor = "visiting" }

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
    local meter = B and B.Meter and (B.Meter()) or ""
    if s.den then
        -- a Den: your role and its two decor budgets (the room and the yard)
        meter = string.format("Room %s  Yard %s  (%s)", s.room or "?", s.yard or "?", DEN_ROLE[s.den] or s.den)
    end
    hud.budget:SetText(meter)
    if hud.redo then hud.redo:SetText((tonumber(s.redo or "") or 0) > 0 and ("Redo (" .. s.redo .. ")") or "Redo") end
    if hud.den then if s.den then hud.den:Show() else hud.den:Hide() end end
    if s.den == "visitor" and not E.toldVisitor then
        E.toldVisitor = true
        E.Note("You're visiting this Den: look around as you like. Its owner can make you a builder.")
    end
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
        -- Shift + wheel turns a carried prop; where the client also gave it to the bar's page keys, the main bar
        -- came back on another page (WrathUnleashedUI.lua, PAGE_KEYS)
        if W.MainBarHome then W.MainBarHome() end
    end
end

-- ---------------------------------------------------------------- the Den (ov_den.lua, mod "wuden")
local DEN_MOD = "wuden"
E.denInfo = {}

function E.DenCmd(text)
    text = tostring(text or ""):gsub("[^%w%s%-_]", ""):sub(1, 60)
    if not SendAddonMessage or not UnitName then return false end
    pcall(SendAddonMessage, "OVMOD", DEN_MOD .. "\t" .. "cmd" .. "\t1/1\t" .. text, "WHISPER", UnitName("player"))
    return true
end

local den   -- the Den panel

local function nameIn(box)
    local t = (box and box:GetText() or ""):gsub("%s+", "")
    if t == "" or not t:match("^[%w_%-]+$") or #t > 24 then return nil end
    return t
end

local function denRefresh()
    if not den then return end
    local d = E.denInfo
    local owner = d.role == "owner"
    den.role:SetText(d.role == "owner" and "Your Den. Friends join with your invite link."
        or d.role == "builder" and "You build in this Den." or "You're visiting this Den.")
    den.builders:SetText("Builders: " .. ((d.builders and d.builders ~= "-") and d.builders:gsub(" ", ", ") or "only the owner"))
    den.look:SetText("Room: " .. (d.theme or "white"))
    for _, b in ipairs(den.ownerOnly) do if owner then b:Enable() else b:Disable() end end
end

local function edit(parent, w, ...)
    local e = (W.Style and W.Style.Input and W.Style.Input(parent)) or CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    e:SetWidth(w); e:SetHeight(20)
    e:SetPoint(...)
    e:SetAutoFocus(false)
    e:SetMaxLetters(24)
    e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return e
end

local function text(parent, t, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(t)
    return fs
end

local function buildDen()
    den = panel(UIParent, 420, 250, { 0.78, 0.64, 1, 1 })
    den:SetPoint("LEFT", UIParent, "LEFT", 24, 0)
    den:SetFrameStrata("DIALOG")
    den:EnableMouse(true)
    local title = den:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    title:SetPoint("TOPLEFT", 14, -12)
    title:SetText("Den")
    den.role = text(den, "", "TOPLEFT", 14, -32)
    den.ownerOnly = {}
    local function own(b) den.ownerOnly[#den.ownerOnly + 1] = b; return b end
    -- Invite a friend: the realm sends the link (the owner only); it lands in a box to copy (Ctrl+C)
    own(bar(den, "Invite a friend", 130, function() E.DenCmd("invite") end, "TOPLEFT", 12, -52))
    den.link = CreateFrame("EditBox", nil, den, "InputBoxTemplate")
    den.link:SetWidth(250); den.link:SetHeight(20)
    den.link:SetPoint("TOPLEFT", 152, -54)
    den.link:SetAutoFocus(false)
    den.link:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    den.link:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
    den.link:SetScript("OnTextChanged", function(self) if E.inviteLink and self:GetText() ~= E.inviteLink then self:SetText(E.inviteLink) end end)
    -- builders
    den.builders = text(den, "", "TOPLEFT", 14, -84)
    den.name = edit(den, 120, "TOPLEFT", 16, -100)
    own(bar(den, "Can build", 90, function() local n = nameIn(den.name); if n then E.DenCmd("allow " .. n .. " build") end end, "TOPLEFT", 142, -98))
    own(bar(den, "View only", 90, function() local n = nameIn(den.name); if n then E.DenCmd("allow " .. n .. " view") end end, "TOPLEFT", 236, -98))
    -- the whole Den as a layout
    text(den, "Layout (the whole Den):", "TOPLEFT", 14, -132)
    den.layout = edit(den, 120, "TOPLEFT", 16, -148)
    bar(den, "Save", 60, function() local n = nameIn(den.layout); if n then E.DenCmd("save " .. n) end end, "TOPLEFT", 142, -146)
    bar(den, "Load", 60, function() local n = nameIn(den.layout); if n then E.DenCmd("load " .. n) end end, "TOPLEFT", 206, -146)
    own(bar(den, "Load, replacing", 120, function() local n = nameIn(den.layout); if n then E.DenCmd("load " .. n .. " replace") end end,
        "TOPLEFT", 270, -146))
    -- the room's look
    den.look = text(den, "", "TOPLEFT", 14, -180)
    local lx = 14
    for _, look in ipairs({ "white", "stone", "wood" }) do
        own(bar(den, look:sub(1, 1):upper() .. look:sub(2), 70, function() E.DenCmd("room " .. look) end, "TOPLEFT", lx, -196))
        lx = lx + 74
    end
    bar(den, "Budget", 70, function() E.DenCmd("budget") end, "TOPLEFT", lx + 20, -196)
    bar(den, "Back to the room", 130, function() E.DenCmd("home") end, "BOTTOMLEFT", 12, 10)
    bar(den, "Builder", 80, function() if W.ToggleBuilder then W.ToggleBuilder() end end, "BOTTOMLEFT", 146, 10)
    bar(den, "Close", 70, function() den:Hide() end, "BOTTOMRIGHT", -12, 10)
    if UISpecialFrames then tinsert(UISpecialFrames, "LeylineDenPanel") end
    _G.LeylineDenPanel = den
    den:Hide()
end

function E.ShowDen(show)
    if not den then buildDen() end
    local B = builder()
    if B and B.Dock then B.Dock(den, on() and true or false) end
    if show then
        den:ClearAllPoints()
        den:SetPoint("LEFT", (on() and WorldFrame) or UIParent, "LEFT", 24, 0)
        denRefresh()
        den:Show()
        if SendAddonMessage and UnitName then   -- asks the realm for the Den's info
            pcall(SendAddonMessage, "OVMOD", DEN_MOD .. "\tinfo\t1/1\t", "WHISPER", UnitName("player"))
        end
    else
        den:Hide()
    end
end
function E.ToggleDen() E.ShowDen(not (den and den:IsShown())) end
function E.DenPanel() return den end

-- The Den's answers: info (role, look, builders) and the invite link, whispered to ourselves by the realm.
function E.OnDenMessage(prefix, msg, channel, sender)
    if prefix ~= "OVMOD" or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local mod, name, data = msg:match("^([^\t]+)\t([^\t]+)\t1/1\t(.*)$")
    if mod ~= DEN_MOD then return end
    if name == "info" then
        local d = {}
        for k, v in data:gmatch("(%a+)=([^;]*)") do d[k] = v:gsub("|", "") end
        E.denInfo = d
        denRefresh()
    elseif name == "invite" and data:match("^https://[%w%.%-]+/join/[a-z2-7]+#[A-Z2-9]+$") then
        E.inviteLink = data
        if not den then buildDen() end
        den.link:SetText(data)
        den.link:SetFocus()
        den.link:HighlightText()
        E.Note("Your invite link is in the Den panel: Ctrl+C copies it. Give it only to friends.")
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
SLASH_LEYLINEDEN1 = "/den"
SlashCmdList["LEYLINEDEN"] = function() E.ToggleDen() end

local denListener = CreateFrame("Frame")
denListener:RegisterEvent("CHAT_MSG_ADDON")
denListener:RegisterEvent("PLAYER_ENTERING_WORLD")
-- On entering the world the addon asks for the Den's info: a Den hears the addon is here (ov_den.lua tells a
-- game without it where to get it), and the panel knows your role. Elsewhere nobody answers.
function E.Hello()
    if E.helloSent or not SendAddonMessage or not UnitName then return end
    E.helloSent = true
    pcall(SendAddonMessage, "OVMOD", DEN_MOD .. "\tinfo\t1/1\t", "WHISPER", UnitName("player"))
end
denListener:SetScript("OnEvent", function(_, event, prefix, msg, channel, sender)
    if event == "PLAYER_ENTERING_WORLD" then return E.Hello() end
    E.OnDenMessage(prefix, msg, channel, sender)
end)

W.EditMode = E
