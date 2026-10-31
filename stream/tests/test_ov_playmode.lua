-- lua5.1 stream/tests/test_ov_playmode.lua [lua_scripts dir] [addon dir]
-- One click to play (ov_playmode.lua) under a fake mod-ale, loaded the way ALE loads it: ov_modapi.lua, ov_golf.lua,
-- ov_modes.lua, then ov_playmode.lua (name order). Covers: the table; the website's "ovplay go" (console only, a real
-- account, a known mode) acted on at login and used once, a restart (the auth DB row), expiry, a first login waiting
-- for .playmode, combat keeping the intent; each mode starting through its own script (minigolf alone tees off, in a
-- party invites; Bumper Balls and Coin Dash solo vs host; the community browser opening the Modes window); the
-- desktop addon's "wuplay go" and .playmode with unknown ids refused and a rate limit; and the launcher's LeylinePlay
-- addon (launcher/src-tauri/src/modes/LeylinePlay.lua) asking once, only while fresh, under a fake 3.3.5a UI.
local scripts = arg[1] or "realm/custom/lua_scripts"
local launcherAddon = arg[2] or "launcher/src-tauri/src/modes/LeylinePlay.lua"

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end
print = function() end

local clock = 3000000
os.time = function() return clock end
local function tick(s) clock = clock + (s or 1) end

-- ---------------------------------------------------------------- fake mod-ale
local events, serverEvents = {}, {}
function RegisterPlayerEvent(id, fn) events[id] = events[id] or {}; table.insert(events[id], fn) end
function RegisterServerEvent(id, fn) serverEvents[id] = fn end
function CreateLuaEvent() end
local function result(rows)
    if not rows or #rows == 0 then return nil end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetString(c) return tostring(self.rows[self.i][c + 1] or "") end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end
