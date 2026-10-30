-- Leyline (3.3.5a API): the in-game window of the Leyline network, in the Mods & Workshop panel's look.
--   Realms:  every Leyline realm (name, ruleset, players, online/offline), this one first. "Copy link" puts the
--            realm's link (PUBLIC_BASE/r/<id>) in the box to copy; "Join" hops there: the browser game reloads
--            on that realm. The home button (always at the bottom: "Back to Wrath", or "Back to Dalaran Hangout" with the Leyline brand on) hops home.
--   Friends across realms: the place for the global friends list (coming).
--   Your game folder: "Streamed: Dalaran, capitals, starting areas" or "Whole world: your game folder", and
--            "Use my game folder", which asks the page for the folder picker (GameFolder.lua).
-- Opened by Esc > Realm List, /leyline and /realms. "Host your own" opens the Host window (Host.lua): set up a realm,
-- and "Your realm" for its GM.
-- This realm is one row: its own relay listing (the Beacon of the same realm, e.g. the Dalaran Hangout's) is not a
-- second row. The realm says which listing that is (S:<id>:<live>, below); an older realm doesn't, so a listed realm
-- with this realm's own name is taken as it too. The row then keeps the listing's id: "Copy link" gives the relay
-- link in the desktop client (where the relay is how other clients come in) and the /wrath link in the browser.
--
-- The client can't make HTTP calls, so the realm sends the list (realm/custom/lua_scripts/ov_leyline.lua) as
-- addon messages, prefix WULY, whispered to yourself:
--   client -> server   L                                             send me the list
--   server -> client   B:<count>:<age seconds>                       a list begins
--                      R:<id>:<live 0|1>:<players|->:<bots|->:<ruleset>:<name>   one realm (id "this" = this realm)
--                      M:<id>:<flags>:<score>:<up|->:<build>:<region|->:<lang|->:<max|->:<tags>   the network fields
--                                                                    of the realm before it (flags F featured,
--                                                                    V verified, N new, S sample hangout, E region
--                                                                    estimated)
--                      N:<realms>:<players>:<bots>                   the network line
--                      E:<count>                                     the list is complete
--                      U:<text>                                      no list (e.g. "Realm list unavailable")
--                      S:<id>:<live 0|1>                             this realm's own relay listing (left out of the
--                                                                    R lines); before E
--
-- The order (the same on every Leyline surface): this realm first when it is a community realm; featured realms;
-- the Leyline Sample Hangout (our own realm, temporary); every other live realm by the network's fair score;
-- offline ones. Filters (build, rules tag, region, language, has players now) narrow the community realms; the
-- sample stays. "Host your own" and "Report" put the website's link in the box to copy.
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
local HOME_REALM = "WrathUnleashed"       -- GetRealmName() on Wrath itself (W.Brand.home while the brand is on)
-- The Leyline brand switch (WrathUnleashedUI.lua W.Brand, from the realm at login): the home realm's name.
local function brand() return W.Brand or { on = false, home = "Wrath", back = "Back to Wrath" } end
local HOP_WAIT = 8                        -- seconds: still here after this = no page took the hop
local WIN_W, WIN_H, ROW_H, ROWS = 560, 632, 34, 7
local SAMPLE_NAME = "Leyline Sample Hangout"
local SAMPLE_NOTE = "temporary"
local LIST_TOP = -98
local ASK_EVERY, ANSWER_WAIT = 30, 6     -- seconds: refresh at most this often; no answer after this = unavailable
local UNAVAILABLE = "Realm list unavailable"

local RULESETS = {
    main = "Level 1 or boost to 80", brawl = "Brawl: everyone 80", progression = "Progression",
    casual = "Casual", dalaran = "Dalaran hangout", custom = "Custom rules",
}

local TAGS = { blizzlike = "Blizzlike", boosted = "Boosted", custom = "Custom", pvp = "PvP", rp = "RP",
    hangout = "Hangout", bots = "Bots" }
local TAG_ORDER = { "blizzlike", "boosted", "custom", "pvp", "rp", "hangout", "bots" }
local BUILDS = { [5875] = "1.12.1", [8606] = "2.4.3", [12340] = "3.3.5a", [15595] = "4.3.4", [18414] = "5.4.8" }
local REGIONS = { ["na-east"] = "NA east", ["na-west"] = "NA west", sa = "S. America", eu = "Europe", africa = "Africa",
    me = "Middle East", asia = "Asia", oce = "Oceania" }

