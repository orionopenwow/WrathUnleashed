-- lua5.1 stream/tests/test_ov_workshop.lua [lua_scripts dir]
-- The Leyline Workshop's realm half (ov_workshop.lua) under a fake mod-ale, loaded the way ALE loads it: after
-- ov_modapi.lua, ov_golf.lua and ov_modes.lua (name order), with a stand-in for ov_build.lua's "wubuild" channel.
-- Covers: the tables; courses and modes joining the Workshop when published (and again: a new version); the word
-- filter; GM review (.workshop and .modes kept in step); the list (kinds, sorts, pages, only approved); thumbs up
-- and down, one per account; Play starting a course (the party is invited by ov_golf), a mode and a build, and
-- counting plays once per account; publishing a build by its code (only the builder's own); the website's
-- "ovws go" (console only) acted on at login; rate limits; a restart; no client code run; no game-brand names.
local scripts = arg[1] or "realm/custom/lua_scripts"

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

local sql, authSql = {}, {}
local charRows = {}      -- query pattern -> rows (for the restart)
local builds = {}        -- code -> { owner, name }
function CharDBExecute(s) sql[#sql + 1] = s end
local function result(rows)
    if not rows or #rows == 0 then return nil end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetString(c) return tostring(self.rows[self.i][c + 1] or "") end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end
function CharDBQuery(q)
    local code = q:match("FROM mod_builder_builds WHERE code = '(%w+)'")
    if code then local b = builds[code]; return b and result({ { b.owner, b.name } }) end
    if q:find("FROM mod_workshop_items", 1, true) then return result(charRows.items) end
    if q:find("FROM mod_workshop_votes", 1, true) then return result(charRows.votes) end
    return nil
end
local accounts = { WR000001 = 1, WR000002 = 2, WR000003 = 3 }
local intentRows = {}
function AuthDBExecute(s)
    authSql[#authSql + 1] = s
    local acc, id, ttl = s:match("REPLACE INTO ov_ws_intents .- VALUES %((%d+), (%d+), UNIX_TIMESTAMP%(%) %+ (%d+)%)")
    if acc then intentRows[tonumber(acc)] = { tonumber(id), clock + tonumber(ttl) } end
    local del = s:match("DELETE FROM ov_ws_intents WHERE account_id = (%d+)")
    if del then intentRows[tonumber(del)] = nil end
end
function AuthDBQuery(q)
    local name = q:match("FROM account WHERE username = '(%w+)'")
    if name then return accounts[name] and result({ { accounts[name] } }) end
    local acc = q:match("FROM ov_ws_intents WHERE account_id = (%d+)")
    if acc then
        local r = intentRows[tonumber(acc)]
        return r and r[2] > clock and result({ { r[1], r[2] - clock } }) or nil
    end
    return nil
end

local online, byGuid = {}, {}
local P = {}
P.__index = P
local function newPlayer(name, guid, account, gm)
    local p = setmetatable({ name = name, guid = guid, account = account, gm = gm or 0, x = 100, y = 200, z = 50, o = 0, map = 0,
        chat = {}, addon = {}, timers = {} }, P)
    online[#online + 1] = p
    byGuid[guid] = p
    return p
end
function P:GetGUIDLow() return self.guid end
function P:GetName() return self.name end
function P:GetAccountId() return self.account end
function P:GetGMRank() return self.gm end
function P:GetX() return self.x end
function P:GetY() return self.y end
function P:GetZ() return self.z end
function P:GetO() return self.o end
function P:GetMapId() return self.map end
function P:GetMap() return { IsBattleground = function() return false end, IsArena = function() return false end } end
function P:IsInCombat() return self.combat or false end
function P:GetDistance(o) return math.abs(self.x - o.x) end
function P:GetGroup() return self.group end
function P:SendBroadcastMessage(t) self.chat[#self.chat + 1] = t end
function P:SendAddonMessage(prefix, msg) self.addon[#self.addon + 1] = { prefix, msg } end
function P:RegisterEvent(fn, delay, rep) self.timers[#self.timers + 1] = { fn = fn, delay = delay } ; return #self.timers end
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
-- ov_build.lua stand-in: its "cmd" channel message, as the Builder window sends it
local buildCmds = {}
OVMod.On("wubuild", "cmd", function(player, data) buildCmds[#buildCmds + 1] = { player.name, data } end)
local WS = dofile(scripts .. "/ov_workshop.lua")
local onAddon = serverEvents[30]

local function command(p, text)
    for _, fn in ipairs(events[42] or {}) do
        local r = fn(42, p, text)
        if r == false then return false end
    end
end
local consoleOut = {}
local console = { SendSysMessage = function(_, m) consoleOut[#consoleOut + 1] = m end }
local function soap(text)
    for _, fn in ipairs(events[42] or {}) do
        local r = fn(42, nil, text, console)
        if r == false then return consoleOut[#consoleOut] end
    end
end
local function login(p) for _, fn in ipairs(events[3] or {}) do fn(3, p) end end
local function toServer(p, mod, name, data)
    local s = data or ""
    local n = math.max(1, math.ceil(#s / 200))
    for i = 1, n do onAddon(30, p, 7, "OVMOD", mod .. "\t" .. name .. "\t" .. i .. "/" .. n .. "\t" .. s:sub((i - 1) * 200 + 1, i * 200), p) end
end
-- What the server sent this player on the Workshop channel since the last call: { {name, data}, ... }
local function inbox(p, mod)
    mod = mod or "wuws"
    local out, parts, keep = {}, {}, {}
    for _, m in ipairs(p.addon) do
        local id, name, i, n, data = m[2]:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
        if id == mod then
            parts[name] = parts[name] or {}
            parts[name][tonumber(i)] = data
            if tonumber(i) == tonumber(n) then out[#out + 1] = { name, table.concat(parts[name]) }; parts[name] = nil end
        else
            keep[#keep + 1] = m
        end
    end
    p.addon = keep
    return out
end
local function lastOf(box, name) for i = #box, 1, -1 do if box[i][1] == name then return box[i][2] end end end
local function lastChat(p) return p.chat[#p.chat] or "" end
local function said(p, pat) for _, m in ipairs(p.chat) do if m:find(pat, 1, true) then return true end end end
local function sqlHas(pat) for _, s in ipairs(sql) do if s:find(pat) then return true end end end
local function rows(data)
    local head, rest = data:match("^([^\n]*)\n?(.*)$")
    local list = {}
    for line in rest:gmatch("[^\n]+") do
        local f = {}
        for v in (line .. "\t"):gmatch("([^\t]*)\t") do f[#f + 1] = v end
        list[#list + 1] = { id = tonumber(f[1]), kind = f[2], title = f[3], author = f[4], version = tonumber(f[5]),
            plays = tonumber(f[6]), up = tonumber(f[7]), down = tonumber(f[8]), mine = tonumber(f[9]), state = f[10], descr = f[11] }
    end
    return head, list
end
local function list(p, args)
    tick(2)
    toServer(p, "wuws", "list", args)
    return rows(lastOf(inbox(p), "items") or "")
end

local ann = newPlayer("Ann", 11, 1)
local bob = newPlayer("Bob", 12, 2)
local bobAlt = newPlayer("Bobalt", 13, 2)      -- Bob's second character, same account
local gm = newPlayer("Gemma", 14, 3, 3)

-- ---------------------------------------------------------------- load
check("tables: items and votes (characters), intents (auth)", sqlHas("^CREATE TABLE IF NOT EXISTS mod_workshop_items")
    and sqlHas("^CREATE TABLE IF NOT EXISTS mod_workshop_votes") and authSql[1]:find("^CREATE TABLE IF NOT EXISTS ov_ws_intents") ~= nil)
check("a global API for the other scripts", OVWorkshop == WS and type(WS.Published) == "function" and type(WS.Reviewed) == "function")
check("hooks from ov_golf and ov_modes", type(OVWorkshopHooks.course) == "table" and OVWorkshopHooks.mode == modes.modes)
check("events: login and command", #(events[3] or {}) >= 1 and #(events[42] or {}) >= 3)
check("OVMod.Dispatch exists", type(OVMod.Dispatch) == "function")
check("the built-in courses and modes are not Workshop items", next(WS._items) == nil)

-- ---------------------------------------------------------------- word filter
local bad = WS.BadWord
check("filter: plain titles pass", not bad("Windmill Nine") and not bad("Class Act") and not bad("Grass Hopper")
    and not bad("Assassin Arena") and not bad("Cocktail Cove") and not bad("Dickens Park") and not bad("Scunthorpe Links"))
check("filter: the worst words are caught", bad("Shit Hole") and bad("sh1t hole") and bad("SHIIIT") and bad("f u c k")
    and bad("f.u.c.k") and bad("motherfucker run") and bad("n1gger") and bad("Fags"))

-- ---------------------------------------------------------------- courses join when published
local COURSE = "course Windmill Nine\nhole 2 First\ntee 0 0 0\ncup 0 0 5\nturf 0 -0.25 2 1 0.25 4\n"
toServer(ann, "wugolf", "publish", COURSE)
local course = WS._items[1]
check("a published course is Workshop item #1", course and course.kind == "course" and course.ref == "ann_windmillnine")
check("a course is approved at once, author is the character name", course.state == "approved" and course.author == "Ann" and course.guid == 11)
check("the author is told its number", said(ann, "#1"))
check("stored with REPLACE INTO", sqlHas("^REPLACE INTO mod_workshop_items .-VALUES %(1, 'course', 'ann_windmillnine', 'Windmill Nine', 'Ann', 11, 1,"))
tick(5)
toServer(ann, "wugolf", "publish", COURSE .. "hole 3 Second\ntee 0 0 0\ncup 0 0 9\n")
check("publishing again is a new version of the same item", WS._items[1].version == 2 and WS._items[2] == nil and WS._items[1].state == "approved")
toServer(bob, "wugolf", "publish", "course Shit Hole\nhole 2\ntee 0 0 0\ncup 0 0 5\n")
local flagged = WS._items[2]
check("a course with a flagged title waits for a GM", flagged and flagged.state == "pending")

-- ---------------------------------------------------------------- modes join and wait for review
local MODE = 'Mode.Title = "Coin Rush"\nfunction OnStart() HUD.Say("go") end\n-- padding padding\n'
toServer(ann, "wumodes", "publish", MODE)
local mode = WS._items[3]
check("a published mode is an item, waiting for a GM", mode and mode.kind == "mode" and mode.ref == "ann_coinrush" and mode.state == "pending")
toServer(bob, "wumodes", "publish", 'Mode.Title = "Tag Arena"\nfunction OnStart() end\n-- padding padding padding\n')
local mode2 = WS._items[4]
command(gm, "modes approve bob_tagarena")
check(".modes approve approves the Workshop item too", mode2.state == "approved" and modes.modes["bob_tagarena"].approved)

-- ---------------------------------------------------------------- GM review
command(bob, "workshop approve 3")
check("players can't review", lastChat(bob):find("GMs", 1, true) and mode.state == "pending")
command(gm, "workshop pending")
check(".workshop pending lists what waits (and flags titles)", said(gm, "#2 course") and said(gm, "title flagged") and said(gm, "#3 mode: Coin Rush by Ann"))
tick(2)
command(gm, "workshop approve 3")
check(".workshop approve approves the mode in /modes too", mode.state == "approved" and modes.modes["ann_coinrush"].approved == true
    and sqlHas("^UPDATE mod_modes SET approved = 1 WHERE mkey = 'ann_coinrush'"))
tick(2)
command(gm, "workshop reject 2")
check(".workshop reject", flagged.state == "rejected")
tick(2)
command(gm, "workshop approve 99")
check("an unknown id", lastChat(gm):find("No Workshop item", 1, true) ~= nil)

-- ---------------------------------------------------------------- the list
local head, l = list(bob, "all plays 1")
check("list: approved only, header kind sort page pages", head == "all plays 1 1" and #l == 3)
local ids = {}
for _, r in ipairs(l) do ids[r.id] = r end
check("list rows carry every field", ids[1] and ids[1].title == "Windmill Nine" and ids[1].author == "Ann" and ids[1].version == 2
    and ids[1].kind == "course" and ids[1].state == "approved" and ids[1].plays == 0 and not ids[2])
head, l = list(bob, "mode new 1")
check("list: by kind", #l == 2 and l[1].kind == "mode" and l[2].kind == "mode")
check("list: newest first", l[1].id == 4 and l[2].id == 3)
head, l = list(bob, "nonsense nonsense 7")
check("list: junk arguments fall back to all, most played, a real page", head == "all plays 1 1")
toServer(bob, "wuws", "list", "all plays 1")
check("list: one a second", #inbox(bob) == 0)

-- ---------------------------------------------------------------- rating
tick(3)
toServer(bob, "wuws", "rate", "1 up")
check("thumbs up", WS._items[1].up == 1 and lastOf(inbox(bob), "rated") == "1 1 0 1")
check("the vote is stored per account", sqlHas("^REPLACE INTO mod_workshop_votes %(item_id, account_id, vote, voted_at%) VALUES %(1, 2, 1,"))
tick(3)
toServer(bobAlt, "wuws", "rate", "1 up")
check("one vote per account: a second character changes nothing", WS._items[1].up == 1)
tick(3)
toServer(bobAlt, "wuws", "rate", "1 down")
check("changing the vote moves it", WS._items[1].up == 0 and WS._items[1].down == 1)
toServer(bobAlt, "wuws", "rate", "1 none")
check("votes: one every couple of seconds", WS._items[1].down == 1)
tick(3)
toServer(bobAlt, "wuws", "rate", "1 none")
check("none takes it back", WS._items[1].down == 0 and sqlHas("^DELETE FROM mod_workshop_votes WHERE item_id = 1 AND account_id = 2"))
tick(3)
toServer(ann, "wuws", "rate", "1 up")
check("you can't rate your own", WS._items[1].up == 0 and lastChat(ann):find("own", 1, true))
tick(3)
toServer(bob, "wuws", "rate", "2 up")
check("a rejected item can't be rated", WS._items[2].up == 0)
tick(3)
toServer(gm, "wuws", "rate", "4 up"); tick(3); toServer(ann, "wuws", "rate", "4 up"); tick(3); toServer(ann, "wuws", "rate", "3 up")
head, l = list(bob, "all rating 1")
check("top rated first", l[1].id == 4 and l[1].up == 2)
head, l = list(ann, "mode rating 1")
check("my vote comes back in the row", l[1].id == 4 and l[1].mine == 1)

-- ---------------------------------------------------------------- Play
bob.group = { GetMembers = function() return { bob, bobAlt } end }
bobAlt.x = 105
tick(10)
toServer(bob, "wuws", "play", "1")
local box = inbox(bob)
check("Play on a course says what started", lastOf(box, "playing") == "1 course Windmill Nine")
local gbox = inbox(bob, "wugolf")
check("ov_golf opened the course where Bob stands", golf.bySeat[12] ~= nil and lastOf(gbox, "lobby") ~= nil)
check("Bob's party is invited", lastOf(inbox(bobAlt, "wugolf"), "invite") ~= nil)
check("a play is counted", WS._items[1].plays == 1 and sqlHas("^UPDATE mod_workshop_items SET plays = 1 WHERE id = 1"))
tick(10)
toServer(bob, "wuws", "play", "1")
check("the same account again soon is not counted again", WS._items[1].plays == 1)
tick(10)
toServer(ann, "wuws", "play", "1")
check("the author's own plays aren't counted", WS._items[1].plays == 1)
toServer(ann, "wuws", "play", "1")
check("Play: one every few seconds", lastChat(ann):find("few seconds", 1, true) ~= nil)
tick(1800)
toServer(bob, "wuws", "play", "1")
check("half an hour later it counts again", WS._items[1].plays == 2)
tick(10)
toServer(ann, "wuws", "play", "4")
check("Play on a mode hosts it (ov_modes lobby)", lastOf(inbox(ann, "wumodes"), "lobby") ~= nil and lastOf(inbox(ann), "playing") == "4 mode Tag Arena")
tick(10)
toServer(ann, "wuws", "play", "2")
check("a rejected item can't be played by others", lastChat(ann):find("isn't in the Workshop", 1, true) and WS._items[2].plays == 0)
tick(10)
toServer(bob, "wuws", "play", "77")
check("an unknown item", lastChat(bob):find("isn't in the Workshop", 1, true) ~= nil)
head, l = list(gm, "all plays 1")
check("most played first", l[1].id == 1 and l[1].plays == 2)

-- ---------------------------------------------------------------- builds: publish by code
builds["ABC234"] = { owner = 11, name = "greencamp" }
builds["XYZ789"] = { owner = 12, name = "bobfort" }
tick(40)
toServer(ann, "wuws", "publish", "nope Green")
check("a code must be 6 letters and digits", lastChat(ann):find("6-letter", 1, true) ~= nil)
tick(40)
toServer(ann, "wuws", "publish", "XYZ789 Mine now")
check("only the builder's own build", lastChat(ann):find("Only the builder", 1, true) ~= nil)
tick(40)
toServer(ann, "wuws", "publish", "QQQQQQ x")
check("an unknown code", lastChat(ann):find("No build has the code", 1, true) ~= nil)
tick(40)
toServer(ann, "wuws", "publish", "ABC234 Sh1t Camp")
check("a flagged title is refused", lastChat(ann):find("another title", 1, true) ~= nil)
tick(40)
toServer(ann, "wuws", "publish", "abc234 Green 'Camp'; DROP TABLE x")
local b = WS._items[5]
check("a build is published by its code, waiting for a GM", b and b.kind == "build" and b.ref == "ABC234" and b.state == "pending"
    and lastOf(inbox(ann), "published") == "5")
check("no quotes reach the title or SQL", b.title == "Green Camp DROP TABLE x" and not sqlHas("'Camp'"))
toServer(ann, "wuws", "publish", "abc234 Again")
check("publish: one every 30 seconds", lastChat(ann):find("30 seconds", 1, true) ~= nil)
tick(40)
command(gm, "workshop approve 5")
tick(10)
toServer(bob, "wuws", "play", "5")
check("Play on a build pastes it through ov_build (the build area's own checks)", buildCmds[#buildCmds][1] == "Bob"
    and buildCmds[#buildCmds][2] == "load ABC234")

-- ---------------------------------------------------------------- dot commands
tick(20)
command(ann, "workshop describe 1 Nine holes and a windmill. \"Fun\" |cffff0000for all|r")
check("describe: the author's own, cleaned", WS._items[1].descr == "Nine holes and a windmill. Fun cffff0000for allr")
tick(20)
command(bob, "workshop describe 1 mine now")
check("describe: not someone else's", WS._items[1].descr:find("windmill", 1, true) ~= nil)
tick(2)
command(ann, "workshop mine")
check(".workshop mine lists your items with their state", said(ann, "#5 build: Green Camp DROP TABLE x (v1, approved"))
tick(2)
command(ann, "workshop")
check(".workshop alone is help", said(ann, ".workshop play <id>"))
check("help points at the web page", said(ann, "play.openvanilla.app/wrath/workshop"))
tick(10)
command(bob, "workshop play 4")
check(".workshop play <id>", lastOf(inbox(bob), "playing") == "4 mode Tag Arena")

-- ---------------------------------------------------------------- the website's Play: ovws go (console only)
check("ovws: players never reach it", command(bob, "ovws go WR000002 1") == nil)
check("ovws go: needs an approved item", soap("ovws go WR000002 2"):find("no approved", 1, true) ~= nil)
check("ovws go: needs a real account", soap("ovws go NOBODY 1"):find("no such account", 1, true) ~= nil)
check("ovws go: bad input is usage", soap("ovws go WR000002 x;DROP"):find("usage", 1, true) ~= nil)
bob.away = true; bobAlt.away = true
check("ovws go: taken", soap("ovws go WR000002 1"):find("^ovws ok: WR000002 %-> 1") ~= nil and intentRows[2][1] == 1)
bob.away = false
bob.timers = {}
tick(5)
login(bob)
check("on login it waits a few seconds first", #bob.timers == 1 and bob.timers[1].delay >= 5000)
local before = WS._items[1].plays
tick(10)
golf.run(bob, "leave")
runTimers(bob)
check("then it plays the item for that character", lastOf(inbox(bob), "playing") == "1 course Windmill Nine" and golf.bySeat[12] ~= nil)
check("used once", intentRows[2] == nil and WS._intents[2] == nil)
login(bob)
check("and not again at the next login", #bob.timers == 0)
check("ovws go: online now plays shortly", soap("ovws go WR000001 4"):find("online now", 1, true) ~= nil and #ann.timers == 1)
tick(1801)
runTimers(ann)
check("an intent expires after 30 minutes", lastOf(inbox(ann), "playing") == nil)

-- ---------------------------------------------------------------- unpublish
tick(5)
command(gm, "workshop unpublish 1")
local inGolf = false
for _, c in ipairs(OVWorkshopHooks.course.COURSES) do if c.key == "ann_windmillnine" then inGolf = true end end
check(".workshop unpublish takes a course out of the Workshop and /golf", WS._items[1] == nil and not inGolf
    and sqlHas("^DELETE FROM mod_workshop_items WHERE id = 1") and sqlHas("^DELETE FROM mod_workshop_votes WHERE item_id = 1"))
tick(5)
command(gm, "workshop unpublish 4")
check("unpublishing a mode hides it from /modes for others", WS._items[4] == nil and modes.modes["bob_tagarena"].approved == false)
tick(5)
command(gm, "modes reject ann_coinrush")
check(".modes reject removes the Workshop item", WS._items[3] == nil)

-- ---------------------------------------------------------------- client data is never trusted
local n = #sql
toServer(bob, "wuws", "play", string.rep("9", 300))
toServer(bob, "wuws", "list", string.rep("x", 400))
check("oversized messages are dropped", #sql == n)
local src = io.open(scripts .. "/ov_workshop.lua"):read("*a")
local code = src:gsub("%-%-[^\n]*", "")
check("no client-sent code is ever run", not code:find("loadstring", 1, true) and not code:find("dofile", 1, true)
    and not code:find("%f[%w]load%s*%(") and not code:find("setfenv", 1, true))

-- ---------------------------------------------------------------- a restart
local saved = {
    items = { { 5, "build", "ABC234", "Green Camp", "Ann", 11, 1, 100, 100, 7, 1, 0, "approved", "A camp." },
              { 6, "mode", "bad key!", "Broken", "Ann", 11, 1, 100, 100, 0, 0, 0, "approved", "" },
              { 8, "course", "zed_course", "Zed's Course", "Zed", 20, 3, 100, 100, 2, 0, 0, "weird", "" } },
    votes = { { 5, 2, 1 }, { 5, 3, "-1" }, { 9, 2, 1 } },
}
charRows = saved
OVWorkshop = nil
local WS2 = dofile(scripts .. "/ov_workshop.lua")
check("restart: items come back from the table", WS2._items[5] and WS2._items[5].plays == 7 and WS2._items[5].descr == "A camp.")
local junk = false
for _, it in pairs(WS2._items) do if it.title == "Broken" or it.ref == "zed_course" then junk = true end end
check("restart: bad rows are skipped", not junk and WS2._items[8] == nil)
check("restart: votes come back, for items that exist", WS2._votes[5][2] == 1 and WS2._votes[5][3] == -1 and WS2._votes[9] == nil)
check("restart: published courses and modes not yet listed are added", WS2._byRef["mode:bob_tagarena"] ~= nil)

-- ---------------------------------------------------------------- nothing players saw names the game brand
local seen = {}
for _, p in ipairs(online) do for _, m in ipairs(p.chat) do seen[#seen + 1] = m end end
for _, m in ipairs(consoleOut) do seen[#seen + 1] = m end
local brand = {}
for _, m in ipairs(seen) do
    local t = m:lower()
    for _, w in ipairs({ "world of warcraft", "warcraft", "lich king", "blizzard" }) do if t:find(w, 1, true) then brand[#brand + 1] = m end end
    if t:find("%f[%w]wow%f[%W]") then brand[#brand + 1] = m end
end
check("no game-brand names (" .. #seen .. " messages)", #brand == 0 and #seen > 20)

realPrint(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
