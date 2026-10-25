-- lua5.1 tests/test_ui.lua ui/WUPings/WUPings.lua
-- Loads the addon with stub frames and a stub map, then sends and receives pings.
local file = assert(arg[1], "path to ui/WUPings/WUPings.lua")
local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local function frame(name)
    local f = { scripts = {}, events = {}, shown = true, w = 1000, h = 660 }
    function f:SetScript(n, fn) self.scripts[n] = fn end
    function f:GetScript(n) return self.scripts[n] end
    function f:HookScript(n, fn) self.hooked = self.hooked or {}; self.hooked[n] = fn end
    function f:RegisterEvent(e) self.events[e] = true end
    function f:Show() self.shown = true end
    function f:Hide() self.shown = false end
    function f:IsShown() return self.shown end
    function f:SetWidth() end
    function f:SetHeight() end
    function f:SetFrameLevel() end
    function f:GetFrameLevel() return 1 end
    function f:SetAllPoints() end
    function f:ClearAllPoints() end
    function f:SetPoint(...) self.point = { ... } end
    function f:SetTexture(t) self.texture = t end
    function f:CreateTexture() return frame() end
    function f:GetWidth() return self.w end
    function f:GetHeight() return self.h end
    function f:GetLeft() return 100 end
    function f:GetTop() return 800 end
    function f:GetEffectiveScale() return 1 end
    function f:AddMessage(m) self.msgs = self.msgs or {}; self.msgs[#self.msgs + 1] = m end
    if name then _G[name] = f end
    return f
end
function CreateFrame(kind, name, parent) return frame(name) end
UIParent, WorldFrame, DEFAULT_CHAT_FRAME, RaidWarningFrame = frame(), frame(), frame(), frame()
WorldMapButton, WorldMapFrame = frame(), frame()
WorldMapFrame.shown = false
local origClick, clicked = function() end, 0
WorldMapButton:SetScript("OnClick", function() clicked = clicked + 1 end)
SlashCmdList = {}
local addon, sounds, notices = {}, {}, {}
local alt, party, target = false, 1, nil
local area, floor, px, py = 504, 0, 0.25, 0.75
function UnitName() return "Tester" end
function UnitExists(u) return u == "target" and target ~= nil end
function UnitCanAttack() return target == "enemy" end
function GetNumPartyMembers() return party end
function GetNumRaidMembers() return 0 end
function SendAddonMessage(prefix, text, chan, to) addon[#addon + 1] = { prefix = prefix, text = text, chan = chan, to = to } end
function PlaySound(s) sounds[#sounds + 1] = s end
function RaidNotice_AddMessage(f, text, c) notices[#notices + 1] = text end
function IsAltKeyDown() return alt end
function GetTime() return 100 end
function GetCurrentMapAreaID() return area end
function GetCurrentMapDungeonLevel() return floor end
function SetMapToCurrentZone() end
function GetPlayerMapPosition() return px, py end
function GetCursorPosition() return 350, 470 end
dofile(file)
WUPingsFrame.scripts.OnEvent(WUPingsFrame, "PLAYER_LOGIN")

check("listens for addon messages", WUPingsFrame.events.CHAT_MSG_ADDON)
check("build", WUPings_Build("attack", 504, 0, 0.5, 0.25) == "attack,504,0,0.5000,0.2500")
check("build refuses junk", WUPings_Build("nuke", 504, 0, 0.5, 0.5) == nil and WUPings_Build("look", 504, 0, 1.2, 0.5) == nil
    and WUPings_Build("look", 0, 0, 0.5, 0.5) == nil)
check("kind words", WUPings_KindFor("") == nil and WUPings_KindFor(" Attack ") == "attack" and WUPings_KindFor("help") == "assist"
    and WUPings_KindFor("omw") == "onmyway" and WUPings_KindFor("boom") == false)

local msg = "pings\tmap\t1/1\tdanger,504,0,0.4000,0.6000,Friend"
local p = WUPings_Parse("OVMOD", msg, "WHISPER", "Tester", "Tester")
check("parses a ping from the realm", p and p.kind == "danger" and p.from == "Friend" and p.x == 0.4 and p.area == 504)
check("only whispers from yourself", WUPings_Parse("OVMOD", msg, "PARTY", "Tester", "Tester") == nil
    and WUPings_Parse("OVMOD", msg, "WHISPER", "Faker", "Tester") == nil)
check("other mods and prefixes ignored", WUPings_Parse("OVMOD", "dalaran-dice\troll\t1/1\tA,2,6,8,3 5", "WHISPER", "Tester", "Tester") == nil
    and WUPings_Parse("CAIO", msg, "WHISPER", "Tester", "Tester") == nil)
check("bad data ignored", WUPings_Parse("OVMOD", "pings\tmap\t1/1\tdanger,504,0,4,0.6,Friend", "WHISPER", "Tester", "Tester") == nil)

WUPingsFrame.scripts.OnEvent(WUPingsFrame, "CHAT_MSG_ADDON", "OVMOD", msg, "WHISPER", "Tester")
check("received: a sound", sounds[#sounds] == "MapPing")
check("received: an on-screen call", notices[#notices] == "Friend: Danger (40, 60)")
check("received: a chat line", DEFAULT_CHAT_FRAME.msgs[#DEFAULT_CHAT_FRAME.msgs]:match("Friend: Danger"))

target = "enemy"
SlashCmdList.WUPINGS("")
local a = addon[#addon]
check("/ping with an enemy targeted sends attack where you stand", a and a.text == "pings\tmap\t1/1\tattack,504,0,0.2500,0.7500")
check("sent to yourself over OVMOD", a.prefix == "OVMOD" and a.chan == "WHISPER" and a.to == "Tester")
check("you see your own ping", notices[#notices] == "Tester: Attack (25, 75)")
target = nil
SlashCmdList.WUPINGS("onmyway")
check("/ping onmyway", addon[#addon].text:match("^pings\tmap\t1/1\tonmyway,"))
local n = #addon
SlashCmdList.WUPINGS("boom")
check("/ping with a bad word shows help", #addon == n and DEFAULT_CHAT_FRAME.msgs[#DEFAULT_CHAT_FRAME.msgs]:match("Alt%-click"))

WorldMapButton.scripts.OnClick(WorldMapButton, "LeftButton")
check("a plain map click still does what it did", clicked == 1 and #addon == n)
alt = true
WorldMapButton.scripts.OnClick(WorldMapButton, "LeftButton")
check("Alt-click on the world map pings that spot", clicked == 1 and addon[#addon].text == "pings\tmap\t1/1\tlook,504,0,0.2500,0.5000")
WorldFrame.hooked.OnMouseUp(WorldFrame, "LeftButton")
check("Alt-click in the world pings where you stand", addon[#addon].text == "pings\tmap\t1/1\tlook,504,0,0.2500,0.7500")

party = 0
n = #addon
SlashCmdList.WUPINGS("")
check("alone: drawn for you, nothing sent", #addon == n and notices[#notices] == "Tester: Look here (25, 75)")
px, py = 0, 0
check("no map here: no ping", WUPings_PingHere("look") == false)

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
