-- lua5.1 stream/tests/test_ov_modes.lua [addon dir] [lua_scripts dir]
-- Leyline Modes end to end under a fake mod-ale and a fake 3.3.5a UI: the realm relay (ov_modes.lua) and the
-- client runtime (WrathUnleashedUI/Modes.lua) with a fake LeylineMode. Covers the sandbox (no game globals, no
-- loading code, a runaway loop stopped by the guard), Bumper Balls hosted and played, keys relayed to the host,
-- state relayed to the other players, a late joiner caught up, the end of a game, publishing and GM review, and
-- that the realm's copy of the built-in mode is the client's. Then devices (ModeDevices.lua): every device, wiring,
-- the per-tick event cap, the editor's Play/Stop (play never touches the authored layout), drafts on the account,
-- publishing a layout, and the Pressure Plates sample end to end.
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
dofile(dir .. "/ModeDevices.lua")
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

check("the realm's built-in modes are the client's", realm.BUMPER == M.BUILTIN and realm.COINDASH == M.COINDASH and realm.PLATES == M.PLATES)

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
check("its author does", (function() for _, m in ipairs(M.modes) do if m.key == "ann_coinrush" then return m.title:find("in review", 1, true) ~= nil end end end)())
for _, fn in ipairs(events[42]) do fn(42, bo, "modes approve ann_coinrush") end
check("only a GM approves", realm.modes["ann_coinrush"].approved == false)
function bo:GetGMRank() return 2 end
for _, fn in ipairs(events[42]) do fn(42, bo, "modes approve ann_coinrush") end
toServer(cy, "list", "")
check("approved, everyone sees it", (find(inbox(cy), "modes") or ""):find("Coin Rush", 1, true) ~= nil)
local stored = false
for _, q in ipairs(sql) do if q:find("REPLACE INTO mod_modes", 1, true) and not q:find("Coin Rush\"", 1, true) and q:find("'ann_coinrush'", 1, true) then stored = true end end
check("scripts are stored as hex, never quoted", stored)

-- ================================================================ devices
local D = M.DeviceLib()
-- The realm's flood limit is per second and this test's clock stands still: let time pass between sends.
local function later() clock = clock + 5 end
local function layout(body, players)
    local text = 'Mode.Title = "T"\nDevices.Run[=[\n' .. body .. '\n]=]\n'
    local H, err = M.Host.Load(text, players or { "Ann" }, 7)
    if not H then return nil, err end
    H.out = {}
    M.Host.Start(H)
    return H, H.env.Devices.rt
