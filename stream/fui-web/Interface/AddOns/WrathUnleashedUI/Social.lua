-- Leyline Friends (3.3.5a API): your Leyline friends in game, in the launcher and on the website, in one list, and
-- Leyline messages to them wherever they are. The same friends as the Leyline launcher's Friends page.
--   The list:    name#tag, in game (character and realm) / in the launcher / offline, unread messages; friend
--                requests to accept or decline; your own requests waiting.
--   Message:     pick a friend, type, Enter. Incoming messages show in chat as "[Leyline] [Name] whispers: ..." (the
--                realm prints those) and here, under the list, for this session.
--   Add:         Name#1234, a name, or a character name. Appear offline / online.
-- Opened by /lfriends (or /leylinefriends), the Leyline button on the Friends window, and "Friends" in the Leyline
-- window (/leyline). Chat commands do the same: .lm <friend> <text>, .lr <text>, .lf (list), .lf add <name>.
--
-- The client can't make HTTP calls, so the realm carries it (realm/custom/lua_scripts/ov_social.lua) as addon messages,
-- prefix WUSO, whispered to yourself:
--   client -> server   L | S:<friend>:<text> | F:<verb>:<arg>
--   server -> client   B:<count>, R:<status>:<unread>:<name>:<tag>:<where> ..., E   (status g l o q p)
--                      M:<from>:<text> (a message), O:<to>:<text> (yours), T:<text> (a notice), X:<text> (offline)
-- Only messages the realm whispers to you (sender = you) count: nobody else can fake a friend or a message.

local W = WrathUnleashedUI
local PREFIX = "WUSO"
local WIN_W, WIN_H, ROW_H, ROWS = 440, 560, 30, 8
local ASK_EVERY = 20
local LOG_MAX, LOG_SHOWN = 50, 5
local STATUS = {
    g = { "In game", 0.25, 0.9, 0.35 }, l = { "In the launcher", 0.35, 0.65, 1 }, o = { "Offline", 0.5, 0.5, 0.5 },
    q = { "Wants to be friends", 1, 0.82, 0 }, p = { "Request sent", 0.7, 0.7, 0.7 },
}

local win
local S = { rows = {}, offset = 0, log = {}, status = "" }

local function now() return (GetTime and GetTime()) or 0 end
local function me() return UnitName and UnitName("player") or "" end

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

local function input(parent, w, ...)
    local e = CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    e:SetWidth(w); e:SetHeight(20)
    e:SetPoint(...)
    e:SetAutoFocus(false)
    e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return e
end

-- No colour codes, links or separators from anyone's text.
local function plain(s, cap)
    s = tostring(s or ""):gsub("|", "/"):gsub("[%z\1-\31]", " ")
    if cap and #s > cap then s = s:sub(1, cap) end
    return s
end

local function setStatus(text)
    S.status = text or ""
    if win then win.status:SetText(S.status) end
end

-- ---------------------------------------------------------------- talking to the realm
local function send(msg)
    if not SendAddonMessage then return false end
    SendAddonMessage(PREFIX, msg:sub(1, 250), "WHISPER", me())
    return true
end

function S.Request(force)
    if not force and S.askedAt and now() - S.askedAt < ASK_EVERY then return false end
    S.askedAt = now()
    return send("L")
end

function S.Send(name, text)
    name, text = plain(name, 40):gsub(":", ""), plain(text, 230)
    if name == "" or text:match("^%s*$") then return false end
    return send("S:" .. name .. ":" .. text)
end

function S.Action(verb, arg)
    return send("F:" .. verb .. ":" .. plain(arg or "", 60):gsub(":", ""))
end

