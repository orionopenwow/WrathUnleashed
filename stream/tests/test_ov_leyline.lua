-- lua5.1 stream/tests/test_ov_leyline.lua [ov_leyline.lua] [leyline-fetch.py]
-- The Leyline realm list, server half: leyline-fetch.py turns a fake relay listing into the data file,
-- ov_leyline.lua (under a fake mod-ale) reads it and answers a WULY request with chunked addon messages.
local script = arg[1] or "realm/custom/lua_scripts/ov_leyline.lua"
local fetch = arg[2] or "realm/custom/leyline-fetch.py"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local tmp = os.tmpname()
local datFile, jsonFile = tmp .. ".dat", tmp .. ".json"
local function write(path, text) local f = assert(io.open(path, "wb")); f:write(text); f:close() end
local function read(path) local f = io.open(path, "rb"); if not f then return nil end; local t = f:read("*a"); f:close(); return t end

-- a fake relay listing (the shape of hosting/relay/wurelay/listing.py)
local function rec(id, name, state, ruleset, players, bots)
    return string.format('{"schema":1,"name":%s,"official":false,"state":"%s","profile":{"game":"Wrath of the Lich King",'
        .. '"ruleset":"%s"},"community":{"realmId":"%s","lastHeartbeat":{"online":true,"players":%s,"bots":%s}}}',
        name, state, ruleset, id, players, bots)
end
write(jsonFile, '{"schema":1,"kind":"community","realms":['
    .. rec("qrstuvwxyz234567", '"Quiet Corner"', "offline", "main", 0, 0) .. ","
    .. rec("abcdefghijklmnop", '"Frost \\"Haven\\" | WoW: fun"', "live", "dalaran", 7, 2) .. ","
    .. rec("aaaaaaaaaaaaaaaa", '"for i=1,1e9 do end \\\\ end"', "live", "weird", 3, "null") .. ","
    .. rec("../../etc/passwd", '"bad id"', "live", "main", 1, 1) .. ","
    .. '{"name":"Fake Official","official":true,"community":{"realmId":"bbbbbbbbbbbbbbbb"}},"junk"]}')

local env = string.format("OV_LEYLINE_OUT='%s' ", datFile)
check("fetch script writes the file", os.execute(env .. "python3 -I " .. fetch .. " --from " .. jsonFile .. " >/dev/null") == 0)
local dat = read(datFile) or ""
check("the file is a data table; quotes and backslashes only as \\ddd", dat:match("^return { updated = %d+, realms = {")
    and not dat:gsub("\\%d%d%d", ""):find("\\", 1, true) and dat:find("\\034Haven\\034"))
check("brand names dropped by the fetch script", not dat:lower():find("wow") and not dat:find("Lich"))
check("bad ids and the fake official left out", not dat:find("passwd") and not dat:find("bbbbbbbb"))
check("a broken listing keeps the old file", os.execute(env .. "python3 -I " .. fetch .. " --from /nonexistent 2>/dev/null") ~= 0
    and read(datFile) == dat)

