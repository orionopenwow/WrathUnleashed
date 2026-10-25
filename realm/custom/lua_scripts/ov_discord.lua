-- ov_discord.lua: the game side of the Leyline Discord bridge (mod-ale). The bridge daemon itself is
-- hosting/discord/wudiscord/bridge.py; it talks to this script over SOAP only (no shared files, no DB login).
--
--   World chat -> Discord   lines said in the realm's World channel (OV_DISCORD_CHANNEL, default "World") are kept
--                           in a small in-memory queue; the daemon fetches them with the console command
--                           "wudiscord pull <after-seq> <after-bug-id> <boot>" every few seconds and posts them.
--   Discord -> game         the daemon runs "wudiscord say <hex name> <hex text>"; every online player who has not
--                           turned it off sees "[Discord] Name: text".
--   Bug feed                "wudiscord pull" also returns the .bug reports (acore_characters.ov_bug_reports, written
--                           by ov_reports.lua) newer than the id the daemon has, for its bug channel.
--   .discord off | on       a player hides (or shows again) the Discord lines; kept in ov_discord_optout.
--
-- Nothing is queued unless the daemon has pulled in the last ACTIVE_SECS: with no daemon running this script only
-- costs one table lookup per channel line. OV_DISCORD=0 in the worldserver's environment turns it off entirely.
-- The console commands answer only from the console / SOAP (player is nil), never from a player.
-- Names and texts cross SOAP hex-encoded, so no quoting, spaces or markup can change the command.
--
-- mod-ale events: 22 ON_CHANNEL_CHAT (event, player, msg, type, lang, channel): channel is the DBC id for the built-in
-- channels and minus the characters-DB channelId for custom ones (0 when PreserveCustomChannels is off; then set
-- OV_DISCORD_ANY_CUSTOM=1 to accept any custom channel). 42 ON_COMMAND (event, player, command, handler).

local ON = (os.getenv("OV_DISCORD") or "1") ~= "0"
local CHANNEL = os.getenv("OV_DISCORD_CHANNEL") or "World"
local ANY_CUSTOM = os.getenv("OV_DISCORD_ANY_CUSTOM") == "1"
local ACTIVE_SECS = 60      -- the daemon counts as running this long after its last pull
local QUEUE_MAX = 200       -- lines kept for the daemon; older ones are dropped
local PULL_MAX = 25         -- lines per pull (the SOAP answer stays small)
local BUGS_PER_PULL = 5
local MAX_NAME, MAX_TEXT = 32, 255
local PER_PLAYER_WINDOW, PER_PLAYER_MAX = 30, 6   -- at most 6 bridged lines per character per 30 s
local SAY_PER_MINUTE = 30   -- Discord lines shown in game per minute, all users together
local DISCORD_TAG = "|cff7289da[Discord]|r "

local BOOT = os.time()      -- the daemon notices a restart (or .reload ale) by this changing: sequence restarts
local seq, queue = 0, {}
local lastPull = nil
local recent = {}           -- char guid -> { times }
local sayTimes = {}
local optout = {}           -- char guid -> true
local botAccounts = {}      -- account id -> true/false (mod-playerbots random bots never bridge)
local channelIds, channelsAt = {}, nil

local function now() return os.time() end

local function hex(s)
    return (tostring(s or ""):gsub(".", function(c) return string.format("%02x", c:byte()) end))
end

local function unhex(h)
    if type(h) ~= "string" or #h % 2 ~= 0 or h:find("[^%x]") then return nil end
    return (h:gsub("%x%x", function(x) return string.char(tonumber(x, 16)) end))
end

-- Text shown in game: control characters out, "|" doubled (no colour codes, links or textures), trimmed, capped.
local function gameSafe(s, cap)
    s = tostring(s or ""):gsub("[%z\1-\31\127]", " "):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
    if #s > cap then
        s = s:sub(1, cap)
        -- do not leave half a UTF-8 character at the end
        while #s > 0 and s:byte(#s) >= 0x80 and s:byte(#s) < 0xC0 do s = s:sub(1, #s - 1) end
        if #s > 0 and s:byte(#s) >= 0xC0 then s = s:sub(1, #s - 1) end
    end
    return (s:gsub("|", "||"))
