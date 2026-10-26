-- Builder (3.3.5a API): the window for the realm's Builder (realm/custom/lua_scripts/ov_build.lua), in the
-- Mods & Workshop panel's look. Pick a prop from the catalog (search, categories), Spawn it where you stand,
-- nudge it (x, y, z), turn it 15 degrees at a time, Undo or Delete, and Save / Load / Share builds by name or
-- code. Also: a budget meter (props and build points), group tools (select mine, copy, paste), prefabs, your
-- plot, the spawn menu (hold Q in edit mode, /spawnmenu) and the properties panel (exact x, y, z, turn, size).
-- Opened by Esc > Mods & Workshop > Builder and by /builder.
--
-- Everything the buttons do is a ".build ..." command, sent over the realm's OVMOD addon channel (ov_modapi.lua),
-- whispered to yourself, mod "wubuild":
--   client -> server   wubuild \t cmd \t 1/1 \t <the text after .build>      e.g. "spawn 2413", "move z 0.5"
--                      wubuild \t catalog \t 1/1 \t                          send me the catalog
--   server -> client   wubuild \t catalog \t i/n \t id,key,category,name,points;...   (the allowlist)
--                      wubuild \t state \t i/n \t sel=..;mine=..;area=..;code=..;n=..;pos=..;pts=..;tier=..;plot=..;clip=..
--                      wubuild \t prefabs \t i/n \t id,name,code,count;...
-- The realm checks everything (role, area, plot, budget, rate) and answers in chat as for the dot commands. The
-- window only ever offers props from the realm's catalog. Without the realm script nothing is sent anywhere
-- else and the window says the Builder isn't on this realm.

local W = WrathUnleashedUI
local PREFIX, MOD = "OVMOD", "wubuild"
local WIN_W, WIN_H, ROW_H, ROWS = 520, 650, 20, 9
local ANSWER_WAIT = 6
local STEPS = { 0.25, 1, 3 }
local TURN = 15
local CATS = { "all", "seating", "tables", "barrels", "crates", "lights", "banners", "tents", "fires", "fences", "nature", "decor" }
local MENU_COLS, MENU_ROWS = 3, 12
local RECENT_MAX = 12

local win, menu, panel
local B = { catalog = {}, shown = {}, offset = 0, cat = 1, step = 2, search = "", state = {}, parts = {}, prefabs = {},
    menuTab = "all", menuSearch = "", menuOffset = 0, menuItems = {} }

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

local function editBox(parent, w, maxLetters, ...)
    local e = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    e:SetWidth(w); e:SetHeight(20)
    e:SetPoint(...)
    e:SetAutoFocus(false)
    if maxLetters then e:SetMaxLetters(maxLetters) end
    e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return e
end

local function now() return (GetTime and GetTime()) or 0 end
local function editing() return W.EditMode and W.EditMode.IsOn and W.EditMode.IsOn() end

local function setStatus(text)
    B.status = text or ""
    if win then win.status:SetText(B.status) end
    if menu then menu.status:SetText(B.status) end
    if panel then panel.status:SetText(B.status) end
end

