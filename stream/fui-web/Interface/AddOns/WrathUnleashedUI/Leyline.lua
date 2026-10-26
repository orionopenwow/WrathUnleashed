-- Leyline (3.3.5a API): the in-game window of the Leyline network, in the Mods & Workshop panel's look.
--   Realms:  every Leyline realm (name, ruleset, players, online/offline), this one first. "Copy link" puts the
--            realm's link (PUBLIC_BASE/r/<id>) in the box to copy; "Join" hops there: the browser game reloads
--            on that realm. "Back to Wrath" (always at the bottom) hops home.
--   Friends across realms: the place for the global friends list (coming).
--   Your game folder: "Streamed: Dalaran, capitals, starting areas" or "Whole world: your game folder", and
--            "Use my game folder", which asks the page for the folder picker (GameFolder.lua).
-- Opened by Esc > Mods & Workshop > Leyline realms, /leyline and /realms.
--
-- The client can't make HTTP calls, so the realm sends the list (realm/custom/lua_scripts/ov_leyline.lua) as
-- addon messages, prefix WULY, whispered to yourself:
--   client -> server   L                                             send me the list
--   server -> client   B:<count>:<age seconds>                       a list begins
--                      R:<id>:<live 0|1>:<players|->:<bots|->:<ruleset>:<name>   one realm (id "this" = this realm)
--                      E:<count>                                     the list is complete
--                      U:<text>                                      no list (e.g. "Realm list unavailable")
--   client -> server   H:<id|wrath>                                  hop there
--   server -> client   H:<id|wrath>                                  echoed back
--
-- Hopping: the addon can't navigate, so it asks the page. Join sends H:<id> to the realm, which echoes it; the
-- browser page (stream/www-files/wrath-page.js) watches CHAT_MSG_ADDON through the game bridge and reloads the
-- game at /wrath?go=r:<id>. It also sets the global WUUI_LEYLINE_HOP, which the page reads (and clears) through
-- the bridge, so a hop works on a realm whose server doesn't echo (a Beacon without ov_leyline.lua). The desktop
-- client has no page: after HOP_WAIT seconds the window says to open the link instead.

local W = WrathUnleashedUI
-- The public site. Links are PUBLIC_BASE .. "/r/<id>"; a future Leyline domain is this one line.
local PUBLIC_BASE = "https://play.openvanilla.app"
local THIS_REALM_PATH = "/wrath"
local PREFIX = "WULY"
local HOME_REALM = "WrathUnleashed"       -- GetRealmName() on Wrath itself
local HOP_WAIT = 8                        -- seconds: still here after this = no page took the hop
local WIN_W, WIN_H, ROW_H, ROWS = 560, 600, 34, 7
local ASK_EVERY, ANSWER_WAIT = 30, 6     -- seconds: refresh at most this often; no answer after this = unavailable
local UNAVAILABLE = "Realm list unavailable"

local RULESETS = {
    main = "Level 1 or boost to 80", brawl = "Brawl: everyone 80", progression = "Progression",
    casual = "Casual", dalaran = "Dalaran hangout", custom = "Custom rules",
}

local win
local L = { realms = {}, status = "", offset = 0 }   -- state and the functions the tests reach (W.Leyline)

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

function L.Link(id)
    if id == "this" then return PUBLIC_BASE .. THIS_REALM_PATH end
    return PUBLIC_BASE .. "/r/" .. id
end

-- ---------------------------------------------------------------- Data

local function setStatus(text)
    L.status = text or ""
    if win then win.status:SetText(L.status) end
end

function L.Request(force)
    if not force and L.askedAt and now() - L.askedAt < ASK_EVERY and not L.failed then return false end
    if not SendAddonMessage or not UnitName then setStatus(UNAVAILABLE); return false end
    L.askedAt, L.waiting, L.failed = now(), true, nil
    setStatus("Asking the realm for the Leyline list...")
    pcall(SendAddonMessage, PREFIX, "L", "WHISPER", UnitName("player"))
    return true
end

local function realmLine(rest)
    local id, live, players, bots, ruleset, name = rest:match("^([%w]+):([01]):([%d%-]+):([%d%-]+):(%a+):(.*)$")
    if not id or not (id == "this" or id:match("^[a-z2-7]+$")) then return nil end
    name = name:gsub("|", ""):sub(1, 40)
    return { id = id, live = live == "1", players = tonumber(players), bots = tonumber(bots),
        ruleset = RULESETS[ruleset] and ruleset or "custom", name = name ~= "" and name or "Unnamed realm" }
end