end
local function step(H, n) for i = 1, n or 1 do M.Host.Update(H, 0.05, function(d) H.out[#H.out + 1] = d end) end end
local function sentText(H) step(H, 2); return table.concat(H.out, ";") end
local function put(H, rt, who, x, z) local a = rt.avatars[who]; a.x, a.z = x, z; step(H, 1) end

-- the schema: every device the milestone asks for, each with properties, events and functions
local want = { "trigger", "button", "timer", "counter", "score", "teleport", "spawn", "round", "hud", "mover" }
local all = true
for _, k in ipairs(want) do
    local s = D.Schema[k]
    if not (s and #s.props > 4 and #s.events > 0 and #s.fns > 0) then all = false end
end
check("devices: all ten kinds, each with properties, events and functions", all and #D.Order == 10)

-- the layout is data: it parses, saves to the same text, and bad layouts are refused with a reason
local PL = D.ParseMode(M.PLATES)
check("devices: the sample parses as data", PL and #PL.devs == 14 and #PL.wires == 13 and PL.title == "Pressure Plates")
check("devices: saving a parsed layout gives the same text", PL and D.Serialize(PL) == M.PLATES)
local _, e1 = D.Parse("d 1 rocket x=1")
local _, e2 = D.Parse("d 1 counter\nd 1 counter")
local _, e3 = D.Parse("d 1 counter\nd 2 timer\nw 1 explode 2 start")
local _, e4 = D.Parse("d 1 counter\nd 2 timer\nw 1 reached 2 launch")
local _, e5 = D.Parse("d 1 counter\nw 1 reached 9 add")
local _, e6 = D.Parse("os.exit()")
check("devices: unknown kinds, twice-used ids and bad wires are refused", e1 and e2 and e3 and e4 and e5 and e6
    and e3:find("no event", 1, true) and e4:find("no function", 1, true))
local big = {}
for i = 1, 70 do big[#big + 1] = "d " .. i .. " counter" end
check("devices: a layout has at most 64 devices", select(2, D.Parse(table.concat(big, "\n"))) ~= nil)
local dv = { kind = "trigger", p = D.Defaults("trigger") }
D.SetProp(dv, "color", "zz0000"); D.SetProp(dv, "w", "1e9"); D.SetProp(dv, "name", "a|cffff0000b\nc"); D.SetProp(dv, "once", "yes")
check("devices: properties are cleaned (colour, numbers, text, on/off)", dv.p.color == "4fa3ff" and dv.p.w == 999 and dv.p.name == "acffff0000bc" and dv.p.once == 1)
local enc = D.Encode("a b=c;]=]{1}")
check("devices: text values are encoded so they can't end the block", not enc:find("[%s=;%]]") and D.Decode(enc) == "a b=c;]=]{1}")
local _, loadErr = M.Host.Load('Mode.Title = "T"\nDevices.Run[=[\nd 1 rocket\n]=]', { "Ann" }, 1)
check("devices: a broken layout says why when it loads", loadErr and loadErr:find("rocket", 1, true) ~= nil)

-- Spawn Point: a ball per player at the spawn, rolled with WASD, kept inside the area
local H, rt = layout("set area=10\nd 1 spawn x=2 z=-3 speed=10\nd 2 counter\nw 1 spawned 2 add", { "Ann", "Bo" })
check("spawn: each player gets a ball at a spawn point", rt.avatars.Ann and rt.avatars.Bo and rt.avatars.Ann.x == 2 and rt.avatars.Ann.z == -3)
check("spawn: players sharing a spawn don't stack", rt.avatars.Bo.x ~= rt.avatars.Ann.x or rt.avatars.Bo.z ~= rt.avatars.Ann.z)
check("spawn: spawned fires per player", rt.devs[2].v == 2)
check("spawn: the keys are WASD (E only with a button)", table.concat(H.keys, " ") == "W A S D")
M.Host.Key(H, "Ann", "W", true); step(H, 10)
check("spawn: W rolls your ball forward", rt.avatars.Ann.z > -3 + 4)
step(H, 40)
check("spawn: you can't leave the area", rt.avatars.Ann.z <= 10)
M.Host.Key(H, "Ann", "W", false)
H.env.OnJoin("Cy")
check("spawn: a late joiner gets a ball (OnJoin)", rt.avatars.Cy ~= nil)
H.env.OnLeave("Bo")
check("spawn: a player who leaves loses theirs", rt.avatars.Bo == nil)
D.Call = H.env.Devices.Call
H.env.Devices.Call(1, "respawnall"); step(H, 1)
check("spawn: respawnall puts everyone back", rt.avatars.Ann.z == -3)

-- Trigger Volume: enter, leave, denied when off, once, enable
H, rt = layout("d 1 spawn z=-8\nd 2 trigger z=0 w=2 d=2 once=0\nd 3 counter\nd 4 counter\nd 5 trigger x=5 on=0\nd 6 counter\nd 7 trigger x=-5 once=1\nd 8 counter\n"
    .. "w 2 enter 3 add\nw 2 leave 4 add\nw 5 denied 6 add\nw 7 enter 8 add")
put(H, rt, "Ann", 0, 0)
check("trigger: walking in fires enter", rt.devs[3].v == 1 and rt.devs[4].v == 0)
put(H, rt, "Ann", 0, 0)
check("trigger: standing in it doesn't fire again", rt.devs[3].v == 1)
put(H, rt, "Ann", 0, -8)
check("trigger: walking out fires leave", rt.devs[4].v == 1)
put(H, rt, "Ann", 5, 0)
check("trigger: a disabled one fires denied", rt.devs[6].v == 1)
put(H, rt, "Ann", -5, 0); put(H, rt, "Ann", 0, -8); put(H, rt, "Ann", -5, 0)
check("trigger: once fires only the first time", rt.devs[8].v == 1)
check("trigger: its pad changes colour when done", sentText(H):find("e,%d+,box,%-5%.00,0%.04,0%.00,3%.00,0%.08,3%.00,0%.0,50ff78") ~= nil)
H.env.Devices.Call(5, "enable"); put(H, rt, "Ann", 0, -8); put(H, rt, "Ann", 5, 0)
check("trigger: enable turns it on", rt.devs[6].v == 1 and rt.devs[5].on == true)

-- Button: E next to it, cooldown, denied when off
H, rt = layout("d 1 spawn z=0\nd 2 button z=1 cooldown=1\nd 3 counter\nd 4 button x=8 on=0\nd 5 counter\nw 2 pressed 3 add\nw 4 denied 5 add")
check("button: E is added to the keys", table.concat(H.keys, " ") == "W A S D E")
M.Host.Key(H, "Ann", "E", true); M.Host.Key(H, "Ann", "E", false); step(H, 1)
check("button: E next to it presses it", rt.devs[3].v == 1)
M.Host.Key(H, "Ann", "E", true); M.Host.Key(H, "Ann", "E", false); step(H, 1)
check("button: it has a cooldown", rt.devs[3].v == 1)
step(H, 25); M.Host.Key(H, "Ann", "E", true); step(H, 1)
check("button: and works again after it", rt.devs[3].v == 2)
put(H, rt, "Ann", 20, 20); M.Host.Key(H, "Ann", "E", false); M.Host.Key(H, "Ann", "E", true); step(H, 1)
check("button: too far away does nothing", rt.devs[3].v == 2)
put(H, rt, "Ann", 8, 0); M.Host.Key(H, "Ann", "E", false); M.Host.Key(H, "Ann", "E", true); step(H, 1)
check("button: a disabled one fires denied", rt.devs[5].v == 1)

-- Timer: counts down to done, counts up, stop, add, the banner
H, rt = layout("d 1 timer seconds=1 auto=1 label=Left\nd 2 counter\nd 3 timer dir=up seconds=0\nd 4 counter\nw 1 done 2 add\nw 1 done 3 start\nw 3 stopped 4 add")
step(H, 10)
check("timer: counts down", rt.devs[1].run and rt.devs[1].t > 0.4 and rt.devs[1].t < 0.6)
check("timer: shows on the banner", sentText(H):find("b,Left 0%.") ~= nil)
step(H, 12)
check("timer: fires done at zero and stops", rt.devs[2].v == 1 and not rt.devs[1].run and rt.devs[1].t == 0)
step(H, 20)
check("timer: counts up", rt.devs[3].run and rt.devs[3].t > 0.8)
H.env.Devices.Call(3, "add", "5"); H.env.Devices.Call(3, "stop"); step(H, 1)
check("timer: add and stop (stopped fires)", rt.devs[3].t > 5.8 and not rt.devs[3].run and rt.devs[4].v == 1)

-- Counter: add with an argument, reached once at the target, set, sub, show
H, rt = layout("d 1 counter target=5 show=1 label=Gems\nd 2 counter\nd 3 counter\nw 1 reached 2 add\nw 1 changed 3 add")
H.env.Devices.Call(1, "add", "3"); step(H, 1)
H.env.Devices.Call(1, "add", "3"); step(H, 1)
H.env.Devices.Call(1, "add"); step(H, 1)
check("counter: add, and reached fires once when it gets to the target", rt.devs[1].v == 7 and rt.devs[2].v == 1 and rt.devs[3].v == 3)
H.env.Devices.Call(1, "set", "0"); H.env.Devices.Call(1, "sub", "2"); step(H, 1)
check("counter: set and sub", rt.devs[1].v == -2)
check("counter: show says the number", sentText(H):find("h,Gems: 7", 1, true) ~= nil)

-- Score Keeper: points to the player on the wire, target, win ends the game
H, rt = layout("d 1 spawn\nd 2 trigger z=5\nd 3 score points=2 target=4\nd 4 hud text={player}%20has%20{3}\nw 2 enter 3 add\nw 3 reached 4 show\nw 3 reached 3 win", { "Ann", "Bo" })
put(H, rt, "Ann", 0, 5); put(H, rt, "Ann", 0, -5)
check("score: the player who set it off scores", H.scores.Ann == 2 and (H.scores.Bo or 0) == 0)
put(H, rt, "Ann", 0, 5)
check("score: reaching the target fires, with {player} and the value filled in", sentText(H):find("h,Ann has 4", 1, true) ~= nil)
check("score: win ends the game", H.endText == "Ann wins!")

-- Teleporter: the pad moves you, the target stays inside the area, send, disable
H, rt = layout("set area=10\nd 1 spawn z=-8\nd 2 teleport x=0 z=0 tx=4 tz=50\nd 3 counter\nd 4 trigger x=9 z=9 w=1 d=1\nw 2 teleported 3 add\nw 4 enter 2 disable")
put(H, rt, "Ann", 0, 0)
check("teleport: stepping on it moves you, inside the area", rt.avatars.Ann.x == 4 and rt.avatars.Ann.z <= 10 and rt.devs[3].v == 1)
put(H, rt, "Ann", 9, 9); put(H, rt, "Ann", 0, 0)
check("teleport: disabled, it doesn't", rt.avatars.Ann.x == 0 and rt.devs[3].v == 1)
H.env.Devices.Call(2, "send", nil, "Ann"); step(H, 1)
check("teleport: send moves the player on the wire", rt.avatars.Ann.x == 4)

-- Round Manager: rounds reset the devices and the players, then the game ends
H, rt = layout("d 1 spawn z=-5\nd 2 round rounds=2 delay=0 wait=1 endtext=Done%20after%20{2}\nd 3 counter\nd 4 trigger z=5\nd 5 counter\n"
    .. "w 2 roundstart 3 add\nw 4 enter 2 endround\nw 4 enter 5 add")
check("round: the first round starts", rt.devs[2].round == 1 and rt.devs[3].v == 1)
put(H, rt, "Ann", 0, 5)
check("round: endround ends it", rt.devs[2].playing == false and rt.devs[5].v == 1)
step(H, 25)
check("round: the next one starts after the wait, with the players back at the spawn", rt.devs[2].round == 2 and rt.devs[3].v == 1 and rt.avatars.Ann.z == -5)
check("round: devices are reset for the new round", rt.devs[5].v == 0)
put(H, rt, "Ann", 0, 5)
check("round: after the last one the game ends with its text", H.endText == "Done after 2")

-- HUD Message: say or banner, argument text, values filled in, clear
H, rt = layout("d 1 hud text=Hi%20{player}\nd 2 hud where=banner text=Top\nd 3 counter start=4\nd 4 trigger\nd 5 spawn z=-5\nw 4 enter 1 show\nw 4 enter 2 show Count%20{3}")
put(H, rt, "Ann", 0, 0)
local txt = sentText(H)
check("hud: show says its text with {player}", txt:find("h,Hi Ann", 1, true) ~= nil)
check("hud: the wire's argument replaces it, on the banner, with {3}", txt:find("b,Count 4", 1, true) ~= nil)

-- Mover: along the path, arrived, back, returned, loop, and a solid one blocks players
H, rt = layout("d 1 spawn z=-6\nd 2 mover z=0 sx=10 sy=2 sz=1 y=1 path=0,4,0 speed=4\nd 3 counter\nd 4 counter\n"
    .. "d 5 mover x=8 z=8 path=2,0,0/2,0,2 speed=20 loop=pingpong auto=1 solid=0\nd 6 counter\n"
    .. "w 2 arrived 3 add\nw 2 returned 4 add\nw 5 arrived 6 add")
M.Host.Key(H, "Ann", "W", true); step(H, 30)
check("mover: a solid one blocks your ball", rt.avatars.Ann.z < -0.9 and rt.avatars.Ann.z > -2)
M.Host.Key(H, "Ann", "W", false)
H.env.Devices.Call(2, "start"); step(H, 30)
check("mover: start runs the path and fires arrived", rt.devs[2].cy == 5 and rt.devs[3].v == 1 and not rt.devs[2].moving)
check("mover: players see it move", sentText(H):find("m,%d+,0%.00,5%.00,0%.00") ~= nil)
M.Host.Key(H, "Ann", "W", true); step(H, 30); M.Host.Key(H, "Ann", "W", false)
check("mover: once it's out of the way you get through", rt.avatars.Ann.z > 2)
H.env.Devices.Call(2, "back"); step(H, 30)
check("mover: back returns it and fires returned", rt.devs[2].cy == 1 and rt.devs[4].v == 1)
step(H, 40)
check("mover: pingpong keeps going", rt.devs[5].moving and rt.devs[6].v >= 2)

-- wiring: one event to many functions, with arguments; a script can listen too
H, rt = layout("d 1 counter\nd 2 counter\nd 3 counter\nd 4 timer auto=0\nw 1 changed 2 add 10\nw 1 changed 3 sub 2\nw 1 changed 4 start")
local heard = 0
H.env.Devices.On(1, "changed", function() heard = heard + 1 end)
H.env.Devices.Call(1, "add"); step(H, 1)
check("wiring: one event drives several wires, with arguments", rt.devs[2].v == 10 and rt.devs[3].v == -2 and rt.devs[4].run)
check("wiring: scripts can listen to device events", heard == 1)

-- the guard: a wire loop is cut off each tick instead of hanging the host
H, rt = layout("d 1 counter target=999999\nd 2 counter\nw 1 changed 1 add\nw 1 changed 2 add")
H.env.Devices.Call(1, "add"); step(H, 1)
check("guard: a wire loop runs at most 64 events a tick", rt.lastEvents == D.MAX_EVENTS and rt.dropped > 0)
step(H, 20)
check("guard: and the mode keeps running", not H.failed and not H.endText and rt.devs[1].v < 100)
check("guard: the host is told about it", (table.concat(M.notes, " ")):find("wire loop", 1, true) ~= nil)
H, rt = layout("d 1 counter\nd 2 counter\nw 1 changed 2 add\nw 2 changed 1 add")
H.env.Devices.Call(1, "add"); step(H, 3)
check("guard: a loop between two devices is cut off too", not H.failed and rt.lastEvents <= D.MAX_EVENTS)
H, rt = layout("d 1 counter")
H.env.Devices.On(1, "changed", function() while true do end end)
H.env.Devices.Call(1, "add"); step(H, 1)
check("guard: an endless loop in a device hook stops the mode (30 ms guard)", H.failed and H.failed:find("too long", 1, true) ~= nil and not guardOn)

-- the sample: Pressure Plates, played solo with the keys
draws = {}
M.Solo(M.PLATES)
H = M.host
rt = H and H.env.Devices.rt
check("sample: Pressure Plates runs, made only of devices", H and H.title == "Pressure Plates" and rt and drew("ent ") >= 10)
check("sample: you start at the spawn with a follow camera", rt.avatars.Ann.z == -9 and drew("cam follow") >= 1)
local hud = _G["LeylineModesHud"]
local function tick(n) for i = 1, n do hud:Fire("OnUpdate", 0.05) end end
local function walkTo(x, z)
    for i = 1, 200 do
        local a = rt.avatars.Ann
        local dx, dz = x - a.x, z - a.z
        if dx * dx + dz * dz < 0.3 then break end
        local keys = { W = dz > 0.3, S = dz < -0.3, D = dx > 0.3, A = dx < -0.3 }
        for k, v in pairs(keys) do _G["LeylineModesKeys"]:Fire(v and "OnKeyDown" or "OnKeyUp", k) end
        tick(1)
    end
    for _, k in ipairs({ "W", "A", "S", "D" }) do _G["LeylineModesKeys"]:Fire("OnKeyUp", k) end
    tick(1)
end
tick(2)
walkTo(6, -2)
check("sample: pad 2 first doesn't count", rt.devs[5].v == 0 and (table.concat(M.notes, " ")):find("Not yet", 1, true) ~= nil)
walkTo(-6, -2)
check("sample: pad 1 counts and lights", rt.devs[5].v == 1 and rt.devs[2].done)
walkTo(0, 6)
check("sample: the door is shut", rt.avatars.Ann.z < 7.5 and not rt.devs[7].moving)
walkTo(6, -2)
walkTo(0, 3)
check("sample: three pads in order open the door", rt.devs[5].v == 3 and rt.devs[7].moving)
local time = rt.devs[6].t
check("sample: the timer stops", not rt.devs[6].run and time > 1)
check("sample: and your time shows", (table.concat(M.notes, " ")):find("Your time: " .. string.format("%.1f", time) .. " s", 1, true) ~= nil)
tick(40)
check("sample: the door went up", rt.devs[7].cy > 4.5)
walkTo(0, 11.5)
check("sample: through the door, the game ends with your time", M.state == "finished"
    and (table.concat(M.notes, " ")):find("Ann got through in " .. string.format("%.1f", time) .. " s!", 1, true) ~= nil)
t = t + 5; for _, f in ipairs(frames) do if f.scripts.OnUpdate and not f.name then f:Fire("OnUpdate", 0.016) end end
check("sample: the realm lists it as a built-in", realm.modes.plates and realm.modes.plates.approved and realm.modes.plates.title == "Pressure Plates")

-- hosted on the realm: the other players see the devices' shapes and HUD, and their keys drive their own ball
later(); inbox(bo); inbox(ann)
toServer(ann, "host", "plates"); deliver()
local lid = M.lobby and M.lobby.id
toServer(bo, "join", tostring(lid)); deliver()
later(); toServer(ann, "go", ""); deliver()
check("hosted: Bo gets the start, not the layout", (find(inbox(bo), "start") or ""):find("Devices", 1, true) == nil and M.host and M.host.title == "Pressure Plates")
later(); flush()
local bst = table.concat((function() local l = {} for _, m in ipairs(inbox(bo)) do if m[1] == "st" then l[#l + 1] = m[2] end end return l end)(), ";")
check("hosted: Bo sees the pads, the door and both balls", select(2, bst:gsub("e,%d+,", "")) >= 9 and select(2, bst:gsub("e,%d+,ball", "")) == 2)
check("hosted: and the HUD", bst:find("h,Step on the pads", 1, true) ~= nil)
rt = M.host.env.Devices.rt
local boZ = rt.avatars.Bo.z
later(); toServer(bo, "in", "W 1"); deliver()
for i = 1, 10 do _G["LeylineModesHud"]:Fire("OnUpdate", 0.05) end
check("hosted: Bo's W rolls Bo's ball on the host", rt.avatars.Bo.z > boZ + 1 and rt.avatars.Ann.z == -9)
M.Leave(); later(); flush(); inbox(bo); inbox(ann)

-- the editor: place, set, wire, Play/Stop, save, publish
local E = M.DevEditor
draws = {}
SlashCmdList["LEYLINEMODES"]("devices")
local ui = _G["LeylineDevicesEditor"]
check("editor: /modes devices opens it with a preview where you stand", ui and ui:IsShown() and drew("origin here") == 1 and drew("ent ") >= 2)
E.LoadText(M.PLATES)
local authored = E.Text()
check("editor: the sample opens", authored == M.PLATES and E.L.title == "Pressure Plates")
E.New()
check("editor: New starts with a spawn point", #E.L.devs == 1 and E.L.devs[1].kind == "spawn")
local pad = E.AddDevice("trigger", E.ME[1], E.ME[2], E.ME[3])
check("editor: add a device at your spot", pad and pad.p.z == -14)
function LeylineMode(text) if text == "cursor" then return "3.26 0.00 -4.74" end if text == "state" then return "" end draws[#draws + 1] = text return "ok" end
E.kind = "counter"
E.Arm("counter")
check("editor: click to place waits for a click on the ground", _G["LeylineDevicesPick"]:IsShown())
_G["LeylineDevicesPick"]:Fire("OnMouseDown", "LeftButton")
local ctr = E.L.devs[#E.L.devs]
check("editor: the click places it at the cursor, snapped", ctr.kind == "counter" and ctr.p.x == 3.5 and ctr.p.z == -4.5 and not _G["LeylineDevicesPick"]:IsShown())
E.sel = pad.id; E.Arm("move"); _G["LeylineDevicesPick"]:Fire("OnMouseDown", "LeftButton")
check("editor: move: click moves the selected device", pad.p.x == 3.5 and pad.p.z == -4.5)
function LeylineMode(text) if text == "state" or text == "cursor" then return "" end draws[#draws + 1] = text return "ok" end
E.sel = ctr.id; E.Refresh()
local targetRow
for _, p in ipairs(ui.props) do if p.key == "target" then targetRow = p end end
check("editor: the selected device's properties are listed", targetRow and targetRow.box:GetText() == "3")
targetRow.box:SetText("2"); targetRow.box:Fire("OnEnterPressed")
check("editor: editing a property sets it", ctr.p.target == 2)
-- wire from the drop-downs: pad enter -> counter add 1
ui.wsrc:Fire("OnClick")
local menu = _G["LeylineDevicesMenu"]
local function pickText(want) for i, r in ipairs(menu.rows) do if r.value ~= nil and r.text.text:find(want, 1, true) then return E.MenuPick(i) end end end
pickText("Trigger Volume")
ui.wev:Fire("OnClick"); pickText("enter")
ui.wdst:Fire("OnClick"); pickText("Counter")
ui.wfn:Fire("OnClick")
local fnList = {}
for _, r in ipairs(menu.rows) do if r.value ~= nil then fnList[#fnList + 1] = r.value end end
check("editor: the function list is the target's functions", table.concat(fnList, ",") == "add,sub,set,reset")
pickText("add")
ui.warg:SetText("1")
local nw = #E.L.wires
for _, f in ipairs(frames) do if f.text == "Add wire" then f:Fire("OnClick") end end
check("editor: Add wire wires an event to a function", #E.L.wires == nw + 1 and E.L.wires[#E.L.wires].ev == "enter" and E.L.wires[#E.L.wires].fn == "add" and E.L.wires[#E.L.wires].arg == "1")
check("editor: the wire is listed", ui.wrows[1]:IsShown() and ui.wrows[1].text.text:find("enter", 1, true) ~= nil)
check("editor: a bad wire is refused", not E.AddWire(pad.id, "reached", ctr.id, "add"))
E.AddWire(pad.id, "leave", ctr.id, "sub")
ui.wrows[2].del:Fire("OnClick")
check("editor: x deletes a wire", #E.L.wires == 1)
E.AddDevice("timer", 0, 0, 0)
local tmr = E.L.devs[#E.L.devs]
E.AddWire(ctr.id, "reached", tmr.id, "start")
E.DeleteDevice(tmr.id)
check("editor: deleting a device deletes its wires", #E.L.wires == 1 and not E.L.byId[tmr.id])
-- Play runs a copy; Stop brings back the authored layout untouched
E.LoadText(M.PLATES)
local before = E.Text()
draws = {}
E.Play()
check("editor: Play runs the layout where the preview was", M.host and M.host.title == "Pressure Plates" and drew("origin keep") >= 1 and not ui:IsShown())
check("editor: a Stop button shows while playing", _G["LeylineDevicesStop"]:IsShown())
rt = M.host.env.Devices.rt; M.host.out = {}
put(M.host, rt, "Ann", -6, -2); put(M.host, rt, "Ann", 6, -2)
rt.devs[7].p.color = "000000"
tick(10)
check("editor: (playing changed things)", rt.devs[5].v == 2 and rt.devs[2].done)
E.Stop()
check("editor: Stop ends the test and reopens the editor", M.host == nil and M.state == "idle" and ui:IsShown() and not _G["LeylineDevicesStop"]:IsShown())
check("editor: the authored layout is exactly as before Play", E.Text() == before and E.L.byId[7].p.color == "b48cff")
check("editor: the preview comes back in the same place", draws[#draws] ~= nil and drew("origin keep") >= 2)
E.Play(); M.host.endText = "done"; tick(1)
t = t + 5; for _, f in ipairs(frames) do if f.scripts.OnUpdate and not f.name then f:Fire("OnUpdate", 0.016) end end
check("editor: when a test ends by itself you're back in the editor", ui:IsShown() and not E.playing and E.Text() == before)
-- save to the account, list, load back
inbox(ann); later()
E.L.title = "Pad Run"
E.Save(); flush()
check("drafts: Save keeps it here", WrathUnleashedUIDB.modes["Pad Run"] ~= nil)
check("drafts: and on your account", realm.drafts[21] and realm.drafts[21]["Pad Run"] == E.Text())
later(); toServer(ann, "dlist", ""); deliver()
check("drafts: your account lists it", E.remote[1] == "Pad Run")
E.New()
later(); toServer(ann, "dload", "Pad Run"); deliver()
check("drafts: and loads it back into the editor", E.L.title == "Pad Run" and E.Text() == realm.drafts[21]["Pad Run"])
toServer(bo, "dload", "Pad Run")
check("drafts: nobody else can load yours", (find(inbox(bo), "draft") or "") == "")
later(); toServer(ann, "dsave", "x\n" .. string.rep("a", 15000))
check("drafts: too big is refused", realm.drafts[21]["x"] == nil)
-- publish through the same path and review
later(); E.Publish(); flush()
local pm = realm.modes["ann_padrun"]
check("publish: a layout goes to review like any mode", pm and pm.approved == false and pm.text == E.Text())
local pend
function ann:GetGMRank() return 1 end
ann.chat = {}
for _, fn in ipairs(events[42]) do fn(42, ann, "modes pending") end
check("publish: review marks it as devices only", (ann.chat[#ann.chat] or ""):find("ann_padrun (Pad Run by Ann, devices)", 1, true) ~= nil)
check("publish: a script with code isn't marked", not realm.isDevices(M.BUILTIN) and not realm.isDevices(M.PLATES .. "\nprint(1)") and realm.isDevices(M.PLATES))
for _, fn in ipairs(events[42]) do fn(42, ann, "modes reject plates") end
check("publish: the built-in sample can't be removed", realm.modes.plates ~= nil)
ui:Hide(); ui:Fire("OnHide")  -- the fake UI doesn't fire OnHide itself
check("editor: closing it clears the preview", draws[#draws] == "clear" and not E.preview)

local seen = {}
for _, f in ipairs(frames) do if type(f.text) == "string" then seen[#seen + 1] = f.text end end
local all = table.concat(seen, "\n"):lower()
check("no brand names or shop words on screen", not all:find("blizzard") and not all:find("warcraft") and not all:find(" buy") and not all:find("shop"))

realPrint(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