-- favourites and recents, per character (WrathUnleashedUIChar is the addon's per-character saved table)
local function store()
    WrathUnleashedUIChar = WrathUnleashedUIChar or {}
    local c = WrathUnleashedUIChar
    c.builder = type(c.builder) == "table" and c.builder or {}
    c.builder.favs = type(c.builder.favs) == "table" and c.builder.favs or {}
    c.builder.recent = type(c.builder.recent) == "table" and c.builder.recent or {}
    return c.builder
end

-- ---------------------------------------------------------------- talking to the realm

local function send(name, data)
    if not SendAddonMessage or not UnitName then return false end
    pcall(SendAddonMessage, PREFIX, MOD .. "\t" .. name .. "\t1/1\t" .. (data or ""), "WHISPER", UnitName("player"))
    return true
end

-- Only letters, digits, -, _ , . and spaces reach the realm; the realm checks the rest.
function B.Command(text)
    text = tostring(text or ""):gsub("[^%w%s%.%-_]", ""):sub(1, 100)
    return send("cmd", text)
end

function B.RequestCatalog()
    B.askedAt, B.waiting = now(), true
    setStatus("Asking the realm for the props...")
    return send("catalog", "")
end

local function parseCatalog(data)
    local list = {}
    for item in data:gmatch("[^;]+") do
        local id, key, cat, name, cost = item:match("^(%d+),([%w]+),(%a+),(.-),(%d+)$")
        if not id then id, key, cat, name = item:match("^(%d+),([%w]+),(%a+),(.+)$") end
        if id and #list < 600 then
            list[#list + 1] = { id = tonumber(id), key = key, cat = cat, name = name:gsub("|", ""), cost = tonumber(cost) or 1 }
        end
    end
    return list
end

local function pair(s)
    local a, b = tostring(s or ""):match("^(%d+)/(%d+)$")
    return tonumber(a), tonumber(b)
end

local function parseState(data)
    local s = {}
    for k, v in data:gmatch("(%a+)=([^;]*)") do s[k] = v:gsub("|", "") end
    local id, entry, name = (s.sel or ""):match("^(%d+),(%d+),(.*)$")
    s.selName = name
    s.count = tonumber(s.n or "") or (name and 1 or 0)
    local x, y, z, t, sc = (s.pos or ""):match("^(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+),(%-?[%d%.]+),([%d%.]+)$")
    if x then s.p = { x = tonumber(x), y = tonumber(y), z = tonumber(z), turn = tonumber(t), scale = tonumber(sc) } end
    s.used, s.cap = pair(s.mine)
    s.ptsUsed, s.ptsCap = pair(s.pts)
    local pid, owner, role, pn, pc, pp, ppc = (s.plot or ""):match("^(%d+),(%w*),(%a+),(%d+)/(%d+),(%d+)/(%d+)$")
    if pid then
        s.plotInfo = { id = tonumber(pid), owner = owner, role = role, n = tonumber(pn), ncap = tonumber(pc),
            pts = tonumber(pp), ptsCap = tonumber(ppc) }
    end
    return s
end

local function stateText(s)
    local parts = {}
    if s.count and s.count > 1 then
        parts[#parts + 1] = "Selected: " .. s.count .. " props" .. (s.selName and (" (last: " .. s.selName .. ")") or "")
    else
        parts[#parts + 1] = s.selName and ("Selected: " .. s.selName) or "Nothing selected"
    end
    if s.mine then parts[#parts + 1] = "props " .. s.mine end
    if s.area and s.area ~= "-" then parts[#parts + 1] = s.area else parts[#parts + 1] = "not in a build area" end
    return table.concat(parts, "  |  ")
end

local ROLE_TEXT = { owner = "yours", builder = "you build here", visitor = "you visit: look and copy only",
    gm = "GM", none = "you can't build here" }

local function plotText(s)
    local p = s.plotInfo
    if not p then return "No plot here. Claim one to build with friends." end
    return string.format("%s's plot (%s): %d/%d props, %d/%d points", p.owner, ROLE_TEXT[p.role] or p.role,
        p.n, p.ncap, p.pts, p.ptsCap)
end

-- The meter: props and points against your limits; the fuller of the two fills the bar.
function B.Meter()
    local s = B.state
    local frac = 0
    if s.used and s.cap and s.cap > 0 then frac = math.max(frac, s.used / s.cap) end
    if s.ptsUsed and s.ptsCap and s.ptsCap > 0 then frac = math.max(frac, s.ptsUsed / s.ptsCap) end
    if frac > 1 then frac = 1 end
    local text = string.format("Props %s   Points %s", s.mine or "?", s.pts or "?")
    if s.tier and s.tier ~= "" then text = text .. "   (" .. s.tier .. ")" end
    return text, frac
end

local function refreshMeter()
    if not win then return end
    local text, frac = B.Meter()
    win.meter:SetText(text)
    win.bar:SetWidth(math.max(1, frac * 200))
    if frac >= 1 then win.bar:SetVertexColor(0.9, 0.2, 0.2)
    elseif frac >= 0.8 then win.bar:SetVertexColor(0.95, 0.75, 0.2)
    else win.bar:SetVertexColor(0.25, 0.8, 0.3) end
    B.meterFrac = frac
    win.plot:SetText(plotText(B.state))
end

-- Why a spawn of item can't happen now (your own limits; the realm checks the rest), or nil.
function B.Blocked(item)
    local s = B.state
    if s.used and s.cap and s.used >= s.cap then
        return string.format("You're at your limit of %d props. Delete some to place more.", s.cap)
    end
    if item and s.ptsUsed and s.ptsCap and s.ptsUsed + (item.cost or 1) > s.ptsCap then
        return string.format("Not enough build points: that needs %d, you have %d left. Delete something first.",
            item.cost or 1, math.max(0, s.ptsCap - s.ptsUsed))
    end
    return nil
end

local function dispatch(name, data)
    if name == "catalog" then
        B.catalog, B.waiting = parseCatalog(data), nil
        B.Filter()
        B.MenuRefresh()
        setStatus(#B.catalog .. " props. Pick one and Spawn it where you stand.")
    elseif name == "state" then
        B.waiting = nil
        B.state = parseState(data)
        -- the browser client (20261026a) carries the whole selection on screen while you drag or carry it
        if LeylineEdit then
            local ids = B.state.ids
            pcall(LeylineEdit, "group " .. ((ids and ids ~= "-") and ids or ""))
        end
        if win then
            win.sel:SetText(stateText(B.state))
            if B.state.code and B.state.code ~= "-" then win.code:SetText(B.state.code) end
            refreshMeter()
        end
        B.PropsFill()
    elseif name == "prefabs" then
        local list = {}
        for item in data:gmatch("[^;]+") do
            local id, pname, code, n = item:match("^(%d+),([%w_%-]+),([%w%-]+),(%d+)$")
            if id and #list < 60 then list[#list + 1] = { kind = "prefab", id = tonumber(id), name = pname, code = code ~= "-" and code or nil, count = tonumber(n) } end
        end
        B.prefabs = list
        B.MenuRefresh()
    end
end

function B.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local mod, name, i, n, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
    if mod ~= MOD then return end
    i, n = tonumber(i), tonumber(n)
    if n < 1 or n > 32 or i < 1 or i > n then return end
    if n == 1 then B.parts[name] = nil; return dispatch(name, data) end
    local buf = B.parts[name]
    if i == 1 or not buf or buf.n ~= n then buf = { n = n, got = 0 }; B.parts[name] = buf end
    if not buf[i] then buf[i] = data; buf.got = buf.got + 1 end
    if buf.got == n then
        B.parts[name] = nil
        dispatch(name, table.concat(buf, "", 1, n))
    end
end

-- ---------------------------------------------------------------- the catalog list

function B.Filter()
    local want, q = CATS[B.cat], B.search:lower()
    B.shown = {}
    for _, c in ipairs(B.catalog) do
        if (want == "all" or c.cat == want) and (q == "" or c.name:lower():find(q, 1, true) or c.key:find(q, 1, true)) then
            B.shown[#B.shown + 1] = c
        end
    end
    B.offset = 0
    if B.pick then
        local still = false
        for _, c in ipairs(B.shown) do if c == B.pick then still = true end end
        if not still then B.pick = nil end
    end
    B.Refresh()
end

function B.Refresh()
    if not win then return end
    local n = #B.shown
    if B.offset > math.max(0, n - ROWS) then B.offset = math.max(0, n - ROWS) end
    for i, row in ipairs(win.rows) do
        local c = B.shown[B.offset + i]
        row.item = c
        if c then
            row.name:SetText((c == B.pick and "|cff40ff40> |r" or "") .. c.name)
            row.cat:SetText(c.cat .. "  " .. (c.cost or 1) .. " pt")
            row:Show()
        else
            row:Hide()
        end
    end
    win.catBtn:SetText("Category: " .. CATS[B.cat])
    win.count:SetText(n > ROWS and string.format("%d-%d of %d", B.offset + 1, math.min(n, B.offset + ROWS), n) or "")
    win.spawn:SetText(B.pick and ("Spawn " .. B.pick.name) or "Spawn")
    if B.pick then win.spawn:Enable() else win.spawn:Disable() end
end

local function addRecent(id)
    local r = store().recent
    for i = #r, 1, -1 do if r[i] == id then table.remove(r, i) end end
    table.insert(r, 1, id)
    while #r > RECENT_MAX do table.remove(r) end
end

function B.Spawn()
    if not B.pick then setStatus("Pick a prop first."); return false end
    local why = B.Blocked(B.pick)
    if why then setStatus(why); return false end
    addRecent(B.pick.id)
    -- In edit mode the next click on the ground places it (EditMode.lua); otherwise at your feet.
    if editing() then
        W.EditMode.StartPlacing(B.pick)
        setStatus("Click the ground where it goes.")
        return true
    end
    return B.Command("spawn " .. B.pick.id)
end

function B.Move(axis, sign)
    return B.Command(string.format("move %s %s", axis, tostring(sign * STEPS[B.step])))
end

function B.Turn(sign) return B.Command("turn " .. (sign * TURN)) end

local function nameIn(box)
    local t = (box:GetText() or ""):gsub("%s+", "")
    if t == "" or not t:match("^[%w_%-]+$") or #t > 24 then return nil end
    return t
end
local function boxName() return nameIn(win.code) end

function B.Save()
    local n = boxName()
    if not n then setStatus("Type a name in the box (letters, digits, - and _)."); return false end
    return B.Command("save " .. n)
end

function B.Load()
    local n = boxName()
    if not n then setStatus("Type a build name or a code in the box."); return false end
    return B.Command("load " .. n)
end

function B.Share()
    local n = boxName()
    if not n then setStatus("Type the name of one of your builds in the box."); return false end
    return B.Command("share " .. n)
end

-- copy / paste: in edit mode the next ground click is the paste point
function B.Paste()
    if editing() and W.EditMode.StartPasting then W.EditMode.StartPasting(); setStatus("Click the ground where it goes."); return true end
    return B.Command("paste")
end

-- prefabs
function B.PastePrefab(name)
    if not name then return false end
    if editing() and W.EditMode.StartPrefab then
        W.EditMode.StartPrefab(name)
        setStatus("Click the ground where the prefab goes.")
        return true
    end
    return B.Command("prefab paste " .. name)
end

local function prefabName()
    local n = win and nameIn(win.prefab)
    if not n then setStatus("Type a prefab name in the box (letters, digits, - and _)."); return nil end
    return n
end

-- plot
local function plotName()
    local n = win and nameIn(win.plotName)
    if not n then setStatus("Type a character name in the box."); return nil end
    return n
end

-- ---------------------------------------------------------------- docking (edit mode hides UIParent)

-- Puts frame on the world frame while editing (UIParent is hidden), back on UIParent after.
function B.Dock(frame, toWorld)
    if not frame then return end
    local parent = (toWorld and WorldFrame) or UIParent
    if frame:GetParent() ~= parent then
        frame:SetParent(parent)
        if toWorld and UIParent.GetEffectiveScale and WorldFrame and WorldFrame.GetEffectiveScale then
            frame:SetScale(UIParent:GetEffectiveScale() / math.max(0.01, WorldFrame:GetEffectiveScale()))
        else
            frame:SetScale(1)
        end
        frame:SetFrameStrata("DIALOG")
    end
end

-- ---------------------------------------------------------------- the spawn menu (hold Q in edit mode)

local MENU_TABS = { "favourites", "recent", "prefabs", "all" }
for i = 2, #CATS do MENU_TABS[#MENU_TABS + 1] = CATS[i] end
local TAB_TEXT = { favourites = "Favourites", recent = "Recent", prefabs = "Prefabs", all = "All props" }
local function tabText(t) return TAB_TEXT[t] or (t:sub(1, 1):upper() .. t:sub(2)) end

local function byIdMap()
    local m = {}
    for _, c in ipairs(B.catalog) do m[c.id] = c end
    return m
end

-- What the menu lists now: only the realm's catalog (and your prefabs), never anything else.
function B.MenuList()
    local tab, q = B.menuTab, B.menuSearch:lower()
    local function match(c) return q == "" or c.name:lower():find(q, 1, true) or (c.key and c.key:find(q, 1, true)) end
    local out = {}
    if tab == "prefabs" then
        for _, f in ipairs(B.prefabs) do if match(f) then out[#out + 1] = f end end
        return out
    end
    local ids = byIdMap()
    if tab == "recent" then
        for _, id in ipairs(store().recent) do local c = ids[id]; if c and match(c) then out[#out + 1] = c end end
        return out
    end
    local favs = store().favs
    for _, c in ipairs(B.catalog) do
        local inTab = tab == "all" or c.cat == tab or (tab == "favourites" and favs[c.id])
        if inTab and match(c) then out[#out + 1] = c end
    end
    return out
end

function B.ToggleFavourite(c)
    if not c or c.kind == "prefab" then return end
    local favs = store().favs
    favs[c.id] = (not favs[c.id]) or nil
    setStatus(favs[c.id] and (c.name .. " is a favourite.") or (c.name .. " is no longer a favourite."))
    B.MenuRefresh()
end

function B.MenuPick(item, mouse)
    if not item then return false end
    if mouse == "RightButton" then B.ToggleFavourite(item); return true end
    local ok
    if item.kind == "prefab" then
        ok = B.PastePrefab(item.name)
    else
        B.pick = item
        B.Refresh()
        ok = B.Spawn()
    end
    -- In edit mode the next click goes to the world, so the menu gets out of the way.
    if ok and editing() and menu then menu:Hide() end
    return ok
end

function B.MenuRefresh()
    if not menu then return end
    B.menuItems = B.MenuList()
    local per = MENU_COLS * MENU_ROWS
    local n = #B.menuItems
    local maxOff = math.max(0, math.ceil((n - per) / MENU_COLS) * MENU_COLS)
    if B.menuOffset > maxOff then B.menuOffset = maxOff end
    if B.menuOffset < 0 then B.menuOffset = 0 end
    local favs = store().favs
    for i, cell in ipairs(menu.cells) do
        local c = B.menuItems[B.menuOffset + i]
        cell.item = c
        if c then
            if c.kind == "prefab" then cell:SetText(c.name .. " (" .. (c.count or 0) .. ")")
            else cell:SetText((favs[c.id] and "* " or "") .. c.name) end
            cell:Show()
        else
            cell:Hide()
        end
    end
    for _, t in ipairs(menu.tabs) do
        t:SetText((t.tab == B.menuTab and "> " or "") .. tabText(t.tab))
    end
    local empty = ""
    if n == 0 then
        if B.menuTab == "favourites" then empty = "No favourites yet: right-click a prop to add it."
        elseif B.menuTab == "recent" then empty = "Props you spawn show up here."
        elseif B.menuTab == "prefabs" then empty = "No prefabs yet: select props, then Save in the Builder's Prefab row."
        else empty = "Nothing matches." end
    end
    menu.empty:SetText(empty)
    menu.count:SetText(n > per and string.format("%d-%d of %d", B.menuOffset + 1, math.min(n, B.menuOffset + per), n) or "")
end

local function buildMenu()
    menu = CreateFrame("Frame", "WrathUnleashedSpawnMenu", UIParent)
    menu:SetWidth(580); menu:SetHeight(400)
    menu:SetPoint("CENTER")
    menu:SetFrameStrata("DIALOG")
    menu:EnableMouse(true)
    menu:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    menu:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = menu:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.05, 0.06, 0.08, 0.95)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    label(menu, "Spawn menu", "GameFontNormalLarge", "TOPLEFT", 20, -18)
    local close = CreateFrame("Button", nil, menu, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    menu.search = editBox(menu, 180, 30, "TOPLEFT", 200, -16)
    menu.search:SetScript("OnTextChanged", function(self)
        B.menuSearch = (self:GetText() or ""):sub(1, 30); B.menuOffset = 0; B.MenuRefresh()
    end)
    label(menu, "Search", "GameFontNormal", "TOPLEFT", 150, -20)
    menu.tabs = {}
    for i, t in ipairs(MENU_TABS) do
        local b = button(menu, tabText(t), 104, function(self) B.menuTab = self.tab; B.menuOffset = 0; B.MenuRefresh() end,
            "TOPLEFT", 18, -46 - (i - 1) * 21)
        b:SetHeight(20)
        b.tab = t
        menu.tabs[i] = b
    end
    menu.grid = CreateFrame("Frame", nil, menu)
    menu.grid:SetWidth(440); menu.grid:SetHeight(MENU_ROWS * 24)
    menu.grid:SetPoint("TOPLEFT", 130, -46)
    menu.grid:EnableMouseWheel(true)
    menu.grid:SetScript("OnMouseWheel", function(_, delta)
        B.menuOffset = math.max(0, B.menuOffset - delta * MENU_COLS); B.MenuRefresh()
    end)
    menu.cells = {}
    for r = 1, MENU_ROWS do
        for c = 1, MENU_COLS do
            local cell = button(menu.grid, "", 142, function(self, mouse) B.MenuPick(self.item, mouse) end,
                "TOPLEFT", (c - 1) * 146, -(r - 1) * 24)
            cell:RegisterForClicks("LeftButtonUp", "RightButtonUp")
            cell:SetScript("OnEnter", function(self)
                local it = self.item
                if not it then return end
                if it.kind == "prefab" then setStatus(string.format("%s: %d props. Click to paste it.", it.name, it.count or 0))
                else setStatus(string.format("%s: %d build point%s. Click to place it, right-click to favourite it.",
                    it.name, it.cost or 1, (it.cost or 1) == 1 and "" or "s")) end
            end)
            menu.cells[#menu.cells + 1] = cell
        end
    end
    menu.empty = label(menu, "", "GameFontHighlight", "TOPLEFT", 140, -60)
    menu.count = label(menu, "", "GameFontHighlightSmall", "BOTTOMRIGHT", -150, 22)
    menu.status = label(menu, B.status or "", "GameFontHighlightSmall", "BOTTOMLEFT", 20, 22)
    menu.status:SetWidth(380)
    button(menu, "Up", 50, function() B.menuOffset = math.max(0, B.menuOffset - MENU_COLS * MENU_ROWS); B.MenuRefresh() end, "BOTTOMRIGHT", -76, 16)
    button(menu, "Down", 50, function() B.menuOffset = B.menuOffset + MENU_COLS * MENU_ROWS; B.MenuRefresh() end, "BOTTOMRIGHT", -20, 16)
    tinsert(UISpecialFrames, "WrathUnleashedSpawnMenu")
    menu:SetScript("OnShow", function()
        if #B.catalog == 0 then B.RequestCatalog() end
        B.MenuRefresh()
    end)
    menu:Hide()
end

-- Shows or hides the spawn menu (hold Q in edit mode; the Spawn menu buttons; /spawnmenu).
function B.ShowMenu(show)
    if not menu then buildMenu() end
    B.Dock(menu, editing())
    if show then
        if editing() then menu:ClearAllPoints(); menu:SetPoint("CENTER", WorldFrame or UIParent, "CENTER", 0, 40) end
        menu:Show()
    else
        menu:Hide()
    end
end
function B.ToggleMenu() B.ShowMenu(not (menu and menu:IsShown())) end

-- ---------------------------------------------------------------- the properties panel

local FIELDS = { { "x", "X" }, { "y", "Y" }, { "z", "Z" }, { "turn", "Turn" }, { "scale", "Size" } }

function B.PropsFill()
    if not panel then return end
    local s = B.state
    local p = s.p
    panel.title2:SetText(p and ((s.count or 1) > 1 and (s.count .. " props (numbers for the last one)") or (s.selName or "")) or "Nothing selected")
    if B.propsEditing then return end
    for _, f in ipairs(FIELDS) do
        local v = p and p[f[1]]
        panel.box[f[1]]:SetText(v and (f[1] == "turn" and string.format("%.0f", v) or string.format("%.2f", v)) or "")
    end
end

local function angleDiff(a, b)
    local d = (a - b) % 360
    if d > 180 then d = 360 - d end
    return d
end

function B.ApplyProps()
    local p = B.state.p
    B.propsEditing = nil
    if not p then setStatus("Select a prop first."); return false end
    local v = {}
    for _, f in ipairs(FIELDS) do
        v[f[1]] = tonumber((panel.box[f[1]]:GetText() or ""):match("^%s*(.-)%s*$"))
        if not v[f[1]] or v[f[1]] ~= v[f[1]] then setStatus("Type numbers in the boxes."); return false end
    end
    local sent = 0
    if math.abs(v.x - p.x) > 0.004 or math.abs(v.y - p.y) > 0.004 or math.abs(v.z - p.z) > 0.004 then
        B.Command(string.format("setpos %.2f %.2f %.2f", v.x, v.y, v.z)); sent = sent + 1
    end
    if angleDiff(v.turn, p.turn) > 0.5 then B.Command(string.format("setturn %.0f", v.turn % 360)); sent = sent + 1 end
    if math.abs(v.scale - p.scale) > 0.004 then B.Command(string.format("setscale %.2f", v.scale)); sent = sent + 1 end
    if sent == 0 then setStatus("Nothing changed.") end
    return sent > 0
end

local function buildPanel()
    panel = CreateFrame("Frame", "WrathUnleashedPropsFrame", UIParent)
    panel:SetWidth(250); panel:SetHeight(234)
    panel:SetPoint("LEFT", UIParent, "LEFT", 24, 0)
    panel:SetFrameStrata("DIALOG")
    panel:EnableMouse(true)
    panel:SetMovable(true)
    panel:RegisterForDrag("LeftButton")
    panel:SetScript("OnDragStart", panel.StartMoving)
    panel:SetScript("OnDragStop", panel.StopMovingOrSizing)
    panel:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    panel:SetBackdropColor(0.06, 0.07, 0.09, 0.92)
    label(panel, "Properties", "GameFontNormal", "TOPLEFT", 14, -12)
    panel.title2 = label(panel, "", "GameFontHighlightSmall", "TOPLEFT", 14, -30)
    panel.title2:SetWidth(220)
    local close = CreateFrame("Button", nil, panel, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -2, -2)
    panel.box = {}
    for i, f in ipairs(FIELDS) do
        label(panel, f[2], "GameFontNormal", "TOPLEFT", 16, -54 - (i - 1) * 26)
        local e = editBox(panel, 120, 12, "TOPLEFT", 80, -50 - (i - 1) * 26)
        e:SetScript("OnEditFocusGained", function() B.propsEditing = true end)
        e:SetScript("OnEnterPressed", function(self) self:ClearFocus(); B.ApplyProps() end)
        panel.box[f[1]] = e
    end
    panel.apply = button(panel, "Apply", 80, function() B.ApplyProps() end, "BOTTOMLEFT", 14, 30)
    button(panel, "Reset", 80, function() B.propsEditing = nil; B.PropsFill() end, "BOTTOMLEFT", 100, 30)
    panel.status = label(panel, "", "GameFontHighlightSmall", "BOTTOMLEFT", 14, 12)
    panel.status:SetWidth(222)
    label(panel, "", "GameFontHighlightSmall", "TOPLEFT", 14, -184):SetText("Turn in degrees; size where the realm allows.")
    panel:SetScript("OnShow", function() B.propsEditing = nil; B.PropsFill() end)
    panel:Hide()
end

function B.ShowProps(show)
    if not panel then buildPanel() end
    B.Dock(panel, editing())
    if show then panel:Show() else panel:Hide() end
end
function B.ToggleProps() B.ShowProps(not (panel and panel:IsShown())) end

-- ---------------------------------------------------------------- window

local function buildRow(i)
    local row = CreateFrame("Button", nil, win.list)
    row:SetWidth(WIN_W - 40); row:SetHeight(ROW_H - 2)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_H)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.name = label(row, "", "GameFontNormal", "LEFT", 4, 0)
    row.name:SetWidth(300)
    row.cat = label(row, "", "GameFontHighlightSmall", "LEFT", 320, 0)
    row:SetScript("OnClick", function(self)
        if self.item then B.pick = self.item; B.Refresh() end
    end)
    row:SetScript("OnDoubleClick", function(self)
        if self.item then B.pick = self.item; B.Refresh(); B.Spawn() end
    end)
    row:Hide()
    return row
end

local function build()
    win = CreateFrame("Frame", "WrathUnleashedBuilderFrame", UIParent)
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
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = win:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.05, 0.06, 0.08, 0.95)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    label(win, "Builder", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, win, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    button(win, "Done", 90, function() win:Hide() end, "BOTTOMRIGHT", -16, 14)
    button(win, "Help", 70, function() B.Command("help") end, "BOTTOMLEFT", 16, 14)
    -- Edit mode (EditMode.lua): the free building camera; F7 does the same.
    win.edit = button(win, "Edit mode (F7)", 120, function()
        if W.EditMode then W.EditMode.Toggle() end
    end, "BOTTOMRIGHT", -112, 14)
    tinsert(UISpecialFrames, "WrathUnleashedBuilderFrame")   -- Esc closes it

    -- search and category
    label(win, "Search", "GameFontNormal", "TOPLEFT", 20, -48)
    local search = editBox(win, 170, nil, "TOPLEFT", 82, -44)
    search:SetScript("OnTextChanged", function(self) B.search = (self:GetText() or ""):sub(1, 30); B.Filter() end)
    win.search = search
    win.catBtn = button(win, "Category: all", 150, function()
        B.cat = B.cat % #CATS + 1; B.Filter()
    end, "TOPLEFT", 270, -42)
    win.reload = button(win, "Refresh", 70, function() B.RequestCatalog() end, "TOPRIGHT", -20, -42)

    -- the list
    win.list = CreateFrame("Frame", nil, win)
    win.list:SetWidth(WIN_W - 40); win.list:SetHeight(ROWS * ROW_H)
    win.list:SetPoint("TOPLEFT", 20, -72)
    win.list:EnableMouseWheel(true)
    win.list:SetScript("OnMouseWheel", function(_, delta) B.offset = math.max(0, B.offset - delta); B.Refresh() end)
    win.rows = {}
    for i = 1, ROWS do win.rows[i] = buildRow(i) end
    local y = -72 - ROWS * ROW_H
    win.count = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 20, y - 8)
    win.menuBtn = button(win, "Spawn menu", 100, function() B.ToggleMenu() end, "TOPRIGHT", -132, y - 4)
    button(win, "Up", 50, function() B.offset = math.max(0, B.offset - ROWS); B.Refresh() end, "TOPRIGHT", -76, y - 4)
    button(win, "Down", 50, function() B.offset = B.offset + ROWS; B.Refresh() end, "TOPRIGHT", -20, y - 4)

    -- spawn and the selection
    win.spawn = button(win, "Spawn", 220, function() B.Spawn() end, "TOPLEFT", 20, y - 32)
    win.near = button(win, "Near", 70, function() B.Command("near") end, "TOPLEFT", 250, y - 32)
    win.undo = button(win, "Undo", 70, function() B.Command("undo") end, "TOPLEFT", 326, y - 32)
    win.delete = button(win, "Delete", 80, function() B.Command("delete") end, "TOPLEFT", 402, y - 32)
    win.sel = label(win, "Nothing selected", "GameFontHighlightSmall", "TOPLEFT", 22, y - 60)
    win.sel:SetWidth(WIN_W - 44)

    -- nudges
    label(win, "Move", "GameFontNormal", "TOPLEFT", 20, y - 86)
    win.nudge = {}
    local x0 = 70
    for k, axis in ipairs({ "x", "y", "z" }) do
        win.nudge[axis .. "-"] = button(win, axis .. " -", 44, function() B.Move(axis, -1) end, "TOPLEFT", x0 + (k - 1) * 96, y - 82)
        win.nudge[axis .. "+"] = button(win, axis .. " +", 44, function() B.Move(axis, 1) end, "TOPLEFT", x0 + (k - 1) * 96 + 46, y - 82)
    end
    win.stepBtn = button(win, "Step " .. STEPS[B.step] .. " yd", 100, function(self)
        B.step = B.step % #STEPS + 1; self:SetText("Step " .. STEPS[B.step] .. " yd")
    end, "TOPLEFT", x0 + 290, y - 82)
    label(win, "Turn", "GameFontNormal", "TOPLEFT", 20, y - 114)
    win.turnL = button(win, "+" .. TURN .. " deg", 80, function() B.Turn(1) end, "TOPLEFT", x0, y - 110)
    win.turnR = button(win, "-" .. TURN .. " deg", 80, function() B.Turn(-1) end, "TOPLEFT", x0 + 86, y - 110)
    win.props = button(win, "Properties", 100, function() B.ToggleProps() end, "TOPLEFT", x0 + 190, y - 110)

    -- group
    label(win, "Group", "GameFontNormal", "TOPLEFT", 20, y - 142)
    win.selall = button(win, "Select mine", 96, function() B.Command("selall") end, "TOPLEFT", x0, y - 138)
    win.copy = button(win, "Copy", 64, function() B.Command("copy") end, "TOPLEFT", x0 + 100, y - 138)
    win.paste = button(win, "Paste", 64, function() B.Paste() end, "TOPLEFT", x0 + 168, y - 138)
    win.selclear = button(win, "Clear selection", 120, function() B.Command("selclear") end, "TOPLEFT", x0 + 236, y - 138)

    -- save / load / share
    label(win, "Build", "GameFontNormal", "TOPLEFT", 20, y - 174)
    win.code = editBox(win, 150, 24, "TOPLEFT", 76, y - 170)
    win.save = button(win, "Save", 70, function() B.Save() end, "TOPLEFT", 236, y - 168)
    win.load = button(win, "Load", 70, function() B.Load() end, "TOPLEFT", 310, y - 168)
    win.share = button(win, "Share", 70, function() B.Share() end, "TOPLEFT", 384, y - 168)
    win.info = label(win, "Save or Share your props in this area by name; Load a name or a 6-letter code where you stand.",
        "GameFontHighlightSmall", "TOPLEFT", 22, y - 194)
    win.info:SetWidth(WIN_W - 44)

    -- prefabs: the selection, saved by name
    label(win, "Prefab", "GameFontNormal", "TOPLEFT", 20, y - 222)
    win.prefab = editBox(win, 150, 24, "TOPLEFT", 76, y - 218)
    win.prefabSave = button(win, "Save", 70, function() local n = prefabName(); if n then B.Command("prefab save " .. n) end end, "TOPLEFT", 236, y - 216)
    win.prefabPaste = button(win, "Paste", 70, function() local n = prefabName(); if n then B.PastePrefab(n) end end, "TOPLEFT", 310, y - 216)
    win.prefabShare = button(win, "Share", 70, function() local n = prefabName(); if n then B.Command("prefab share " .. n) end end, "TOPLEFT", 384, y - 216)

    -- plot
    label(win, "Plot", "GameFontNormal", "TOPLEFT", 20, y - 252)
    win.claim = button(win, "Claim", 60, function() B.Command("plot claim") end, "TOPLEFT", 66, y - 248)
    win.plotInfoBtn = button(win, "Info", 50, function() B.Command("plot") end, "TOPLEFT", 128, y - 248)
    win.plotName = editBox(win, 100, 12, "TOPLEFT", 190, y - 250)
    win.plotAdd = button(win, "Add", 50, function() local n = plotName(); if n then B.Command("plot add " .. n) end end, "TOPLEFT", 296, y - 248)
    win.plotVisitor = button(win, "Visitor", 64, function() local n = plotName(); if n then B.Command("plot add " .. n .. " visitor") end end, "TOPLEFT", 348, y - 248)
    win.plotRemove = button(win, "Remove", 66, function() local n = plotName(); if n then B.Command("plot remove " .. n) end end, "TOPLEFT", 414, y - 248)
    win.plot = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 22, y - 276)
    win.plot:SetWidth(WIN_W - 44)

    -- the budget meter
    label(win, "Budget", "GameFontNormal", "TOPLEFT", 20, y - 302)
    win.barBg = win:CreateTexture(nil, "BACKGROUND")
    win.barBg:SetTexture(0, 0, 0, 0.5)
    win.barBg:SetWidth(200); win.barBg:SetHeight(10)
    win.barBg:SetPoint("TOPLEFT", 80, y - 304)
    win.bar = win:CreateTexture(nil, "ARTWORK")
    win.bar:SetTexture(1, 1, 1, 1)
    win.bar:SetWidth(1); win.bar:SetHeight(10)
    win.bar:SetPoint("TOPLEFT", 80, y - 304)
    win.meter = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 290, y - 302)

    win.status = label(win, B.status or "", "GameFontHighlightSmall", "BOTTOMLEFT", 96, 20)
    win.status:SetWidth(WIN_W - 220)

    win:SetScript("OnUpdate", function()
        if B.waiting and B.askedAt and now() - B.askedAt > ANSWER_WAIT then
            B.waiting = nil
            setStatus("The Builder isn't on this realm yet.")
        end
    end)
    win:SetScript("OnShow", function()
        if PlaySound then pcall(PlaySound, "igCharacterInfoOpen") end
        if #B.catalog == 0 then B.RequestCatalog() end
        B.Refresh()
        refreshMeter()
    end)
    win:Hide()
end

function W.ToggleBuilder()
    if not win then build() end
    if win:IsShown() then win:Hide() else win:Show() end
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) B.OnMessage(prefix, msg, channel, sender) end)

SLASH_WUBUILDER1, SLASH_WUBUILDER2 = "/builder", "/build"
SlashCmdList["WUBUILDER"] = function() W.ToggleBuilder() end
SLASH_WUSPAWNMENU1 = "/spawnmenu"
SlashCmdList["WUSPAWNMENU"] = function() B.ToggleMenu() end

W.Builder = B
B.Window, B.STEPS, B.CATS = function() return win end, STEPS, CATS
B.Menu, B.Panel, B.MENU_TABS = function() return menu end, function() return panel end, MENU_TABS
