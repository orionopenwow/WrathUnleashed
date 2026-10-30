-- lua5.1 stream/tests/social_realm_driver.lua realm/custom/lua_scripts/ov_social.lua [start clock]
-- A fake realm for test_social.py: ov_social.lua under a fake mod-ale, driven line by line on stdin, so the portal's
-- bridge (stream/social.py) is tested against the real script. Every answer ends with a line "END".
--   USER <account id> <NAME>         an auth DB row
--   LOGIN <account id> <guid> <Char> a character enters the world;   LOGOUT <account id>
--   CMD <account id> <text>          the character types a command (".lm Bob hi")
--   ADDON <account id> <msg>         the character's addon sends a WUSO message
--   SOAP <command>                   a console command over SOAP: its output lines
--   MSGS <account id>                what that character saw since the last MSGS (chat lines), then addon lines "@..."
--   TICK <seconds>                   the clock moves on
local file = assert(arg[1], "ov_social.lua")
local clock = tonumber(arg[2]) or 2000000   -- the boot time (a restart: a new one)
os.time = function() return clock end
local events, server = {}, {}
function RegisterPlayerEvent(id, fn) events[id] = fn end
function RegisterServerEvent(id, fn) server[id] = fn end
local USERS = {}
function AuthDBQuery(q)
    local name = USERS[tonumber(q:match("id = (%d+)"))]
    if not name then return nil end
    return { GetString = function() return name end }
end
local online, byAcc = {}, {}
function GetPlayersInWorld() local t = {}; for _, p in ipairs(online) do t[#t + 1] = p end; return t end
dofile(file)

local function player(acc, guid, name)
    local p = { acc = acc, guid = guid, name = name, msgs = {}, addon = {} }
    function p:GetAccountId() return self.acc end
    function p:GetGUIDLow() return self.guid end
    function p:GetName() return self.name end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    function p:SendAddonMessage(prefix, m) self.addon[#self.addon + 1] = m end
    return p
end

for line in io.lines() do
    local cmd, rest = line:match("^(%u+) ?(.*)$")
    if cmd == "USER" then
        local id, name = rest:match("^(%d+) (%S+)$"); USERS[tonumber(id)] = name
    elseif cmd == "LOGIN" then
        local id, guid, name = rest:match("^(%d+) (%d+) (%S+)$")
        local p = player(tonumber(id), tonumber(guid), name)
        online[#online + 1] = p; byAcc[tonumber(id)] = p
        events[3](3, p)
    elseif cmd == "LOGOUT" then
        local p = byAcc[tonumber(rest)]
        if p then
            events[4](4, p)
            for i, q in ipairs(online) do if q == p then table.remove(online, i) break end end
            byAcc[tonumber(rest)] = nil
        end
    elseif cmd == "CMD" then
        local id, text = rest:match("^(%d+) (.*)$"); events[42](42, byAcc[tonumber(id)], text)
    elseif cmd == "ADDON" then
        local id, text = rest:match("^(%d+) (.*)$"); local p = byAcc[tonumber(id)]
        server[30](30, p, 7, "WUSO", text, p)
    elseif cmd == "SOAP" then
        events[42](42, nil, rest, { SendSysMessage = function(_, m) print(m) end })
    elseif cmd == "MSGS" then
        local p = byAcc[tonumber(rest)]
        if p then
            for _, m in ipairs(p.msgs) do print(m) end
            for _, m in ipairs(p.addon) do print("@" .. m) end
            p.msgs, p.addon = {}, {}
        end
    elseif cmd == "TICK" then
        clock = clock + tonumber(rest)
    end
    print("END")
    io.stdout:flush()
end
