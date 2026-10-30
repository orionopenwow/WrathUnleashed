-- Host.lua (3.3.5a API): "Host your own realm", in game. Opened from the Leyline realm window (Esc > Realm List >
-- Host your own) or /host.
--
-- Set up a realm: every choice the host kit takes (hosting/kit/tools/wuhost/setup.py, cores.py; docs/HOST-ANY-CLIENT.md)
--   core and ruleset, realm name, type, rates (XP / loot / reputation), start (level 1 or the boost), bots, public or
--   private, sign-up, Hero Key sign-in, region, language, tags, max players. The game can't start programs, so
--   "Start hosting" hands the choices over, as one query string (H.Query; the same names and checks as
--   stream/hostflow.py prefill() and launcher/src-tauri/src/deeplink.rs host_query()):
--     the browser game: the page (stream/www-files/wrath-page.js watchHostAsk) takes the global WUUI_LEYLINE_HOST
--       and offers the website's host page, /wrath/host?<query>, filled in (the realm key is made on the host's PC);
--     the desktop client: leyline://host?<query> (the launcher's Host page) and the website link, in the box to copy.
-- Your realm: on your own realm as its GM, the realm half (realm/custom/lua_scripts/ov_hostctl.lua) answers over the
--   Open Mod API (OVMOD, mod "wuhost"): status, announce, message of the day, kick / ban / unban, the allow list, a
--   restart with a five-minute warning (two clicks, never instant). Bots, rates, sign-up, the Leyline list and the
--   invite link change on the host's PC: those buttons put leyline://host?manage=<what> in the box (the launcher's
--   Host page). The server checks the GM level on every action; this window only hides what it can't use.

local W = WrathUnleashedUI
local H = {}
W.Host = H

local PUBLIC_BASE = "https://play.openvanilla.app"
local WIN_W, WIN_H, ROW = 560, 632, 26
local PAGE_WAIT = 8          -- seconds: the page didn't take the hand-over by then = no page (the desktop client)
local SEND_EVERY = 1         -- seconds between control messages from this window (the realm limits too)