function L.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local kind, rest = msg:match("^(%u):(.*)$")
    if kind == "B" then
        L.incoming = {}
        L.age = tonumber(rest:match(":(%d+)$") or "")
    elseif kind == "R" and L.incoming then
        local r = realmLine(rest)
        if r and #L.incoming < 100 then L.incoming[#L.incoming + 1] = r end
    elseif kind == "E" and L.incoming then
        L.realms, L.incoming, L.waiting = L.incoming, nil, nil
        local n = 0
        for _, r in ipairs(L.realms) do if r.id ~= "this" then n = n + 1 end end
        local age = L.age and L.age >= 120 and string.format(" (updated %d min ago)", math.floor(L.age / 60)) or ""
        setStatus((n == 0 and "No other realms are open right now." or (n == 1 and "1 other realm" or (n .. " other realms")) .. " on Leyline.") .. age)
        L.Refresh()
    elseif kind == "H" and L.hopping and rest == L.hopping.target then
        L.hopping.echoed = true   -- the page reloads the game on it now
    elseif kind == "U" then
        L.incoming, L.waiting, L.failed = nil, nil, true
        L.realms = {}
        setStatus(rest ~= "" and rest:gsub("|", "") or UNAVAILABLE)
        L.Refresh()
    end
end

-- ---------------------------------------------------------------- Window

local function players(r)
    if not r.live then return "" end
    if not r.players then return "" end
    return r.players .. " playing" .. ((r.bots and r.bots > 0) and (" +" .. r.bots .. " bots") or "")
end

local function copy(text)
    local box = win.copy
    box.fixed = text; box:SetText(text); box:SetFocus(); box:HighlightText()
end

function L.Refresh()
    if not win then return end
    local n = #L.realms
    if L.offset > math.max(0, n - ROWS) then L.offset = math.max(0, n - ROWS) end
    for i, row in ipairs(win.rows) do
        local r = L.realms[L.offset + i]
        row.realm = r
        if r then
            row.name:SetText(r.id == "this" and (r.name .. "  |cff8fd3ff(you are here)|r") or r.name)
            row.rules:SetText(RULESETS[r.ruleset])
            row.players:SetText(players(r))
            row.state:SetText(r.live and "|cff40ff40online|r" or "|cff9d9d9doffline|r")
            row:Show()
        else
            row:Hide()
        end
    end
    win.count:SetText(n > ROWS and string.format("%d-%d of %d", L.offset + 1, math.min(n, L.offset + ROWS), n) or "")
end

local function info(text) if win then win.info:SetText(text) end end

function L.OnWrath()
    if not GetRealmName then return true end
    local ok, name = pcall(GetRealmName)
    return not ok or name == nil or name == HOME_REALM
end

-- Ask the page to reload the game on target ("wrath" or a relay realm id). False for anything else.
function L.Hop(target, name)
    if type(target) ~= "string" or not (target == "wrath" or (#target == 16 and target:match("^[a-z2-7]+$"))) then
        return false
    end
    WUUI_LEYLINE_HOP = target
    L.hopping = { target = target, name = name or "Wrath", at = now() }
    if SendAddonMessage and UnitName then pcall(SendAddonMessage, PREFIX, "H:" .. target, "WHISPER", UnitName("player")) end
    if target == "wrath" then
        info("Back to Wrath... the game reloads there in a moment.")
    else
        info("Hopping to " .. (name or "that realm") .. "... the game reloads there in a moment. The first time, you "
            .. "make an account on that realm (or sign in to yours); the Dalaran Hangout uses your Wrath login.")
    end
    return true
end

function L.Back()
    if L.OnWrath() then info("You're on Wrath now."); return false end
    return L.Hop("wrath", "Wrath")
end

function L.Join(r)
    local link = L.Link(r.id)
    if r.id == "this" then
        info("You're on " .. r.name .. " now. Share the link above to bring friends here.")
    elseif not r.live then
        info(r.name .. " is offline right now. Its link is above: try again later.")
    else
        L.Hop(r.id, r.name)
    end
    copy(link)
end

local function buildRow(i)
    local row = CreateFrame("Button", nil, win.list)
    row:SetWidth(WIN_W - 40); row:SetHeight(ROW_H - 2)
    row:SetPoint("TOPLEFT", 0, -(i - 1) * ROW_H)
    row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    row.name = label(row, "", "GameFontNormal", "TOPLEFT", 4, -2)
    row.name:SetWidth(230)
    row.rules = label(row, "", "GameFontHighlightSmall", "TOPLEFT", row.name, "BOTTOMLEFT", 0, -2)
    row.rules:SetWidth(230)
    row.players = label(row, "", "GameFontHighlightSmall", "TOPLEFT", 244, -4)
    row.players:SetWidth(100)
    row.state = label(row, "", "GameFontHighlightSmall", "TOPLEFT", 244, -18)
    row.copyBtn = button(row, "Copy link", 80, function(self)
        local r = self:GetParent().realm
        if r then win.info:SetText("The link to " .. r.name .. ". Ctrl+C copies it."); copy(L.Link(r.id)) end
    end, "RIGHT", -64, 0)
    row.join = button(row, "Join", 56, function(self)
        local r = self:GetParent().realm
        if r then L.Join(r) end
    end, "RIGHT", -4, 0)
    row:SetScript("OnClick", function(self) if self.realm then copy(L.Link(self.realm.id)) end end)
    row:Hide()
    return row
end

local function buildFriends(parent)
    local box = CreateFrame("Frame", nil, parent)
    box:SetPoint("BOTTOMLEFT", 16, 44); box:SetPoint("BOTTOMRIGHT", -16, 44)
    box:SetHeight(84)
    box:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } })
    box:SetBackdropColor(0, 0, 0, 0.45)
    label(box, "Friends across realms", "GameFontNormal", "TOPLEFT", 12, -10)
    label(box, "Coming", "GameFontDisableSmall", "TOPRIGHT", -12, -12)
    box.text = label(box, "Your Leyline friends on every realm in one list: who's online, where they are, "
        .. "and a click to join them.", "GameFontHighlightSmall", "TOPLEFT", 12, -30)
    box.text:SetWidth(WIN_W - 60)
    box.list = CreateFrame("Frame", nil, box)   -- the rows go here when friends arrive
    box.list:SetPoint("TOPLEFT", 12, -50); box.list:SetPoint("BOTTOMRIGHT", -12, 8)
    box.add = button(box, "Add a friend", 110, function() end, "BOTTOMRIGHT", -10, 8)
    box.add:Disable()
    return box
