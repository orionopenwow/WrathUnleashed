-- ov_discord.lua under a fake mod-ale:  lua5.1 hosting/tests/test_ov_discord.lua realm/custom/lua_scripts/ov_discord.lua
local file = assert(arg[1], "usage: lua5.1 test_ov_discord.lua <ov_discord.lua>")

local clock = 1000000
os.time = function() return clock end
local realGetenv = os.getenv
local ENV = {}
os.getenv = function(k) if ENV[k] ~= nil then return ENV[k] end return realGetenv(k) end

local function fakeQuery(rows)
    if not rows or #rows == 0 then return nil end
    local r = 1
    return {
        GetUInt32 = function(_, c) return rows[r][c + 1] end,
        GetString = function(_, c) return tostring(rows[r][c + 1]) end,
        NextRow = function() r = r + 1; return r <= #rows end,
    }
end

local charSql, events = {}, {}
local CHANNEL_ROWS = { { 7 }, { 8 } }      -- "World" for each faction
local BUGS = { { 3, "Arthas", 80, 571, 4395, "the |cffff0000vendor|r is gone @everyone" }, { 4, "Jaina", 12, 0, 12, "stuck" } }
local OPTOUT = { { 77 } }
function CharDBExecute(q) charSql[#charSql + 1] = q end
function CharDBQuery(q)
    charSql[#charSql + 1] = q
    if q:match("FROM channels WHERE name = 'World'") then return fakeQuery(CHANNEL_ROWS) end
    if q:match("MAX%(id%)") then return fakeQuery({ { 4 } }) end
    if q:match("FROM ov_discord_optout") then return fakeQuery(OPTOUT) end
    local after = q:match("FROM ov_bug_reports WHERE id > (%-?%d+)")
    if after then
        local out = {}
        for _, b in ipairs(BUGS) do if b[1] > tonumber(after) then out[#out + 1] = b end end
        return fakeQuery(out)
    end
end
local ACCOUNTS = { [1] = "PLAYER", [2] = "RNDBOT42", [3] = "OTHER" }
function AuthDBQuery(q)
    local id = tonumber(q:match("WHERE id = (%d+)") or "")
    return ACCOUNTS[id] and fakeQuery({ { ACCOUNTS[id] } })
end
function RegisterPlayerEvent(id, fn) events[id] = fn end

local function player(guid, name, account)
    local p = { msgs = {} }
    function p:GetGUIDLow() return guid end
    function p:GetName() return name end
    function p:GetAccountId() return account end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    return p
end
local alice, bot, hidden = player(10, "Alice", 1), player(11, "Botty", 2), player(77, "Quiet", 3)
local ONLINE = { alice, bot, hidden }
function GetPlayersInWorld() return ONLINE end

dofile(file)
local T = assert(OV_DISCORD_TEST)

local pass, fail = 0, 0
local function check(name, ok, extra)
    if ok then pass = pass + 1; print("PASS " .. name)
    else fail = fail + 1; print("FAIL " .. name .. (extra and ("  " .. tostring(extra)) or "")) end
end

local function console(cmd)
    local out = {}
    local h = { SendSysMessage = function(_, m) out[#out + 1] = m end }
    local r = events[42](42, nil, cmd, h)
    return out, r
end

-- hex
check("hex round trip", T.unhex(T.hex("Héllo |cff00ff00x|r")) == "Héllo |cff00ff00x|r")
check("unhex refuses odd / non-hex", T.unhex("abc") == nil and T.unhex("zz") == nil)
check("gameSafe doubles pipes and drops control chars", T.gameSafe("a|cffff0000b\n\tc", 50) == "a||cffff0000b c")
check("gameSafe caps without half a UTF-8 character", T.gameSafe(string.rep("é", 10), 5) == "éé")

-- inactive: nothing queued before the daemon's first pull
events[22](22, alice, "hello before", 17, 0, -7)
check("nothing queued while no daemon pulls", #T.queue() == 0)

local out, r = console("wudiscord pull 0 -1")
check("pull answers from the console and is handled", r == false and out[1] == string.format("wudiscord ok %d 0 0", T.BOOT), out[1])

-- channel filter
events[22](22, alice, "hi world", 17, 0, -7)
events[22](22, alice, "other faction world", 17, 0, -8)
events[22](22, alice, "trade spam", 17, 0, 2)          -- built-in Trade
events[22](22, alice, "guild channel", 17, 0, -99)     -- another custom channel
events[22](22, alice, "unknown id", 17, 0, 0)
events[22](22, bot, "bot line", 17, 0, -7)
events[22](22, alice, "   ", 17, 0, -7)
local q = T.queue()
check("only World lines are queued (both factions)", #q == 2 and q[1].text == "hi world" and q[2].text == "other faction world", #q)
check("bots never bridge", (function() for _, e in ipairs(q) do if e.name == "Botty" then return false end end return true end)())

out = console("wudiscord pull 0 -1")
check("pull returns the lines hex-encoded", out[1] == string.format("wudiscord ok %d 2 2", T.BOOT)
    and out[2] == "C 1 " .. T.hex("Alice") .. " " .. T.hex("hi world"), out[2])
out = console("wudiscord pull 1 -1")
check("pull after a sequence returns only newer lines", #out == 2 and out[2]:match("^C 2 "), #out)
out = console("wudiscord pull 99 -1")
check("a sequence ahead of this boot gets everything (restart)", #out == 3)
out = console("wudiscord pull 1 -1 " .. (T.BOOT - 5))
check("a sequence from an earlier boot gets everything", #out == 3)
out = console("wudiscord pull 1 -1 " .. T.BOOT)
check("the same boot: only newer lines", #out == 2)

-- per-player rate limit (6 per 30 s)
for i = 1, 10 do events[22](22, alice, "spam " .. i, 17, 0, -7) end
check("per-character rate limit", #T.queue() == 2 + 4, #T.queue())
clock = clock + 31
events[22](22, alice, "after the window", 17, 0, -7)
check("rate window passes", T.queue()[#T.queue()].text == "after the window")

-- bugs
out = console("wudiscord pull 0 2")
local bugs = {}
for _, l in ipairs(out) do if l:match("^B ") then bugs[#bugs + 1] = l end end
check("bug reports newer than the id", #bugs == 2 and bugs[1]:match("^B 3 " .. T.hex("Arthas") .. " 80 571 4395 "), bugs[1])
out = console("wudiscord pull 0 4")
check("no bugs after the newest", #out == 1 + #T.queue())
out = console("wudiscord bugmax")
check("bugmax", out[1] == "wudiscord bugmax 4")

-- say
out = console("wudiscord say " .. T.hex("Mod|Person") .. " " .. T.hex("hello |Hitem:1|h[x]|h in game"))
check("say answers with the count", out[1] == "wudiscord ok said 1", out[1])
check("players see [Discord] Name: text with pipes neutralised",
    alice.msgs[#alice.msgs] == "|cff7289da[Discord]|r Mod||Person: hello ||Hitem:1||h[x]||h in game", alice.msgs[#alice.msgs])
check("bots and hidden players do not get it", #bot.msgs == 0 and #hidden.msgs == 0)
out = console("wudiscord say zz 00")
check("bad hex refused", out[1]:match("usage"))
for i = 1, 40 do console("wudiscord say " .. T.hex("A") .. " " .. T.hex("x" .. i)) end
out = console("wudiscord say " .. T.hex("A") .. " " .. T.hex("one more"))
check("Discord lines per minute are capped", out[1]:match("busy"), out[1])

-- players cannot use the console verbs
local before = #T.queue()
local r2 = events[42](42, alice, "wudiscord say " .. T.hex("x") .. " " .. T.hex("y"), nil)
check("a player typing wudiscord gets nothing done", r2 == nil and #T.queue() == before)

-- .discord off / on
events[42](42, alice, ".discord off")
check(".discord off stores the choice", charSql[#charSql]:match("REPLACE INTO ov_discord_optout %(guid%) VALUES %(10%)"))
clock = clock + 120
console("wudiscord say " .. T.hex("B") .. " " .. T.hex("hidden now"))
check("hidden player no longer gets Discord lines", not alice.msgs[#alice.msgs]:match("hidden now"))
events[42](42, alice, ".discord on")
console("wudiscord say " .. T.hex("B") .. " " .. T.hex("back"))
check(".discord on shows them again", alice.msgs[#alice.msgs]:match("B: back$"))
events[42](42, alice, ".discord")
check(".discord explains, with the Leyline name", alice.msgs[#alice.msgs]:match("Leyline Discord"))

-- stops queueing when the daemon stops pulling
clock = clock + 120
local n = #T.queue()
events[22](22, alice, "nobody listening", 17, 0, -7)
check("no daemon for a minute: nothing queued", #T.queue() == n)

-- brand rule: nothing the script itself says names the game
local src = io.open(file):read("*a")
local said = {}
for s in src:gmatch('"([^"]*)"') do said[#said + 1] = s end
local bad = table.concat(said, " "):lower()
check("no game-brand names in the script's text", not (bad:find("warcraft") or bad:find("%f[%a]wow%f[%A]")
    or bad:find("lich king") or bad:find("blizzard")))

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
