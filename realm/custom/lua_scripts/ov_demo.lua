-- Leyline guest pass: "Try Leyline in the Goldshire Inn" (mod-ale).
--
-- The website (stream/wrath_portal.py + stream/demo.py, behind WU_GUEST_DEMO=1) hands a visitor a
-- short-lived login from a pool of guest accounts the operator made (stream/server/demo-pool.sh:
-- accounts LYDEMO01.., each with one ready-made character). This script keeps those characters in
-- the Goldshire Inn:
--
--   * on login: brought to the inn, alive and at full health, out of any group; a welcome banner
--     and "Make a free account to keep playing"
--   * every few seconds: anyone who leaves the inn's small radius (or the map) is brought back
--   * no trade, no mail, no group invites (either way), no whispers, channels, yells, guild or
--     party chat ("say" and emotes stay: the inn is a room full of people)
--   * the pass's time: a warning two minutes before the end, then the character is logged out
--   * on logout: the script forgets the character (timers end with the session anyway)
--
-- Only accounts named LYDEMO... count, and only while the website has opened a pass for them:
--     ovdemo begin <ACCOUNT> <seconds>     ovdemo end <ACCOUNT>      (console / SOAP only)
-- "begin" is stored in acore_auth.ov_demo_passes so a realm restart keeps the pass; a LYDEMO account
-- that logs in without an open pass is logged out at once. "end" logs the character out. The website
-- also gives the account a new random password whenever a pass ends, so a past visitor can't return.
-- GMs are never held.
--
-- APIs (mod-ale, as the other ov_*.lua scripts use them): RegisterPlayerEvent 3 LOGIN, 4 LOGOUT,
-- 18 CHAT (event, player, msg, type, lang; false = blocked), 19 WHISPER (.., receiver), 20 GROUP,
-- 21 GUILD, 22 CHANNEL (.., channel), 28 MAP_CHANGE, 42 COMMAND (player nil from the console),
-- 48 CAN_INIT_TRADE (event, player, target), 49 CAN_SEND_MAIL (event, player, receiverGuid, ...),
-- 51 CAN_GROUP_INVITE (event, player, memberName). The "can" hooks return true to allow and false to
-- refuse, so they are correct whichever default the core uses (no other script uses them).
-- AuthDBQuery/AuthDBExecute, GetPlayersInWorld, GetPlayerByName, Player:Teleport/KickPlayer/IsGM/
-- GetAccountId/GetGUIDLow/GetGroup, WorldObject:RegisterEvent/RemoveEventById, Unit:IsDead/
-- ResurrectPlayer/SetHealth/GetMaxHealth, Group:RemoveMember.

-- The one public base URL (the website). Keep in step with PUBLIC_BASE_URL in stream/demo.py.
local PUBLIC_BASE_URL = "https://play.openvanilla.app"
local SIGNUP_URL = PUBLIC_BASE_URL .. "/login?next=%2Fwrath"

local PREFIX = "LYDEMO"
-- The Lion's Pride Inn, Goldshire (Elwynn Forest, map 0), in front of the innkeeper's counter.
-- Check on the live realm with .gps where you want guests to appear, and change these if needed.
local INN = { 0, -9460.3, 18.9, 57.0, 3.98 }
local CENTRE_X, CENTRE_Y = -9462.0, 16.0   -- the middle of the inn
local RADIUS = 40                          -- yards: the inn, its stairs and the porch
local Z_MIN, Z_MAX = 45, 85
local CHECK_EVERY_MS = 2000
local WARN_BEFORE = 120                    -- seconds
local TAG = "|cff5fe3ff[Leyline guest]|r "

local CHAT_YELL = 6
local KEEP_OUT = "This guest pass stays in the Goldshire Inn."
local FREE = "Make a free account to keep playing: " .. SIGNUP_URL

local byAccount = {}     -- accountId -> { demo = bool, name = "LYDEMO.." } (cache)
local passes = {}        -- ACCOUNT -> expires (os.time)
local watching = {}      -- guid -> true
local pending = {}       -- guid -> true (a teleport is queued)
local warned = {}        -- guid -> true
local lastTold = {}      -- guid -> os.time of the last "stays in the inn"

local function now() return os.time() end

