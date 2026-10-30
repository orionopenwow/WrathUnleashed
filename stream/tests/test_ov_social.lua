-- lua5.1 stream/tests/test_ov_social.lua [realm/custom/lua_scripts/ov_social.lua]
-- ov_social.lua under a fake mod-ale: the SOAP console (pull, msg, tell, fr), presence events, .lm/.lr/.lf, the
-- WUSO addon messages, the sender stamped from the auth DB (never the client), bots left out, rate limits, escaping.
local file = arg[1] or "realm/custom/lua_scripts/ov_social.lua"
local clock = 1000000
os.time = function() return clock end
local events, server = {}, {}
function RegisterPlayerEvent(id, fn) events[id] = fn end
function RegisterServerEvent(id, fn) server[id] = fn end
local USERS = { [1] = "WR000001", [2] = "WR000002", [3] = "RNDBOT0042", [4] = "WR000004" }
local authQueries = 0
function AuthDBQuery(q)
    authQueries = authQueries + 1
    local id = tonumber(q:match("id = (%d+)"))
    local name = USERS[id]
    if not name then return nil end
    return { GetString = function() return name end }
end
local online = {}
function GetPlayersInWorld() return online end
dofile(file)
local T = assert(OV_SOCIAL_TEST)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local function player(acc, guid, name)
    local p = { acc = acc, guid = guid, name = name, msgs = {}, addon = {} }
    function p:GetAccountId() return self.acc end
    function p:GetGUIDLow() return self.guid end
    function p:GetName() return self.name end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    function p:SendAddonMessage(prefix, m, kind, to) self.addon[#self.addon + 1] = { prefix, m, kind, to } end
    return p
end

local function console(cmd)
    local out = {}
    local h = { SendSysMessage = function(_, m) out[#out + 1] = m end }
    local r = events[42](42, nil, cmd, h)
    return out, r
end

local function hex(s) return T.hex(s) end
local function last(t) return t[#t] end

check("events registered", events[3] and events[4] and events[42] and server[30])
check("hex round trip", T.unhex(hex("Héllo |cff0000ff:x")) == "Héllo |cff0000ff:x")
check("bad hex refused", T.unhex("zz") == nil and T.unhex("abc") == nil)

local alice = player(1, 11, "Alicia")
local bob = player(2, 22, "Bobbert")
local bot = player(3, 33, "Botty")
online = { alice, bob, bot }

-- before the portal pulls: nothing is queued, the player hears why
events[3](3, alice)
check("login before the portal pulls: not queued", #T.queue() == 0)
check(".lm handled", events[42](42, alice, ".lm Bob hi there") == false)
check(".lm with the portal away: says offline", last(alice.msgs):find("offline right now") and #T.queue() == 0)

-- the first pull (full): everyone online but the bot
local out = console("ovsocial pull 0 0 1")
check("pull header", out[1] == string.format("ovsocial ok %d 0 0", T.BOOT))
local ps = {}
for _, l in ipairs(out) do if l:sub(1, 2) == "P " then ps[#ps + 1] = l end end
check("full pull lists online players, never bots", #ps == 2 and ps[1] == "P WR000001 " .. hex("Alicia") .. " 11"
    and ps[2] == "P WR000002 " .. hex("Bobbert") .. " 22")

-- presence and messages, stamped with the character's own account
events[3](3, bob)
check("login queued with the auth DB's account name", last(T.queue()).line == "I 1 WR000002 " .. hex("Bobbert"))
events[42](42, alice, "lm Bob hi |cffff0000red|r")
local m = last(T.queue()).line
check(".lm queued: account, character, friend, text (hex)",
    m == "M 2 WR000001 " .. hex("Alicia") .. " " .. hex("Bob") .. " " .. hex("hi |cffff0000red|r"))
check(".lm echoed whisper-style, colour codes defused",
    last(alice.msgs):find("^|cff66ccff%[Leyline%]|r |cffff80ffTo %[Bob%]: hi ||cffff0000red||r|r$") ~= nil)
check(".lm tells the panel too (O:)", last(alice.addon)[1] == "WUSO" and last(alice.addon)[2]:find("^O:Bob:hi") ~= nil
    and last(alice.addon)[3] == 7 and last(alice.addon)[4] == alice)
local before = #T.queue()
events[42](42, alice, "lm Bob")
check(".lm without text: usage, nothing queued", #T.queue() == before and last(alice.msgs):find("%.lm <friend> <message>"))

-- the client can't pick the sender: an addon S: from alice is alice's
server[30](30, alice, 7, "WUSO", "S:Bob:from the panel", alice)
check("addon S: queued as the sender's own account", last(T.queue()).line:find("^M %d+ WR000001 ") ~= nil)
check("addon hook returns false (never relayed)", server[30](30, alice, 7, "WUSO", "S:Bob:x", alice) == false)
check("other prefixes untouched", server[30](30, alice, 7, "OTHER", "S:Bob:x", alice) == nil)

-- the portal pulls again: everything since 0, then acknowledges
out = console("ovsocial pull 0 " .. T.BOOT .. " 0")
local n = tonumber(out[1]:match("^ovsocial ok %d+ %d+ (%d+)$"))
local upto = tonumber(out[1]:match("^ovsocial ok %d+ (%d+)"))
check("pull returns the queued events", n == #T.queue() and n >= 3 and out[2]:sub(1, 2) == "I ")
out = console("ovsocial pull " .. upto .. " " .. T.BOOT .. " 0")
check("asking after the last one drops them", out[1] == string.format("ovsocial ok %d %d 0", T.BOOT, upto) and #T.queue() == 0)
events[4](4, bob)
out = console("ovsocial pull " .. upto .. " 99 0")
check("a pull from an earlier boot gets everything again", #out == 2 and out[2]:find("^O %d+ WR000002 ") ~= nil)
console("ovsocial pull " .. (upto + 1) .. " " .. T.BOOT .. " 0")

-- rate limit: 8 actions per 30 s
local carl = player(4, 44, "Carl")
online[#online + 1] = carl
for i = 1, 8 do events[42](42, carl, "lm Alicia line " .. i) end
local q0 = #T.queue()
events[42](42, carl, "lm Alicia one too many")
check("rate limit at 8 per 30 s", #T.queue() == q0 and last(carl.msgs):find("Slow down"))
clock = clock + 31
events[42](42, carl, "lm Alicia again")
check("rate limit resets", #T.queue() == q0 + 1)

-- incoming: msg, tell
out = console("ovsocial msg WR000001 77 " .. hex("Bob") .. " " .. hex("yo |Hitem:1|h[x]|h"))
check("msg shown whisper-style with [Leyline]", out[1] == "ovsocial ok shown 77"
    and last(alice.msgs) == "|cff66ccff[Leyline]|r |cffff80ff[Bob] whispers: yo ||Hitem:1||h[x]||h|r")
check("msg tells the panel (M:)", last(alice.addon)[2] == "M:Bob:yo  Hitem 1 h[x] h" or last(alice.addon)[2]:find("^M:Bob:yo") ~= nil)
out = console("ovsocial msg WR000009 78 " .. hex("Bob") .. " " .. hex("hi"))
check("msg for someone not online: none", out[1] == "ovsocial none")
out = console("ovsocial msg WR000001 x zz zz")
check("bad msg refused", out[1]:find("usage"))
events[42](42, alice, ".lr thanks")
check(".lr replies to the last sender", last(T.queue()).line:find(" " .. hex("Bob") .. " " .. hex("thanks") .. "$") ~= nil)
out = console("ovsocial tell WR000001 " .. hex("Bob is now in game (Bobbert)."))
check("tell", out[1] == "ovsocial ok told" and last(alice.msgs) == "|cff66ccff[Leyline]|r Bob is now in game (Bobbert).")
check("bots: never found for delivery", console("ovsocial tell RNDBOT0042 " .. hex("x"))[1] == "ovsocial none")

-- the friends list in two parts
local text = "Bob\t4821\tg\tBobbert on WrathUnleashed\t2\nDana\t1234\to\t\t0\nEve\t5555\tq\tWants to be friends\t0"
local h = hex(text)
local a1, a2 = h:sub(1, 40), h:sub(41)
out = console("ovsocial fr WR000001 1 2 " .. a1)
check("fr part 1 waits for the rest", out[1] == "ovsocial ok part 1" and T.lists()["WR000001"] == nil)
alice.addon = {}
server[30](30, alice, 7, "WUSO", "L", alice)   -- the panel asks (no list yet: an empty one, and asks the portal)
check("panel asks: empty list sent", alice.addon[1][2] == "B:0" and alice.addon[2][2] == "E")
alice.addon = {}
out = console("ovsocial fr WR000001 2 2 " .. a2)
check("fr complete", out[1] == "ovsocial ok fr 3" and #T.lists()["WR000001"] == 3)
check("the panel gets the rows at once", #alice.addon == 5 and alice.addon[1][2] == "B:3"
    and alice.addon[2][2] == "R:g:2:Bob:4821:Bobbert on WrathUnleashed" and alice.addon[4][2] == "R:q:0:Eve:5555:Wants to be friends"
    and alice.addon[5][2] == "E")
alice.msgs = {}
events[42](42, alice, "lf")
check(".lf prints the list", #alice.msgs == 3 and alice.msgs[1]:find("Bob#4821: in game %- Bobbert on WrathUnleashed")
    and alice.msgs[1]:find("2 new") and alice.msgs[3]:find("Eve#5555: wants to be friends"))
check("fr with a bad part refused", console("ovsocial fr WR000001 3 2 00")[1]:find("usage"))
check("fr empty list", console("ovsocial fr WR000002 1 1 -")[1] == "ovsocial ok fr 0")
check("parseList ignores junk lines", #T.parseList("a\tb\tz\t\t0\nok\t1\tg\tw\t1") == 1)

-- .lf actions
events[42](42, alice, "lf add Dana#1234")
check(".lf add queued", last(T.queue()).line == "F " .. last(T.queue()).seq .. " WR000001 " .. hex("Alicia") .. " " .. hex("add") .. " " .. hex("Dana#1234"))
events[42](42, alice, "lf offline")
check(".lf offline queued", last(T.queue()).line:find(" " .. hex("offline") .. " $") ~= nil or last(T.queue()).line:find(" " .. hex("offline") .. " ") ~= nil)
local q1 = #T.queue()
events[42](42, alice, "lf frobnicate x")
check(".lf unknown verb: help, nothing queued", #T.queue() == q1 and last(alice.msgs):find("%.lf add"))
server[30](30, alice, 7, "WUSO", "F:accept:Eve", alice)
check("addon F: queued", last(T.queue()).line:find(" " .. hex("accept") .. " " .. hex("Eve") .. "$") ~= nil)

-- bots can't use it
local qb = #T.queue()
events[3](3, bot)
events[42](42, bot, "lm Alicia hi")
server[30](30, bot, 7, "WUSO", "S:Alicia:hi", bot)
check("bots: no events, no messages", #T.queue() == qb and #bot.msgs == 0)

-- other commands are left alone; console verbs
check("other commands untouched", events[42](42, alice, "gm on") == nil and events[42](42, alice, "lookup item x") == nil)
check("unknown console verb", console("ovsocial nope")[1]:find("unknown verb"))
check("non-social console commands untouched", select(2, console("server info")) == nil)
check("status", console("ovsocial status")[1]:find("^ovsocial status active=true"))
check("auth DB asked once per account", authQueries <= 5)

-- nothing players see names the game's brand
local src = io.open(file):read("*a")
local shown = {}
for s in src:gmatch('"([^"]*)"') do shown[#shown + 1] = s end
local bad = false
for _, s in ipairs(shown) do
    local l = s:lower()
    if l:find("warcraft") or l:find("blizzard") or l:find("lich king") or l:find("%f[%a]wow%f[%A]") then bad = true end
end
check("no brand names in player-visible strings", not bad)

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
