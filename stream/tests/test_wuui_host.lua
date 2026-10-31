-- lua5.1 stream/tests/test_wuui_host.lua [addon dir] [lua_scripts dir]
-- The in-game hosting window (WrathUnleashedUI/Host.lua) and its realm half (realm/custom/lua_scripts/ov_hostctl.lua,
-- under a fake mod-ale with ov_modapi.lua), plus the Leyline look (Style.lua) and the Esc menu's Realm List:
--   Style: buttons (kinds, hover / pressed / disabled), tabs, the window's title bar with the Leyline mark, the palette,
--          our own media files (TGA, power-of-two, 32-bit);
--   Esc > Realm List opens the realm window; its Host your own opens the Host window;
--   Set up a realm: the choices, the checks (name, brands, rates and bots per ruleset, numbers), the query string
--          (the order and names hostflow.py and deeplink.rs read), the hand-over (page: WUUI_LEYLINE_HOST and the
--          website link; desktop: the leyline:// link), the page that never takes it;
--   Your realm: a player gets gm=0 and every action refused (and nothing happens); the GM: status, announce (and its
--          limit), message of the day, kick / ban / unban (never yourself, never a GM of your level), the allow list
--          (a login kicked when not on it), a restart only with five minutes' warning (two clicks; one at a time;
--          cancel), the action rate limit; the host kit's facts file read as data only.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local scripts = arg[2] or "realm/custom/lua_scripts"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets
local frames, created = {}, {}
local Frame = {}
Frame.__index = function(self, k)
    local v = rawget(Frame, k)
    if v ~= nil then return v end
    if type(k) == "string" and k:match("^%u") then return function() end end
    return nil
end
function Frame:SetScript(n, fn) self.scripts[n] = fn end
function Frame:GetScript(n) return self.scripts[n] end
function Frame:Fire(n, ...) local fn = self.scripts[n]; if fn then return fn(self, ...) end end
function Frame:Show()
    local was = self:IsVisible(); self.shown = true
    if not was and self:IsVisible() then self:Fire("OnShow") end
end
function Frame:Hide()
    local was = self:IsVisible(); self.shown = false
    if was then self:Fire("OnHide") end
end
function Frame:IsShown() return self.shown end
function Frame:IsVisible()
    if not self.shown then return false end
    return self.parent == nil or self.parent.top or self.parent:IsVisible()
