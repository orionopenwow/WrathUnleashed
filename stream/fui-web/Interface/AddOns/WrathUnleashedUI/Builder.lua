-- Builder (3.3.5a API): the window for the realm's Builder (realm/custom/lua_scripts/ov_build.lua), in the
-- Mods & Workshop panel's look. Pick a prop from the catalog (search, categories), Spawn it where you stand,
-- nudge it (x, y, z), turn it 15 degrees at a time, Undo or Delete, and Save / Load / Share builds by name or
-- code. Opened by Esc > Mods & Workshop > Builder and by /builder.
--
-- Everything the buttons do is a ".build ..." command, sent over the realm's OVMOD addon channel (ov_modapi.lua),
-- whispered to yourself, mod "wubuild":
--   client -> server   wubuild \t cmd \t 1/1 \t <the text after .build>      e.g. "spawn 2413", "move z 0.5"
--                      wubuild \t catalog \t 1/1 \t                          send me the catalog
--   server -> client   wubuild \t catalog \t i/n \t id,key,category,name;...
--                      wubuild \t state \t i/n \t sel=..;mine=..;area=..;code=..
-- The realm checks everything (role, area, limits) and answers in chat as for the dot commands. Without the
-- realm script nothing is sent anywhere else and the window says the Builder isn't on this realm.

local W = WrathUnleashedUI
local PREFIX, MOD = "OVMOD", "wubuild"
local WIN_W, WIN_H, ROW_H, ROWS = 520, 520, 20, 9
local ANSWER_WAIT = 6
local STEPS = { 0.25, 1, 3 }
local TURN = 15
local CATS = { "all", "seating", "tables", "barrels", "crates", "lights", "banners", "tents", "fires", "fences", "nature", "decor" }

local win
local B = { catalog = {}, shown = {}, offset = 0, cat = 1, step = 2, search = "", state = {}, parts = {} }

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

local function now() return (GetTime and GetTime()) or 0 end

local function setStatus(text)
    B.status = text or ""
    if win then win.status:SetText(B.status) end
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
        local id, key, cat, name = item:match("^(%d+),([%w]+),(%a+),(.+)$")
        if id and #list < 600 then
            list[#list + 1] = { id = tonumber(id), key = key, cat = cat, name = name:gsub("|", "") }
        end
    end
    return list
end

local function parseState(data)
    local s = {}
    for k, v in data:gmatch("(%a+)=([^;]*)") do s[k] = v:gsub("|", "") end
    local id, entry, name = (s.sel or ""):match("^(%d+),(%d+),(.*)$")
    s.selName = name
    return s
end

local function stateText(s)
    local parts = {}
    parts[#parts + 1] = s.selName and ("Selected: " .. s.selName) or "Nothing selected"
    if s.mine then parts[#parts + 1] = "props " .. s.mine end
    if s.area and s.area ~= "-" then parts[#parts + 1] = s.area else parts[#parts + 1] = "not in a build area" end
    return table.concat(parts, "  |  ")
end

local function dispatch(name, data)
    if name == "catalog" then
        B.catalog, B.waiting = parseCatalog(data), nil
        B.Filter()
        setStatus(#B.catalog .. " props. Pick one and Spawn it where you stand.")
    elseif name == "state" then
        B.waiting = nil
        B.state = parseState(data)
        if win then
            win.sel:SetText(stateText(B.state))
            if B.state.code and B.state.code ~= "-" then win.code:SetText(B.state.code) end
        end
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
            row.cat:SetText(c.cat)
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

function B.Spawn()
    if not B.pick then setStatus("Pick a prop first."); return false end
    -- In edit mode the next click on the ground places it (EditMode.lua); otherwise at your feet.
    if W.EditMode and W.EditMode.IsOn and W.EditMode.IsOn() then
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

local function boxName()
    local t = (win.code:GetText() or ""):gsub("%s+", "")
    if t == "" or not t:match("^[%w_%-]+$") or #t > 24 then return nil end
    return t
end

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
    win:SetBackdrop({ bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
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
    local search = CreateFrame("EditBox", nil, win, "InputBoxTemplate")
    search:SetWidth(170); search:SetHeight(20)
    search:SetPoint("TOPLEFT", 82, -44)
    search:SetAutoFocus(false)
    search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
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

    -- save / load / share
    label(win, "Build", "GameFontNormal", "TOPLEFT", 20, y - 146)
    local code = CreateFrame("EditBox", nil, win, "InputBoxTemplate")
    code:SetWidth(150); code:SetHeight(20)
    code:SetPoint("TOPLEFT", 76, y - 142)
    code:SetAutoFocus(false)
    code:SetMaxLetters(24)
    code:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    win.code = code
    win.save = button(win, "Save", 70, function() B.Save() end, "TOPLEFT", 236, y - 140)
    win.load = button(win, "Load", 70, function() B.Load() end, "TOPLEFT", 310, y - 140)
    win.share = button(win, "Share", 70, function() B.Share() end, "TOPLEFT", 384, y - 140)
    win.info = label(win, "Type a name to Save or Share your props in this area, or a name or a 6-letter code to "
        .. "Load a build where you stand.", "GameFontHighlightSmall", "TOPLEFT", 22, y - 168)
    win.info:SetWidth(WIN_W - 44)
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

W.Builder = B
B.Window, B.STEPS, B.CATS = function() return win end, STEPS, CATS