-- ---------------------------------------------------------------- fake mod-ale
local clock = 1000000
os.time = function() return clock end
local realGetenv = os.getenv
local envs = { OV_LEYLINE_FILE = datFile, OV_REALM_NAME = "WrathUnleashed" }
os.getenv = function(k) if envs[k] ~= nil then return envs[k] end return realGetenv(k) end
local serverEvents, playerEvents = {}, {}
function RegisterServerEvent(id, fn) serverEvents[id] = fn end
function RegisterPlayerEvent(id, fn) playerEvents[id] = fn end
local function fakePlayer(guid, bot)
    local p = { sent = {}, guid = guid }
    function p:SendAddonMessage(prefix, msg, kind, to) self.sent[#self.sent + 1] = { prefix, msg, kind, to } end
    function p:GetGUIDLow() return self.guid end
    function p:IsBot() return bot == true end
    return p
end
local world = { fakePlayer(1), fakePlayer(2), fakePlayer(3, true) }
function GetPlayersInWorld() return world end

dofile(script)
local T = assert(OV_LEYLINE_TEST)
check("handlers registered", serverEvents[30] and playerEvents[4])

local me = world[1]
-- the list's B/R/E/U lines (the M and N lines of the network fields are checked on their own below)
local function msgs(p, all)
    local out = {}
    for _, m in ipairs(p.sent) do if all or not m[2]:match("^[MN]:") then out[#out + 1] = m[2] end end
    return out
end
local r = serverEvents[30](30, me, 7, "WULY", "L", me)
local got = msgs(me)
check("handled, never relayed", r == false)
check("whispered back with prefix WULY", me.sent[1] and me.sent[1][1] == "WULY" and me.sent[1][3] == 7 and me.sent[1][4] == me)
check("begins with B:<count>:<age>", got[1] and got[1]:match("^B:4:%d+$"))
check("this realm first, players and bots counted", got[2] == "R:this:1:2:1:main:WrathUnleashed")
check("live realm by players, name cleaned", got[3] == "R:abcdefghijklmnop:1:7:2:dalaran:Frost \"Haven\" fun")
check("unknown ruleset -> custom, missing bots -> -", got[4] and got[4]:match("^R:aaaaaaaaaaaaaaaa:1:3:%-:custom:"))
check("offline realm last", got[5] == "R:qrstuvwxyz234567:0:0:0:main:Quiet Corner")
check("ends with E:<count>", got[6] == "E:4" and #got == 6)
local maxLen = 0
for _, m in ipairs(got) do if #m > maxLen then maxLen = #m end end
check("every message fits one addon message", maxLen < 200)

me.sent = {}
serverEvents[30](30, me, 7, "WULY", "L", me)
check("one request per 5 seconds", #me.sent == 0)
clock = clock + 6
serverEvents[30](30, me, 7, "WULY", "L", me)
check("...then answered again", #msgs(me) == 6)
check("other prefixes left alone", serverEvents[30](30, me, 7, "OVARM", "S:0:x", me) == nil)
me.sent = {}
serverEvents[30](30, me, 7, "WULY", string.rep("L", 100), me)
check("junk ignored", #me.sent == 0)

-- ---------------------------------------------------------------- the network fields (M and N lines)
clock = clock + 6
me.sent = {}
serverEvents[30](30, me, 7, "WULY", "L", me)
local all = msgs(me, true)
check("an M line after every R line", all[2]:match("^R:this:") and all[3]:match("^M:this:")
    and all[4]:match("^R:abcdefghijklmnop:") and all[5]:match("^M:abcdefghijklmnop:"))
check("M for an old listing: no flags, 3.3.5a, no tags", all[5] == "M:abcdefghijklmnop:-:0:-:12340:-:-:-:")
check("N: the network line before E (this realm + live ones)", all[#all - 1] == "N:3:12:3" and all[#all] == "E:4")

local function nrec(id, name, extra)
    return string.format('{"name":"%s","state":"live","profile":{"ruleset":"main","build":%s},"tags":%s,'
        .. '"region":%s,"language":%s,"maxPlayers":%s,"community":{"realmId":"%s","lastHeartbeat":{"players":%d,"bots":0},'
        .. '"uptime":{"h24":%s,"d7":%s},"score":%s,"featured":%s,"verified":%s,"new":%s,"regionEstimate":%s}}',
        name, extra.build or "12340", extra.tags or "[]", extra.region or "null", extra.lang or "null", extra.maxp or "null",
        id, extra.players or 0, extra.h24 or "null", extra.d7 or "null", extra.score or "0", extra.featured or "false",
        extra.verified or "false", extra.new or "false", extra.est or "null")
end
write(jsonFile, '{"realms":[' .. nrec("cccccccccccccccc", "Plain", { score = "30", players = 9 }) .. ","
    .. nrec("dddddddddddddddd", "Picked", { score = "12", featured = "true", verified = "true", tags = '["pvp","rp","evil"]',
        region = '"eu"', lang = '"de"', maxp = "100", d7 = "97", build = "5875" }) .. ","
    .. nrec("eeeeeeeeeeeeeeee", "Sampler", { score = "50", players = 2 }) .. ","
    .. nrec("ffffffffffffffff", "Far Away", { score = "5", est = '"oce"', lang = '"klingon now"', new = "true" }) .. "]}")
check("fetch with the network fields", os.execute(env .. "OV_LEYLINE_HOME=eeeeeeeeeeeeeeee python3 -I " .. fetch .. " --from "
    .. jsonFile .. " >/dev/null") == 0)
T.cache.at = -1e9
clock = clock + 60
me.sent = {}
serverEvents[30](30, me, 7, "WULY", "L", me)
all = msgs(me, true)
local plain = {}
for _, m in ipairs(all) do local id, rest = m:match("^M:([%w]+):(.*)$"); if id then plain[id] = rest end end
check("before the Sample Hangout (no OV_SAMPLER): the hangout's record is a realm like any other",
    plain.eeeeeeeeeeeeeeee:match("^%-:") and plain.this:match("^%-:") and all[#all - 1] == "N:5:13:1")
envs.OV_SAMPLER = "1"
clock = clock + 60
me.sent = {}
serverEvents[30](30, me, 7, "WULY", "L", me)
all = msgs(me, true)
local order, metas = {}, {}
for _, m in ipairs(all) do
    local id = m:match("^R:([%w]+):")
    if id then order[#order + 1] = id end
    local mid, rest = m:match("^M:([%w]+):(.*)$")
    if mid then metas[mid] = rest end
end
check("order: this, featured, the sample hangout, then by score",
    table.concat(order, " ") == "this dddddddddddddddd eeeeeeeeeeeeeeee cccccccccccccccc ffffffffffffffff")
check("featured realm: flags, uptime, build, region, language, max, tags", metas.dddddddddddddddd == "FV:12:97:5875:eu:de:100:pvp,rp")
check("OV_SAMPLER=1: the hangout's record flagged S, and this realm is the sample", metas.eeeeeeeeeeeeeeee:match("^S:")
    and metas.this:match("^S:") and metas.this:match(":hangout$"))
check("estimated region marked E, a bad language dropped", metas.ffffffffffffffff == "NE:5:-:12340:oce:-:-:")
check("N counts this realm once (not its relay record too)", all[#all - 1] == "N:4:11:1")

-- this realm's own relay listing (OV_LEYLINE_SELF_ID): an S line instead of a second R line, counted once
envs.OV_LEYLINE_SELF_ID = "cccccccccccccccc"
clock = clock + 6
me.sent = {}
T.cache.at = -1e9
serverEvents[30](30, me, 7, "WULY", "L", me)
all = msgs(me, true)
local sLine, ownR
for _, m in ipairs(all) do
    if m:match("^S:") then sLine = m end
    if m:match("^R:cccccccccccccccc:") then ownR = true end
end
check("own listing: S:<id>:<live>, no R line for it", sLine == "S:cccccccccccccccc:1" and not ownR)
check("own listing: not counted twice in N", all[#all - 1] == "N:3:2:1")
envs.OV_LEYLINE_SELF_ID = "../etc"
check("a malformed OV_LEYLINE_SELF_ID is ignored", T.selfId() == nil)
envs.OV_LEYLINE_SELF_ID = nil

-- the data file is read as data only
write(datFile, 'return { updated = 1, realms = { { id = "abcdefghijklmnop", name = "x" } } } while true do end')
T.cache.at = -1e9
check("a file with code in it is refused", T.readFile() == nil)
write(datFile, 'return { updated = 1, realms = { { id = "abcdefghijklmnop", name = "while true do end" } } }')
local list = T.readFile()
check("words inside strings are fine", list and list[1].name == "while true do end")
check("cleanName drops brands and escapes", T.cleanName("|cffff0000World of Warcraft|r Blizzard realm") == "realm"
    and T.cleanName("WoW") == "Unnamed realm" and T.cleanName("Wowza") == "Wowza")

-- an official realm (Vanilla Remastered, leyline-fetch's vr-realm.id): the O flag and "· Official" on its name
write(datFile, 'return { updated = 1, realms = { { id = "vrvrvrvrvrvrvrvr", name = "Vanilla Remastered", live = true, '
    .. 'build = 5875, official = true }, { id = "abcdefghijklmnop", name = "Plain", live = true } } }')
T.cache.at = -1e9
local ol = T.readFile()
check("official: read from the data file", ol and ol[1].official == true and ol[2].official == false)
local po = fakePlayer(11)
serverEvents[30](30, po, 7, "WULY", "L", po)
local om, rLine, mLine, plainR = msgs(po, true), nil, nil, nil
for _, m in ipairs(om) do
    if m:match("^R:vrvrvrvrvrvrvrvr:") then rLine = m end
    if m:match("^M:vrvrvrvrvrvrvrvr:") then mLine = m end
    if m:match("^R:abcdefghijklmnop:") then plainR = m end
end
check("official: labelled Official in the list", rLine and rLine:match(":Vanilla Remastered · Official$") ~= nil)
check("official: the O flag", mLine and mLine:match("^M:vrvrvrvrvrvrvrvr:[A-Z]*O") ~= nil)
check("official: other realms unchanged", plainR and plainR:match(":Plain$") ~= nil)
check("official: the label is never doubled", T.officialName({ official = true, name = "X · Official" }) == "X · Official")

-- missing file
os.remove(datFile)
T.cache.at = -1e9
local p2 = fakePlayer(9)
serverEvents[30](30, p2, 7, "WULY", "L", p2)
check("missing file: Realm list unavailable", msgs(p2)[1] == "U:Realm list unavailable" and #p2.sent == 1)

os.remove(jsonFile); os.remove(tmp)
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