end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text end
function Frame:Enable() self.enabled = true end
function Frame:Disable() self.enabled = false end
function Frame:RegisterEvent(e) self.events[e] = true end
function Frame:UnregisterEvent(e) self.events[e] = nil end
function Frame:GetName() return self.name end
function Frame:GetParent() return self.parent end
function Frame:GetHeight() return self.h or 0 end
function Frame:SetHeight(h) self.h = h end
function Frame:SetTexture(a, ...) self.tex = select("#", ...) > 0 and { a, ... } or a end
function Frame:SetTextColor(r, g, b) self.color = { r, g, b } end
function Frame:GetTextColor() if self.color then return unpack(self.color) end return 1, 0.82, 0 end
function Frame:GetObjectType() return self.kind end
function Frame:GetRegions() local t = {}; for _, c in ipairs(created) do if c.parent == self and c.region then t[#t + 1] = c end end; return unpack(t) end
function Frame:GetChildren() local t = {}; for _, c in ipairs(created) do if c.parent == self and not c.region then t[#t + 1] = c end end; return unpack(t) end
function Frame:SetBackdrop(b) self.backdrop = b end
function Frame:SetBackdropColor(...) self.bdColor = { ... } end
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    created[#created + 1] = f
    return f
end
function Frame:CreateFontString() local f = new("FontString", nil, self); f.region = true; return f end
function Frame:CreateTexture(_, layer) local t = new("Texture", nil, self); t.region = true; t.layer = layer; return t end
function CreateFrame(kind, name, parent, template)
    local f = new(kind, name, parent); frames[#frames + 1] = f; f.template = template
    if template == "OptionsSliderTemplate" and name then new("FontString", name .. "Low", f); new("FontString", name .. "High", f) end
    return f
end

UIParent = new("Frame", "UIParent"); UIParent.top = true
function UIParent:GetScale() return 1 end
GameMenuFrame = new("Frame", "GameMenuFrame"); GameMenuFrame.top = true; GameMenuFrame.h = 300
UISpecialFrames = {}
function tinsert(t, v) table.insert(t, v) end
SlashCmdList = {}
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
function GetScreenHeight() return 981 end
function InCombatLockdown() return false end
function SetBinding() return 1 end
function SaveBindings() end
function SetCVar() end
function HasAction() return false end
function UnitLevel() return 80 end
function UnitClass() return "Mage", "MAGE" end
function UnitName() return "Tester" end
function GetRealmName() return "Dalaran Hangout" end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
local clock = 100
function GetTime() return clock end

-- ---------------------------------------------------------------- the realm (ov_modapi.lua + ov_hostctl.lua, fake mod-ale)
local tmp = os.tmpname()
local hostFile = tmp .. ".dat"
local function write(path, text) local f = assert(io.open(path, "wb")); f:write(text); f:close() end
write(hostFile, 'return { realm_id = "abcdefghijklmnop", visibility = "public", signup = "open", bots = 40, '
    .. 'herokey = false, rates = "3/1/2", join = "https://relay.openvanilla.app/join/abcdefghijklmnop" }\n')
local realGetenv = os.getenv
os.getenv = function(k) if k == "OV_HOST_FILE" then return hostFile end return realGetenv(k) end
local serverClock = 1000000
os.time = function() return serverClock end
local addonHandlers, playerEvents = {}, {}
function RegisterServerEvent(id, fn) if id == 30 then addonHandlers[#addonHandlers + 1] = fn end end
function RegisterPlayerEvent(id, fn) playerEvents[id] = playerEvents[id] or {}; table.insert(playerEvents[id], fn) end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end
local world, commands, worldMsgs, sql = {}, {}, {}, {}
local function fakePlayer(name, gm, guid)
    local p = { name = name, gm = gm, guid = guid, chat = {}, kicked = false }
    function p:GetName() return self.name end
    function p:GetGMRank() return self.gm end
    function p:GetGUIDLow() return self.guid end
    function p:SendAddonMessage(prefix, msg) if self.isMe then fireClient(prefix, msg, "WHISPER", "Tester") end end
    function p:SendBroadcastMessage(m) self.chat[#self.chat + 1] = m end
    function p:KickPlayer() self.kicked = true end
    function p:RegisterEvent(fn) fn(nil, nil, nil, self) end
    world[#world + 1] = p
    return p
end
local me = fakePlayer("Tester", 0, 1); me.isMe = true
local other = fakePlayer("Grumpy", 0, 2)
local staff = fakePlayer("Staff", 3, 3)
function GetPlayersInWorld() return world end
function GetPlayerByName(n) for _, p in ipairs(world) do if p.name:lower() == n:lower() then return p end end end
function RunCommand(c) commands[#commands + 1] = c end
function SendWorldMessage(m) worldMsgs[#worldMsgs + 1] = m end
function CharDBExecute(q) sql[#sql + 1] = q end
function CharDBQuery() return nil end
function AuthDBQuery(q) if q:find("uptime") then return { GetString = function() return tostring(serverClock - 3725) end } end end
function GetRealmID() return 1 end
local luaEvents = {}
function CreateLuaEvent(fn, ms, times) luaEvents[#luaEvents + 1] = { fn = fn, ms = ms, times = times } end
package.preload["ov_modapi"] = function() return dofile(scripts .. "/ov_modapi.lua") end
dofile(scripts .. "/ov_modapi.lua")
dofile(scripts .. "/ov_hostctl.lua")
local HC = assert(OVHostCtl)
os.getenv = realGetenv

local sent = {}
function SendAddonMessage(prefix, msg, channel, target)
    sent[#sent + 1] = { prefix, msg, channel, target }
    if target == UnitName("player") then for _, h in ipairs(addonHandlers) do h(30, me, 7, prefix, msg, me) end end
end

-- ---------------------------------------------------------------- the addon, in .toc order
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
local at = {}
for i, f in ipairs(files) do at[f] = i end
check(".toc: Style.lua right after WrathUnleashedUI.lua, Host.lua before Leyline.lua (still last)",
    at["Style.lua"] == 2 and at["WrathUnleashedUI.lua"] == 1 and at["Host.lua"] < at["Leyline.lua"] and files[#files] == "Leyline.lua")
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
local S, H, L = assert(W.Style), assert(W.Host), assert(W.Leyline)

-- ---------------------------------------------------------------- Style.lua
local function near(c, hex)
    local r, g, b = tonumber(hex:sub(1, 2), 16) / 255, tonumber(hex:sub(3, 4), 16) / 255, tonumber(hex:sub(5, 6), 16) / 255
    return math.abs(c[1] - r) < 0.003 and math.abs(c[2] - g) < 0.003 and math.abs(c[3] - b) < 0.003
end
check("palette: the launcher's colours", near(S.C.bg, "181b23") and near(S.C.bg2, "11131a") and near(S.C.border, "2b3040")
    and near(S.C.accent, "5b8def") and near(S.C.violet, "8b5cf6") and near(S.C.text, "e6e8ef") and near(S.C.muted, "9aa3b5"))
check("Hex for coloured words", S.Hex("accent") == "|cff5b8def" and S.Hex("nope") == "|cffe6e8ef")
local parent = CreateFrame("Frame", nil, UIParent)
local clicks = 0
local b = S.Button(parent, "Go", 80, function() clicks = clicks + 1 end, "primary", "TOPLEFT", 1, 1)
check("button: no stock template, our text", b.template == nil and b:GetText() == "Go" and b.styleText.text == "Go")
local function bg(x) return x.styleBg.tex end
check("primary: the accent", near(bg(b), "5b8def"))
b:Fire("OnEnter"); local hover = bg(b)
b:Fire("OnMouseDown"); local pressed = bg(b)
b:Fire("OnMouseUp"); b:Fire("OnLeave")
check("hover lighter, pressed darker, back after", near(hover, "7aa3f3") and near(pressed, "4a78d4") and near(bg(b), "5b8def"))
b:Disable()
check("disabled: the off fill and grey text", b.enabled == false and near(bg(b), "1d2029") and near(b.styleText.color, "5d6474"))
b:Enable()
check("enabled again", b.enabled == true and near(bg(b), "5b8def"))
b:Fire("OnClick")
check("click works", clicks == 1)
local g = S.Button(parent, "Later", 80, nil, nil)
check("ghost by default: the dark fill, border edge", near(bg(g), "222632") and near(g.styleEdge[1].tex, "2b3040"))
S.Tab(g, true)
check("a selected tab: accent edge", near(g.styleEdge[1].tex, "5b8def"))
local winf = CreateFrame("Frame", "StyleProbe", UIParent)
local title = S.Window(winf, "Probe")
local mark
for _, c in ipairs(created) do if c.parent == winf and c.kind == "Texture" and c.tex == S.MARK then mark = c end end
check("window: the title bar with the Leyline mark and the title", title.text == "Probe" and mark ~= nil
    and S.MARK == "Interface\\AddOns\\WrathUnleashedUI\\Media\\leyline-mark-64" and winf.backdrop.bgFile == S.WHITE
    and near(winf.bdColor, "181b23"))
local gold = winf:CreateFontString()
gold.color = { 1, 0.82, 0 }
winf.styleWatch:Fire("OnShow")
check("gold text takes the palette's text colour when the window shows", near(gold.color, "e6e8ef"))

-- our own media: 32-bit TGA, power-of-two sizes
local function tga(path)
    local f = io.open(path, "rb"); if not f then return nil end
    local h = f:read(18); f:close()
    if not h or #h < 18 then return nil end
    return h:byte(3), h:byte(13) + 256 * h:byte(14), h:byte(15) + 256 * h:byte(16), h:byte(17)
end
local okMedia = true
for _, m in ipairs({ { "white8x8", 8 }, { "leyline-mark-64", 64 }, { "leyline-mark-128", 128 } }) do
    local kind, w, hgt, bpp = tga(dir .. "/Media/" .. m[1] .. ".tga")
    if not (kind == 2 and w == m[2] and hgt == m[2] and bpp == 32) then okMedia = false; print("  media " .. m[1]) end
end
check("Media: white8x8, leyline-mark-64 and -128 as 32-bit uncompressed TGA", okMedia)

-- ---------------------------------------------------------------- Esc > Realm List > Host your own
check("Esc menu: Realm List and Mods & Workshop", GameMenuButtonRealmList and GameMenuButtonRealmList.text == "Realm List"
    and GameMenuButtonAddOns.text == "Mods & Workshop")
GameMenuButtonRealmList:Fire("OnClick")
local lwin = L.Window()
check("Realm List opens the realm window", lwin and lwin:IsShown())
lwin.host:Fire("OnClick")
local hwin = H.Window()
check("Host your own opens the Host window on Set up", hwin and hwin:IsShown() and H.tab == 1 and not lwin:IsShown()
    and UISpecialFrames[#UISpecialFrames] == "WrathUnleashedHostFrame")
check("/host", SLASH_WUHOST1 == "/host" and SlashCmdList.WUHOST)

-- ---------------------------------------------------------------- the choices and their checks
local o = H.Defaults()
local errs, first = H.Validate(o)
check("no name: refused", errs and errs.name and first == "Give your realm a name.")
o.name = "  Frost Haven's Den "
check("a good name passes", H.Validate(o) == nil)
check("query: fixed order, names encoded", H.Query(o) ==
    "core=azerothcore&preset=dalaran&name=Frost%20Haven%27s%20Den&type=normal&vis=public&signup=open&herokey=off&tags=boosted,hangout"
    or H.Query(o) == "core=azerothcore&preset=dalaran&name=Frost%20Haven%27s%20Den&type=normal&vis=public&signup=open&herokey=off&tags=boosted%2Changout")
for _, bad in ipairs({ "My WoW realm", "warcraft fans", "Lich King", "BLIZZARD", "x<y>", string.rep("a", 33) }) do
    o.name = bad
    if not (H.Validate(o) or {}).name then check("refused name " .. bad, false) end
end
check("brand names, odd characters and long names refused", true)
o.name = "Wowza"
check("a word that only starts like a brand is fine", H.Validate(o) == nil)
o = H.Defaults(); o.name = "Den"
o.bots = 40
check("Dalaran hangout: no bots", (H.Validate(o) or {}).bots ~= nil)
o.preset = "main"; o.start = "level1"; o.xp = 5; o.loot = 2; o.rep = 0; o.region = "eu"; o.lang = "pt-BR"; o.max = 100
o.vis = "private"; o.signup = "invite"; o.herokey = "on"; o.type = "rppvp"; o.tags = { rp = true, pvp = true }
check("main with bots, rates, level 1 start", H.Validate(o) == nil)
local q = H.Query(o)
check("query carries every choice", q == "core=azerothcore&preset=main&name=Den&type=rppvp&xp=5&loot=2&start=level1&bots=40"
    .. "&vis=private&signup=invite&herokey=on&region=eu&lang=pt-BR&tags=pvp%2Crp&max=100")
check("links: website and launcher", H.WebLink(o) == "https://play.openvanilla.app/wrath/host?" .. q
    and H.DeepLink(o) == "leyline://host?" .. q and H.ManageLink("bots") == "leyline://host?manage=bots"
    and H.ManageLink("evil") == nil)
o.start = "fast"
check("main: start is level1 or boost", (H.Validate(o) or {}).start ~= nil)
o.start = "boost"; o.xp = 11
check("rates 1x-10x", (H.Validate(o) or {}).xp ~= nil)
o.xp = 2.5
check("whole numbers only", (H.Validate(o) or {}).xp ~= nil)
o.xp = 3; o.bots = 500
check("bots at most 200", (H.Validate(o) or {}).bots ~= nil)
o.bots = 0; o.max = -1
check("max players 0-10000", (H.Validate(o) or {}).max ~= nil)
o.max = 0; o.core = "cmangos"
check("a ruleset must belong to its core", (H.Validate(o) or {}).preset ~= nil)
o.preset = "cmangos-1.12.1"
check("CMaNGOS: rates are the ruleset's", (H.Validate(o) or {}).xp ~= nil)
o.xp, o.loot = 0, 0
check("CMaNGOS with the ruleset's rates", H.Validate(o) == nil and not H.Query(o):find("xp=") and not H.Query(o):find("bots="))
o.region = "mars"
check("region from the list", (H.Validate(o) or {}).region ~= nil)
o.region = ""; o.tags = { bots = true }
check("tags from the list (bots follow the bot count)", (H.Validate(o) or {}).tags ~= nil)

-- the window's controls
H.opts = H.Defaults()
H.RefreshSetup()
local s = hwin.setup
check("set up: the ruleset fixes what it fixes (Dalaran: no bots, boost)", s.bots.enabled == false and s.start.enabled == false
    and s.bots:GetText() == "None in this ruleset")
H.Cycle("preset", H.PRESETS.azerothcore)
check("cycling the ruleset: main, bots and the start open", H.opts.preset == "main" and s.bots.enabled == true
    and s.start.enabled == true and H.opts.tags.boosted and not H.opts.tags.hangout)
s.start:Fire("OnClick")
check("start: level 1 only", H.opts.start == "level1" and s.start:GetText() == "Level 1 only")
H.Cycle("core", H.CORES)
check("cycling the core: CMaNGOS, its first ruleset, rates off", H.opts.core == "cmangos" and H.opts.preset == "cmangos-1.12.1"
    and s.xp.enabled == false and s.bots:GetText() == "Coming on this core")
H.Cycle("core", H.CORES)
s.name.text = "Den"; s.name:Fire("OnTextChanged")
check("typing the name", H.opts.name == "Den" and s.problem:GetText() == "")
s.name.text = ""; s.name:Fire("OnTextChanged")
check("the first problem shows under the choices", s.problem:GetText():find("Give your realm a name"))
s.go:Fire("OnClick")
check("Start hosting with a problem: says it, hands nothing over", WUUI_LEYLINE_HOST == nil and H.lastInfo == "Give your realm a name.")
s.name.text = "Den"; s.name:Fire("OnTextChanged")

-- the hand-over: the browser game (a page) and the desktop client
WUUI_GAMEFOLDER = { page = true }
s.go:Fire("OnClick")
check("browser: WUUI_LEYLINE_HOST for the page, the website link in the box",
    WUUI_LEYLINE_HOST == H.Query(H.opts) and hwin.copy:GetText() == H.WebLink(H.opts) and H.lastInfo:find("Open the host page"))
clock = clock + H.PAGE_WAIT + 1
hwin:Fire("OnUpdate", 0.1)
check("the page never took it: cleared, and says what to open", WUUI_LEYLINE_HOST == nil and H.lastInfo:find("Open the link below"))
WUUI_GAMEFOLDER = nil
s.go:Fire("OnClick")
check("desktop: the leyline:// link in the box, nothing for a page", WUUI_LEYLINE_HOST == nil
    and hwin.copy:GetText() == H.DeepLink(H.opts))
s.web:Fire("OnClick")
check("Copy website link", hwin.copy:GetText() == H.WebLink(H.opts))
hwin.copy.text = "typed"; hwin.copy:Fire("OnTextChanged")
check("the box can't be typed over", hwin.copy:GetText() == H.WebLink(H.opts))

-- ---------------------------------------------------------------- Your realm: a normal player
local function lastSent() return sent[#sent] end
hwin.tabs[2]:Fire("OnClick")
check("Your realm asks the realm (OVMOD wuhost status, to self)", lastSent()[1] == "OVMOD"
    and lastSent()[2] == "wuhost\tstatus\t1/1\t" and lastSent()[4] == "Tester")
check("a player: gm=0, the controls hidden, says only the GM", H.status and H.status.gm == false
    and hwin.control.status:GetText():find("^Only this realm's GM") and not hwin.control.restart:IsShown())
local before = { #commands, #worldMsgs }
for _, a in ipairs({ { "announce", "hi all" }, { "motd", "x" }, { "kick", "Grumpy" }, { "ban", "Grumpy\t24" },
                     { "unban", "Grumpy" }, { "allow", "on" }, { "restart", "" }, { "cancel", "" } }) do
    serverClock = serverClock + 3; clock = clock + 2
    SendAddonMessage("OVMOD", "wuhost\t" .. a[1] .. "\t1/1\t" .. a[2], "WHISPER", "Tester")
end
check("a player: every action refused, nothing ran", #commands == before[1] and #worldMsgs == before[2]
    and not other.kicked and H.lastReply.kind == "err" and H.lastReply.text == "Only this realm's GM can do that.")
check("GM level 1 or 2 is not enough (default 3)", (function() me.gm = 2; local r = HC.IsGM(me); me.gm = 0; return r == false end)())

-- ---------------------------------------------------------------- the GM
me.gm = 3
serverClock = serverClock + 3; clock = clock + 2
hwin.control.refresh:Fire("OnClick")
local st = H.status
check("GM status: uptime, players, bots, the host kit's facts", st.gm and st.up == "3725" and st.players == "3" and st.bots == "0"
    and st.listed == "1" and st.signup == "open" and st.botsCfg == "40" and st.rates == "3/1/2" and st.herokey == "off"
    and st.invite == "https://relay.openvanilla.app/join/abcdefghijklmnop" and hwin.control.restart:IsShown())
check("status text", hwin.control.status:GetText():find("^Up 1h 2m") and hwin.control.status:GetText():find("On the Leyline list: yes"))
local function act(btnOrFn)
    serverClock = serverClock + 3; clock = clock + 2
    if type(btnOrFn) == "function" then btnOrFn() else btnOrFn:Fire("OnClick") end
end
hwin.control.say.text = "|cffff0000Hello|r from World of Warcraft"
act(function() H.Send("announce", hwin.control.say:GetText()) end)
check("announce: cleaned, to everyone", worldMsgs[#worldMsgs] == "|cff5b8def[Realm]|r Hello from" and H.lastReply.kind == "ok")
act(function() H.Send("announce", "again") end)
check("announce: one every 10 s", worldMsgs[#worldMsgs] == "|cff5b8def[Realm]|r Hello from" and H.lastReply.kind == "err")
serverClock = serverClock + 10
act(function() H.Send("motd", "42 is the answer") end)
check("message of the day (a leading number can't be read as a realm id)", commands[#commands] == "server set motd - 42 is the answer")
act(function() H.Send("kick", "Grumpy") end)
check("kick", other.kicked and H.lastReply.text == "Grumpy was kicked.")
act(function() H.Send("kick", "Tester") end)
check("not yourself", H.lastReply.text == "Not yourself.")
act(function() H.Send("kick", "Staff") end)
check("not a GM of your level", not staff.kicked and H.lastReply.text == "Not a GM of your level or higher.")
act(function() H.Send("ban", "Grumpy 24") end)
check("ban 24h", commands[#commands] == "ban character Grumpy 24h Banned by the realm's GM")
act(function() H.Send("ban", "Grumpy 9999") end)
check("ban: 1 to 720 hours", H.lastReply.text == "Ban for 1 to 720 hours.")
act(function() H.Send("unban", "grumpy") end)
check("unban (name cleaned)", commands[#commands] == "unban character Grumpy")
act(function() H.Send("kick", "Rob'); DROP") end)
check("a bad name is refused", H.lastReply.kind == "err")
-- the action limit
serverClock = serverClock + 3
SendAddonMessage("OVMOD", "wuhost\tunban\t1/1\tGrumpy", "WHISPER", "Tester")
SendAddonMessage("OVMOD", "wuhost\tunban\t1/1\tGrumpy", "WHISPER", "Tester")
check("one action every 2 seconds", H.lastReply.text:find("^One moment"))
-- the allow list
act(function() H.Send("allow", "add Friendly") end)
act(function() H.Send("allow", "on") end)
check("allow list on, with a name", HC._allow.on and HC._allow.names.Friendly and H.lastReply.text:find("^Only characters on your list"))
local stranger = fakePlayer("Stranger", 0, 9)
for _, fn in ipairs(playerEvents[3]) do fn(3, stranger) end
local friendly = fakePlayer("Friendly", 0, 10)
for _, fn in ipairs(playerEvents[3]) do fn(3, friendly) end
check("a login not on the list is told and sent off; a listed one stays", stranger.kicked
    and stranger.chat[1]:find("invite%-only") and not friendly.kicked)
act(function() H.Send("allow", "off") end)
-- the restart: two clicks, five minutes, one at a time, cancel
local n = #commands
act(hwin.control.restart)
check("restart: the first click only asks to confirm", #commands == n and hwin.control.restart:GetText() == "Click again to confirm")
clock = clock + 6
act(hwin.control.restart)
check("restart: a late second click starts over", #commands == n)
act(hwin.control.restart)
check("restart: confirmed, 300 seconds and a warning to everyone", commands[#commands] == "server restart 300"
    and worldMsgs[#worldMsgs]:find("restarts in 5 minutes") and HC._restart.at == serverClock + 300)
act(function() H.Send("restart") end)
check("never a second one while one is coming", H.lastReply.text:find("^A restart is already coming"))
act(function() H.Send("restart", "1") end)
check("the client can't pick the delay", HC.RESTART_DELAY == 300 and commands[#commands] == "server restart 300")
act(hwin.control.cancel)
check("cancel", commands[#commands] == "server restart cancel" and HC._restart.at == nil)
act(function() H.Send("restart") end)
check("then one restart per 10 minutes", H.lastReply.text:find("^One restart every 10 minutes"))

-- the launcher's host console: rows in ov_host_queue, run as the console, answered once, never late
check("the console queue: made and looked at every 3 s on a host kit's realm", #luaEvents == 1 and luaEvents[1].ms == 3000
    and luaEvents[1].times == 0 and (function() for _, q in ipairs(sql) do if q:find("CREATE TABLE IF NOT EXISTS ov_host_queue") then return true end end end)())
local function hx(t) return (t:gsub(".", function(c) return string.format("%02X", c:byte()) end)) end
local function unhx(h) return (h:gsub("%x%x", function(x) return string.char(tonumber(x, 16)) end)) end
local queue = {}
local realCharQuery = CharDBQuery
CharDBQuery = function(q)
    if not q:find("FROM ov_host_queue") then return realCharQuery(q) end
    local rows = {}
    for _, r in ipairs(queue) do if not r.done then rows[#rows + 1] = r end end
    if #rows == 0 then return nil end
    local i = 1
    return { GetString = function(_, c) local r = rows[i]; return ({ tostring(r.id), r.action, hx(r.data), tostring(r.at) })[c + 1] end,
             NextRow = function() i = i + 1; return i <= #rows end }
end
local function answers()
    for _, q in ipairs(sql) do
        local h, id = q:match("^UPDATE ov_host_queue SET done = 1, result = UNHEX%('(%x*)'%) WHERE id = (%d+)$")
        if h then for _, r in ipairs(queue) do if r.id == tonumber(id) and not r.done then r.done = unhx(h) end end end
    end
end
local function console(action, data, age)
    serverClock = serverClock + 3
    local r = { id = #queue + 1, action = action, data = data or "", at = serverClock - (age or 0) }
    queue[#queue + 1] = r
    luaEvents[1].fn(); answers()
    return r.done
end
serverClock = serverClock + 700   -- past the in-game restart's cooldown
other.kicked = false
check("console: announce to everyone", console("announce", "From the launcher") == "ok:Announced to everyone online."
    and worldMsgs[#worldMsgs] == "|cff5b8def[Realm]|r From the launcher")
check("console: kick (it outranks every GM)", console("kick", "Grumpy") == "ok:Grumpy was kicked." and other.kicked)
check("console: ban and unban, the same checks", console("ban", "Grumpy\t24") == "ok:Grumpy is banned for 24 hours."
    and commands[#commands] == "ban character Grumpy 24h Banned by the realm's GM" and console("ban", "Grumpy\t9999") == "err:Ban for 1 to 720 hours.")
local nc = #commands
check("console: a restart is always five minutes, whatever it sends", console("restart", "1") == "ok:Restart in 5 minutes. Everyone online was told."
    and commands[nc + 1] == "server restart 300" and HC._restart.at == serverClock + 300)
check("console: cancel", console("cancel") == "ok:Restart cancelled." and commands[#commands] == "server restart cancel")
local st = console("status")
check("console: status lines", st:find("^status:gm=1\n") and st:find("\nplayers=%d") and st:find("\nrestart=0"))
check("console: an unknown control is refused", console("shutdown") == "err:The realm doesn't know that control.")
local before = #commands
check("console: a row that waited too long is never run", console("restart", "", HC.QUEUE_MAX_AGE + 1):find("^err:That waited too long")
    and #commands == before and HC._restart.at == nil)
local runs = 0
for _, q in ipairs(sql) do if q:find("WHERE id = 1$") then runs = runs + 1 end end
luaEvents[1].fn()
local again = 0
for _, q in ipairs(sql) do if q:find("WHERE id = 1$") then again = again + 1 end end
check("console: each row answered once", runs == 1 and again == 1)
CharDBQuery = realCharQuery

-- the host kit's facts are data only
write(hostFile, 'return { realm_id = "abcdefghijklmnop" } os.execute("x")')
HC.ForgetHost()
check("a facts file with code is refused", HC.ReadHost() == nil)
write(hostFile, 'return { realm_id = "abcdefghijklmnop", join = "https://x.example/join/abcdefghijklmnop#SECRET" }')
HC.ForgetHost()
local d = HC.ReadHost()
check("a private invite (with its secret) is never passed on", d and d.realm_id == "abcdefghijklmnop" and d.join == nil)

-- the manage buttons: the launcher, never a secret
H.status.invite = "-"
local manage
for _, f in ipairs(created) do if f.text == "Bots" and f.parent == hwin.pages[2] then manage = f end end
manage:Fire("OnClick")
check("Bots: the launcher's Host page", hwin.copy:GetText() == "leyline://host?manage=bots")

-- nothing on screen names the game or its maker, or a client version
local bad
for _, f in ipairs(created) do
    local t = (f.kind == "FontString" or f.kind == "Button") and f.text or nil
    if type(t) == "string" and (t:lower():find("warcraft") or t:lower():find("%f[%w]wow%f[%W]") or t:lower():find("lich king")
        or t:lower():find("blizzard") or t:find("3%.3%.5") or t:find("1%.12") or t:find("2%.4%.3")) then bad = t end
end
check("no game-brand names or client versions on screen", bad == nil)
if bad then print("  shown: " .. bad) end

os.remove(tmp); os.remove(hostFile)
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