local function addLog(who, text, mine)
    S.log[#S.log + 1] = { who = who, text = text, mine = mine }
    while #S.log > LOG_MAX do table.remove(S.log, 1) end
end

function S.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or channel ~= "WHISPER" or sender ~= me() or type(msg) ~= "string" then return end
    local kind, rest = msg:sub(1, 1), msg:sub(3)
    if kind == "B" then
        S.incoming = {}
    elseif kind == "R" and S.incoming then
        local st, unread, name, tag, where = rest:match("^(%a):(%d+):([^:]*):([^:]*):(.*)$")
        if st and STATUS[st] and name ~= "" then
            S.incoming[#S.incoming + 1] = { status = st, unread = tonumber(unread) or 0, name = name, tag = tag, where = where }
        end
    elseif kind == "E" and S.incoming then
        S.rows, S.incoming = S.incoming, nil
        local on = 0
        for _, r in ipairs(S.rows) do if r.status == "g" or r.status == "l" then on = on + 1 end end
        S.online = on
        if not S.statusSticky then setStatus(#S.rows == 0 and "No Leyline friends yet. Add one below." or (on .. " online")) end
    elseif kind == "M" or kind == "O" then
        local who, text = rest:match("^([^:]*):(.*)$")
        if who then addLog(who, text, kind == "O") end
    elseif kind == "T" or kind == "X" then
        S.statusSticky = true
        setStatus(plain(rest, 200))
    end
    if win and win:IsShown() then S.Refresh() end
    if S.adopted then S.UpdateAdopted() end
end

-- ---------------------------------------------------------------- the window
local function pick(name)
    S.selected = name
    if win then
        win.to:SetText(name and ("To " .. name .. ":") or "Pick a friend to message")
        if name then win.say:SetFocus() end
    end
    S.Refresh()
end

local function buildRow(i)
    local row = CreateFrame("Frame", nil, win.list)
    row:SetWidth(WIN_W - 40); row:SetHeight(ROW_H)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_H)
    row.dot = row:CreateTexture(nil, "ARTWORK")
    row.dot:SetWidth(8); row.dot:SetHeight(8)
    row.dot:SetPoint("LEFT", 4, 0)
    row.name = label(row, "", "GameFontNormal", "TOPLEFT", 18, -2)
    row.where = label(row, "", "GameFontHighlightSmall", "TOPLEFT", 18, -16)
    row.where:SetWidth(WIN_W - 230)
    row.unread = label(row, "", "GameFontNormalSmall", "TOPRIGHT", -150, -4)
    row.a = button(row, "Message", 72, function(self) S.RowAction(row, "a") end, "TOPRIGHT", -76, -4)
    row.b = button(row, "Remove", 70, function(self) S.RowAction(row, "b") end, "TOPRIGHT", -2, -4)
    row:Hide()
    return row
end

function S.RowAction(row, which)
    local r = row.data
    if not r then return end
    local full = r.tag ~= "" and (r.name .. "#" .. r.tag) or r.name
    if r.status == "q" then
        S.Action(which == "a" and "accept" or "decline", full)
    elseif r.status == "p" then
        return
    elseif which == "a" then
        pick(full)
    else
        if row.confirm then
            row.confirm = nil
            S.Action("remove", full)
        else
            row.confirm = true
            row.b:SetText("Sure?")
            return
        end
    end
    S.askedAt = nil
end

function S.Refresh()
    if not win then return end
    local rows = S.rows
    S.offset = math.max(0, math.min(S.offset, math.max(0, #rows - ROWS)))
    for i = 1, ROWS do
        local row, r = win.rows[i], rows[i + S.offset]
        row.data, row.confirm = r, nil
        if r then
            local st = STATUS[r.status]
            row.dot:SetTexture(st[2], st[3], st[4], 1)
            row.name:SetText(plain(r.name, 24) .. (r.tag ~= "" and ("|cff808080#" .. r.tag .. "|r") or ""))
            row.where:SetText(st[1] .. (r.where ~= "" and r.status ~= "q" and r.status ~= "p" and (": " .. plain(r.where, 60)) or ""))
            row.unread:SetText(r.unread > 0 and ("|cffff80ff" .. r.unread .. " new|r") or "")
            if r.status == "q" then
                row.a:SetText("Accept"); row.b:SetText("Decline"); row.a:Show(); row.b:Show()
            elseif r.status == "p" then
                row.a:Hide(); row.b:Hide()
            else
                row.a:SetText("Message"); row.b:SetText("Remove"); row.a:Show(); row.b:Show()
            end
            row:Show()
        else
            row:Hide()
        end
    end
    win.count:SetText(#rows > ROWS and string.format("%d-%d of %d", S.offset + 1, math.min(#rows, S.offset + ROWS), #rows) or "")
    -- the conversation with the selected friend (this session)
    local lines, sel = {}, S.selected and S.selected:gsub("#%d+$", ""):lower()
    for i = #S.log, 1, -1 do
        local e = S.log[i]
        if not sel or e.who:gsub("#%d+$", ""):lower() == sel then
            table.insert(lines, 1, e.mine and ("|cffff80ffTo " .. plain(e.who, 24) .. ":|r " .. plain(e.text, 200))
                or ("|cffff80ff" .. plain(e.who, 24) .. ":|r " .. plain(e.text, 200)))
            if #lines >= LOG_SHOWN then break end
        end
    end
    for i = 1, LOG_SHOWN do win.log[i]:SetText(lines[i] or "") end
end

local function build()
    win = CreateFrame("Frame", "WrathUnleashedSocialFrame", UIParent)
    win:SetWidth(WIN_W); win:SetHeight(WIN_H)
    win:SetPoint("CENTER", 220, 0)
    win:SetFrameStrata("DIALOG")
    win:EnableMouse(true)
    win:SetMovable(true)
    win:RegisterForDrag("LeftButton")
    win:SetScript("OnDragStart", win.StartMoving)
    win:SetScript("OnDragStop", win.StopMovingOrSizing)
    win:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    win:SetBackdropColor(0.05, 0.06, 0.08, 0.95)
    do
        local bg = win:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.05, 0.06, 0.08, 0.95)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    label(win, "Leyline Friends", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, win, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    tinsert(UISpecialFrames, "WrathUnleashedSocialFrame")

    win.status = label(win, S.status, "GameFontHighlightSmall", "TOPLEFT", 20, -46)
    win.status:SetWidth(WIN_W - 130)
    win.refresh = button(win, "Refresh", 80, function() S.statusSticky = nil; S.Request(true) end, "TOPRIGHT", -20, -40)

    win.list = CreateFrame("Frame", nil, win)
    win.list:SetWidth(WIN_W - 40); win.list:SetHeight(ROWS * ROW_H)
    win.list:SetPoint("TOPLEFT", 20, -68)
    win.list:EnableMouseWheel(true)
    win.list:SetScript("OnMouseWheel", function(_, delta) S.offset = math.max(0, S.offset - delta); S.Refresh() end)
    win.rows = {}
    for i = 1, ROWS do win.rows[i] = buildRow(i) end
    local y = -68 - ROWS * ROW_H
    win.count = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 20, y - 6)

    -- add a friend, appear offline
    label(win, "Add a friend (Name#1234 or a character):", "GameFontNormalSmall", "TOPLEFT", 20, y - 26)
    win.add = input(win, WIN_W - 140, "TOPLEFT", 26, y - 42)
    local function add()
        local t = win.add:GetText() or ""
        if t:match("%S") then S.Action("add", t); win.add:SetText(""); win.add:ClearFocus(); S.askedAt = nil end
    end
    win.add:SetScript("OnEnterPressed", add)
    win.addBtn = button(win, "Add", 70, add, "TOPRIGHT", -20, y - 40)

    -- the conversation
    win.to = label(win, "Pick a friend to message", "GameFontNormal", "TOPLEFT", 20, y - 74)
    win.log = {}
    for i = 1, LOG_SHOWN do
        win.log[i] = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 22, y - 92 - (i - 1) * 14)
        win.log[i]:SetWidth(WIN_W - 44)
    end
    win.say = input(win, WIN_W - 140, "BOTTOMLEFT", 26, 46)
    local function say()
        local t = win.say:GetText() or ""
        if not S.selected then setStatus("Pick a friend first: Message on their row.") return end
        if S.Send(S.selected, t) then win.say:SetText("") end
    end
    win.say:SetScript("OnEnterPressed", say)
    win.sayBtn = button(win, "Send", 70, say, "BOTTOMRIGHT", -20, 44)

    win.offline = button(win, "Appear offline", 120, function() S.Action("offline", "") end, "BOTTOMLEFT", 16, 14)
    win.online = button(win, "Show me online", 120, function() S.Action("online", "") end, "BOTTOMLEFT", 140, 14)
    button(win, "Done", 80, function() win:Hide() end, "BOTTOMRIGHT", -16, 14)

    win:SetScript("OnShow", function()
        if PlaySound then pcall(PlaySound, "igCharacterInfoOpen") end
        S.Request(false)
        S.Refresh()
    end)
    win:Hide()
end

function W.ToggleSocial()
    if not win then build() end
    if win:IsShown() then win:Hide() else win:Show() end
end

-- The "Friends across realms" box in the Leyline window (Leyline.lua) becomes a live summary with a button here.
function S.UpdateAdopted()
    local box = S.adopted
    if not box then return end
    local n = #S.rows
    box.text:SetText(n == 0 and "Your Leyline friends in game, in the launcher and on the website. Add someone with their Name#1234."
        or string.format("%d Leyline friend%s, %d online. Message them wherever they are.", n, n == 1 and "" or "s", S.online or 0))
end

function S.Adopt(box)
    S.adopted = box
    if box.soon then box.soon:SetText("") end
    box.add:SetText("Friends")
    box.add:SetScript("OnClick", function() W.ToggleSocial() end)
    box.add:Enable()
    S.UpdateAdopted()
end

-- A Leyline button on the game's own Friends window.
local function hookFriendsFrame()
    if S.hooked or not FriendsFrame then return end
    S.hooked = true
    local b = CreateFrame("Button", "WrathUnleashedSocialFriendsButton", FriendsFrame, "UIPanelButtonTemplate")
    b:SetWidth(76); b:SetHeight(20)
    b:SetText("Leyline")
    b:SetPoint("TOPRIGHT", FriendsFrame, "TOPRIGHT", -40, -44)
    b:SetScript("OnClick", function() W.ToggleSocial() end)
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:RegisterEvent("PLAYER_ENTERING_WORLD")
listener:SetScript("OnEvent", function(_, event, prefix, msg, channel, sender)
    if event == "CHAT_MSG_ADDON" then
        S.OnMessage(prefix, msg, channel, sender)
    else   -- entering the world: the Friends button, and the list (so the Leyline window's summary is ready)
        hookFriendsFrame()
        S.Request(false)
    end
end)
hookFriendsFrame()

SLASH_WUSOCIAL1, SLASH_WUSOCIAL2 = "/lfriends", "/leylinefriends"
SlashCmdList["WUSOCIAL"] = function() W.ToggleSocial() end

W.Social = S
S.Window, S.PREFIX = function() return win end, PREFIX