local win
-- state and the functions the tests reach (W.Leyline). all: every realm as sent; realms: what the window shows.
local L = { realms = {}, all = {}, status = "", offset = 0, filter = {} }

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end

local function button(parent, text, w, onClick, ...)
    if W.Style then local b = W.Style.Button(parent, text, w, onClick, nil, ...); b:SetHeight(22); return b end
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

-- The browser game's page publishes WUUI_GAMEFOLDER = { page = true, ... } (wrath-page.js); the desktop client has none.
function L.HasPage() return WUUI_PAGE == true or (type(WUUI_GAMEFOLDER) == "table" and WUUI_GAMEFOLDER.page == true) end

-- A row's link: this realm's is the /wrath page in the browser, its relay link in the desktop client when it is listed.
function L.RowLink(r)
    if r.id == "this" and r.relayId and not L.HasPage() then return L.Link(r.relayId) end
    return L.Link(r.id)
end

-- The Join button's text: "You're here" on this realm's row; "Join through the relay" only where that is how this
-- player would come back in (this realm listed on the relay, live, and no browser page: the desktop client), else Join.
function L.JoinText(r)
    if r.id ~= "this" then return "Join" end
    if r.relayId and r.relayLive and not L.HasPage() then return "Join through the relay" end
    return "You're here"
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