-- ---------------------------------------------------------------- the choices (the host kit's own values)

H.CORES = { "azerothcore", "cmangos" }
H.CORE_LABEL = { azerothcore = "AzerothCore", cmangos = "CMaNGOS" }
H.CORES_COMING = "TrinityCore, VMaNGOS: coming"
H.PRESETS = {
    azerothcore = { "dalaran", "main", "brawl", "progression" },
    cmangos = { "cmangos-1.12.1", "cmangos-2.4.3" },
}
H.PRESET_LABEL = {
    dalaran = "Dalaran hangout", main = "Classic levelling", brawl = "Brawl: everyone 80", progression = "Progression",
    ["cmangos-1.12.1"] = "CMaNGOS Classic", ["cmangos-2.4.3"] = "CMaNGOS TBC",
}
H.TYPES = { "normal", "pvp", "rp", "rppvp" }
H.TYPE_LABEL = { normal = "Normal", pvp = "PvP", rp = "RP", rppvp = "RP-PvP" }
H.RATES = { 0, 1, 2, 3, 5, 10 }            -- 0 = the ruleset's own
H.BOTS = { 0, 10, 20, 40, 80, 150 }
H.SIGNUP = { "open", "invite", "off" }
H.SIGNUP_LABEL = { open = "Open: anyone", invite = "Invite link only", off = "Closed" }
H.REGIONS = { "", "na-east", "na-west", "sa", "eu", "africa", "me", "asia", "oce" }
H.REGION_LABEL = { [""] = "not set", ["na-east"] = "NA east", ["na-west"] = "NA west", sa = "S. America", eu = "Europe",
    africa = "Africa", me = "Middle East", asia = "Asia", oce = "Oceania" }
H.LANGS = { "", "en", "de", "fr", "es", "pt-BR", "ru", "it", "pl", "zh", "ko" }
H.TAGS = { "blizzlike", "boosted", "custom", "pvp", "rp", "hangout" }
H.TAG_LABEL = { blizzlike = "Blizzlike", boosted = "Boosted", custom = "Custom", pvp = "PvP", rp = "RP", hangout = "Hangout" }
H.MANAGE = { bots = "Bots", rates = "Rates", signup = "Sign-up", list = "Leyline list", invite = "Invite link" }
H.MANAGE_ORDER = { "bots", "rates", "signup", "list", "invite" }

-- What each ruleset fixes (setup.py PROFILES / PROFILE_BOTS / PROFILE_TAGS).
local FIXED = {
    dalaran = { start = "Boost to 80 in Dalaran", bots = false, tags = { "hangout", "boosted" } },
    main = { start = nil, bots = true, tags = { "boosted" } },
    brawl = { start = "Everyone starts at 80", bots = true, tags = { "boosted", "pvp", "custom" } },
    progression = { start = "Level 1, one world at a time", bots = true, tags = { "blizzlike" } },
    ["cmangos-1.12.1"] = { start = "Level 1", bots = false, rates = false, tags = { "blizzlike" } },
    ["cmangos-2.4.3"] = { start = "Level 1", bots = false, rates = false, tags = { "blizzlike" } },
}
H.FIXED = FIXED

function H.Defaults()
    return { core = "azerothcore", preset = "dalaran", name = "", type = "normal", xp = 0, loot = 0, rep = 0,
        start = "boost", bots = 0, vis = "public", signup = "open", herokey = "off", region = "", lang = "",
        tags = { hangout = true, boosted = true }, max = 0 }
end
H.opts = H.Defaults()

local function has(list, v) for _, x in ipairs(list) do if x == v then return true end end return false end

local BANNED = { "world%s*of%s*warcraft", "warcraft", "lich%s*king", "blizzard", "%f[%a]wow%f[%A]" }

-- The checks (the same as hostflow.py and deeplink.rs): nil when fine, else { field = message } and the first one.
function H.Validate(o)
    local e, first = {}, nil
    local function bad(k, m) e[k] = m; first = first or m end
    if not has(H.CORES, o.core) then bad("core", "Pick a core.") end
    if not has(H.PRESETS[o.core] or {}, o.preset) then bad("preset", "Pick a ruleset for that core.") end
    local name = type(o.name) == "string" and o.name:gsub("^%s+", ""):gsub("%s+$", "") or ""
    if name == "" then bad("name", "Give your realm a name.")
    elseif #name > 32 or not name:match("^[A-Za-z0-9 _'%-]+$") then bad("name", "Realm names: up to 32 letters, digits, spaces, _ ' or -.")
    else
        for _, p in ipairs(BANNED) do if name:lower():find(p) then bad("name", "Leave game and publisher names out: pick your own.") break end end
    end
    if not has(H.TYPES, o.type) then bad("type", "Pick a realm type.") end
    local fixed = FIXED[o.preset] or {}
    for _, k in ipairs({ "xp", "loot", "rep" }) do
        local v = tonumber(o[k])
        if not v or v < 0 or v > 10 or v ~= math.floor(v) then bad(k, "Rates: 1x to 10x.")
        elseif v > 0 and fixed.rates == false then bad(k, "Rates are set by the ruleset on this core.") end
    end
    if o.preset == "main" and o.start ~= "level1" and o.start ~= "boost" then bad("start", "Start at level 1 or with the boost.") end
    local b = tonumber(o.bots)
    if not b or b < 0 or b > 200 or b ~= math.floor(b) then bad("bots", "Bots: 0 to 200.")
    elseif b > 0 and not fixed.bots then bad("bots", "This ruleset runs without bots.") end
    if o.vis ~= "public" and o.vis ~= "private" then bad("vis", "Public or private.") end
    if not has(H.SIGNUP, o.signup) then bad("signup", "Pick who can make accounts.") end
    if o.herokey ~= "on" and o.herokey ~= "off" then bad("herokey", "Hero Key sign-in: on or off.") end
    if not has(H.REGIONS, o.region or "") then bad("region", "Pick a region.") end
    if not has(H.LANGS, o.lang or "") then bad("lang", "Pick a language.") end
    for t in pairs(o.tags or {}) do if not has(H.TAGS, t) then bad("tags", "Unknown tag.") end end
    local m = tonumber(o.max)
    if not m or m < 0 or m > 10000 or m ~= math.floor(m) then bad("max", "Max players: 0 (not shown) to 10000.") end
    if first then return e, first end
    return nil
end

local function enc(s)
    return (tostring(s):gsub("[^A-Za-z0-9%-_%.~]", function(c) return string.format("%%%02X", c:byte()) end))
end
H.Encode = enc

-- The query string, always in this order (the page, the website and the launcher check the same names).
function H.Query(o)
    local q = {}
    local function add(k, v) q[#q + 1] = k .. "=" .. enc(v) end
    add("core", o.core); add("preset", o.preset); add("name", (o.name:gsub("^%s+", ""):gsub("%s+$", "")))
    add("type", o.type)
    if (FIXED[o.preset] or {}).rates ~= false then
        for _, k in ipairs({ "xp", "loot", "rep" }) do if (tonumber(o[k]) or 0) > 0 then add(k, o[k]) end end
    end
    if o.preset == "main" then add("start", o.start) end
    if (FIXED[o.preset] or {}).bots then add("bots", o.bots) end
    add("vis", o.vis); add("signup", o.signup); add("herokey", o.herokey)
    if o.region ~= "" then add("region", o.region) end
    if o.lang ~= "" then add("lang", o.lang) end
    local tags = {}
    for _, t in ipairs(H.TAGS) do if o.tags and o.tags[t] then tags[#tags + 1] = t end end
    if #tags > 0 then add("tags", table.concat(tags, ",")) end
    if (tonumber(o.max) or 0) > 0 then add("max", o.max) end
    return table.concat(q, "&")
end

function H.WebLink(o) return PUBLIC_BASE .. "/wrath/host?" .. H.Query(o) end
function H.DeepLink(o) return "leyline://host?" .. H.Query(o) end
function H.ManageLink(what) return H.MANAGE[what] and ("leyline://host?manage=" .. what) or nil end

-- The browser game's page sets WUUI_PAGE = true (and WUUI_GAMEFOLDER = { page = true, ... }) every second (wrath-page.js).
function H.HasPage() return WUUI_PAGE == true or (type(WUUI_GAMEFOLDER) == "table" and WUUI_GAMEFOLDER.page == true) end

local function now() return (GetTime and GetTime()) or 0 end

-- ---------------------------------------------------------------- the realm half (OVMOD "wuhost")

H.status = nil       -- the last status: { gm = bool, ... }
local lastSend = -1e9
function H.Send(action, data)
    if not SendAddonMessage or not UnitName then return false end
    if action ~= "status" and now() - lastSend < SEND_EVERY then return false end
    if action ~= "status" then lastSend = now() end
    data = tostring(data or ""):gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("[\t\n|]", " ")
    if action == "ban" or action == "allow" then data = data:gsub(" ", "\t", 1) end
    pcall(SendAddonMessage, "OVMOD", "wuhost\t" .. action .. "\t1/1\t" .. data:sub(1, 200), "WHISPER", UnitName("player"))
    return true
end

function H.ParseStatus(data)
    local s = {}
    for line in (data or ""):gmatch("[^\n]+") do
        local k, v = line:match("^(%w+)=(.*)$")
        if k then s[k] = v end
    end
    s.gm = s.gm == "1"
    return s
end

local win
local function info(text) H.lastInfo = text; if win and win.info then win.info:SetText(text) end end
local function copy(text)
    H.lastCopy = text
    if not win or not win.copy then return end
    local box = win.copy
    box.fixed = text; box:SetText(text); box:SetFocus(); box:HighlightText()
end
H.Info, H.Copy = info, copy

local refreshControl   -- set by the window

function H.OnMessage(prefix, msg, channel, sender)
    if prefix ~= "OVMOD" or channel ~= "WHISPER" or type(msg) ~= "string" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local kind, data = msg:match("^wuhost\t(%a+)\t1/1\t(.*)$")
    if not kind then return end
    if kind == "status" then
        H.status = H.ParseStatus(data)
        if refreshControl then refreshControl() end
    elseif kind == "ok" or kind == "err" then
        local t = data:gsub("|", "")
        H.lastReply = { kind = kind, text = t }
        if win and win.control then
            win.control.reply:SetText((kind == "ok" and (W.Style and W.Style.Hex("ok") or "") or (W.Style and W.Style.Hex("danger") or ""))
                .. t .. "|r")
        end
        H.Send("status")
    end
end

-- ---------------------------------------------------------------- Start hosting

function H.Start(o)
    o = o or H.opts
    local errs, first = H.Validate(o)
    if errs then info(first); return false, first end
    local q = H.Query(o)
    if H.HasPage() then
        WUUI_LEYLINE_HOST = q
        H.handing = { at = now() }
        info("Your browser shows \"Open the host page\" at the bottom: click it to make your realm on the website, "
            .. "then start it on your PC with the file it gives you. The link is below too.")
        copy(H.WebLink(o))
    else
        info("Open this in the Leyline launcher (Host page, filled in), or the website link (Copy website link). "
            .. "Ctrl+C copies it.")
        copy(H.DeepLink(o))
    end
    return true, q
end

-- ---------------------------------------------------------------- the window

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end
local function button(parent, text, w, onClick, kind, ...)
    if W.Style then return W.Style.Button(parent, text, w, onClick, kind, ...) end
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(22); b:SetText(text); b:SetPoint(...); b:SetScript("OnClick", onClick)
    return b
end
local function input(parent, w, ...)
    local e = W.Style and W.Style.Input(parent, w, 22) or CreateFrame("EditBox", nil, parent, "InputBoxTemplate")
    e:SetWidth(w); e:SetHeight(22); e:SetPoint(...); e:SetAutoFocus(false)
    e:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    return e
end
local function muted(fs) if W.Style then W.Style.Muted(fs) end return fs end

local function step(list, cur, dir)
    for i, v in ipairs(list) do
        if v == cur then return list[((i - 1 + (dir or 1)) % #list) + 1] end
    end
    return list[1]
end
H.Step = step

local function rateText(v) return (tonumber(v) or 0) == 0 and "ruleset" or (v .. "x") end

-- Every control's text from H.opts (and what the ruleset fixes).
local function refreshSetup()
    if not win then return end
    local o, s = H.opts, win.setup
    local fixed = FIXED[o.preset] or {}
    s.core:SetText(H.CORE_LABEL[o.core])
    s.preset:SetText(H.PRESET_LABEL[o.preset])
    s.type:SetText(H.TYPE_LABEL[o.type])
    for _, k in ipairs({ "xp", "loot", "rep" }) do
        s[k]:SetText((k == "xp" and "XP " or k == "loot" and "Loot " or "Rep ") .. rateText(o[k]))
        if fixed.rates == false then s[k]:Disable() else s[k]:Enable() end
    end
    if o.preset == "main" then
        s.start:SetText(o.start == "boost" and "Level 1, or the boost to 80" or "Level 1 only"); s.start:Enable()
    else
        s.start:SetText(fixed.start or "Level 1"); s.start:Disable()
    end
    if fixed.bots then s.bots:SetText(o.bots == 0 and "Off" or (o.bots .. " bots")); s.bots:Enable()
    else s.bots:SetText(o.core == "cmangos" and "Coming on this core" or "None in this ruleset"); s.bots:Disable() end
    s.vis:SetText(o.vis == "public" and "Public: on the Leyline list" or "Private: invite link only")
    s.signup:SetText(H.SIGNUP_LABEL[o.signup])
    s.herokey:SetText(o.herokey == "on" and "Hero Key sign-in: on" or "Hero Key sign-in: off")
    s.region:SetText("Region: " .. H.REGION_LABEL[o.region or ""])
    s.lang:SetText("Language: " .. (o.lang ~= "" and o.lang or "not set"))
    for t, b in pairs(s.tagButtons) do if W.Style then W.Style.Tab(b, o.tags[t]) else b:SetAlpha(o.tags[t] and 1 or 0.5) end end
    local errs, first = H.Validate(o)
    s.problem:SetText(errs and ((W.Style and W.Style.Hex("warn") or "") .. first .. "|r") or "")
end
H.RefreshSetup = refreshSetup

local function cycle(key, list, dir)
    H.opts[key] = step(list, H.opts[key], dir)
    if key == "core" then H.opts.preset = H.PRESETS[H.opts.core][1] end
    if key == "core" or key == "preset" then
        local f = FIXED[H.opts.preset] or {}
        H.opts.tags = {}
        for _, t in ipairs(f.tags or {}) do H.opts.tags[t] = true end
        if not f.bots then H.opts.bots = 0 end
        if f.rates == false then H.opts.xp, H.opts.loot, H.opts.rep = 0, 0, 0 end
        if H.opts.type == "pvp" or H.opts.type == "rppvp" then H.opts.tags.pvp = true end
    end
    refreshSetup()
end
H.Cycle = cycle

local function cycler(parent, key, list, w, ...)
    local b = button(parent, "", w, function(_, mouse) cycle(key, list, mouse == "RightButton" and -1 or 1) end, "ghost", ...)
    if b.RegisterForClicks then b:RegisterForClicks("LeftButtonUp", "RightButtonUp") end
    return b
end

local function buildSetup(page)
    local s = { tagButtons = {} }
    local y = -6
    local function row(text)
        local fs = label(page, text, "GameFontNormalSmall", "TOPLEFT", 8, y - 5)
        muted(fs)
        local at = y
        y = y - ROW
        return at
    end
    local X = 150
    local at = row("Server core")
    s.core = cycler(page, "core", H.CORES, 150, "TOPLEFT", X, at)
    muted(label(page, H.CORES_COMING, "GameFontDisableSmall", "TOPLEFT", X + 160, at - 5))
    at = row("Ruleset")
    s.preset = button(page, "", 210, function(_, mouse)
        cycle("preset", H.PRESETS[H.opts.core], mouse == "RightButton" and -1 or 1)
    end, "ghost", "TOPLEFT", X, at)
    if s.preset.RegisterForClicks then s.preset:RegisterForClicks("LeftButtonUp", "RightButtonUp") end
    at = row("Realm name")
    s.name = input(page, 210, "TOPLEFT", X, at)
    s.name:SetMaxLetters(32)
    s.name:SetScript("OnTextChanged", function(self) H.opts.name = self:GetText() or ""; refreshSetup() end)
    at = row("Type")
    s.type = cycler(page, "type", H.TYPES, 110, "TOPLEFT", X, at)
    at = row("Rates")
    s.xp = cycler(page, "xp", H.RATES, 96, "TOPLEFT", X, at)
    s.loot = cycler(page, "loot", H.RATES, 96, "TOPLEFT", X + 100, at)
    s.rep = cycler(page, "rep", H.RATES, 96, "TOPLEFT", X + 200, at)
    at = row("New characters")
    s.start = button(page, "", 210, function() H.opts.start = H.opts.start == "boost" and "level1" or "boost"; refreshSetup() end,
        "ghost", "TOPLEFT", X, at)
    at = row("Bots")
    s.bots = cycler(page, "bots", H.BOTS, 160, "TOPLEFT", X, at)
    at = row("Who can find it")
    s.vis = button(page, "", 210, function() H.opts.vis = H.opts.vis == "public" and "private" or "public"; refreshSetup() end,
        "ghost", "TOPLEFT", X, at)
    at = row("Accounts")
    s.signup = cycler(page, "signup", H.SIGNUP, 150, "TOPLEFT", X, at)
    s.herokey = button(page, "", 170, function() H.opts.herokey = H.opts.herokey == "on" and "off" or "on"; refreshSetup() end,
        "ghost", "TOPLEFT", X + 156, at)
    at = row("Where")
    s.region = cycler(page, "region", H.REGIONS, 150, "TOPLEFT", X, at)
    s.lang = cycler(page, "lang", H.LANGS, 150, "TOPLEFT", X + 156, at)
    at = row("Tags")
    for i, t in ipairs(H.TAGS) do
        s.tagButtons[t] = button(page, H.TAG_LABEL[t], 62, function()
            H.opts.tags[t] = not H.opts.tags[t] or nil; refreshSetup()
        end, "ghost", "TOPLEFT", X + (i - 1) * 64, at)
    end
    at = row("Max players")
    s.max = input(page, 60, "TOPLEFT", X, at)
    s.max:SetMaxLetters(5)
    s.max:SetScript("OnTextChanged", function(self)
        local t = self:GetText() or ""
        H.opts.max = t == "" and 0 or (tonumber(t) or -1); refreshSetup()
    end)
    muted(label(page, "0 = not shown on the list", "GameFontDisableSmall", "TOPLEFT", X + 70, at - 5))
    s.problem = label(page, "", "GameFontHighlightSmall", "TOPLEFT", 8, y - 4)
    s.problem:SetWidth(WIN_W - 60)
    y = y - 22
    s.go = button(page, "Start hosting", 140, function() H.Start() end, "primary", "TOPLEFT", 8, y)
    s.deep = button(page, "Copy launcher link", 150, function()
        local errs, first = H.Validate(H.opts)
        if errs then return info(first) end
        info("Open it in the Leyline launcher: its Host page opens with these choices. Ctrl+C copies it.")
        copy(H.DeepLink(H.opts))
    end, "ghost", "TOPLEFT", 154, y)
    s.web = button(page, "Copy website link", 150, function()
        local errs, first = H.Validate(H.opts)
        if errs then return info(first) end
        info("The website's host page with these choices: sign in, check them, press Start server. Ctrl+C copies it.")
        copy(H.WebLink(H.opts))
    end, "ghost", "TOPLEFT", 310, y)
    win.setup = s
end

-- "Your realm": what the realm reports, and the GM's controls.
local function fmtUp(sec)
    sec = tonumber(sec)
    if not sec then return "-" end
    local d, h, m = math.floor(sec / 86400), math.floor(sec % 86400 / 3600), math.floor(sec % 3600 / 60)
    return (d > 0 and (d .. "d ") or "") .. h .. "h " .. m .. "m"
end
H.FormatUptime = fmtUp

function H.StatusLines(s)
    if not s then return "Asking the realm..." end
    if not s.gm then
        return "Only this realm's GM can run it from here. Hosting your own? Set it up in the first tab: when you "
            .. "play on your realm with your GM account, its controls are here."
    end
    local dash = function(v) return (v == nil or v == "-" or v == "") and "-" or v end
    local listed = s.listed == "1" and "yes" or s.listed == "0" and "no (private)" or "ask the launcher"
    return string.format("Up %s  ·  %s playing  ·  %s bots online\nOn the Leyline list: %s  ·  Sign-up: %s  ·  Hero Key: %s\n"
        .. "Bots set: %s  ·  Rates (XP/loot/rep): %s  ·  Allow list: %s (%s names)%s",
        fmtUp(s.up), dash(s.players), dash(s.bots), listed, dash(s.signup), dash(s.herokey), dash(s.botsCfg),
        dash(s.rates), s.allow == "on" and "on" or "off", dash(s.allowed),
        (tonumber(s.restart) or 0) > 0 and ("\nRestart in " .. s.restart .. " s") or "")
end

local function buildControl(page)
    local c = {}
    local box = CreateFrame("Frame", nil, page)
    box:SetPoint("TOPLEFT", 4, -4); box:SetPoint("TOPRIGHT", -4, -4); box:SetHeight(70)
    if W.Style then W.Style.Box(box) end
    c.status = label(box, "Asking the realm...", "GameFontHighlightSmall", "TOPLEFT", 10, -10)
    c.status:SetWidth(WIN_W - 140)
    c.refresh = button(box, "Refresh", 70, function() H.Send("status") end, "ghost", "TOPRIGHT", -8, -8)
    c.gmOnly = {}
    local function gm(x) c.gmOnly[#c.gmOnly + 1] = x; return x end
    local y = -86
    gm(muted(label(page, "Say to everyone online", "GameFontNormalSmall", "TOPLEFT", 6, y)))
    c.say = gm(input(page, 380, "TOPLEFT", 6, y - 14))
    c.say:SetMaxLetters(200)
    gm(button(page, "Announce", 100, function() if H.Send("announce", c.say:GetText()) then c.say:SetText("") end end,
        "primary", "TOPLEFT", 394, y - 14))
    y = y - 46
    gm(muted(label(page, "Message of the day", "GameFontNormalSmall", "TOPLEFT", 6, y)))
    c.motd = gm(input(page, 380, "TOPLEFT", 6, y - 14))
    c.motd:SetMaxLetters(200)
    gm(button(page, "Set", 100, function() H.Send("motd", c.motd:GetText()) end, "ghost", "TOPLEFT", 394, y - 14))
    y = y - 46
    gm(muted(label(page, "A player (character name)", "GameFontNormalSmall", "TOPLEFT", 6, y)))
    c.who = gm(input(page, 140, "TOPLEFT", 6, y - 14))
    c.who:SetMaxLetters(12)
    local function who() return (c.who:GetText() or ""):gsub("%s", "") end
    gm(button(page, "Kick", 58, function() H.Send("kick", who()) end, "ghost", "TOPLEFT", 152, y - 14))
    gm(button(page, "Ban 24h", 70, function() H.Send("ban", who() .. " 24") end, "danger", "TOPLEFT", 212, y - 14))
    gm(button(page, "Unban", 62, function() H.Send("unban", who()) end, "ghost", "TOPLEFT", 284, y - 14))
    gm(button(page, "Allow", 62, function() H.Send("allow", "add " .. who()) end, "ghost", "TOPLEFT", 348, y - 14))
    gm(button(page, "Remove", 70, function() H.Send("allow", "del " .. who()) end, "ghost", "TOPLEFT", 412, y - 14))
    y = y - 46
    c.allow = gm(button(page, "Only my allow list: off", 190, function()
        H.Send("allow", (H.status and H.status.allow == "on") and "off" or "on")
    end, "ghost", "TOPLEFT", 6, y))
    -- the restart: two clicks (the second within 5 s), then the realm gives everyone 5 minutes
    c.restart = gm(button(page, "Restart in 5 min", 140, function(self)
        if self.armed and now() - self.armed < 5 then
            self.armed = nil
            self:SetText("Restart in 5 min")
            H.Send("restart")
        else
            self.armed = now()
            self:SetText("Click again to confirm")
        end
    end, "danger", "TOPLEFT", 202, y))
    c.cancel = gm(button(page, "Cancel restart", 120, function() H.Send("cancel") end, "ghost", "TOPLEFT", 348, y))
    y = y - 34
    gm(muted(label(page, "On your PC (the launcher's Host page): these change how the realm runs", "GameFontNormalSmall",
        "TOPLEFT", 6, y)))
    for i, what in ipairs(H.MANAGE_ORDER) do
        gm(button(page, H.MANAGE[what], 96, function()
            if what == "invite" and H.status and H.status.invite and H.status.invite ~= "-" then
                info("Your realm's public join page: share it. Ctrl+C copies it.")
                return copy(H.status.invite)
            end
            info("Open this in the Leyline launcher: the Host page, at " .. H.MANAGE[what] .. ". Ctrl+C copies it.")
            copy(H.ManageLink(what))
        end, "ghost", "TOPLEFT", 6 + (i - 1) * 100, y - 16))
    end
    c.reply = label(page, "", "GameFontHighlightSmall", "TOPLEFT", 6, y - 48)
    c.reply:SetWidth(WIN_W - 60)
    win.control = c
end

refreshControl = function()
    if not win or not win.control then return end
    local c, s = win.control, H.status
    c.status:SetText(H.StatusLines(s))
    local isGM = s and s.gm
    for _, x in ipairs(c.gmOnly) do if isGM then x:Show() else x:Hide() end end
    if isGM then c.allow:SetText(s.allow == "on" and "Only my allow list: on" or "Only my allow list: off") end
end
H.RefreshControl = function() refreshControl() end

local function showTab(n)
    H.tab = n
    for i, p in ipairs(win.pages) do
        if i == n then p:Show() else p:Hide() end
        if W.Style then W.Style.Tab(win.tabs[i], i == n) else win.tabs[i]:SetAlpha(i == n and 1 or 0.6) end
    end
    if n == 2 then H.Send("status"); refreshControl() else refreshSetup() end
end
H.ShowTab = function(n) H.Show(n) end

local function build()
    win = CreateFrame("Frame", "WrathUnleashedHostFrame", UIParent)
    win:SetWidth(WIN_W); win:SetHeight(WIN_H)
    win:SetPoint("CENTER")
    win:SetFrameStrata("DIALOG")
    win:EnableMouse(true)
    win:SetMovable(true)
    win:RegisterForDrag("LeftButton")
    win:SetScript("OnDragStart", win.StartMoving)
    win:SetScript("OnDragStop", win.StopMovingOrSizing)
    if W.Style then
        W.Style.Window(win, "Host your own realm")
        W.Style.Close(win)
    else
        local bg = win:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.094, 0.106, 0.137, 0.97); bg:SetAllPoints()
        label(win, "Host your own realm", "GameFontNormalLarge", "TOP", 0, -12)
        local close = CreateFrame("Button", nil, win, "UIPanelCloseButton")
        close:SetPoint("TOPRIGHT", -2, -2)
    end
    tinsert(UISpecialFrames, "WrathUnleashedHostFrame")   -- Esc closes it
    win.pages, win.tabs = {}, {}
    for i, name in ipairs({ "Set up a realm", "Your realm" }) do
        local page = CreateFrame("Frame", nil, win)
        page:SetPoint("TOPLEFT", 16, -72); page:SetPoint("BOTTOMRIGHT", -16, 110)
        page:Hide()
        win.pages[i] = page
        win.tabs[i] = button(win, name, 130, function() showTab(i) end, "ghost", "TOPLEFT", 16 + (i - 1) * 134, -40)
    end
    buildSetup(win.pages[1])
    buildControl(win.pages[2])

    local box = W.Style and W.Style.Input(win, WIN_W - 40, 22) or CreateFrame("EditBox", nil, win, "InputBoxTemplate")
    box:SetWidth(WIN_W - 40); box:SetHeight(22)
    box:SetPoint("BOTTOMLEFT", 20, 76)
    box:SetAutoFocus(false)
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    box:SetScript("OnTextChanged", function(self) if self.fixed and self:GetText() ~= self.fixed then self:SetText(self.fixed) end end)
    win.copy = box
    win.info = label(win, "Your realm runs on your own PC, free; players reach it through the Leyline relay. Pick your "
        .. "choices, then Start hosting.", "GameFontHighlightSmall", "BOTTOMLEFT", 20, 46)
    win.info:SetWidth(WIN_W - 40)
    muted(win.info)
    button(win, "Back to realms", 120, function() win:Hide(); if W.ShowRealmList then W.ShowRealmList() end end,
        "ghost", "BOTTOMLEFT", 16, 14)
    button(win, "Done", 90, function() win:Hide() end, "ghost", "BOTTOMRIGHT", -16, 14)

    win:SetScript("OnUpdate", function()
        if H.handing and now() - H.handing.at > PAGE_WAIT then   -- the page never took it
            H.handing = nil
            if WUUI_LEYLINE_HOST then
                WUUI_LEYLINE_HOST = nil
                info("Open the link below in your browser (or the launcher link: Copy launcher link) to finish.")
            end
        end
    end)
    win:SetScript("OnShow", function() if PlaySound then pcall(PlaySound, "igCharacterInfoOpen") end end)
    if W.Style then W.Style.Recolor(win) end
    win:Hide()
end

function H.Show(tab)
    if not win then build() end
    win:Show()
    showTab(tab or H.tab or 1)
end
function H.Toggle()
    if win and win:IsShown() then win:Hide() else H.Show() end
end
function W.ToggleHost() H.Toggle() end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) H.OnMessage(prefix, msg, channel, sender) end)

SLASH_WUHOST1 = "/host"
SlashCmdList["WUHOST"] = function(arg) H.Show(arg == "realm" and 2 or nil) end

H.Window, H.PUBLIC_BASE, H.PAGE_WAIT = function() return win end, PUBLIC_BASE, PAGE_WAIT
