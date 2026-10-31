-- The official realm's login welcome (ov_discord.lua) under a fake mod-ale: one line, where help is, the Discord.
--   lua5.1 stream/tests/test_ov_welcome.lua realm/custom/lua_scripts/ov_discord.lua
local file = assert(arg[1], "usage: lua5.1 test_ov_welcome.lua <ov_discord.lua>")
local events = {}
function CharDBExecute() end
function CharDBQuery() return nil end
function AuthDBQuery() return nil end
function RegisterPlayerEvent(id, fn) events[id] = fn end
function GetPlayersInWorld() return {} end
dofile(file)
local T = assert(OV_DISCORD_TEST)

local pass, fail = 0, 0
local function check(name, ok, extra)
    if ok then pass = pass + 1; print("PASS " .. name)
    else fail = fail + 1; print("FAIL " .. name .. (extra and ("  " .. tostring(extra)) or "")) end
end

local W = T.WELCOME
local plain = W:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", "")
check("one line", not W:find("\n"), W)
check("says where help is: .wu or the Discord", plain:find("Need help? Type .wu or ask on the Discord", 1, true) ~= nil, plain)
check("the Discord invite", plain:find("discord.gg/", 1, true) ~= nil)
check("the two things to try", plain:find("/golf", 1, true) and plain:find("/modes", 1, true))
check("ASCII only (the game font)", not W:find("[\128-\255]"))
local low = plain:lower()
check("no game-brand names", not (low:find("warcraft") or low:find("blizzard") or low:find("lich king") or low:find("%f[%a]wow%f[%A]")))

-- a player logging in gets it once (no timers in this fake: straight away)
local got = {}
local p = { GetName = function() return "Alice" end, GetAccountId = function() return 1 end, GetGUIDLow = function() return 10 end,
    SendBroadcastMessage = function(_, m) got[#got + 1] = m end }
T.onLoginWelcome(3, p)
check("sent once at login", #got == 1 and got[1] == W, #got)

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
