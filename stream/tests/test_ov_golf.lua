-- lua5.1 stream/tests/test_ov_golf.lua [addon dir] [lua_scripts dir]
-- Leyline minigolf end to end under a fake mod-ale and a fake 3.3.5a UI: the realm referee (ov_golf.lua) through
-- the OVMOD channel (ov_modapi.lua), and the HUD (WrathUnleashedUI/Golf.lua) driving a fake LeylineGolf (the
-- browser client's function). Covers: the course list, a lobby with a party invite, join, tee off, turns, shot
-- relay (input checks, wrong-turn refusals), rest reports, strokes, penalties, the cap, holes in sequence, the
-- desync warning, the final results and the record; Practice with no realm; and that the three copies of
-- Meadow Nine (client file, HUD, realm) are the same text.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local scripts = arg[2] or "realm/custom/lua_scripts"

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end
print = function() end

local clock = 2000000
os.time = function() return clock end

-- ---------------------------------------------------------------- fake mod-ale
local events, serverEvents, luaEvents = {}, {}, {}
function RegisterPlayerEvent(id, fn) events[id] = events[id] or {}; table.insert(events[id], fn) end
function RegisterServerEvent(id, fn) serverEvents[id] = fn end
function CreateLuaEvent(fn, delay, rep) luaEvents[#luaEvents + 1] = fn end
local sql, runs = {}, {}
function CharDBExecute(s)
    sql[#sql + 1] = s
    local guid, name, course, strokes, players, verified, inputs, at = s:match(
        "^INSERT INTO mod_golf_runs %(.-%) VALUES %((%d+), '(%w+)', '([%w_]+)', (%d+), (%d+), (%d+), '([^']*)', (%d+)%)")
    if guid then runs[#runs + 1] = { id = #runs + 1, name = name, course = course, strokes = tonumber(strokes), players = tonumber(players), verified = tonumber(verified), inputs = inputs } end
end
local function result(rows)
    if not rows or #rows == 0 then return nil end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetString(c) return tostring(self.rows[self.i][c + 1] or "") end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end
function CharDBQuery(q)
    local course = q:match("FROM mod_golf_runs WHERE course = '([%w_]+)'")
    if course then
        local list = {}
        for _, r in ipairs(runs) do if r.course == course then list[#list + 1] = r end end
        table.sort(list, function(a, b) return a.strokes < b.strokes end)
        local rows = {}
        for _, r in ipairs(list) do rows[#rows + 1] = { r.id, r.name, r.strokes, r.verified, r.players } end
        return result(rows)
    end
    local id = q:match("FROM mod_golf_runs WHERE id = (%d+)")
    if id then local r = runs[tonumber(id)]; return r and result({ { r.name, r.course, r.strokes, r.inputs } }) end
    return nil
end

local players, byGuid = {}, {}
local P = {}
P.__index = P
local function newPlayer(name, guid, x)
    local p = setmetatable({ name = name, guid = guid, x = x or 100, y = 200, z = 50, o = 1.25, map = 0, chat = {}, addon = {} }, P)
    players[name] = p
    byGuid[guid] = p
    return p
end
function P:GetGUIDLow() return self.guid end
function P:GetName() return self.name end
function P:GetX() return self.x end
function P:GetY() return self.y end
function P:GetZ() return self.z end
function P:GetO() return self.o end
function P:GetMapId() return self.map end
function P:GetMap() return { IsBattleground = function() return false end, IsArena = function() return false end } end
function P:IsInCombat() return false end
function P:GetDistance(o) return math.abs(self.x - o.x) end
function P:GetGroup() return self.group end
function P:SendBroadcastMessage(t) self.chat[#self.chat + 1] = t end
function P:SendAddonMessage(prefix, msg) self.addon[#self.addon + 1] = { prefix, msg } end
function GetPlayerByGUID(g) return byGuid[g] end

package.path = scripts .. "/?.lua;" .. package.path
local OVMod = dofile(scripts .. "/ov_modapi.lua")
package.loaded["ov_modapi"] = OVMod
local golfMod = dofile(scripts .. "/ov_golf.lua")
local onAddon = serverEvents[30]

local function toServer(p, name, data)
    onAddon(30, p, 7, "OVMOD", "wugolf\t" .. name .. "\t1/1\t" .. (data or ""), p)
end
-- What the server sent a player, reassembled: { {name, data}, ... } since the last call.
local function inbox(p)
    local out, bufs = {}, {}
    for _, m in ipairs(p.addon) do
        local mod, name, i, n, data = m[2]:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
        if mod == "wugolf" then
            i, n = tonumber(i), tonumber(n)
            bufs[name] = bufs[name] or {}
            bufs[name][i] = data
            if i == n then out[#out + 1] = { name, table.concat(bufs[name], "", 1, n) }; bufs[name] = nil end
        end
    end
    p.addon = {}
    return out
end
local function find(list, name)
    for _, m in ipairs(list) do if m[1] == name then return m[2] end end
end
local function lastChat(p) return p.chat[#p.chat] or "" end
local function anyMsg(list, text)
    for _, m in ipairs(list) do if m[1] == "msg" and m[2]:find(text, 1, true) then return true end end
    return false
end

-- ---------------------------------------------------------------- the realm, two players
local ann = newPlayer("Ann", 11, 100)
local bo = newPlayer("Bo", 12, 110)
local far = newPlayer("Far", 13, 400)
local group = { GetMembers = function() return { ann, bo, far } end }
ann.group, bo.group, far.group = group, group, group

toServer(ann, "courses", "")
local list = find(inbox(ann), "courses") or ""
check("the realm lists Meadow Nine with its holes and par", list:find("meadow,Meadow Nine,9,26", 1, true) ~= nil)

toServer(ann, "start", "meadow")
local a1, b1, f1 = inbox(ann), inbox(bo), inbox(far)
check("the host gets a lobby", (find(a1, "lobby") or ""):match("^1 Ann Meadow_Nine Ann$") ~= nil)
check("a party member nearby is invited", (find(b1, "invite") or "") == "1 Ann Meadow_Nine")
check("a party member far away is not", find(f1, "invite") == nil)

toServer(bo, "go", "")
check("an invite alone isn't a seat", lastChat(bo):find("not in a game") ~= nil)
toServer(bo, "join", "1")
check("joining updates everyone's lobby", (find(inbox(ann), "lobby") or ""):match("Ann,Bo$") ~= nil)
toServer(bo, "go", "")
check("only the host tees off", lastChat(bo):find("Only the host") ~= nil)
inbox(bo)

toServer(ann, "go", "")
local a2, b2 = inbox(ann), inbox(bo)
local session = find(a2, "session") or ""
check("tee off sends the session at the host's spot", session:match("^1 100%.000 200%.000 50%.000 1%.2500 Meadow_Nine$") ~= nil)
local course = find(b2, "course") or ""
check("everyone gets the whole course text", #course > 2000 and course:find("hole 4 Grand Finale", 1, true) ~= nil)
check("hole 1 starts", (find(a2, "hole") or "") == "1 2 First Putt")
check("Ann putts first, from the tee", (find(a2, "turn") or ""):match("^Ann 1 0%.000 0%.110 0%.000 0 0$") ~= nil)

toServer(bo, "shot", "0 500")
check("out of turn, a shot is ignored", find(inbox(ann), "shot") == nil)
toServer(ann, "shot", "4000 500")
check("an aim out of range is ignored", find(inbox(ann), "shot") == nil)
toServer(ann, "shot", "0 1001")
check("a power out of range is ignored", find(inbox(ann), "shot") == nil)
toServer(ann, "shot", "12 640")
local shotA, shotB = find(inbox(ann), "shot") or "", find(inbox(bo), "shot") or ""
check("a shot goes to everyone, same input, phase and shot number", shotA ~= "" and shotA == shotB
    and shotA:match("^Ann 0%.000 0%.110 0%.000 12 640 0 1 1$") ~= nil)
toServer(ann, "shot", "12 640")
check("one shot at a time", find(inbox(bo), "shot") == nil)

-- Bo's client agrees; Ann reports where it stopped.
toServer(bo, "rest", "1 rest 0.100 0.110 7.500 00aa11bb22cc33dd")
toServer(ann, "rest", "1 rest 0.100 0.110 7.500 00aa11bb22cc33dd")
local a3 = inbox(ann)
check("a rest moves the game on: Ann again, from where it stopped", (find(a3, "turn") or ""):match("^Ann 2 0%.100 0%.110 7%.500") ~= nil)
check("the scorecard counts it", (find(a3, "score") or ""):match("^Ann=1,") ~= nil)
inbox(bo)

clock = clock + 2
toServer(ann, "shot", "0 300")
toServer(ann, "rest", "2 holed 0.000 0.000 10.000 1111222233334444")
local a4 = inbox(ann)
check("holed in two on a par 2 is par", (find(a4, "msg") or ""):find("holes out with par", 1, true) ~= nil)
check("then it's Bo's turn on the tee", (find(a4, "turn") or ""):match("^Bo 1 0%.000 0%.110 0%.000 1 ") ~= nil)
inbox(bo)

-- Bo: water, then off the course, then the cap.
clock = clock + 2
toServer(bo, "shot", "900 900"); toServer(bo, "rest", "3 water 0 0.11 0 aaaa")
check("water costs a stroke", (find(inbox(ann), "msg") or ""):find("splashes in", 1, true) ~= nil)
for i = 4, 7 do
    clock = clock + 2
    toServer(bo, "shot", "900 900"); toServer(bo, "rest", i .. " out 0 0.11 0 aaaa")
end
local a5 = inbox(ann)
check("off the course costs a stroke too", anyMsg(a5, "goes off the course"))
check("the cap picks Bo up at par + 4", anyMsg(a5, "picks up at 6"))
check("and hole 2 starts", (find(a5, "hole") or "") == "2 3 Dogleg Right")
inbox(bo)

-- A desync: Bo's client saw a different roll.
clock = clock + 2
toServer(ann, "shot", "70 880")
local n8 = (find(inbox(bo), "shot") or ""):match("(%d+)$")
toServer(bo, "rest", n8 .. " rest 1.000 0.110 3.000 ffff0000ffff0000")
toServer(ann, "rest", n8 .. " rest 1.000 0.110 3.000 0000ffff0000ffff")
check("two different hashes are announced", anyMsg(inbox(bo), "saw Ann's shot differently"))
inbox(ann)

-- Leaving mid-game: the other plays on alone.
toServer(bo, "leave", "")
check("a leaver is announced", (find(inbox(ann), "msg") or ""):find("Bo left", 1, true) ~= nil)

-- Play Ann through the rest of the course.
local guard = 0
while golfMod.sessions[1] and guard < 200 do
    guard = guard + 1
    clock = clock + 2
    toServer(ann, "shot", "0 500")
    local s = golfMod.sessions[1]
    if s then toServer(ann, "rest", s.shotNo .. " holed 0 0 0 abcd") end
end
local fin = inbox(ann)
check("the round finishes with the results", (find(fin, "done") or ""):match("^Ann=%d+;Bo=%d+$") ~= nil)
check("then the session ends", find(fin, "end") ~= nil and golfMod.sessions[1] == nil)
local recorded = false
for _, s in ipairs(sql) do if s:find("INSERT INTO mod_golf_scores", 1, true) and s:find("'Ann'", 1, true) then recorded = true end end
check("the score is recorded, unverified after the desync", recorded and sql[#sql]:find(", 0, %d+%)$") ~= nil)

toServer(ann, "start", "nowhere")
check("an unknown course says so", lastChat(ann):find("No course called", 1, true) ~= nil)

-- A shooter who never reports doesn't stall the game.
toServer(ann, "start", "meadow"); toServer(ann, "go", ""); inbox(ann)
toServer(ann, "shot", "0 500")
clock = clock + 31
for _, fn in ipairs(luaEvents) do fn() end
check("a lost report counts from where it was hit", (find(inbox(ann), "msg") or ""):find("lost in the post", 1, true) ~= nil)
for _, fn in ipairs(events[4] or {}) do fn(4, ann) end
check("logging out ends a solo game", next(golfMod.sessions) == nil)

-- ---------------------------------------------------------------- the HUD (one client: Ann's)
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
function Frame:Hide() local was = self.shown; self.shown = false; if was then self:Fire("OnHide") end end
function Frame:IsShown() return self.shown end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text end
function Frame:Enable() self.enabled = true end
function Frame:Disable() self.enabled = false end
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
WrathUnleashedUI = {}
WrathUnleashedUIDB = {}
-- Ann's client talks to the fake realm; what the realm whispers back arrives as CHAT_MSG_ADDON.
function SendAddonMessage(prefix, msg, chan, target)
    onAddon(30, ann, 7, prefix, msg, ann)
end
local calls = {}
local state = "aiming=0 power=0 angle=0 rolling=0 hole=0 charging=0"
function LeylineGolf(text)
    if text == "state" then return state end
    calls[#calls + 1] = text
    return "ok"
end
local function called(prefix)
    for i = #calls, 1, -1 do if calls[i]:sub(1, #prefix) == prefix then return calls[i] end end
end

dofile(dir .. "/Golf.lua")
local G = WrathUnleashedUI.Golf
local listener
for _, f in ipairs(frames) do if f.events["CHAT_MSG_ADDON"] then listener = f end end
local function deliver()
    for _, m in ipairs(ann.addon) do listener:Fire("OnEvent", "CHAT_MSG_ADDON", m[1], m[2], "WHISPER", "Ann") end
    ann.addon = {}
end

check("the practice copy of the course is the realm's", G and (function()
    local src = io.open(dir .. "/Golf.lua"):read("*a")
    local realm = golfMod.COURSES[1].text
    return src:find(realm, 1, true) ~= nil
end)())
local courseFile = os.getenv("GOLF_COURSE_FILE")
if courseFile then
    local f = io.open(courseFile)
    check("the realm's copy is the client's course file", f and f:read("*a") == golfMod.COURSES[1].text)
end

-- Practice: no realm at all.
G.Practice()
check("practice loads Meadow Nine where you stand", (called("load ") or ""):match("^load here\n") ~= nil)
check("and builds hole 1", called("hole ") == "hole 1")
check("your ball goes on the tee and you aim", called("ball ") == "ball Ann 0 0.000 0.110 0.000" and called("aim ") == "aim Ann")
G.OnShoot(15, 700)
check("a putt plays at once in practice", (called("shot ") or ""):match("^shot Ann 0%.000 0%.110 0%.000 15 700 %d+$") ~= nil)
G.OnRest("Ann", "holed", 0, 0, 10, "abcd")
check("holed: on to hole 2", called("hole ") == "hole 2")
for h = 2, 9 do
    G.OnShoot(0, 500)
    G.OnRest("Ann", "holed", 0, 0, 0, "abcd")
end
t = t + 4
_G["LeylineGolfHud"]:Fire("OnUpdate")
check("after nine holes the round ends and the course goes", called("end") == "end" and not G.playing)
check("a practice best is kept", WrathUnleashedUIDB.golfBest and WrathUnleashedUIDB.golfBest["Meadow Nine"] == 9)

-- On the realm: the window, Play here, Tee off, a turn and a shot round trip.
calls = {}
SlashCmdList["LEYLINEGOLF"]("")
deliver()
check("the window lists the realm's courses", G.courses[1] and G.courses[1].key == "meadow" and G.courses[1].par == 26)
G.PlayHere("meadow"); deliver()
check("Play here opens a lobby with Ann as host", G.lobby and G.lobby.host == "Ann")
send = nil
G.lobby = G.lobby
SendAddonMessage("OVMOD", "wugolf\tgo\t1/1\t", "WHISPER", "Ann"); deliver()
check("tee off loads the realm's course at the realm's spot", (called("load ") or ""):match("^load 100%.000 200%.000 50%.000 1%.2500\n") ~= nil)
check("and it's Ann's turn", called("aim ") == "aim Ann")
G.OnShoot(25, 610); deliver()
check("the shot comes back from the realm and plays", (called("shot ") or ""):match("^shot Ann 0%.000 0%.110 0%.000 25 610 ") ~= nil)
G.OnRest("Ann", "rest", 0.2, 0.11, 6, "beef"); deliver()
check("the rest report gives the next turn from there", (called("ball ") or ""):match("^ball Ann 0 0%.200 0%.110 6%.000") ~= nil)
G.Leave()
check("leaving clears the course", called("end") == "end" and next(golfMod.sessions) == nil)

-- The course editor: publish a course in parts, the realm lists it with its author.
local myCourse = "course Ann's 'Quick' Nine\nby Ann\n\nhole 2 Opener\ntee  0 0 0\ncup  0 0 8\nturf 0 -0.25 4   1.5 0.25 5.5\n"
    .. string.rep("# padding so the course needs several parts\n", 30)
local editorOn = true
local plainGolf = LeylineGolf
LeylineGolf = function(text)
    if text == "editorstate" then return editorOn and "on=1 hole=1 holes=1 par=2 tool=select sel=- pieces=1 undo=0 redo=0 grid=0.25 carry=0 name=Opener|" or "on=0" end
    if text == "editortext" then return myCourse end
    return plainGolf(text)
end
check("the editor is offered when the client has it", G.Editor.Available())
G.Editor.Start()
check("the editor starts here", called("editor on here") ~= nil)
G.Editor.Publish()
check("publishing also keeps a saved copy", WrathUnleashedUIDB.golfCourses and WrathUnleashedUIDB.golfCourses["Ann's 'Quick' Nine"] == myCourse)
local pump
for _, f in ipairs(frames) do if f.scripts.OnUpdate and f ~= _G["LeylineGolfHud"] and f ~= _G["LeylineGolfEditor"] and not f.name then pump = f end end
for i = 1, 5 do t = t + 1.1; if pump then pump:Fire("OnUpdate") end end
deliver()
local listed
for _, c in ipairs(golfMod.COURSES) do if c.author == "Ann" then listed = c end end
check("the realm publishes it under the author's name", listed and listed.key == "ann_annsquicknine")
check("quotes never reach the database", listed and not listed.text:find("'", 1, true))
local stored = false
for _, q in ipairs(sql) do if q:find("REPLACE INTO mod_golf_courses", 1, true) and q:find("ann_annsquicknine", 1, true) then stored = true end end
check("and stores it", stored)
toServer(ann, "courses", ""); local cl = find(inbox(ann), "courses") or ""
check("everyone's course list shows it with the author", cl:find("ann_annsquicknine,Anns Quick Nine,1,2,Ann", 1, true) ~= nil)
for i = 1, 5 do
    toServer(ann, "publish", "course Extra " .. i .. "\nhole 2\ntee 0 0 0\ncup 0 0 5\nturf 0 -0.25 2 1 0.25 4\n")
end
check("five courses each at most", lastChat(ann):find("You have 5 courses published", 1, true) ~= nil)
toServer(ann, "publish", "course Broken\nhole 2\ncup 0 0 5\n")
check("a course the game would refuse can't be published", lastChat(ann):find("can't be published", 1, true) ~= nil)
golfMod.run(ann, "unpublish ann_annsquicknine")
check("only a GM takes a course down", lastChat(ann):find("Only a GM", 1, true) ~= nil)
function ann:GetGMRank() return 3 end
golfMod.run(ann, "unpublish ann_annsquicknine")
check("a GM can", lastChat(ann):find("Taken down", 1, true) ~= nil)
ann.GetGMRank = nil
editorOn = false
G.Editor.Stop()
LeylineGolf = plainGolf

-- Leaderboards and replays: a solo round where every putt drops is recorded, listed and replayed.
golfMod.run(ann, "leave")
toServer(ann, "start", "meadow"); toServer(ann, "go", ""); inbox(ann)
for h = 1, 9 do
    clock = clock + 2
    toServer(ann, "shot", (h * 10) .. " " .. (500 + h))
    toServer(ann, "rest", golfMod.sessions[next(golfMod.sessions)].shotNo .. " holed 0 0 0 abcd")
end
inbox(ann)
local run = runs[#runs]
check("a finished round's inputs are recorded", run and run.name == "Ann" and run.strokes == 9 and select(2, run.inputs:gsub("|", "")) == 8
    and run.inputs:match("^10,501,%d+|20,502,%d+|") ~= nil)
check("the Bo round (with a leaver) has no replay", (function() for _, r in ipairs(runs) do if r.name == "Bo" then return false end end return true end)())
SlashCmdList["LEYLINEGOLF"]("")
G.pick = "meadow"
G.AskTop("meadow"); deliver()
check("best rounds list the course's top rounds", G.view == "top" and G.top.rows[1] and G.top.rows[1].name == "Ann" and G.top.rows[1].strokes == 9)
calls = {}
local hudFrame = _G["LeylineGolfHud"]
G.Watch(G.top.rows[1].id); deliver()
check("watching loads the course where you stand", (called("load ") or ""):match("^load here\n") ~= nil)
check("a replay never arms your aim", called("aim ") == nil)
t = t + 2; hudFrame:Fire("OnUpdate")
check("the replay plays the logged shot with its logged phase", (called("shot ") or ""):match("^shot Ann 0%.000 0%.110 0%.000 10 501 %d+$") ~= nil
    and called("shot "):match("(%d+)$") == run.inputs:match("^10,501,(%d+)"))
for h = 1, 9 do
    G.OnRest("Ann", "holed", 0, 0, 0, "abcd")
    t = t + 2; hudFrame:Fire("OnUpdate")
end
check("a faithful replay checks out", G.replayResult == true)
t = t + 4; hudFrame:Fire("OnUpdate")
-- The same round, but the replay rolls differently on hole 1 (a tampered record would do this).
G.Watch(G.top.rows[1].id); deliver()
t = t + 2; hudFrame:Fire("OnUpdate")
G.OnRest("Ann", "rest", 0, 0.11, 3, "abcd")
t = t + 2; hudFrame:Fire("OnUpdate")
for h = 1, 12 do G.OnRest("Ann", "holed", 0, 0, 0, "abcd"); t = t + 2; hudFrame:Fire("OnUpdate") end
check("a replay that doesn't reproduce the score says so", G.replayResult == false)
t = t + 4; hudFrame:Fire("OnUpdate")

-- Without the browser client's function the window says what's needed.
LeylineGolf = nil
G.Practice()
check("no LeylineGolf: Practice explains instead of failing", (G.status or ""):find("browser client", 1, true) ~= nil)

-- Nothing on screen names a game company or sells anything.
local seen = {}
for _, f in ipairs(frames) do if type(f.text) == "string" then seen[#seen + 1] = f.text end end
local all = table.concat(seen, "\n"):lower()
check("no brand names or shop words on screen", not all:find("blizzard") and not all:find("warcraft") and not all:find("buy") and not all:find("shop"))

realPrint(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