local function metaLine(rest)
    local id, flags, score, up, build, region, lang, maxp, tags =
        rest:match("^([%w]+):([%u%-]+):(%d+):([%d%-]+):(%d+):([%w%-]+):([%a%-]+):([%d%-]+):([%a,]*)$")
    if not id then return nil end
    local t = {}
    for x in tags:gmatch("%a+") do if TAGS[x] then t[#t + 1] = x end end
    return id, { featured = flags:find("F") ~= nil, verified = flags:find("V") ~= nil, new = flags:find("N") ~= nil,
        sample = flags:find("S") ~= nil, est = flags:find("E") ~= nil, score = tonumber(score) or 0,
        up = tonumber(up), build = BUILDS[tonumber(build) or 0] and tonumber(build) or 12340,
        region = REGIONS[region] and region or nil, lang = (lang:match("^%l%l%l?$") or lang:match("^%l%l%-%u%u$")) and lang or nil,
        maxp = tonumber(maxp), tags = t }
end

-- The filters: every value a community realm in the list has, in order.
local function values(key)
    local seen, out = {}, {}
    for _, r in ipairs(L.all) do
        if r.id ~= "this" then
            local vs = key == "tag" and (r.tags or {}) or { r[key] }
            for _, v in ipairs(vs) do
                if v ~= nil and not seen[v] then seen[v] = true; out[#out + 1] = v end
            end
        end
    end
    if key == "tag" then
        local ordered = {}
        for _, t in ipairs(TAG_ORDER) do if seen[t] then ordered[#ordered + 1] = t end end
        return ordered
    end
    table.sort(out, function(a, b)
        if type(a) == "number" and type(b) == "number" then return a < b end
        return tostring(a) < tostring(b)
    end)
    return out
end
L.Values = values

local function matches(r)
    local f = L.filter
    if f.build and (r.build or 12340) ~= f.build then return false end
    if f.region and r.region ~= f.region then return false end
    if f.lang and (r.lang or ""):sub(1, 2) ~= f.lang:sub(1, 2) then return false end
    if f.now and not (r.live and (r.players or 0) > 0) then return false end
    if f.tag then
        local has = false
        for _, t in ipairs(r.tags or {}) do if t == f.tag then has = true end end
        if not has then return false end
    end
    return true
end

-- What the window shows, in the network's order (see the top of this file).
local function sameName(a, b)
    if type(a) ~= "string" or type(b) ~= "string" then return false end
    local function k(x) return (x:lower():gsub("[^%w]", "")) end
    return k(a) ~= "" and k(a) == k(b)
end
L.SameName = sameName

-- This realm's own relay listing (the realm's S line, or a non-sample listing with this realm's name): merged into
-- the "this" row, never a row of its own.
local function isSelf(r, this)
    if not this or r.id == "this" or r.sample then return false end
    if L.selfId then return r.id == L.selfId end
    return sameName(r.name, this.name)
end
L.IsSelf = isSelf

function L.View()
    local this, sample, featured, rest, offline = nil, nil, {}, {}, {}
    for _, r in ipairs(L.all) do if r.id == "this" then this = r end end
    local thisSample = this and this.sample
    if this then this.relayId, this.relayLive = L.selfId, L.selfLive end
    for _, r in ipairs(L.all) do
        if r.id == "this" then
            -- placed below
        elseif isSelf(r, this) then
            this.relayId, this.relayLive = r.id, r.live
        elseif r.sample then
            if not thisSample then sample = r end   -- on the sample itself, its relay record is this realm again
        elseif matches(r) then
            if not r.live then offline[#offline + 1] = r
            elseif r.featured then featured[#featured + 1] = r
            else rest[#rest + 1] = r end
        end
    end
    local out = {}
    local function add(list) for _, r in ipairs(list) do out[#out + 1] = r end end
    if this and not thisSample then out[#out + 1] = this end
    add(featured)
    if thisSample then out[#out + 1] = this elseif sample then out[#out + 1] = sample end
    add(rest); add(offline)
    L.realms = out
    return out
end

function L.Cycle(key)
    if key == "now" then
        L.filter.now = not L.filter.now or nil
    else
        local vs, cur, nextv = values(key), L.filter[key], nil
        if cur == nil then nextv = vs[1] else
            for i, v in ipairs(vs) do if v == cur then nextv = vs[i + 1] end end
        end
        L.filter[key] = nextv
    end
    L.offset = 0
    L.View()
    L.Refresh()
end

local function networkLine(n)
    return string.format("%d realm%s · %d player%s online", n.realms, n.realms == 1 and "" or "s", n.players,
        n.players == 1 and "" or "s") .. (n.bots > 0 and (" · " .. n.bots .. " bots") or "")
end
L.NetworkLine = networkLine

function L.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local kind, rest = msg:match("^(%u):(.*)$")
    if kind == "B" then
        L.incoming, L.network, L.selfId, L.selfLive = {}, nil, nil, nil
        L.age = tonumber(rest:match(":(%d+)$") or "")
    elseif kind == "M" and L.incoming then
        local id, m = metaLine(rest)
        local last = L.incoming[#L.incoming]
        if id and last and last.id == id then
            for k, v in pairs(m) do last[k] = v end
        end
    elseif kind == "S" and L.incoming then
        local id, live = rest:match("^([a-z2-7]+):([01])$")
        if id and #id == 16 then L.selfId, L.selfLive = id, live == "1" end
    elseif kind == "N" and L.incoming then
        local n, p, b = rest:match("^(%d+):(%d+):(%d+)$")
        if n then L.network = { realms = tonumber(n), players = tonumber(p), bots = tonumber(b) } end
    elseif kind == "R" and L.incoming then
        local r = realmLine(rest)
        if r and #L.incoming < 100 then L.incoming[#L.incoming + 1] = r end
    elseif kind == "E" and L.incoming then
        L.all, L.incoming, L.waiting = L.incoming, nil, nil
        L.View()
        local n = 0
        for _, r in ipairs(L.realms) do if r.id ~= "this" then n = n + 1 end end
        local age = L.age and L.age >= 120 and string.format(" (updated %d min ago)", math.floor(L.age / 60)) or ""
        if L.network then
            setStatus(networkLine(L.network) .. "." .. age)
        else
            setStatus((n == 0 and "No other realms are open right now." or (n == 1 and "1 other realm" or (n .. " other realms")) .. " on Leyline.") .. age)
        end
        L.Refresh()
    elseif kind == "H" and L.hopping and rest == L.hopping.target then
        L.hopping.echoed = true   -- the page reloads the game on it now
    elseif kind == "U" then
        L.incoming, L.waiting, L.failed = nil, nil, true
        L.realms, L.all = {}, {}
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

-- The row's texts: the name (with the sample's label and the Featured / Verified / New badges), the rules line
-- (ruleset, then tags, build, region, language when the realm has them) and the state (with the uptime badge).
function L.Texts(r)
    local name = r.name
    if r.sample then name = (brand().on and brand().home or SAMPLE_NAME) .. " · " .. SAMPLE_NOTE end
    if r.id == "this" then name = name .. "  |cff8b5cf6(you are here)|r" end
    local badges = {}
    if r.featured then badges[#badges + 1] = "|cff8b5cf6Featured|r" end
    if r.verified then badges[#badges + 1] = "|cff4cc38aVerified|r" end
    if r.new then badges[#badges + 1] = "|cff5b8defNew|r" end
    if #badges > 0 then name = name .. "  " .. table.concat(badges, " ") end
    local extra = {}
    for _, t in ipairs(r.tags or {}) do if r.id ~= "this" or not r.sample then extra[#extra + 1] = TAGS[t] end end
    if r.build and r.build ~= 12340 then extra[#extra + 1] = BUILDS[r.build] end
    if r.region then extra[#extra + 1] = REGIONS[r.region] .. (r.est and "?" or "") end
    if r.lang then extra[#extra + 1] = r.lang end
    local rules = RULESETS[r.ruleset] .. (#extra > 0 and (" · " .. table.concat(extra, ", ")) or "")
    local state = r.live and "|cff4cc38aonline|r" or "|cff9aa3b5offline|r"
    if r.up then state = state .. " · " .. r.up .. "% up" end
    return name, rules, state
end

function L.Refresh()
    if not win then return end
    if win.filters then
        local f = L.filter
        win.filters.build:SetText("Build: " .. (f.build and BUILDS[f.build] or "any"))
        win.filters.tag:SetText("Rules: " .. (f.tag and TAGS[f.tag] or "any"))
        win.filters.region:SetText("Region: " .. (f.region and REGIONS[f.region] or "any"))
        win.filters.lang:SetText("Lang: " .. (f.lang or "any"))
        win.filters.now:SetText(f.now and "Has players" or "Everyone")
    end
    local n = #L.realms
    if L.offset > math.max(0, n - ROWS) then L.offset = math.max(0, n - ROWS) end
    for i, row in ipairs(win.rows) do
        local r = L.realms[L.offset + i]
        row.realm = r
        if r then
            local name, rules, state = L.Texts(r)
            row.name:SetText(name)
            row.rules:SetText(rules)
            row.players:SetText(players(r))
            row.state:SetText(state)
            row.join:SetText(L.JoinText(r))
            row.join:SetWidth(r.id == "this" and L.JoinText(r) ~= "Join" and 150 or 56)
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
    -- Home is our realm under any of its names: today's, the Sample Hangout's, and the Leyline brand's.
    return not ok or name == nil or name == HOME_REALM or name == "Leyline Sample Hangout"
        or name == "Dalaran Hangout" or (brand().on and name == brand().home)
end

-- Ask the page to reload the game on target ("wrath" or a relay realm id). False for anything else.
function L.Hop(target, name)
    if type(target) ~= "string" or not (target == "wrath" or (#target == 16 and target:match("^[a-z2-7]+$"))) then
        return false
    end
    WUUI_LEYLINE_HOP = target
    L.hopping = { target = target, name = name or brand().home, at = now() }
    if SendAddonMessage and UnitName then pcall(SendAddonMessage, PREFIX, "H:" .. target, "WHISPER", UnitName("player")) end
    if target == "wrath" then
        info(brand().back .. "... the game reloads there in a moment.")
    else
        info("Hopping to " .. (name or "that realm") .. "... the game reloads there in a moment. The first time, you "
            .. "make an account on that realm (or sign in to yours); the Dalaran Hangout uses your "
            .. (brand().on and "own" or "Wrath") .. " login.")
    end
    return true
end

-- "Host your own": the three steps, and the website's page in the box to copy.
L.HOST_LINK = PUBLIC_BASE .. "/wrath/realms#host-your-own"
function L.HostYourOwn()
    if W.Host and W.Host.Show then   -- Host.lua: set up a realm, and "Your realm" for its GM
        if win then win:Hide() end
        W.Host.Show(1)
        return true
    end
    info("Host your own realm: 1. Get the Leyline launcher and Docker. 2. Open Host, pick a profile and your rules. "
        .. "3. Make it public: it shows up here. The link has the details.")
    copy(L.HOST_LINK)
end

function L.ReportLink(id) return PUBLIC_BASE .. "/wrath/realms/report?realm=" .. id end
function L.Report(r)
    r = r or L.selected
    if not r or r.id == "this" or r.sample then
        info("Pick a community realm in the list (click its row), then Report.")
        return false
    end
    info("Open this link to report " .. r.name .. " to Leyline staff (you sign in on the website).")
    copy(L.ReportLink(r.id))
    return true
end

-- The brand can arrive after the window was made: relabel its home button then.
if W.OnBrand then
    W.OnBrand(function(b)
        if win and win.back then win.back:SetText(b.back); win.back:SetWidth(170) end
    end)
end

function L.Back()
    if L.OnWrath() then info("You're on " .. brand().home .. " now."); return false end
    return L.Hop("wrath", brand().home)
end

function L.Join(r)
    local link = L.RowLink(r)
    if r.id == "this" then
        if L.JoinText(r) == "Join through the relay" then
            info("You're on " .. r.name .. " now. Other clients come in through the relay: the link above (or "
                .. "leyline://realm/" .. r.relayId .. " in the Leyline launcher).")
        else
            info("You're on " .. r.name .. " now. Share the link above to bring friends here.")
        end
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
    if W.Style then
        local hl = row:CreateTexture(nil, "HIGHLIGHT")
        hl:SetTexture(W.Style.C.accent[1], W.Style.C.accent[2], W.Style.C.accent[3], 0.10)
        hl:SetAllPoints()
        local line = row:CreateTexture(nil, "BACKGROUND")
        line:SetTexture(W.Style.Unpack(W.Style.C.border))
        line:SetPoint("BOTTOMLEFT", 0, -1); line:SetPoint("BOTTOMRIGHT", 0, -1); line:SetHeight(1)
    else
        row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    end
    row.name = label(row, "", "GameFontNormal", "TOPLEFT", 4, -2)
    row.name:SetWidth(230)
    row.rules = label(row, "", "GameFontHighlightSmall", "TOPLEFT", row.name, "BOTTOMLEFT", 0, -2)
    row.rules:SetWidth(230)
    row.players = label(row, "", "GameFontHighlightSmall", "TOPLEFT", 244, -4)
    row.players:SetWidth(100)
    row.state = label(row, "", "GameFontHighlightSmall", "TOPLEFT", 244, -18)
    row.copyBtn = button(row, "Copy link", 80, function(self)
        local r = self:GetParent().realm
        if r then L.selected = r; win.info:SetText("The link to " .. r.name .. ". Ctrl+C copies it."); copy(L.RowLink(r)) end
    end, "RIGHT", -64, 0)
    row.join = button(row, "Join", 56, function(self)
        local r = self:GetParent().realm
        if r then L.Join(r) end
    end, "RIGHT", -4, 0)
    row:SetScript("OnClick", function(self)
        if self.realm then L.selected = self.realm; copy(L.RowLink(self.realm)) end
    end)
    row:Hide()
    return row
end

local function buildFriends(parent)
    local box = CreateFrame("Frame", nil, parent)
    box:SetPoint("BOTTOMLEFT", 16, 44); box:SetPoint("BOTTOMRIGHT", -16, 44)
    box:SetHeight(84)
    if W.Style then W.Style.Backdrop(box, W.Style.C.bg2) else box:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border", tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 } }) end
    box:SetBackdropColor(0, 0, 0, 0.45)
    label(box, "Friends across realms", "GameFontNormal", "TOPLEFT", 12, -10)
    box.soon = label(box, "Coming", "GameFontDisableSmall", "TOPRIGHT", -12, -12)
    box.text = label(box, "Your Leyline friends on every realm in one list: who's online, where they are, "
        .. "and a click to join them.", "GameFontHighlightSmall", "TOPLEFT", 12, -30)
    box.text:SetWidth(WIN_W - 60)
    box.list = CreateFrame("Frame", nil, box)   -- the rows go here when friends arrive
    box.list:SetPoint("TOPLEFT", 12, -50); box.list:SetPoint("BOTTOMRIGHT", -12, 8)
    box.add = button(box, "Add a friend", 110, function() end, "BOTTOMRIGHT", -10, 8)
    box.add:Disable()
    if W.Social and W.Social.Adopt then W.Social.Adopt(box) end   -- Leyline friends (Social.lua)
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
    if not W.Style then   -- Style.lua draws the window (S.Window, at its title)
        win:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    end
    win:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = win:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.094, 0.106, 0.137, 0.97)   -- #181b23 (Style.lua)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    local _ = (W.Style and W.Style.Window(win, "Leyline") or label(win, "Leyline", "GameFontNormalLarge", "TOP", 0, -18))
    local close = (W.Style and W.Style.Close(win) or CreateFrame("Button", nil, win, "UIPanelCloseButton"))
    close:SetPoint("TOPRIGHT", -6, -6)
    button(win, "Done", 90, function() win:Hide() end, "BOTTOMRIGHT", -16, 14)
    win.back = button(win, brand().back, brand().on and 170 or 120, function() L.Back() end, "BOTTOMLEFT", 16, 14)
    win.host = button(win, "Host your own", 120, function() L.HostYourOwn() end, "BOTTOM", 0, 14)
    if W.Style then W.Style.SetKind(win.host, "primary") end
    tinsert(UISpecialFrames, "WrathUnleashedLeylineFrame")   -- Esc closes it

    label(win, "Realms", "GameFontNormal", "TOPLEFT", 20, -46)
    win.status = label(win, L.status, "GameFontHighlightSmall", "TOPLEFT", 84, -48)
    win.status:SetWidth(WIN_W - 200)
    win.refresh = button(win, "Refresh", 80, function() L.Request(true) end, "TOPRIGHT", -20, -42)

    -- filters: each button steps through the values the listed realms have, then back to "any"
    win.filters = {
        build = button(win, "Build: any", 104, function() L.Cycle("build") end, "TOPLEFT", 20, -68),
        tag = button(win, "Rules: any", 104, function() L.Cycle("tag") end, "TOPLEFT", 126, -68),
        region = button(win, "Region: any", 118, function() L.Cycle("region") end, "TOPLEFT", 232, -68),
        lang = button(win, "Lang: any", 90, function() L.Cycle("lang") end, "TOPLEFT", 352, -68),
        now = button(win, "Everyone", 86, function() L.Cycle("now") end, "TOPLEFT", 444, -68),
    }

    win.list = CreateFrame("Frame", nil, win)
    win.list:SetWidth(WIN_W - 40); win.list:SetHeight(ROWS * ROW_H)
    win.list:SetPoint("TOPLEFT", 20, LIST_TOP)
    win.list:EnableMouseWheel(true)
    win.list:SetScript("OnMouseWheel", function(_, delta)
        L.offset = math.max(0, L.offset - delta); L.Refresh()
    end)
    win.rows = {}
    for i = 1, ROWS do win.rows[i] = buildRow(i) end
    local listBottom = LIST_TOP - ROWS * ROW_H
    win.count = label(win, "", "GameFontHighlightSmall", "TOPLEFT", 20, listBottom - 8)
    button(win, "Up", 50, function() L.offset = math.max(0, L.offset - ROWS); L.Refresh() end,
        "TOPRIGHT", -76, listBottom - 4)
    button(win, "Down", 50, function() L.offset = L.offset + ROWS; L.Refresh() end, "TOPRIGHT", -20, listBottom - 4)
    win.report = button(win, "Report", 64, function() L.Report() end, "TOPRIGHT", -132, listBottom - 4)

    local box = W.Style and W.Style.Input(win, WIN_W - 50, 20) or CreateFrame("EditBox", nil, win, "InputBoxTemplate")
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
            info(h.target == "wrath" and "Hopping works in the browser game. Open " .. L.Link("this") .. " to play on " .. brand().home .. "."
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

-- Esc > Realm List (ModsPanel.lua's game menu button): always shows the window.
function W.ShowRealmList()
    if not win then build() end
    win:Show()
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) L.OnMessage(prefix, msg, channel, sender) end)

SLASH_WULEYLINE1, SLASH_WULEYLINE2 = "/leyline", "/realms"
SlashCmdList["WULEYLINE"] = function() W.ToggleLeyline() end

W.Leyline = L
L.Window, L.PUBLIC_BASE, L.PREFIX, L.HOP_WAIT = function() return win end, PUBLIC_BASE, PREFIX, HOP_WAIT