end

local function build()
    win = CreateFrame("Frame", "WrathUnleashedLeylineFrame", UIParent)
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
    label(win, "Leyline", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, win, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    button(win, "Done", 90, function() win:Hide() end, "BOTTOMRIGHT", -16, 14)
    win.back = button(win, "Back to Wrath", 120, function() L.Back() end, "BOTTOMLEFT", 16, 14)
    tinsert(UISpecialFrames, "WrathUnleashedLeylineFrame")   -- Esc closes it

    label(win, "Realms", "GameFontNormal", "TOPLEFT", 20, -46)
    win.status = label(win, L.status, "GameFontHighlightSmall", "TOPLEFT", 84, -48)
    win.status:SetWidth(WIN_W - 200)
    win.refresh = button(win, "Refresh", 80, function() L.Request(true) end, "TOPRIGHT", -20, -42)

    win.list = CreateFrame("Frame", nil, win)
    win.list:SetWidth(WIN_W - 40); win.list:SetHeight(ROWS * ROW_H)
    win.list:SetPoint("TOPLEFT", 20, -70)
    win.list:EnableMouseWheel(true)
    win.list:SetScript("OnMouseWheel", function(_, delta)
        L.offset = math.max(0, L.offset - delta); L.Refresh()
    end)
    win.rows = {}
    for i = 1, ROWS do win.rows[i] = buildRow(i) end
    local listBottom = -70 - ROWS * ROW_H
    win.count = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 20, listBottom - 8)
    button(win, "Up", 50, function() L.offset = math.max(0, L.offset - ROWS); L.Refresh() end,
        "TOPRIGHT", -76, listBottom - 4)
    button(win, "Down", 50, function() L.offset = L.offset + ROWS; L.Refresh() end, "TOPRIGHT", -20, listBottom - 4)

    local box = CreateFrame("EditBox", nil, win, "InputBoxTemplate")
    box:SetWidth(WIN_W - 50); box:SetHeight(20)
    box:SetPoint("TOPLEFT", 26, listBottom - 34)
    box:SetAutoFocus(false)
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    box:SetScript("OnTextChanged", function(self) if self.fixed and self:GetText() ~= self.fixed then self:SetText(self.fixed) end end)
    win.copy = box
    win.info = label(win, "Copy link puts a realm's link here; Ctrl+C copies it. Anyone with the link can play there "
        .. "in their browser.", "GameFontHighlightSmall", "TOPLEFT", 22, listBottom - 58)
    win.info:SetWidth(WIN_W - 44)

    -- Your game folder (GameFolder.lua): streamed places, or the whole world from the player's own folder.
    if W.GameFolder then win.folder = W.GameFolder.Attach(win, listBottom - 98, WIN_W) end

    win.friends = buildFriends(win)

    -- No answer from the realm in time: say so (and let Refresh try again).
    win:SetScript("OnUpdate", function()
        if L.waiting and L.askedAt and now() - L.askedAt > ANSWER_WAIT then
            L.waiting, L.failed, L.incoming = nil, true, nil
            setStatus(UNAVAILABLE)
        end
        if L.hopping and now() - L.hopping.at > HOP_WAIT then   -- no page took it (the desktop client)
            local h = L.hopping
            L.hopping, WUUI_LEYLINE_HOP = nil, nil
            info(h.target == "wrath" and "Hopping works in the browser game. Open " .. L.Link("this") .. " to play on Wrath."
                or "Hopping works in the browser game. Open the link above to play on " .. h.name .. ".")
        end
    end)
    win:SetScript("OnShow", function()
        if PlaySound then pcall(PlaySound, "igCharacterInfoOpen") end
        L.Request(false)
        L.Refresh()
    end)
    win:Hide()
end

function W.ToggleLeyline()
    if not win then build() end
    if win:IsShown() then win:Hide() else win:Show() end
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) L.OnMessage(prefix, msg, channel, sender) end)

SLASH_WULEYLINE1, SLASH_WULEYLINE2 = "/leyline", "/realms"
SlashCmdList["WULEYLINE"] = function() W.ToggleLeyline() end

W.Leyline = L
L.Window, L.PUBLIC_BASE, L.PREFIX, L.HOP_WAIT = function() return win end, PUBLIC_BASE, PREFIX, HOP_WAIT
