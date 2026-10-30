-- lua5.1 stream/tests/test_wuui_leyline.lua [addon dir] [ov_leyline.lua]
-- Fake 3.3.5a API: loads every file of WrathUnleashedUI in .toc order, opens the Leyline window from
-- Esc > Mods & Workshop, and runs a real round trip through ov_leyline.lua (fake mod-ale): the WULY request,
-- the chunked answer, the rows, Copy link, Join (the hop: H:<id> to the realm, echoed back, and the
-- WUUI_LEYLINE_HOP global the page reads), Back to Wrath, the friends placeholder, "Realm list unavailable",
-- and no game-brand names in anything the window shows.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local server = arg[2] or "realm/custom/lua_scripts/ov_leyline.lua"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets (as test_wuui_collections.lua)
local frames, created = {}, {}
local Frame = {}
Frame.__index = function(self, k)
    local v = rawget(Frame, k)
    if v ~= nil then return v end
    if type(k) == "string" and k:match("^%u") then return function() end end -- other widget methods: no-ops
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
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    created[#created + 1] = f
    return f
end
function Frame:CreateFontString() return new("FontString", nil, self) end
function Frame:CreateTexture() return new("Texture", nil, self) end
function CreateFrame(kind, name, parent, template)
    local f = new(kind, name, parent); frames[#frames + 1] = f
    if template == "OptionsSliderTemplate" and name then  -- the template's Low / High labels
        new("FontString", name .. "Low", f); new("FontString", name .. "High", f)
    end
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
function SetBindingClick() return 1 end
function SaveBindings() end
function SetCVar() end
function HasAction() return false end
function UnitLevel() return 80 end
function UnitClass() return "Mage", "MAGE" end
function UnitName() return "Tester" end
local realmName = "WrathUnleashed"
function GetRealmName() return realmName end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
local clock = 100
function GetTime() return clock end

-- ---------------------------------------------------------------- the realm (ov_leyline.lua under fake mod-ale)
local tmp = os.tmpname()
local datFile = tmp .. ".dat"
local function writeDat(text) local f = assert(io.open(datFile, "wb")); f:write(text); f:close() end
writeDat('return { updated = 999000, realms = {\n'
    .. '  { id = "abcdefghijklmnop", name = "Frost Haven", ruleset = "dalaran", live = true, players = 7, bots = 2 },\n'
    .. '  { id = "qrstuvwxyz234567", name = "Quiet Corner", ruleset = "main", live = false, players = 0, bots = 0 },\n'
    .. '} }\n')
local realGetenv = os.getenv
os.getenv = function(k) if k == "OV_LEYLINE_FILE" then return datFile end return realGetenv(k) end
local serverClock = 1000000
os.time = function() return serverClock end
local onServerAddon
function RegisterServerEvent(id, fn) if id == 30 then onServerAddon = fn end end
function RegisterPlayerEvent() end
function GetPlayersInWorld() return { {}, {} } end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end
local player = { GetGUIDLow = function() return 1 end }
function player:SendAddonMessage(prefix, msg) fireClient(prefix, msg, "WHISPER", "Tester") end
dofile(server)
os.getenv = realGetenv   -- os.time stays fake: the realm's 5 s rate limit runs on serverClock

local sent = {}
function SendAddonMessage(prefix, msg, channel, target)
    sent[#sent + 1] = { prefix, msg, channel, target }
    if target == UnitName("player") and onServerAddon then onServerAddon(30, player, 7, prefix, msg, player) end
end

-- ---------------------------------------------------------------- load the addon in .toc order
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
check(".toc lists Leyline.lua last", files[#files] == "Leyline.lua")
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
local L = assert(W.Leyline, "W.Leyline")
check("builds nothing until opened", L.Window() == nil)
check("/leyline and /realms", SLASH_WULEYLINE1 == "/leyline" and SLASH_WULEYLINE2 == "/realms" and SlashCmdList.WULEYLINE)
check("one public base for links", L.PUBLIC_BASE == "https://play.openvanilla.app"
    and L.Link("abcdefghijklmnop") == "https://play.openvanilla.app/r/abcdefghijklmnop")

-- Esc > Mods & Workshop > Leyline realms
GameMenuButtonAddOns:Fire("OnClick")
local mods = _G.WrathUnleashedModsFrame
local hop
for _, f in ipairs(created) do if f.parent == mods and f.text == "Leyline realms" then hop = f end end
check("Mods & Workshop has a Leyline realms button", mods and mods:IsShown() and hop)
hop:Fire("OnClick")
local win = L.Window()
check("it opens the Leyline window and closes the panel", win and win:IsShown() and not mods:IsShown())
check("Esc closes it", UISpecialFrames[#UISpecialFrames] == "WrathUnleashedLeylineFrame")
check("asked the realm once (WULY L, whispered to self)", #sent == 1 and sent[1][1] == "WULY" and sent[1][2] == "L"
    and sent[1][3] == "WHISPER" and sent[1][4] == "Tester")

local function shown()
    local out = {}
    for _, r in ipairs(win.rows) do if r:IsShown() then out[#out + 1] = r end end
    return out
end
local rows = shown()
check("three realms, this one first", #rows == 3 and rows[1].realm.id == "this"
    and rows[1].name:GetText():find("^WrathUnleashed") and rows[1].name:GetText():find("you are here"))
check("name, ruleset, players, online", rows[2].name:GetText() == "Frost Haven" and rows[2].rules:GetText() == "Dalaran hangout"
    and rows[2].players:GetText() == "7 playing +2 bots" and rows[2].state:GetText():find("online"))
check("offline realm", rows[3].state:GetText():find("offline") and rows[3].players:GetText() == ""
    and rows[3].rules:GetText() == "Level 1 or boost to 80")
check("status counts the other realms", win.status:GetText():find("^2 other realms on Leyline"))

rows[2].copyBtn:Fire("OnClick")
check("Copy link fills the box with /r/<id>", win.copy:GetText() == "https://play.openvanilla.app/r/abcdefghijklmnop")
win.copy:SetText("typed over"); win.copy:Fire("OnTextChanged")
check("the box can't be typed over", win.copy:GetText() == "https://play.openvanilla.app/r/abcdefghijklmnop")
local before = #sent
rows[3].join:Fire("OnClick")
check("Join on an offline realm: says so, no hop", win.info:GetText():find("^Quiet Corner is offline")
    and win.copy:GetText() == "https://play.openvanilla.app/r/qrstuvwxyz234567" and #sent == before and WUUI_LEYLINE_HOP == nil
    and L.hopping == nil)
rows[1].join:Fire("OnClick")
check("Join on this realm: you're here", win.info:GetText():find("^You're on WrathUnleashed")
    and win.copy:GetText() == "https://play.openvanilla.app/wrath")

local function says(parent, pat)
    for _, f in ipairs(created) do
        if f.parent == parent and f.kind == "FontString" and (f.text or ""):find(pat) then return true end
    end
end
check("Friends across realms: Leyline friends (Social.lua) take the box", says(win.friends, "^Friends across realms$")
    and not says(win.friends, "^Coming$") and win.friends.list and win.friends.add.enabled == true
    and win.friends.add:GetText() == "Friends" and W.Social.adopted == win.friends)

-- reopening soon after doesn't ask again; Refresh does
win:Hide(); win:Show()
check("reopening within 30 s doesn't ask again", #sent == 1)
win.refresh:Fire("OnClick")
check("Refresh asks again (the realm rate-limits to 5 s)", #sent == 2)

-- ---------------------------------------------------------------- the hop
local echoes = {}
local listener
for _, f in ipairs(frames) do if f.events.CHAT_MSG_ADDON then listener = f end end
local realOnEvent = listener:GetScript("OnEvent")
listener:SetScript("OnEvent", function(self, ev, prefix, msg, ...)    -- what the page sees (CHAT_MSG_ADDON)
    if prefix == "WULY" and msg:sub(1, 2) == "H:" then echoes[#echoes + 1] = msg end
    return realOnEvent(self, ev, prefix, msg, ...)
end)
rows = shown()
rows[2].join:Fire("OnClick")
local last = sent[#sent]
check("Join on a live realm: H:<id> whispered to self", last[1] == "WULY" and last[2] == "H:abcdefghijklmnop"
    and last[3] == "WHISPER" and last[4] == "Tester")
check("Join: the realm echoes it back (the page's cue)", echoes[1] == "H:abcdefghijklmnop" and L.hopping and L.hopping.echoed)
check("Join: the page's fallback global is set", WUUI_LEYLINE_HOP == "abcdefghijklmnop")
check("Join: says it's hopping, and the account step", win.info:GetText():find("^Hopping to Frost Haven")
    and win.info:GetText():find("make an account"))
check("Join still puts the link in the box", win.copy:GetText() == "https://play.openvanilla.app/r/abcdefghijklmnop")
check("the realm drops a malformed hop", (function()
    local n = #echoes
    serverClock = serverClock + 5
    SendAddonMessage("WULY", "H:../../etc", "WHISPER", "Tester")
    SendAddonMessage("WULY", "H:ABCDEFGHIJKLMNOP", "WHISPER", "Tester")
    return #echoes == n end)())
check("the addon refuses a malformed hop", L.Hop("not-a-realm") == false and L.Hop("ABCDEFGHIJKLMNOP") == false
    and WUUI_LEYLINE_HOP == "abcdefghijklmnop")

-- no page took it (the desktop client): after HOP_WAIT the window says so and clears the request
clock = clock + L.HOP_WAIT + 1
win:Fire("OnUpdate", 0.1)
check("no page: the hop is dropped and the window says why", L.hopping == nil and WUUI_LEYLINE_HOP == nil
    and win.info:GetText():find("^Hopping works in the browser game"))

-- Back to Wrath: always there; on Wrath it says so, on a community realm it hops home
check("Back to Wrath button", win.back and win.back.text == "Back to Wrath")
before = #sent
win.back:Fire("OnClick")
check("Back to Wrath on Wrath: you're here, no hop", win.info:GetText() == "You're on Wrath now." and #sent == before
    and WUUI_LEYLINE_HOP == nil)
realmName = "Frost Haven"
serverClock = serverClock + 5
win.back:Fire("OnClick")
check("Back to Wrath on a community realm: H:wrath", sent[#sent][2] == "H:wrath" and WUUI_LEYLINE_HOP == "wrath"
    and echoes[#echoes] == "H:wrath" and win.info:GetText():find("^Back to Wrath"))
WUUI_LEYLINE_HOP, L.hopping, realmName = nil, nil, "WrathUnleashed"
listener:SetScript("OnEvent", realOnEvent)

-- the client ignores messages that aren't the realm's answer to us
fireClient("WULY", "B:1:0", "WHISPER", "Someone")
fireClient("WULY", "R:zzzz:1:1:1:main:Spoof", "WHISPER", "Someone")
fireClient("WULY", "E:1", "WHISPER", "Someone")
check("ignores other senders", #shown() == 3)
fireClient("WULY", "R:abcdefghijklmnop:1:1:1:main:Stray", "WHISPER", "Tester")
check("ignores rows outside a list", #shown() == 3)

-- missing file on the realm: Realm list unavailable
os.remove(datFile)
OV_LEYLINE_TEST.cache.at = -1e9
serverClock = serverClock + 10
win.refresh:Fire("OnClick")
check("missing file: Realm list unavailable", win.status:GetText() == "Realm list unavailable" and #shown() == 0)

-- no answer at all (no server script): unavailable after a few seconds
onServerAddon = nil
win.refresh:Fire("OnClick")
check("waiting...", win.status:GetText():find("^Asking"))
clock = clock + 10
win:Fire("OnUpdate", 0.1)
check("no answer: Realm list unavailable", win.status:GetText() == "Realm list unavailable")

-- many realms: paging and the mouse wheel
local msgs = { "B:12:0" }
for i = 1, 12 do msgs[#msgs + 1] = string.format("R:%s:1:%d:0:casual:Realm %d", string.rep(string.char(96 + i), 16), i, i) end
msgs[#msgs + 1] = "E:12"
for _, m in ipairs(msgs) do fireClient("WULY", m, "WHISPER", "Tester") end
check("a page of 7 of 12", #shown() == 7 and win.count:GetText() == "1-7 of 12")
win.list:Fire("OnMouseWheel", -1)
check("mouse wheel scrolls", shown()[1].name:GetText() == "Realm 2")

-- nothing the window shows names the game or its maker
local bad
for _, f in ipairs(created) do
    local t = (f.kind == "FontString" or f.kind == "Button") and f.text or nil
    if t and (t:lower():find("warcraft") or t:lower():find("%f[%w]wow%f[%W]") or t:lower():find("lich king")
        or t:lower():find("blizzard") or t:find("Open ?Vanilla") or t:find("OpenWoW")) then bad = t end
end
check("no game-brand or old project names on screen", bad == nil)
if bad then print("  shown: " .. bad) end

os.remove(tmp)
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
