-- lua5.1 stream/tests/test_wuui_social.lua [addon dir] [ov_social.lua]
-- Fake 3.3.5a API: loads every file of WrathUnleashedUI in .toc order and runs the Leyline Friends panel (Social.lua)
-- against the real ov_social.lua (fake mod-ale): /lfriends, the WUSO list request, the list the portal sends
-- ("ovsocial fr"), the rows (in game, launcher, offline, a request), Message + Enter (an .lm with the realm's own
-- account), Accept, Add, an incoming message, the Leyline window's friends box, and that only messages the realm
-- whispers to you count.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local server = arg[2] or "realm/custom/lua_scripts/ov_social.lua"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets (as test_wuui_leyline.lua)
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
function Frame:SetFocus() self.focus = true end
function Frame:ClearFocus() self.focus = false end
local clock = 100
function GetTime() return clock end

-- ---------------------------------------------------------------- the realm (ov_social.lua under fake mod-ale)
local serverClock = 1000000
os.time = function() return serverClock end
local events, onServerAddon = {}, nil
function RegisterServerEvent(id, fn) if id == 30 then onServerAddon = fn end end
function RegisterPlayerEvent(id, fn) events[id] = fn end
function AuthDBQuery() return { GetString = function() return "WR000001" end } end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end
local player = { chat = {} }
function player:GetAccountId() return 1 end
function player:GetGUIDLow() return 1 end
function player:GetName() return "Tester" end
function player:SendAddonMessage(prefix, msg) fireClient(prefix, msg, "WHISPER", "Tester") end
function player:SendBroadcastMessage(m) self.chat[#self.chat + 1] = m end
function GetPlayersInWorld() return { player } end
dofile(server)
local T = assert(OV_SOCIAL_TEST)
local function console(cmd)
    local out = {}
    events[42](42, nil, cmd, { SendSysMessage = function(_, m) out[#out + 1] = m end })
    return out
end

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
local listed = false
for _, f in ipairs(files) do if f == "Social.lua" then listed = true end end
check(".toc lists Social.lua", listed)
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
local S = assert(W.Social, "W.Social")
check("/lfriends and /leylinefriends", SLASH_WUSOCIAL1 == "/lfriends" and SLASH_WUSOCIAL2 == "/leylinefriends" and SlashCmdList.WUSOCIAL)
check("builds nothing until opened", S.Window() == nil)

console("ovsocial pull 0 0 1")   -- the portal is running
SlashCmdList.WUSOCIAL("")
local win = S.Window()
check("opens", win and win:IsShown())
check("asked the realm (WUSO L, whispered to self)", sent[#sent][1] == "WUSO" and sent[#sent][2] == "L"
    and sent[#sent][3] == "WHISPER" and sent[#sent][4] == "Tester")
check("an empty list until the portal sends one", #S.rows == 0 and win.status:GetText():find("No Leyline friends yet"))

local list = "Bob\t4821\tg\tBobbert on WrathUnleashed\t2\nDana\t1234\tl\tIn the launcher\t0\n"
    .. "Zed\t0007\to\t\t0\nEve\t5555\tq\tWants to be friends\t0\nFinn#2\t\tp\tRequest sent\t0"
check("the portal's list arrives", console("ovsocial fr WR000001 1 1 " .. T.hex(list))[1] == "ovsocial ok fr 5")
local rows = win.rows
check("rows: in game first, with where and unread", rows[1]:IsShown() and rows[1].name:GetText():find("^Bob")
    and rows[1].where:GetText() == "In game: Bobbert on WrathUnleashed" and rows[1].unread:GetText():find("2 new"))
check("launcher and offline rows", rows[2].where:GetText():find("^In the launcher") and rows[3].where:GetText() == "Offline")
check("a request: Accept / Decline", rows[4].a:GetText() == "Accept" and rows[4].b:GetText() == "Decline")
check("my waiting request: no buttons", rows[5].a:IsShown() == false and rows[5].b:IsShown() == false)
check("status counts who's online", win.status:GetText() == "2 online")

-- message Bob
rows[1].a:Fire("OnClick")
check("Message picks the friend", win.to:GetText() == "To Bob#4821:" and win.say.focus)
local q0 = #T.queue()
win.say:SetText("hello |cffff0000there")
win.say:Fire("OnEnterPressed")
local line = T.queue()[#T.queue()].line
check("Enter sends it through the realm as an .lm, stamped with my account", #T.queue() == q0 + 1
    and line:find("^M %d+ WR000001 " .. T.hex("Tester") .. " " .. T.hex("Bob#4821") .. " ") ~= nil
    and win.say:GetText() == "")
check("no colour codes leave the panel", not line:find(T.hex("|c")))
check("the echo shows under the list", (win.log[1]:GetText() or ""):find("To Bob#4821:|r hello") ~= nil)
console("ovsocial msg WR000001 9 " .. T.hex("Bob") .. " " .. T.hex("hi back"))
local seen = false
for i = 1, #win.log do if (win.log[i]:GetText() or ""):find("Bob:|r hi back") then seen = true end end
check("an incoming message shows in the panel", seen)
check("and in chat, whisper-style", player.chat[#player.chat]:find("%[Bob%] whispers: hi back"))

-- accept, add, appear offline
rows[4].a:Fire("OnClick")
check("Accept: F:accept with the name#tag", T.queue()[#T.queue()].line:find(" " .. T.hex("accept") .. " " .. T.hex("Eve#5555") .. "$") ~= nil)
win.add:SetText("Gil#0101")
win.add:Fire("OnEnterPressed")
check("Add: F:add", T.queue()[#T.queue()].line:find(" " .. T.hex("add") .. " " .. T.hex("Gil#0101") .. "$") ~= nil)
clock = clock + 31; serverClock = serverClock + 31
win.offline:Fire("OnClick")
check("Appear offline: F:offline", T.queue()[#T.queue()].line:find(" " .. T.hex("offline") .. " ") ~= nil)
rows[2].b:Fire("OnClick")
local qn = #T.queue()
check("Remove asks first", rows[2].b:GetText() == "Sure?" and #T.queue() == qn)
rows[2].b:Fire("OnClick")
check("then removes", T.queue()[#T.queue()].line:find(" " .. T.hex("remove") .. " " .. T.hex("Dana#1234") .. "$") ~= nil)

-- only the realm's whispers to me count
local before = #S.rows
fireClient("WUSO", "B:1", "WHISPER", "Mallory")
fireClient("WUSO", "R:g:0:Fake:0000:x", "WHISPER", "Mallory")
fireClient("WUSO", "E", "WHISPER", "Mallory")
fireClient("WUSO", "M:Bob:fake", "PARTY", "Tester")
check("addon messages from anyone else are ignored", #S.rows == before and S.rows[1].name == "Bob"
    and S.log[#S.log].text ~= "fake")

-- the Leyline window's friends box
if W.ToggleLeyline then
    W.ToggleLeyline()
    local lw = W.Leyline.Window()
    check("the Leyline window's friends box opens this panel", lw.friends.add:GetText() == "Friends" and lw.friends.add.enabled)
    check("with a live summary", lw.friends.text:GetText():find("^5 Leyline friends, 2 online"))
    win:Hide()
    lw.friends.add:Fire("OnClick")
    check("Friends button toggles the panel", win:IsShown())
end

-- no brand names in anything shown
local bad = false
for _, f in ipairs(created) do
    local t = tostring(f.text or ""):lower()
    if t:find("warcraft") or t:find("blizzard") or t:find("lich king") or t:find("%f[%a]wow%f[%A]") then bad = true end
end
check("no brand names in the panel", not bad)

print(string.format("%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
