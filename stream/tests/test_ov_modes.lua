-- lua5.1 stream/tests/test_ov_modes.lua [addon dir] [lua_scripts dir]
-- Leyline Modes end to end under a fake mod-ale and a fake 3.3.5a UI: the realm relay (ov_modes.lua) and the
-- client runtime (WrathUnleashedUI/Modes.lua) with a fake LeylineMode. Covers the sandbox (no game globals, no
-- loading code, a runaway loop stopped by the guard), Bumper Balls hosted and played, keys relayed to the host,
-- state relayed to the other players, a late joiner caught up, the end of a game, publishing and GM review, and
-- that the realm's copy of the built-in mode is the client's.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local scripts = arg[2] or "realm/custom/lua_scripts"

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end
print = function() end
local clock = 3000000
os.time = function() return clock end

-- fake mod-ale
local events, serverEvents = {}, {}
function RegisterPlayerEvent(id, fn) events[id] = events[id] or {}; table.insert(events[id], fn) end
function RegisterServerEvent(id, fn) serverEvents[id] = fn end
function CreateLuaEvent() end
local sql = {}
function CharDBExecute(s) sql[#sql + 1] = s end
function CharDBQuery() return nil end
local byGuid = {}
local P = {}; P.__index = P
local function newPlayer(name, guid, x)
    local p = setmetatable({ name = name, guid = guid, x = x, y = 0, z = 0, o = 0.5, chat = {}, addon = {} }, P)
    byGuid[guid] = p
    return p
end
function P:GetGUIDLow() return self.guid end
function P:GetName() return self.name end
function P:GetX() return self.x end
function P:GetY() return self.y end
function P:GetZ() return self.z end
function P:GetO() return self.o end
function P:GetMapId() return 0 end
function P:IsInCombat() return false end
function P:GetDistance(o) return math.abs(self.x - o.x) end
function P:GetGroup() return self.group end
function P:SendBroadcastMessage(t) self.chat[#self.chat + 1] = t end
function P:SendAddonMessage(prefix, msg) self.addon[#self.addon + 1] = { prefix, msg } end
function GetPlayerByGUID(g) return byGuid[g] end

package.path = scripts .. "/?.lua;" .. package.path
local OVMod = dofile(scripts .. "/ov_modapi.lua")
package.loaded["ov_modapi"] = OVMod
local realm = dofile(scripts .. "/ov_modes.lua")
local onAddon = serverEvents[30]
local function toServer(p, name, data) onAddon(30, p, 7, "OVMOD", "wumodes\t" .. name .. "\t1/1\t" .. (data or ""), p) end
local function inbox(p)
    local out, bufs = {}, {}
    for _, m in ipairs(p.addon) do
        local mod, name, i, n, data = m[2]:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
        if mod == "wumodes" then
            i, n = tonumber(i), tonumber(n)
            bufs[name] = bufs[name] or {}
            bufs[name][i] = data
            if i == n then out[#out + 1] = { name, table.concat(bufs[name], "", 1, n) }; bufs[name] = nil end
        end
    end
    p.addon = {}
    return out
end
local function find(list, name) for _, m in ipairs(list) do if m[1] == name then return m[2] end end end

-- fake UI
local frames = {}
local Frame = {}
Frame.__index = function(self, k)
    local v = rawget(Frame, k)
    if v ~= nil then return v end
    if type(k) == "string" and k:match("^%u") then return function() end end
end
function Frame:SetScript(n, fn) self.scripts[n] = fn end
function Frame:Fire(n, ...) local fn = self.scripts[n]; if fn then return fn(self, ...) end end
function Frame:Show() local was = self.shown; self.shown = true; if not was then self:Fire("OnShow") end end
function Frame:Hide() self.shown = false end
function Frame:IsShown() return self.shown end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text end
function Frame:RegisterEvent(e) self.events[e] = true end
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    frames[#frames + 1] = f
    return f
end
function Frame:CreateFontString() return new("FontString", nil, self) end
function Frame:CreateTexture() return new("Texture", nil, self) end
function CreateFrame(kind, name, parent) return new(kind, name, parent) end
UIParent = new("Frame", "UIParent")
UISpecialFrames = {}
function tinsert(t, v) table.insert(t, v) end
SlashCmdList = {}
local t = 0
function GetTime() return t end
function UnitName() return "Ann" end
function PlaySound() end
WrathUnleashedUI, WrathUnleashedUIDB = {}, {}

local ann, bo, cy = newPlayer("Ann", 21, 0), newPlayer("Bo", 22, 10), newPlayer("Cy", 23, 100)
local group = { GetMembers = function() return { ann, bo, cy } end }
ann.group, bo.group, cy.group = group, group, group
function SendAddonMessage(prefix, msg) onAddon(30, ann, 7, prefix, msg, ann) end
local draws = {}
function LeylineMode(text) if text == "state" or text == "cursor" then return "" end draws[#draws + 1] = text return "ok" end
local guardOn = false
function LeylineGuard(ms)
    -- The real guard is a VM hook in the client; here, plain Lua's debug hook does the same job.
    if ms > 0 then
        local n = 0
        debug.sethook(function() n = n + 1; if n > 2000 then error("mode script ran too long (an endless loop?)") end end, "", 1000)
        guardOn = true
    else
        debug.sethook(); guardOn = false
    end
end
local function drew(prefix) local c = 0 for _, d in ipairs(draws) do if d:sub(1, #prefix) == prefix then c = c + 1 end end return c end

dofile(dir .. "/Modes.lua")
local M = WrathUnleashedUI.Modes
local listener, pump
for _, f in ipairs(frames) do
    if f.events["CHAT_MSG_ADDON"] then listener = f end
end
local function deliver()
    for _, m in ipairs(ann.addon) do listener:Fire("OnEvent", "CHAT_MSG_ADDON", m[1], m[2], "WHISPER", "Ann") end
    ann.addon = {}
end
local function flush()
    for i = 1, 6 do
        t = t + 1.1
        local hud = _G["LeylineModesHud"]
        if hud and hud.shown then hud:Fire("OnUpdate", 0.12) end
        for _, f in ipairs(frames) do if f.scripts.OnUpdate and not f.name then f:Fire("OnUpdate", 0.016) end end
        deliver()
    end
end

check("the realm's built-in modes are the client's", realm.BUMPER == M.BUILTIN and realm.COINDASH == M.COINDASH)

-- the sandbox
local H, err = M.Host.Load("x = CreateFrame; y = SendAddonMessage; z = loadstring; w = getfenv; v = _G.LeylineMode; Mode.Title = 'T'", { "Ann" }, 1)
check("a mode loads", H ~= nil)
check("a mode sees none of the game's globals", H and H.env.x == nil and H.env.y == nil and H.env.z == nil and H.env.w == nil and H.env.v == nil)
local H2 = M.Host.Load("function OnTick() while true do end end", { "Ann" }, 1)
M.Host.Update(H2, 0.06, function() end)
check("an endless loop stops the mode, not the game", H2.failed and H2.failed:find("too long", 1, true) ~= nil and not guardOn)
local _, bad = M.Host.Load("this is not lua", { "Ann" }, 1)
check("a broken script says so", bad and bad:find("error", 1, true) ~= nil)
local H3 = M.Host.Load("function OnStart() for i = 1, 400 do Ent.Spawn{} end end", { "Ann" }, 1)
M.Host.Start(H3)
check("entities are capped", H3.failed and H3.failed:find("too many", 1, true) ~= nil)

-- solo
M.Solo(M.BUILTIN)
check("solo Bumper Balls places the arena here", drew("origin here") == 1 and drew("ent ") >= 4)
check("and follows your ball", drew("cam follow") >= 1)
local before = drew("mv ")
_G["LeylineModesKeys"]:Fire("OnKeyDown", "W")
for i = 1, 20 do _G["LeylineModesHud"]:Fire("OnUpdate", 0.05) end
check("your keys roll your ball", drew("mv ") > before)
_G["LeylineModesKeys"]:Fire("OnKeyDown", "ESCAPE")
check("Esc lets go of the keys", not _G["LeylineModesKeys"]:IsShown())
M.Leave()
check("leaving clears the arena", draws[#draws] == "cam off" or draws[#draws - 1] == "clear")

-- Coin Dash runs its 60 seconds and ends with a winner
draws = {}
M.Solo(M.COINDASH)
check("Coin Dash builds an arena and coins", drew("ent ") >= 15)
_G["LeylineModesKeys"]:Fire("OnKeyDown", "W")
for i = 1, 1250 do _G["LeylineModesHud"]:Fire("OnUpdate", 0.05) end
check("Coin Dash ends after a minute", M.state == "finished" and (table.concat(M.notes, " ")):find("wins Coin Dash", 1, true) ~= nil)
t = t + 5; for _, f in ipairs(frames) do if f.scripts.OnUpdate and not f.name then f:Fire("OnUpdate", 0.016) end end
-- the editor: the template runs
M.Editor()
check("the editor opens on the template", _G["LeylineModesEditorBox"]:GetText() == M.TEMPLATE)
draws = {}
M.Solo(_G["LeylineModesEditorBox"]:GetText())
check("the template runs", drew("ent ") >= 2 and M.host and M.host.title == "My Mode")
M.Leave()

-- on the realm: Ann hosts, Bo joins, Cy joins late
draws = {}
SlashCmdList["LEYLINEMODES"]("")
flush()
check("the realm lists Bumper Balls and Coin Dash", M.modes[1] and M.modes[1].key == "bumper" and M.modes[1].max == 8 and M.modes[2] and M.modes[2].key == "coindash")
M.pick = "bumper"
_G["LeylineModesFrame"].host = _G["LeylineModesFrame"].host
toServer(ann, "host", "bumper"); deliver()
check("hosting opens a lobby", M.lobby and M.lobby.host == "Ann")
check("party nearby is invited, far away isn't", find(inbox(bo), "invite") ~= nil and find(inbox(cy), "invite") == nil)
toServer(bo, "join", "1")
deliver(); inbox(bo)
toServer(bo, "go", "")
check("only the host starts", find(inbox(bo), "start") == nil)
toServer(ann, "go", "")
deliver()
local bstart = find(inbox(bo), "start") or ""
check("players get the start without the script", bstart:match("^1 Ann ") ~= nil and not bstart:find("Bumper", 1, true))
check("the host runs it", M.host ~= nil and M.host.title == "Bumper Balls" and drew("ent ") >= 5)
flush()
local bo1 = inbox(bo)
check("the host's mode keys reach the players", find(bo1, "keys") == "W A S D SPACE")
check("the host's state reaches the players", (find(bo1, "st") or ""):find("e,%d+,ball") ~= nil)
-- Bo's W, relayed to the host, moves Bo's ball there
toServer(bo, "in", "W 1")
deliver()
local boBall
for p, b in pairs({}) do end
for i = 1, 30 do _G["LeylineModesHud"]:Fire("OnUpdate", 0.05) end
flush()
check("a player's keys reach the host's mode", (find(inbox(bo), "st") or ""):find("m,%d+,") ~= nil)
inbox(ann)
toServer(bo, "in", "w; 1")
check("malformed keys are dropped by the realm", find(inbox(ann), "in") == nil)
toServer(bo, "st", "e,1,box,0,0,0,1,1,1,0,ffffff")
check("only the host's state is relayed", find(inbox(ann), "st") == nil)
toServer(cy, "join", "1")
deliver(); flush()
local c1 = inbox(cy)
check("a late joiner gets the start and the field so far", (find(c1, "start") or ""):match("^1 Ann ") ~= nil and (find(c1, "st") or ""):find("e,1,cyl", 1, true) ~= nil)
check("and is in the host's game", (function() for _, p in ipairs(M.host.players) do if p == "Cy" then return true end end end)())
-- the end
M.host.endText = "Ann wins Bumper Balls!"
_G["LeylineModesHud"]:Fire("OnUpdate", 0.05)
flush()
check("the end reaches everyone and closes the game", (find(inbox(bo), "end") or ""):find("Ann wins", 1, true) ~= nil and next(realm.sessions) == nil)

-- publishing
local mine = "Mode.Title = \"Coin Rush\"\nMode.Keys = { \"W\" }\nfunction OnStart() HUD.Say('go') end\n"
toServer(ann, "publish", mine)
check("a published mode waits for review", realm.modes["ann_coinrush"] and realm.modes["ann_coinrush"].approved == false)
toServer(bo, "list", "")
check("others don't see it before review", not (find(inbox(bo), "modes") or ""):find("Coin Rush", 1, true))
toServer(ann, "list", ""); deliver()
check("its author does", M.modes[3] and M.modes[3].title:find("in review", 1, true) ~= nil)
for _, fn in ipairs(events[42]) do fn(42, bo, "modes approve ann_coinrush") end
check("only a GM approves", realm.modes["ann_coinrush"].approved == false)
function bo:GetGMRank() return 2 end
for _, fn in ipairs(events[42]) do fn(42, bo, "modes approve ann_coinrush") end
toServer(cy, "list", "")
check("approved, everyone sees it", (find(inbox(cy), "modes") or ""):find("Coin Rush", 1, true) ~= nil)
local stored = false
for _, q in ipairs(sql) do if q:find("REPLACE INTO mod_modes", 1, true) and not q:find("Coin Rush\"", 1, true) and q:find("'ann_coinrush'", 1, true) then stored = true end end
check("scripts are stored as hex, never quoted", stored)

local seen = {}
for _, f in ipairs(frames) do if type(f.text) == "string" then seen[#seen + 1] = f.text end end
local all = table.concat(seen, "\n"):lower()
check("no brand names or shop words on screen", not all:find("blizzard") and not all:find("warcraft") and not all:find(" buy") and not all:find("shop"))

realPrint(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