local function accountName(accountId)
    local c = byAccount[accountId]
    if c then return c.name end
    local q = AuthDBQuery(string.format("SELECT username FROM account WHERE id = %d", accountId))
    local name = q and q:GetString(0):upper() or ""
    byAccount[accountId] = { name = name, demo = name:sub(1, #PREFIX) == PREFIX }
    return name
end

local function isDemo(p)
    if not p or p:IsGM() then return false end
    accountName(p:GetAccountId())
    return byAccount[p:GetAccountId()].demo
end

local function passLeft(p)
    local exp = passes[accountName(p:GetAccountId())]
    return exp and (exp - now()) or nil
end

local function loadPasses()
    local q = AuthDBQuery("SELECT a.username, p.expires_at - UNIX_TIMESTAMP() FROM ov_demo_passes p "
        .. "JOIN account a ON a.id = p.account_id WHERE p.expires_at > UNIX_TIMESTAMP()")
    if q then
        repeat
            passes[q:GetString(0):upper()] = now() + q:GetInt32(1)
        until not q:NextRow()
    end
end

local function say(p, msg) p:SendBroadcastMessage(TAG .. msg) end

local function inInn(p)
    if p:GetMapId() ~= INN[1] then return false end
    local dx, dy, z = p:GetX() - CENTRE_X, p:GetY() - CENTRE_Y, p:GetZ()
    return dx * dx + dy * dy <= RADIUS * RADIUS and z >= Z_MIN and z <= Z_MAX
end

local function leaveGroup(p)
    local g = p:GetGroup()
    if g then pcall(function() g:RemoveMember(p:GetGUID()) end) end
end

-- Deferred: teleporting from inside a login or map hook is unsafe.
local function bringBack(p, delay, quiet)
    local guid = p:GetGUIDLow()
    if pending[guid] then return end
    pending[guid] = true
    p:RegisterEvent(function(_, _, _, pl)
        pending[guid] = nil
        if not isDemo(pl) then return end
        if pl:IsDead() then pl:ResurrectPlayer(100, false) end
        pl:Teleport(INN[1], INN[2], INN[3], INN[4], INN[5])
        local t = now()
        if not quiet and (lastTold[guid] or 0) + 20 <= t then
            lastTold[guid] = t
            pl:SendAreaTriggerMessage(KEEP_OUT)
            say(pl, KEEP_OUT .. " " .. FREE)
        end
    end, delay or 250, 1)
end

local function endSession(p, why)
    say(p, why .. " " .. FREE)
    p:SendAreaTriggerMessage(why)
    local guid = p:GetGUIDLow()
    p:RegisterEvent(function(_, _, _, pl) pl:KickPlayer() end, 3000, 1)
    watching[guid] = nil
end

local function tick(p)
    local left = passLeft(p)
    if not left or left <= 0 then
        endSession(p, "Your guest pass has ended. Thanks for visiting!")
        return false
    end
    local guid = p:GetGUIDLow()
    if left <= WARN_BEFORE and not warned[guid] then
        warned[guid] = true
        p:SendAreaTriggerMessage("Two minutes left on your guest pass")
        say(p, "Two minutes left on your guest pass. " .. FREE)
    end
    if not inInn(p) then bringBack(p) end
    return true
end

local function watch(p)
    local guid = p:GetGUIDLow()
    if watching[guid] then return end
    watching[guid] = true
    p:RegisterEvent(function(eventId, _, _, pl)
        if not watching[guid] or not isDemo(pl) or not tick(pl) then
            watching[guid] = nil
            pl:RemoveEventById(eventId)
        end
    end, CHECK_EVERY_MS, 0)
end

local function welcome(p)
    p:SendAreaTriggerMessage("Welcome to Leyline! You're a guest in the Goldshire Inn")
    say(p, "Welcome to Leyline, playing in your browser. This guest pass keeps you in the Goldshire Inn: "
        .. "look around, meet the regulars, try the controls (WASD to move, right mouse to look).")
    say(p, "Chat channels, whispers, trade, mail and groups are off on guest passes. " .. FREE)
end

local function onLogin(event, player)
    local guid = player:GetGUIDLow()
    watching[guid], pending[guid], warned[guid] = nil, nil, nil
    byAccount[player:GetAccountId()] = nil       -- read the name again: the cache is per session
    if not isDemo(player) then return end
    local left = passLeft(player)
    if not left or left <= 0 then
        -- No open pass (an old password, or the realm was told the pass ended): out at once.
        endSession(player, "This guest pass isn't open. Start a new one on the website.")
        return
    end
    leaveGroup(player)
    if player:GetHealth() < player:GetMaxHealth() and not player:IsDead() then player:SetHealth(player:GetMaxHealth()) end
    bringBack(player, 1500, true)
    player:RegisterEvent(function(_, _, _, pl) welcome(pl) end, 3000, 1)
    watch(player)
end

local function onLogout(event, player)
    local guid = player:GetGUIDLow()
    if isDemo(player) then leaveGroup(player) end
    watching[guid], pending[guid], warned[guid], lastTold[guid] = nil, nil, nil, nil
    byAccount[player:GetAccountId()] = nil
end

local function onMap(event, player)
    if isDemo(player) and not inInn(player) then bringBack(player) end
end

local function refuse(p, what)
    say(p, what .. " are off on guest passes. " .. FREE)
    return false
end

local function onChat(event, player, msg, msgType, lang)
    if isDemo(player) and msgType == CHAT_YELL then return refuse(player, "Yells") end
end
local function onWhisper(event, player, msg, msgType, lang, receiver)
    if isDemo(player) or isDemo(receiver) then
        if isDemo(player) then return refuse(player, "Whispers") end
        return false
    end
end
local function onGroupChat(event, player) if isDemo(player) then return refuse(player, "Party chat") end end
local function onGuildChat(event, player) if isDemo(player) then return refuse(player, "Guild chat") end end
local function onChannelChat(event, player) if isDemo(player) then return refuse(player, "Chat channels") end end

local function onCanTrade(event, player, target)
    if isDemo(player) then return refuse(player, "Trades") end
    if isDemo(target) then
        say(player, "Guests in the Goldshire Inn can't trade.")
        return false
    end
    return true
end

local function onCanMail(event, player)
    if isDemo(player) then return refuse(player, "Mail") end
    return true
end

local function onCanInvite(event, player, memberName)
    if isDemo(player) then return refuse(player, "Groups") end
    local other = memberName and GetPlayerByName and GetPlayerByName(memberName)
    if other and isDemo(other) then
        say(player, "Guests in the Goldshire Inn can't join groups.")
        return false
    end
    return true
end

local function onlineByAccount(id)
    for _, p in ipairs(GetPlayersInWorld() or {}) do
        if p:GetAccountId() == id then return p end
    end
end

-- console: ovdemo begin <ACCOUNT> <seconds> | ovdemo end <ACCOUNT>
local function consoleCommand(command, handler)
    local verb, rest = command:match("^ovdemo%s+(%a+)%s*(.*)$")
    if not verb then return nil end
    local function reply(msg) if handler then handler:SendSysMessage(msg) end end
    local name, secs = rest:match("^(%w+)%s+(%d+)%s*$")
    if verb == "end" then name = rest:match("^(%w+)%s*$") end
    name = name and name:upper()
    if not name or #name > 16 or name:sub(1, #PREFIX) ~= PREFIX
        or (verb == "begin" and (not secs or tonumber(secs) < 60 or tonumber(secs) > 4 * 3600)) then
        reply("ovdemo: usage: ovdemo begin <" .. PREFIX .. "account> <seconds 60-14400> | ovdemo end <" .. PREFIX .. "account>")
        return false
    end
    local q = AuthDBQuery(string.format("SELECT id FROM account WHERE username = '%s'", name))
    if not q then
        reply("ovdemo: no such account " .. name)
        return false
    end
    local id = q:GetUInt32(0)
    if verb == "begin" then
        secs = tonumber(secs)
        AuthDBExecute(string.format("REPLACE INTO ov_demo_passes (account_id, expires_at) "
            .. "VALUES (%d, UNIX_TIMESTAMP() + %d)", id, secs))
        passes[name] = now() + secs
        reply(string.format("ovdemo ok: %s open for %d s", name, secs))
    elseif verb == "end" then
        AuthDBExecute(string.format("DELETE FROM ov_demo_passes WHERE account_id = %d", id))
        passes[name] = nil
        local p = onlineByAccount(id)
        if p then p:KickPlayer() end
        reply("ovdemo ok: " .. name .. " ended" .. (p and " (logged out)" or ""))
    else
        reply("ovdemo: unknown verb " .. verb)
    end
    return false
end

local function onCommand(event, player, command, handler)
    if not player then return consoleCommand(command or "", handler) end
end

AuthDBExecute("CREATE TABLE IF NOT EXISTS ov_demo_passes (account_id INT UNSIGNED NOT NULL PRIMARY KEY, "
    .. "expires_at INT UNSIGNED NOT NULL, KEY expires_at (expires_at))")
loadPasses()

-- After .reload ale every timed event is gone: watch the guests already online again.
local function rearm()
    for _, p in ipairs(GetPlayersInWorld() or {}) do
        watching[p:GetGUIDLow()], pending[p:GetGUIDLow()] = nil, nil
        if isDemo(p) then watch(p) end
    end
end
if CreateLuaEvent then CreateLuaEvent(rearm, 2000, 1) else rearm() end

RegisterPlayerEvent(3, onLogin)        -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, onLogout)       -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(18, onChat)        -- PLAYER_EVENT_ON_CHAT
RegisterPlayerEvent(19, onWhisper)     -- PLAYER_EVENT_ON_WHISPER
RegisterPlayerEvent(20, onGroupChat)   -- PLAYER_EVENT_ON_GROUP_CHAT
RegisterPlayerEvent(21, onGuildChat)   -- PLAYER_EVENT_ON_GUILD_CHAT
RegisterPlayerEvent(22, onChannelChat) -- PLAYER_EVENT_ON_CHANNEL_CHAT
RegisterPlayerEvent(28, onMap)         -- PLAYER_EVENT_ON_MAP_CHANGE
RegisterPlayerEvent(42, onCommand)     -- PLAYER_EVENT_ON_COMMAND
RegisterPlayerEvent(48, onCanTrade)    -- PLAYER_EVENT_ON_CAN_INIT_TRADE
RegisterPlayerEvent(49, onCanMail)     -- PLAYER_EVENT_ON_CAN_SEND_MAIL
RegisterPlayerEvent(51, onCanInvite)   -- PLAYER_EVENT_ON_CAN_GROUP_INVITE

-- for tests (stream/tests/test_ov_demo.lua loads this file under a fake ALE)
OV_DEMO_TEST = { passes = passes, inInn = inInn, isDemo = isDemo, INN = INN, SIGNUP_URL = SIGNUP_URL }
