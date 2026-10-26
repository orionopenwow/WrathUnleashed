-- The Workshop tab of Esc > Mods & Workshop (3.3.5a API): what players made, to play in one click.
--   Browse the approved courses, modes and builds (All, Courses, Modes, Builds), or your own (Mine, any state);
--   sort by Most played, Top rated or New; thumbs up or down (one vote per account); Play.
--   Play on a course starts it where you stand and invites your party; a mode is hosted the same way; a build
--   is pasted where you stand in your build area. The realm does it (realm/custom/lua_scripts/ov_workshop.lua):
--   this file only asks, and opens the minigolf, Modes or Builder window when the realm says it started.
--   Publish a build: its 6-letter code from .build share. Courses and modes join when you publish them.
-- OVMOD channel, mod "wuws" (see ov_workshop.lua for the full list):
--   client -> server   list <kind> <sort> <page> | mine | rate <id> <up|down|none> | play <id> | publish <code> <title>
--   server -> client   items <kind> <sort> <page> <pages>\n<rows> | rated <id> <up> <down> <mine> |
--                      playing <id> <kind> <title> | published <id> | msg <text>
-- Opened by Esc > Mods & Workshop > Workshop, and /workshop.

local W = WrathUnleashedUI
local PREFIX, MOD = "OVMOD", "wuws"
local ROWS, ROW_H, PAGE_W = 5, 40, 436
local ANSWER_WAIT = 6
local SITE = "https://play.openvanilla.app/wrath/workshop"

local KINDS = { { "all", "All" }, { "course", "Courses" }, { "mode", "Modes" }, { "build", "Builds" }, { "mine", "Mine" } }
local SORTS = { { "plays", "Most played" }, { "rating", "Top rated" }, { "new", "New" } }
local KIND_LABEL = { course = "Course", mode = "Mode", build = "Build" }
local STATE_LABEL = { pending = "|cffffd100waiting for a GM|r", rejected = "|cffff6060not approved|r" }

local S = { items = {}, kind = "all", sort = "plays", page = 1, pages = 1, status = "" }
W.Workshop = S

local page   -- the tab's frame, once built

local function now() return (GetTime and GetTime()) or 0 end
local function tidy(s) return (tostring(s or ""):gsub("|", "")) end

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end

local function button(parent, text, w, onClick, ...)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(20)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end

local function status(text)
    S.status = text or ""
    if page then page.status:SetText(S.status) end
end

local function send(name, data)
    if not SendAddonMessage or not UnitName then return false end
    pcall(SendAddonMessage, PREFIX, MOD .. "\t" .. name .. "\t1/1\t" .. (data or ""), "WHISPER", UnitName("player"))
    return true
end

-- ---------------------------------------------------------------- reading the realm's rows