function CharDBExecute() end
function CharDBQuery() return nil end
local accounts = { WR000001 = 1, WR000002 = 2, WR000003 = 3 }
local intentRows, authSql = {}, {}
function AuthDBExecute(s)
    authSql[#authSql + 1] = s
    local acc, id, ttl = s:match("REPLACE INTO ov_playmode_intents .- VALUES %((%d+), '([%w%-]+)', UNIX_TIMESTAMP%(%) %+ (%d+)%)")
    if acc then intentRows[tonumber(acc)] = { id, clock + tonumber(ttl) } end
    local del = s:match("DELETE FROM ov_playmode_intents WHERE account_id = (%d+)")
    if del then intentRows[tonumber(del)] = nil end
end
function AuthDBQuery(q)
    local name = q:match("FROM account WHERE username = '(%w+)'")
    if name then return accounts[name] and result({ { accounts[name] } }) end
    local acc = q:match("FROM ov_playmode_intents WHERE account_id = (%d+)")
    if acc then
        local r = intentRows[tonumber(acc)]
        return r and r[2] > clock and result({ { r[1], r[2] - clock } }) or nil
    end
    return nil
end

local online, byGuid = {}, {}
local P = {}
P.__index = P
local function newPlayer(name, guid, account)
    local p = setmetatable({ name = name, guid = guid, account = account, x = 100, y = 200, z = 50, o = 0, map = 571,
        chat = {}, addon = {}, timers = {} }, P)
    online[#online + 1] = p
    byGuid[guid] = p
    return p
end
function P:GetGUIDLow() return self.guid end
function P:GetName() return self.name end
function P:GetAccountId() return self.account end
function P:GetGMRank() return 0 end
function P:GetX() return self.x end
function P:GetY() return self.y end
function P:GetZ() return self.z end
function P:GetO() return self.o end
function P:GetMapId() return self.map end
function P:GetMap() return { IsBattleground = function() return false end, IsArena = function() return false end } end
function P:IsInCombat() return self.combat or false end
function P:IsDead() return false end
function P:InBattleground() return false end
function P:InArena() return false end
function P:GetDistance(o) return math.abs(self.x - o.x) end
function P:GetGroup() return self.group end
function P:SendBroadcastMessage(t) self.chat[#self.chat + 1] = t end
function P:SendAddonMessage(prefix, msg) self.addon[#self.addon + 1] = { prefix, msg } end
function P:RegisterEvent(fn, delay) self.timers[#self.timers + 1] = { fn = fn, delay = delay }; return #self.timers end
function GetPlayerByGUID(g) return byGuid[g] end
function GetPlayersInWorld() local t = {}; for _, p in ipairs(online) do if not p.away then t[#t + 1] = p end end; return t end
local function runTimers(p)
    local list = p.timers
    p.timers = {}
    for _, t in ipairs(list) do t.fn(1, t.delay, 1, p) end
    return #list
end

-- ---------------------------------------------------------------- load, in ALE's name order
package.path = scripts .. "/?.lua;" .. package.path
local OVMod = dofile(scripts .. "/ov_modapi.lua")
package.loaded["ov_modapi"] = OVMod
local golf = dofile(scripts .. "/ov_golf.lua")
local modes = dofile(scripts .. "/ov_modes.lua")
local PM = dofile(scripts .. "/ov_playmode.lua")
local onAddon = serverEvents[30]

local function command(p, text)
    for _, fn in ipairs(events[42] or {}) do
        if fn(42, p, text) == false then return false end
    end
end
local consoleOut = {}
local console = { SendSysMessage = function(_, m) consoleOut[#consoleOut + 1] = m end }
local function soap(text)
    for _, fn in ipairs(events[42] or {}) do
        if fn(42, nil, text, console) == false then return consoleOut[#consoleOut] end
    end
end
local function login(p) for _, fn in ipairs(events[3] or {}) do fn(3, p) end end
local function firstLogin(p) for _, fn in ipairs(events[30] or {}) do fn(30, p) end end
local function toServer(p, mod, name, data) onAddon(30, p, 7, "OVMOD", mod .. "\t" .. name .. "\t1/1\t" .. (data or ""), p) end
-- what the server sent this player on `mod` since the last call: { {name, data}, ... }
local function inbox(p, mod)
    local out, keep = {}, {}
    for _, m in ipairs(p.addon) do
        local id, name, i, n, data = m[2]:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
        if id == mod then out[#out + 1] = { name, data } else keep[#keep + 1] = m end
    end
    p.addon = keep
    return out
end
local function has(box, name) for _, m in ipairs(box) do if m[1] == name then return m[2] end end end
local function said(p, pat) for _, m in ipairs(p.chat) do if m:find(pat, 1, true) then return true end end end
local function clear(p) p.chat, p.addon, p.timers = {}, {}, {} end

check("loaded", type(PM) == "table" and PM.MODES ~= nil and OVMod.Dispatch ~= nil)
check("the table: four live realm modes", PM.MODES["minigolf"] and PM.MODES["bumper-balls"] and PM.MODES["coin-dash"]
    and PM.MODES["community"] and PM.validMode("minigolf") and not PM.validMode("brawl") and not PM.validMode("x;y"))
check("the intent table is made", authSql[1]:find("CREATE TABLE IF NOT EXISTS ov_playmode_intents", 1, true) ~= nil)

local ann = newPlayer("Ann", 11, 1)
local bob = newPlayer("Bob", 12, 2)
local cat = newPlayer("Cat", 13, 3)
cat.x = 102

-- ---------------------------------------------------------------- ovplay go (console only)
check("players never reach ovplay", command(ann, "ovplay go WR000001 minigolf") == nil)
check("ovplay go: an unknown mode is usage", soap("ovplay go WR000002 brawl"):find("usage", 1, true) ~= nil)
check("ovplay go: bad input is usage", soap("ovplay go WR000002 x';DROP"):find("usage", 1, true) ~= nil)
check("ovplay go: needs a real account", soap("ovplay go NOBODY minigolf"):find("no such account", 1, true) ~= nil)
bob.away = true
check("ovplay go: taken", soap("ovplay go wr000002 bumper-balls"):find("^ovplay ok: WR000002 %-> bumper%-balls") ~= nil
    and intentRows[2][1] == "bumper-balls")
login(bob)
check("login: acted on after the others' delays", #bob.timers == 1 and bob.timers[1].delay == 7000)
runTimers(bob)
local box = inbox(bob, "wumodes")
check("bumper balls alone: solo, the script sent to the client", has(box, "script") and has(box, "script"):find("Bumper Balls", 1, true) ~= nil)
check("used once", intentRows[2] == nil and PM.pending[2] == nil)
clear(bob)
login(bob)
check("nothing waiting next time", #bob.timers == 0)
bob.away = false

-- restart: the row is all there is
soap("ovplay go WR000002 coin-dash")
PM.pending[2] = nil
clear(bob)
login(bob)
runTimers(bob)
check("after a restart: from the auth DB, coin dash solo", (has(inbox(bob, "wumodes"), "script") or ""):find("Coin Dash", 1, true) ~= nil)

-- expiry
soap("ovplay go WR000002 coin-dash")
tick(PM.TTL + 1)
clear(bob)
login(bob)
check("expired after " .. (PM.TTL / 60) .. " minutes (10)", PM.TTL == 600 and #bob.timers == 0 and intentRows[2] == nil)

-- online now
clear(ann)
check("ovplay go: online now starts shortly", soap("ovplay go WR000001 minigolf"):find("online now", 1, true) ~= nil and #ann.timers == 1)
runTimers(ann)
local g = inbox(ann, "wugolf")
check("minigolf alone: a lobby, then teed off at once", has(g, "lobby") and has(g, "session") and has(g, "course"))
check("minigolf: a golf session on the realm", golf.bySeat[11] ~= nil)
golf.run(ann, "leave")

-- combat keeps the intent
tick(10)
clear(ann)
soap("ovplay go WR000001 coin-dash")
ann.combat = true
runTimers(ann)
check("in combat: says how, keeps it", said(ann, "not in combat") and said(ann, ".playmode coin-dash") and intentRows[1] ~= nil)
ann.combat = false
tick(10)
clear(ann)
check(".playmode with nothing named: the waiting one", command(ann, ".playmode") == false and #ann.timers == 1)
runTimers(ann)
check("then it starts and is used", has(inbox(ann, "wumodes"), "script") ~= nil and intentRows[1] == nil)

-- a click from more than 5 minutes ago never starts a round at login: it waits for .playmode (smoke 2026-10-30)
tick(10)
soap("ovplay go WR000002 bumper-balls")
bob.away = true
tick(PM.LOGIN_FRESH + 1)
clear(bob)
login(bob)
runTimers(bob)
check("stale click: no round at login", has(inbox(bob, "wumodes"), "script") == nil)
check("stale click: says it's waiting and how", said(bob, "Waiting for you: Bumper Balls") and said(bob, ".playmode bumper-balls") and intentRows[2] ~= nil)
tick(10)
clear(bob)
command(bob, ".playmode")
runTimers(bob)
check("stale click: .playmode then starts it", has(inbox(bob, "wumodes"), "script") ~= nil and intentRows[2] == nil)

-- a reconnect never starts a round by itself: only the first login after the click has its turn
tick(10)
soap("ovplay go WR000002 coin-dash")
bob.combat = true
clear(bob)
login(bob)
runTimers(bob)
check("first login in combat: says how, keeps it", said(bob, "not in combat") and intentRows[2] ~= nil)
bob.combat = false
tick(20)
clear(bob)
login(bob)   -- a reconnect after a disconnect
runTimers(bob)
check("reconnect: no round by itself", has(inbox(bob, "wumodes"), "script") == nil and intentRows[2] ~= nil)
check("reconnect: the reminder instead", said(bob, "Waiting for you: Coin Dash"))
PM.pending[2] = nil; intentRows[2] = nil
bob.away = false

-- first login waits
tick(10)
soap("ovplay go WR000003 minigolf")
cat.away = true
clear(cat)
firstLogin(cat)
login(cat)
runTimers(cat)
check("a first login is never interrupted", said(cat, "Waiting for you: Minigolf") and intentRows[3] ~= nil and golf.bySeat[13] == nil)
cat.away = false

-- party: invites, opens the window
local members = { ann, cat }
local group = { GetMembers = function() return members end, IsRaidGroup = function() return false end }
ann.group, cat.group = group, group
tick(10)
clear(ann); clear(cat)
command(ann, ".playmode bumper-balls")
local a = inbox(ann, "wumodes")
check("bumper balls in a party: a lobby, its window opened", has(a, "lobby") and has(a, "open") and not has(a, "script"))
check("the party member nearby is invited", has(inbox(cat, "wumodes"), "invite") ~= nil)
tick(10)
clear(ann); clear(cat)
command(ann, ".playmode minigolf")
a = inbox(ann, "wugolf")
check("minigolf in a party: a lobby, no tee off, the window opened", has(a, "lobby") and has(a, "open") and not has(a, "session"))
golf.run(ann, "leave")
ann.group, cat.group = nil, nil

-- the community browser
tick(10)
clear(ann)
command(ann, ".playmode community")
check("community: opens the Modes window", has(inbox(ann, "wumodes"), "open") ~= nil and said(ann, "/modes"))

-- the desktop addon's ask, and refusals
tick(10)
clear(ann)
toServer(ann, "wuplay", "go", "coin-dash")
check("wuplay go: starts it", has(inbox(ann, "wumodes"), "script") ~= nil)
clear(ann)
toServer(ann, "wuplay", "go", "coin-dash")
check("rate limit: one start every few seconds", said(ann, "One start every few seconds") and #inbox(ann, "wumodes") == 0)
tick(10)
clear(ann)
toServer(ann, "wuplay", "go", "brawl")
check("unknown id: the list, nothing started", said(ann, "Modes you can start") and #ann.addon == 0)
clear(ann)
toServer(ann, "wuplay", "go", "../../x")
check("odd id: refused", said(ann, "Modes you can start") and #ann.addon == 0)
clear(ann)
command(ann, ".playmode cancel")
check(".playmode cancel with nothing", said(ann, "Nothing is waiting"))
check("other commands pass through", command(ann, "golf courses") == false and command(ann, ".wugo") == nil)

-- no game-brand names in what players read
local src = io.open(scripts .. "/ov_playmode.lua"):read("*a")
local bad = false
for line in src:gmatch("[^\n]+") do
    if not line:match("^%s*%-%-") and (line:lower():find("warcraft", 1, true) or line:find("%f[%w]WoW%f[%W]") or line:lower():find("blizzard", 1, true)) then bad = true end
end
check("no game-brand names", not bad)

-- ---------------------------------------------------------------- the launcher's LeylinePlay addon (fake UI)
local sent, frames, now = {}, {}, 1000
local function ui()
    sent, frames = {}, {}
    _G.LeylinePlayDB = nil
    function UnitName() return "Ann" end
    function time() return 1800000000 + now end
    function GetTime() return now end
    function SendAddonMessage(prefix, msg, kind, target) sent[#sent + 1] = { prefix, msg, kind, target } end
    function CreateFrame()
        local f = { scripts = {}, events = {} }
        function f:RegisterEvent(e) self.events[e] = true end
        function f:UnregisterEvent(e) self.events[e] = nil end
        function f:SetScript(k, fn) self.scripts[k] = fn end
        frames[#frames + 1] = f
        return f
    end
end
local function fire(e)
    for _, f in ipairs(frames) do if f.events[e] and f.scripts.OnEvent then f.scripts.OnEvent(f, e) end end
end
local function wait(s)
    for _ = 1, s * 10 do now = now + 0.1; for _, f in ipairs(frames) do if f.scripts.OnUpdate then f.scripts.OnUpdate(f, 0.1) end end end
end
local function addon(pending)
    ui()
    LEYLINE_PENDING = pending
    dofile(launcherAddon)
end
addon({ mode = "minigolf", nonce = "n1", made = 1800000000 + now - 30 })
fire("PLAYER_ENTERING_WORLD")
check("addon: waits a little after login", #sent == 0)
wait(10)
check("addon: asks once on the OVMOD channel", #sent == 1 and sent[1][1] == "OVMOD" and sent[1][2] == "wuplay\tgo\t1/1\tminigolf"
    and sent[1][3] == "WHISPER" and sent[1][4] == "Ann")
fire("PLAYER_ENTERING_WORLD"); wait(10)
check("addon: not again in this session", #sent == 1)
local db = LeylinePlayDB
addon({ mode = "minigolf", nonce = "n1", made = 1800000000 + now - 30 })
LeylinePlayDB = db   -- saved variables come back at the next login
fire("ADDON_LOADED"); fire("PLAYER_ENTERING_WORLD"); wait(10)
check("addon: the same nonce never again (saved variables)", #sent == 0)
addon({ mode = "minigolf", nonce = "n2", made = 1800000000 + now - 1200 })
fire("PLAYER_ENTERING_WORLD"); wait(10)
check("addon: a stale one (over 15 minutes) is ignored", #sent == 0)
addon({ mode = "mini golf;x", nonce = "n3", made = 1800000000 + now })
fire("PLAYER_ENTERING_WORLD"); wait(10)
check("addon: an odd id is ignored", #sent == 0)
addon(nil)
fire("PLAYER_ENTERING_WORLD"); wait(10)
check("addon: nothing pending, nothing sent", #sent == 0)
-- end to end: the addon's message reaches the realm
addon({ mode = "coin-dash", nonce = "n4", made = 1800000000 + now })
fire("PLAYER_ENTERING_WORLD"); wait(10)
tick(10)
clear(ann)
local m = sent[1]
onAddon(30, ann, 7, m[1], m[2], ann)
check("addon -> realm: coin dash starts", has(inbox(ann, "wumodes"), "script") ~= nil)

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