end

local function sqlName(s) return (tostring(s):gsub("[^%w _%-]", "")) end

local function loadChannelIds()
    channelIds, channelsAt = {}, now()
    local q = CharDBQuery(string.format("SELECT channelId FROM channels WHERE name = '%s'", sqlName(CHANNEL)))
    if q then
        repeat channelIds[q:GetUInt32(0)] = true until not q:NextRow()
    end
end

local function isBridgedChannel(channel)
    channel = tonumber(channel) or 0
    if channel > 0 then return false end      -- built-in channels (General, Trade, LookingForGroup ...)
    if channel == 0 then return ANY_CUSTOM end
    local id = -channel
    if not channelIds[id] and (not channelsAt or now() - channelsAt >= 30) then loadChannelIds() end
    return channelIds[id] == true
end

local function isBot(player)
    local acc = player:GetAccountId()
    if botAccounts[acc] == nil then
        local q = AuthDBQuery(string.format("SELECT username FROM account WHERE id = %d", acc))
        botAccounts[acc] = q ~= nil and q:GetString(0):upper():find("^RNDBOT") ~= nil
    end
    return botAccounts[acc]
end

local function allowPlayer(guid)
    local t, kept = now(), {}
    for _, x in ipairs(recent[guid] or {}) do
        if t - x < PER_PLAYER_WINDOW then kept[#kept + 1] = x end
    end
    recent[guid] = kept
    if #kept >= PER_PLAYER_MAX then return false end
    kept[#kept + 1] = t
    return true
end

local function active() return lastPull ~= nil and now() - lastPull <= ACTIVE_SECS end

local function onChannelChat(event, player, msg, msgType, lang, channel)
    if not ON or not player or not active() then return end
    if not isBridgedChannel(channel) then return end
    if isBot(player) then return end
    local text = tostring(msg or "")
    if text:find("^%s*$") then return end
    if not allowPlayer(player:GetGUIDLow()) then return end
    seq = seq + 1
    queue[#queue + 1] = { seq = seq, name = player:GetName():sub(1, MAX_NAME), text = text:sub(1, MAX_TEXT) }
    while #queue > QUEUE_MAX do table.remove(queue, 1) end
    -- nothing returned: the line goes to the channel unchanged
end

-- console -------------------------------------------------------------------------------------------------------
local function pull(rest, reply)
    local after, bugAfter, boot = rest:match("^(%d+)%s+(%-?%d+)%s*(%d*)%s*$")
    if not after then reply("wudiscord: usage: wudiscord pull <after-seq> <after-bug-id|-1> [boot]"); return end
    after, bugAfter = tonumber(after), tonumber(bugAfter)
    lastPull = now()
    -- a daemon whose sequence belongs to an earlier boot (restart or .reload ale) gets everything queued
    if (boot ~= "" and tonumber(boot) ~= BOOT) or after > seq then after = 0 end
    local lines, n = {}, 0
    for _, e in ipairs(queue) do
        if e.seq > after and n < PULL_MAX then
            lines[#lines + 1] = string.format("C %d %s %s", e.seq, hex(e.name), hex(e.text)); n = n + 1
        end
    end
    if bugAfter >= 0 then
        local q = CharDBQuery(string.format("SELECT id, char_name, level, map_id, zone_id, text FROM ov_bug_reports "
            .. "WHERE id > %d ORDER BY id LIMIT %d", bugAfter, BUGS_PER_PULL))
        if q then
            repeat
                lines[#lines + 1] = string.format("B %d %s %d %d %d %s", q:GetUInt32(0), hex(q:GetString(1)),
                    q:GetUInt32(2), q:GetUInt32(3), q:GetUInt32(4), hex(q:GetString(5)))
            until not q:NextRow()
        end
    end
    reply(string.format("wudiscord ok %d %d %d", BOOT, seq, #lines))
    for _, l in ipairs(lines) do reply(l) end
end

local function bugMax(reply)
    local q = CharDBQuery("SELECT COALESCE(MAX(id), 0) FROM ov_bug_reports")
    reply("wudiscord bugmax " .. (q and q:GetUInt32(0) or 0))
end

local function allowSay()
    local t, kept = now(), {}
    for _, x in ipairs(sayTimes) do if t - x < 60 then kept[#kept + 1] = x end end
    sayTimes = kept
    if #kept >= SAY_PER_MINUTE then return false end
    kept[#kept + 1] = t
    return true
end

local function say(rest, reply)
    local hn, ht = rest:match("^(%x+)%s+(%x+)%s*$")
    local name, text = unhex(hn), unhex(ht)
    if not name or not text then reply("wudiscord: usage: wudiscord say <hex name> <hex text>"); return end
    name, text = gameSafe(name, MAX_NAME), gameSafe(text, 200)
    if name == "" or text == "" then reply("wudiscord: empty"); return end
    if not allowSay() then reply("wudiscord busy: too many lines this minute"); return end
    local line, shown = DISCORD_TAG .. name .. ": " .. text, 0
    for _, p in ipairs(GetPlayersInWorld() or {}) do
        if not optout[p:GetGUIDLow()] and not isBot(p) then p:SendBroadcastMessage(line); shown = shown + 1 end
    end
    reply("wudiscord ok said " .. shown)
end

local function console(command, handler)
    local verb, rest = command:match("^wudiscord%s+(%a+)%s*(.*)$")
    if not verb then return nil end
    local function reply(m) if handler then handler:SendSysMessage(m) end end
    if not ON then reply("wudiscord off (OV_DISCORD=0)"); return false end
    if verb == "pull" then pull(rest, reply)
    elseif verb == "bugmax" then bugMax(reply)
    elseif verb == "say" then say(rest, reply)
    elseif verb == "status" then
        reply(string.format("wudiscord status channel=%s active=%s queued=%d seq=%d", CHANNEL, tostring(active()), #queue, seq))
    else reply("wudiscord: unknown verb " .. verb) end
    return false
end

-- player: .discord off | on ----------------------------------------------------------------------------------------
local function tell(p, m) p:SendBroadcastMessage(DISCORD_TAG .. m) end

local function playerCommand(player, rest)
    local guid, arg = player:GetGUIDLow(), (rest or ""):lower():match("^(%a*)")
    if arg == "off" then
        optout[guid] = true
        CharDBExecute(string.format("REPLACE INTO ov_discord_optout (guid) VALUES (%d)", guid))
        tell(player, "Discord lines hidden. |cffffff00.discord on|r shows them again.")
    elseif arg == "on" then
        optout[guid] = nil
        CharDBExecute(string.format("DELETE FROM ov_discord_optout WHERE guid = %d", guid))
        tell(player, "Discord lines shown.")
    else
        tell(player, "The " .. CHANNEL .. " channel is shared with the Leyline Discord (/join " .. CHANNEL .. "). "
            .. (optout[guid] and "You have it hidden: |cffffff00.discord on|r." or "|cffffff00.discord off|r hides the Discord lines."))
    end
end

local function onCommand(event, player, command, handler)
    command = command or ""
    if not player then return console(command, handler) end
    local verb, rest = command:gsub("^[%.!]", ""):match("^(%S+)%s*(.*)$")
    if verb and verb:lower() == "discord" then
        if ON then playerCommand(player, rest) end
        return false
    end
end

-- Every hidden-choice at load (a small table): survives .reload ale for players already online.
local function loadOptout()
    optout = {}
    local q = CharDBQuery("SELECT guid FROM ov_discord_optout")
    if q then
        repeat optout[q:GetUInt32(0)] = true until not q:NextRow()
    end
end

CharDBExecute("CREATE TABLE IF NOT EXISTS ov_discord_optout (guid INT UNSIGNED NOT NULL PRIMARY KEY, "
    .. "at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)")
if ON then loadChannelIds(); loadOptout() end

RegisterPlayerEvent(22, onChannelChat) -- PLAYER_EVENT_ON_CHANNEL_CHAT
RegisterPlayerEvent(42, onCommand)     -- PLAYER_EVENT_ON_COMMAND

-- for tests
OV_DISCORD_TEST = { hex = hex, unhex = unhex, gameSafe = gameSafe, onChannelChat = onChannelChat,
    onCommand = onCommand, queue = function() return queue end, BOOT = BOOT }