-- One row: id \t kind \t title \t author \t version \t plays \t up \t down \t myvote \t state \t description
function S.ParseRow(line)
    local f = {}
    for v in (tostring(line or "") .. "\t"):gmatch("([^\t]*)\t") do f[#f + 1] = v end
    local id = tonumber(f[1])
    if not id or not KIND_LABEL[f[2]] then return nil end
    return { id = id, kind = f[2], title = tidy(f[3]):sub(1, 48), author = tidy(f[4]):sub(1, 12), version = tonumber(f[5]) or 1,
        plays = tonumber(f[6]) or 0, up = tonumber(f[7]) or 0, down = tonumber(f[8]) or 0, mine = tonumber(f[9]) or 0,
        state = f[10] or "approved", descr = tidy(f[11]):sub(1, 140) }
end

function S.Ask()
    S.askedAt, S.waiting = now(), true
    if S.kind == "mine" then return send("mine", "") end
    return send("list", string.format("%s %s %d", S.kind, S.sort, S.page))
end

-- After Play: the window of the thing that started (the realm has already sent it its lobby or paste).
local OPEN = {
    course = function() return "LeylineGolfFrame", W.Golf and W.Golf.Toggle end,
    mode = function() return "LeylineModesFrame", W.Modes and W.Modes.Toggle end,
    build = function() return "WrathUnleashedBuilderFrame", W.ToggleBuilder end,
}
function S.Opened(kind)
    local how = OPEN[kind]
    if not how then return end
    local name, toggle = how()
    local f = _G[name]
    if f and f.IsShown and f:IsShown() then return end
    if type(toggle) == "function" then pcall(toggle) end
end

function S.Dispatch(name, data)
    data = data or ""
    if name == "items" then
        local head, rest = data:match("^([^\n]*)\n?(.*)$")
        local kind, sort, p, pages = (head or ""):match("^(%a+) (%a+) (%d+) (%d+)")
        if not kind then return end
        S.waiting = nil
        S.page, S.pages = tonumber(p), math.max(1, tonumber(pages))
        S.items = {}
        for line in (rest or ""):gmatch("[^\n]+") do
            local it = S.ParseRow(line)
            if it and #S.items < 20 then S.items[#S.items + 1] = it end
        end
        if #S.items == 0 then
            status(S.kind == "mine" and "Nothing of yours yet. Publish a course or a mode, or a build below."
                or "Nothing here yet. Make something: /golf edit, /modes edit or /builder.")
        else
            status("")
        end
        S.Refresh()
    elseif name == "rated" then
        local id, up, down, mine = data:match("^(%d+) (%d+) (%d+) (%-?%d+)")
        for _, it in ipairs(S.items) do
            if it.id == tonumber(id) then it.up, it.down, it.mine = tonumber(up), tonumber(down), tonumber(mine) end
        end
        S.Refresh()
    elseif name == "playing" then
        local id, kind, title = data:match("^(%d+) (%a+) ?(.*)$")
        if not id then return end
        status("Starting " .. tidy(title) .. "...")
        if WrathUnleashedModsFrame and WrathUnleashedModsFrame:IsShown() then WrathUnleashedModsFrame:Hide() end
        S.Opened(kind)
    elseif name == "published" then
        status("Published as #" .. tidy(data) .. ". A GM looks at it before others see it.")
        if page then page.code:SetText(""); page.title:SetText("") end
    elseif name == "msg" then
        status(tidy(data))
    end
end

function S.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local mod, name, i, n, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
    if mod ~= MOD then return end
    i, n = tonumber(i), tonumber(n)
    if n < 1 or n > 64 or i < 1 or i > n then return end
    S.parts = S.parts or {}
    if n == 1 then S.parts[name] = nil; return S.Dispatch(name, data) end
    local buf = S.parts[name]
    if i == 1 or not buf or buf.n ~= n then buf = { n = n, got = 0 }; S.parts[name] = buf end
    if not buf[i] then buf[i] = data; buf.got = buf.got + 1 end
    if buf.got == n then
        S.parts[name] = nil
        S.Dispatch(name, table.concat(buf, "", 1, n))
    end
end

-- ---------------------------------------------------------------- actions

function S.Play(id) status("Asking the realm..."); return send("play", tostring(id)) end
function S.Rate(it, how)
    if how == "up" and it.mine == 1 then how = "none" elseif how == "down" and it.mine == -1 then how = "none" end
    return send("rate", it.id .. " " .. how)
end
function S.Show(kind, sort)
    if kind then S.kind, S.page = kind, 1 end
    if sort then S.sort, S.page = sort, 1 end
    S.Ask()
    S.Refresh()
end
function S.Publish(code, title)
    code = tostring(code or ""):upper():gsub("[^A-Z0-9]", "")
    if #code ~= 6 then status("A build code is 6 letters and digits (.build share <name> gives one)."); return false end
    title = tostring(title or ""):gsub("[^%w %-!&%.,%?:%(%)]", ""):sub(1, 40)
    status("Publishing " .. code .. "...")
    return send("publish", code .. " " .. title)
end

-- ---------------------------------------------------------------- the tab

function S.Refresh()
    if not page then return end
    for _, b in ipairs(page.kindBtns) do b:SetAlpha(b.key == S.kind and 1 or 0.55) end
    for _, b in ipairs(page.sortBtns) do
        b:SetAlpha(b.key == S.sort and 1 or 0.55)
        if S.kind == "mine" then b:Hide() else b:Show() end
    end
    for i, r in ipairs(page.rows) do
        local it = S.items[i]
        r.item = it
        if it then
            r.title:SetText(string.format("%s |cff9d9d9dby %s - %s v%d|r", it.title, it.author, KIND_LABEL[it.kind], it.version))
            local line = string.format("%d play%s  |cff7fff7f+%d|r |cffff7f7f-%d|r", it.plays, it.plays == 1 and "" or "s", it.up, it.down)
            if STATE_LABEL[it.state] then line = line .. "  " .. STATE_LABEL[it.state] end
            if it.descr ~= "" then line = line .. "  " .. it.descr end
            r.line:SetText(line)
            r.up:SetText(it.mine == 1 and "[+]" or "+")
            r.down:SetText(it.mine == -1 and "[-]" or "-")
            r.title:Show(); r.line:Show(); r.play:Show()
            if it.state == "approved" and S.kind ~= "mine" then r.up:Show(); r.down:Show() else r.up:Hide(); r.down:Hide() end
        else
            r.title:Hide(); r.line:Hide(); r.play:Hide(); r.up:Hide(); r.down:Hide()
        end
    end
    page.count:SetText(S.kind == "mine" and "" or string.format("Page %d of %d", S.page, S.pages))
end

function W.BuildWorkshopItems(p)
    page = p
    p.kindBtns, p.sortBtns, p.rows = {}, {}, {}
    for i, k in ipairs(KINDS) do
        local b = button(p, k[2], 80, function() S.Show(k[1], nil) end, "TOPLEFT", 10 + (i - 1) * 84, -4)
        b.key = k[1]
        p.kindBtns[i] = b
    end
    for i, s in ipairs(SORTS) do
        local b = button(p, s[2], 100, function() S.Show(nil, s[1]) end, "TOPLEFT", 10 + (i - 1) * 104, -28)
        b.key = s[1]
        p.sortBtns[i] = b
    end
    for i = 1, ROWS do
        local y = -56 - (i - 1) * ROW_H
        local r = {}
        r.title = label(p, "", "GameFontNormal", "TOPLEFT", 12, y)
        r.title:SetWidth(PAGE_W - 150)
        r.line = label(p, "", "GameFontHighlightSmall", "TOPLEFT", 12, y - 16)
        r.line:SetWidth(PAGE_W - 150); r.line:SetHeight(20)
        r.play = button(p, "Play", 56, function() if r.item then S.Play(r.item.id) end end, "TOPLEFT", PAGE_W - 130, y - 2)
        r.up = button(p, "+", 30, function() if r.item then S.Rate(r.item, "up") end end, "TOPLEFT", PAGE_W - 70, y - 2)
        r.down = button(p, "-", 30, function() if r.item then S.Rate(r.item, "down") end end, "TOPLEFT", PAGE_W - 38, y - 2)
        p.rows[i] = r
    end
    local by = -56 - ROWS * ROW_H
    button(p, "Prev", 56, function() if S.page > 1 then S.page = S.page - 1; S.Ask() end end, "TOPLEFT", 10, by)
    button(p, "Next", 56, function() if S.page < S.pages then S.page = S.page + 1; S.Ask() end end, "TOPLEFT", 70, by)
    p.count = label(p, "", "GameFontHighlightSmall", "TOPLEFT", 134, by - 4)
    label(p, "On the web: " .. SITE:gsub("^https://", ""), "GameFontDisableSmall", "TOPLEFT", 210, by - 4)

    local py = by - 30
    label(p, "Publish a build:", "GameFontHighlightSmall", "TOPLEFT", 12, py - 4)
    local code = CreateFrame("EditBox", nil, p, "InputBoxTemplate")
    code:SetWidth(70); code:SetHeight(20); code:SetPoint("TOPLEFT", 112, py)
    code:SetAutoFocus(false); code:SetMaxLetters(6)
    code:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    local title = CreateFrame("EditBox", nil, p, "InputBoxTemplate")
    title:SetWidth(150); title:SetHeight(20); title:SetPoint("TOPLEFT", 192, py)
    title:SetAutoFocus(false); title:SetMaxLetters(40)
    title:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    button(p, "Publish", 70, function() S.Publish(code:GetText(), title:GetText()) end, "TOPLEFT", 350, py)
    label(p, "code from .build share, then a title", "GameFontDisableSmall", "TOPLEFT", 112, py - 20)
    p.code, p.title = code, title

    p.status = label(p, S.status, "GameFontHighlightSmall", "TOPLEFT", 12, py - 40)
    p.status:SetWidth(PAGE_W - 20)
    p:SetScript("OnUpdate", function()
        if S.waiting and S.askedAt and now() - S.askedAt > ANSWER_WAIT then
            S.waiting = nil
            status("The Workshop isn't on this realm yet.")
        end
    end)
    S.Refresh()
end

-- The Mods & Workshop panel calls this when the tab opens.
function W.RefreshWorkshopItems()
    S.Ask()
    S.Refresh()
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) S.OnMessage(prefix, msg, channel, sender) end)
