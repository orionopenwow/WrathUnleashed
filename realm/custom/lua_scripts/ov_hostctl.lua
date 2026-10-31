-- ov_hostctl.lua: "Your realm" in the in-game Host window (WrathUnleashedUI/Host.lua), the realm half (mod-ale).
--
-- The realm's GM runs their realm from the game: status, announce, message of the day, kick, ban / unban, an allow
-- list (only listed characters may log in), and a restart with a five-minute warning. Everything the realm can't do
-- from here (bots, rates, sign-up, the Leyline list, the invite link with its secret) the window hands to the
-- launcher's Host page (leyline://host) or the website, never to this script.
--
-- Who may: a player whose account's GM level on this realm is at least OV_HOSTCTL_GM (default 3: the host kit gives
-- the host's own account level 3, hosting/kit/tools/wuhost/agent.py grant_gm). Everyone else gets only
-- "status" with gm=0 (so the window says "only this realm's GM") and every other action is refused and logged.
-- OV_HOSTCTL=0 turns the whole script off.
--
-- Transport: the Open Mod API (ov_modapi.lua, prefix OVMOD, whispered to yourself, never relayed). mod "wuhost":
--   client -> server   status                       (data empty)
--                      announce   <text>            to everyone online, as "[Realm] <text>"
--                      motd       <text>            the message of the day (.server set motd)
--                      kick       <name>
--                      ban        <name>\t<hours>   1-720 hours (.ban character)
--                      unban      <name>
--                      allow      on|off | add\t<name> | del\t<name>
--                      restart    (data empty)      a restart in RESTART_DELAY seconds (never sooner), with warnings
--                      cancel     (data empty)      cancels a pending restart
--   server -> client   status     key=value lines (\n): gm, up, players, bots, restart, allow, allowed, vis,
--                                 listed, signup, botsCfg, herokey, rates, invite, motd
--                      ok         <text>            done
--                      err        <text>            refused (and why)
-- Rate limits: one action per ACTION_COOLDOWN seconds per player, an announce per ANNOUNCE_COOLDOWN seconds, a
-- restart per RESTART_COOLDOWN seconds. Text from the client is cleaned (no colour codes, no pipes, no control
-- characters, brand names out) and capped; names are letters only, at most 12.
--
-- The host kit's facts for status (hosting/kit/tools/wuhost/setup.py writes them next to the scripts, data only):
--   host       <kit>/realm-files/lua_scripts/host-realm.dat
--   container  /azerothcore/lua_scripts/host-realm.dat     (OV_HOST_FILE overrides)
--   return { realm_id = "...", visibility = "public", signup = "open", bots = 40, herokey = false, rates = "3/1/2",
--            join = "https://.../join/<id>" }        (join only for a public realm: a private invite holds a secret)
-- No file (the operator's own realm): those lines say "-" and the window points at the launcher.
--
-- The launcher's host console (launcher/src-tauri/src/host/console.rs) runs the same actions from the host's own PC,
-- out of game: it adds a row to ov_host_queue in the characters database (docker exec into the realm's own database
-- container; the kit has no SOAP), and this script runs it as the console within QUEUE_EVERY ms and writes the answer
-- back ("ok:<text>", "err:<text>" or "status:<lines>"). The same checks, limits and five-minute restart as the window;
-- a row older than QUEUE_MAX_AGE seconds is answered "err" and never run late. Only on a host kit's realm (the facts
-- file above is there when the script loads); the operator's own realm never polls.
--
-- mod-ale used: RegisterPlayerEvent 3 ON_LOGIN, 4 ON_LOGOUT; CreateLuaEvent (the console queue); Player:GetGMRank / GetName / GetGUIDLow / KickPlayer /
-- SendBroadcastMessage / RegisterEvent; GetPlayerByName, GetPlayersInWorld, SendWorldMessage, RunCommand,
-- CharDBQuery / CharDBExecute, AuthDBQuery, GetRealmID.

if (os.getenv("OV_HOSTCTL") or "1") == "0" then return end
local OVMod = require("ov_modapi")

local MOD = "wuhost"
local GM_LEVEL = tonumber(os.getenv("OV_HOSTCTL_GM") or "") or 3
local FILE = os.getenv("OV_HOST_FILE") or "/azerothcore/lua_scripts/host-realm.dat"
local RESTART_DELAY = 300
local QUEUE_EVERY, QUEUE_MAX_AGE = 3000, 120
local ACTION_COOLDOWN, ANNOUNCE_COOLDOWN, RESTART_COOLDOWN = 2, 10, 600
local MAX_TEXT, MAX_ALLOW = 200, 500
local TAG = "|cff5b8def[Realm]|r "
local LOADED_AT = os.time()

local H = {}
OVHostCtl = H

local function try(obj, method, ...)
    if not obj then return nil end
    local okf, fn = pcall(function() return obj[method] end)
    if not okf or type(fn) ~= "function" then return nil end
    local ok, a = pcall(fn, obj, ...)
    if ok then return a end
end

local function gmLevel(player) return tonumber(try(player, "GetGMRank")) or 0 end
function H.IsGM(player) return player ~= nil and gmLevel(player) >= GM_LEVEL end

local function log(text) print("[ov_hostctl] " .. text) end

-- ---------------------------------------------------------------- cleaning

local function anyCase(word)
    return (word:gsub("%a", function(c) return "[" .. c:lower() .. c:upper() .. "]" end))
end
local BRANDS = {}
for _, w in ipairs({ "world of warcraft", "warcraft", "lich king", "blizzard", "wow" }) do
    BRANDS[#BRANDS + 1] = "%f[%w]" .. anyCase(w):gsub(" ", "%%s+") .. "%f[%W]"
end

function H.CleanText(s)
    if type(s) ~= "string" then return nil end
    s = s:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("[%z\1-\31\127|]", " ")
    for _, p in ipairs(BRANDS) do s = s:gsub(p, "") end
    s = s:gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
    if #s > MAX_TEXT then s = s:sub(1, MAX_TEXT):gsub("[\128-\191]*$", ""):gsub("[\192-\255]$", "") end
    return s ~= "" and s or nil
end

function H.CleanName(s)
    if type(s) ~= "string" or not s:match("^%a+$") or #s < 2 or #s > 12 then return nil end
    return s:sub(1, 1):upper() .. s:sub(2):lower()
end

-- ---------------------------------------------------------------- the host kit's facts (data only)

local DATA_WORDS = { ["return"] = true, ["true"] = true, ["false"] = true, realm_id = true, visibility = true,
    signup = true, bots = true, herokey = true, rates = true, join = true, listed = true }
local cache = { at = -1e9 }
function H.ReadHost()
    local now = os.time()
    if now - cache.at < 30 then return cache.doc end
    cache.at, cache.doc = now, nil
    local f = io.open(FILE, "rb")
    if not f then return nil end
    local text = f:read(4097)
    f:close()
    if not text or #text > 4096 then return nil end
    -- the writer escapes quotes and backslashes as \ddd: anything else after a backslash, or any word outside the
    -- strings that is not one of DATA_WORDS, and the file is refused (it can never run code)
    if text:gsub("\\%d%d%d", ""):find("\\", 1, true) then return nil end
    for word in text:gsub('"[^"\n]*"', '""'):gmatch("[%a_][%w_]*") do
        if not DATA_WORDS[word] then return nil end
    end
    local chunk
    if setfenv then
        chunk = loadstring(text, "=host-realm")
        if chunk then setfenv(chunk, {}) end
    else
        chunk = load(text, "=host-realm", "t", {})
    end
    if not chunk then return nil end
    local ok, d = pcall(chunk)
    if not ok or type(d) ~= "table" then return nil end
    local function one(v, set) return set[v] and v or nil end
    local doc = {
        realm_id = type(d.realm_id) == "string" and d.realm_id:match("^[a-z2-7]+$") and #d.realm_id == 16 and d.realm_id or nil,
        visibility = one(d.visibility, { public = true, private = true }),
        signup = one(d.signup, { open = true, invite = true, off = true }),
        bots = tonumber(d.bots) and math.max(0, math.min(1000, math.floor(tonumber(d.bots)))) or nil,
        herokey = d.herokey == true,
        rates = type(d.rates) == "string" and d.rates:match("^[%d%-]+/[%d%-]+/[%d%-]+$") and d.rates or nil,
        listed = d.listed,
    }
    -- the public join page only: https, no fragment (a private realm's invite carries its secret after #)
    if type(d.join) == "string" and d.join:match("^https://[%w%.%-]+/join/[a-z2-7]+$") and #d.join < 160 then
        doc.join = d.join
    end
    cache.doc = doc
    return doc
end
function H.ForgetHost() cache.at = -1e9 end

-- ---------------------------------------------------------------- state

local last, lastAnnounce = {}, {}   -- guid -> os.time()
local restart = { at = nil, by = nil, last = -1e9 }
local allow = { on = false, names = {}, n = 0, loaded = false }

local function charQuery(sql)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, sql)
    if ok then return q end
end
local function charExec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end

local function loadAllow()
    if allow.loaded then return end
    allow.loaded = true
    charExec("CREATE TABLE IF NOT EXISTS ov_host_allow (name VARCHAR(12) NOT NULL PRIMARY KEY) ENGINE=InnoDB")
    charExec("CREATE TABLE IF NOT EXISTS ov_host_settings (k VARCHAR(32) NOT NULL PRIMARY KEY, v VARCHAR(64) NOT NULL) ENGINE=InnoDB")
    local q = charQuery("SELECT name FROM ov_host_allow")
    if q then
        repeat
            local n = H.CleanName(q:GetString(0))
            if n and not allow.names[n] then allow.names[n] = true; allow.n = allow.n + 1 end
        until not q:NextRow()
    end
    local s = charQuery("SELECT v FROM ov_host_settings WHERE k = 'allow'")
    allow.on = s ~= nil and s:GetString(0) == "on"
end

local function setAllowOn(on)
    allow.on = on
    charExec("REPLACE INTO ov_host_settings (k, v) VALUES ('allow', '" .. (on and "on" or "off") .. "')")
end

local function isBot(p)
    for _, m in ipairs({ "IsBot", "IsPlayerbot" }) do
        if try(p, m) == true then return true end
    end
    return false
end

local function counts()
    local people, bots = 0, 0
    local ok, list = pcall(GetPlayersInWorld)
    if ok and type(list) == "table" then
        for _, p in ipairs(list) do if isBot(p) then bots = bots + 1 else people = people + 1 end end
    end
    return people, bots
end

-- The world server's start: the auth database's uptime row for this realm, else when this script was loaded.
local function startedAt()
    if AuthDBQuery then
        local rid = tonumber((GetRealmID and select(2, pcall(GetRealmID))) or 1) or 1
        local ok, q = pcall(AuthDBQuery, "SELECT starttime FROM uptime WHERE realmid = " .. math.floor(rid)
            .. " ORDER BY starttime DESC LIMIT 1")
        if ok and q then
            local t = tonumber(q:GetString(0))
            if t and t > 0 then return t end
        end
    end
    return LOADED_AT
end

local motd = nil

-- The launcher's host console stands in for a player: the realm's owner, above every GM level; its answer is kept here.
local CONSOLE = { console = true }
function CONSOLE:GetGUIDLow() return 0 end
function CONSOLE:GetName() return "the host console" end
function CONSOLE:GetGMRank() return 255 end

-- ---------------------------------------------------------------- replies

local function reply(player, kind, data)
    if player == CONSOLE then CONSOLE.answer = { kind, data or "" }; return end
    OVMod.Send(player, MOD, kind, data or "")
end
local function ok(player, text) reply(player, "ok", text) end
local function err(player, text) reply(player, "err", text) end

function H.Status(player)
    if not H.IsGM(player) then return reply(player, "status", "gm=0") end
    loadAllow()
    local people, bots = counts()
    local host = H.ReadHost() or {}
    local lines = {
        "gm=1",
        "up=" .. math.max(0, os.time() - startedAt()),
        "players=" .. people,
        "bots=" .. bots,
        "restart=" .. (restart.at and math.max(0, restart.at - os.time()) or 0),
        "allow=" .. (allow.on and "on" or "off"),
        "allowed=" .. allow.n,
        "vis=" .. (host.visibility or "-"),
        "listed=" .. (host.visibility == "public" and "1" or host.visibility == "private" and "0" or "-"),
        "signup=" .. (host.signup or "-"),
        "botsCfg=" .. (host.bots and tostring(host.bots) or "-"),
        "herokey=" .. (host.realm_id and (host.herokey and "on" or "off") or "-"),
        "rates=" .. (host.rates or "-"),
        "invite=" .. (host.join or "-"),
        "motd=" .. (motd or "-"),
    }
    reply(player, "status", table.concat(lines, "\n"))
end

-- ---------------------------------------------------------------- actions (GM only)

local ACTIONS = {}

function ACTIONS.announce(player, data)
    local t = H.CleanText(data)
    if not t then return err(player, "Write something to announce.") end
    local g, now = player:GetGUIDLow(), os.time()
    if lastAnnounce[g] and now - lastAnnounce[g] < ANNOUNCE_COOLDOWN then
        return err(player, "One announcement every " .. ANNOUNCE_COOLDOWN .. " seconds.")
    end
    lastAnnounce[g] = now
    if SendWorldMessage then pcall(SendWorldMessage, TAG .. t) end
    ok(player, "Announced to everyone online.")
end

function ACTIONS.motd(player, data)
    local t = H.CleanText(data)
    if not t then return err(player, "Write the message of the day.") end
    if t:match("^%d") then t = "- " .. t end   -- a leading number would be read as a realm id
    if not RunCommand then return err(player, "This realm can't set the message from here.") end
    pcall(RunCommand, "server set motd " .. t)
    motd = t
    ok(player, "Message of the day set.")
end

local function target(player, data)
    local name = H.CleanName(data)
    if not name then return nil, "A character name: letters only." end
    if name:lower() == tostring(try(player, "GetName") or ""):lower() then return nil, "Not yourself." end
    return name
end

function ACTIONS.kick(player, data)
    local name, why = target(player, data)
    if not name then return err(player, why) end
    local p = GetPlayerByName and GetPlayerByName(name)
    if not p then return err(player, name .. " isn't online.") end
    if gmLevel(p) >= gmLevel(player) then return err(player, "Not a GM of your level or higher.") end
    try(p, "SendBroadcastMessage", TAG .. "You were removed from this realm by its GM.")
    try(p, "KickPlayer")
    ok(player, name .. " was kicked.")
end

function ACTIONS.ban(player, data)
    local who, hours = (data or ""):match("^(%a+)\t(%d+)$")
    local name, why = target(player, who)
    if not name then return err(player, why) end
    hours = tonumber(hours)
    if not hours or hours < 1 or hours > 720 then return err(player, "Ban for 1 to 720 hours.") end
    local p = GetPlayerByName and GetPlayerByName(name)
    if p and gmLevel(p) >= gmLevel(player) then return err(player, "Not a GM of your level or higher.") end
    if not RunCommand then return err(player, "This realm can't ban from here.") end
    pcall(RunCommand, string.format("ban character %s %dh Banned by the realm's GM", name, hours))
    ok(player, name .. " is banned for " .. hours .. " hours.")
end

function ACTIONS.unban(player, data)
    local name, why = target(player, data)
    if not name then return err(player, why) end
    if not RunCommand then return err(player, "This realm can't unban from here.") end
    pcall(RunCommand, "unban character " .. name)
    ok(player, name .. " is no longer banned.")
end

function ACTIONS.allow(player, data)
    loadAllow()
    data = data or ""
    if data == "on" or data == "off" then
        setAllowOn(data == "on")
        return ok(player, data == "on" and "Only characters on your list (and GMs) can log in now."
            or "Everyone can log in again.")
    end
    local verb, who = data:match("^(%a+)\t(%a+)$")
    local name = H.CleanName(who)
    if not name or (verb ~= "add" and verb ~= "del") then return err(player, "A character name: letters only.") end
    if verb == "add" then
        if allow.names[name] then return ok(player, name .. " is already on the list.") end
        if allow.n >= MAX_ALLOW then return err(player, "The list is full (" .. MAX_ALLOW .. ").") end
        allow.names[name], allow.n = true, allow.n + 1
        charExec("REPLACE INTO ov_host_allow (name) VALUES ('" .. name .. "')")
        return ok(player, name .. " is on the list.")
    end
    if allow.names[name] then allow.names[name], allow.n = nil, allow.n - 1 end
    charExec("DELETE FROM ov_host_allow WHERE name = '" .. name .. "'")
    ok(player, name .. " is off the list.")
end

-- A restart always gives everyone RESTART_DELAY seconds: the core counts down in chat itself, and we say why.
function ACTIONS.restart(player)
    local now = os.time()
    if restart.at and restart.at > now then
        return err(player, "A restart is already coming in " .. (restart.at - now) .. " seconds.")
    end
    if now - restart.last < RESTART_COOLDOWN then
        return err(player, "One restart every " .. math.floor(RESTART_COOLDOWN / 60) .. " minutes.")
    end
    if not RunCommand then return err(player, "Restart from the launcher's Host page.") end
    restart.at, restart.by, restart.last = now + RESTART_DELAY, try(player, "GetName"), now
    pcall(RunCommand, "server restart " .. RESTART_DELAY)
    if SendWorldMessage then
        pcall(SendWorldMessage, TAG .. "The realm restarts in 5 minutes. Finish what you're doing; it is back a "
            .. "minute or two later.")
    end
    log("restart in " .. RESTART_DELAY .. " s by " .. tostring(restart.by))
    ok(player, "Restart in 5 minutes. Everyone online was told.")
end

function ACTIONS.cancel(player)
    if not (restart.at and restart.at > os.time()) then return err(player, "No restart is coming.") end
    restart.at = nil
    if RunCommand then pcall(RunCommand, "server restart cancel") end
    if SendWorldMessage then pcall(SendWorldMessage, TAG .. "The restart is cancelled.") end
    ok(player, "Restart cancelled.")
end

-- One entry for every action: GM check first, then the rate limit, then the action.
function H.Handle(player, action, data)
    if not player then return false end
    if action == "status" then return H.Status(player) end
    local fn = ACTIONS[action]
    if not fn then return false end
    if not H.IsGM(player) then
        log(string.format("refused %s from %s (GM level %d)", action, tostring(try(player, "GetName")), gmLevel(player)))
        err(player, "Only this realm's GM can do that.")
        return false
    end
    local g, now = player:GetGUIDLow(), os.time()
    if last[g] and now - last[g] < ACTION_COOLDOWN then
        err(player, "One moment: one action every " .. ACTION_COOLDOWN .. " seconds.")
        return false
    end
    last[g] = now
    fn(player, data)
    return true
end

for _, a in ipairs({ "status", "announce", "motd", "kick", "ban", "unban", "allow", "restart", "cancel" }) do
    OVMod.On(MOD, a, function(player, data) H.Handle(player, a, data) end)
end

-- The allow list at login: a character not on it (and not a GM) is told and sent off a moment later.
local function onLogin(event, player)
    if not player then return end
    loadAllow()
    if not allow.on or gmLevel(player) > 0 or isBot(player) then return end
    local name = H.CleanName(try(player, "GetName"))
    if name and allow.names[name] then return end
    try(player, "SendBroadcastMessage", TAG .. "This realm is invite-only right now: ask its GM to add you.")
    local okReg = pcall(function()
        player:RegisterEvent(function(_, _, _, p) if p then try(p, "KickPlayer") end end, 3000, 1)
    end)
    if not okReg then try(player, "KickPlayer") end
end

local function onLogout(event, player)
    if not player then return end
    local g = player:GetGUIDLow()
    last[g], lastAnnounce[g] = nil, nil
end

RegisterPlayerEvent(3, onLogin)    -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, onLogout)   -- PLAYER_EVENT_ON_LOGOUT

-- ---------------------------------------------------------------- the launcher's host console (ov_host_queue)

local QUEUE_TABLE = "CREATE TABLE IF NOT EXISTS ov_host_queue (id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
    .. "action VARCHAR(16) NOT NULL, data VARBINARY(255) NOT NULL, at INT UNSIGNED NOT NULL, done TINYINT NOT NULL "
    .. "DEFAULT 0, result VARBINARY(1024) NULL) ENGINE=InnoDB"
local queueSeen, lastClean = {}, 0

local function unhex(h)
    if type(h) ~= "string" or #h % 2 ~= 0 or h:find("[^%x]") then return nil end
    return (h:gsub("%x%x", function(x) return string.char(tonumber(x, 16)) end))
end
local function hex(s) return (s:gsub(".", function(c) return string.format("%02X", c:byte()) end)) end

-- One look at the queue: runs what waits (at most 5), answers each row once.
function H.RunQueue()
    local q = charQuery("SELECT id, action, HEX(data), at FROM ov_host_queue WHERE done = 0 ORDER BY id LIMIT 5")
    local n = 0
    if q then
        repeat
            local id = tonumber(q:GetString(0))
            if id and not queueSeen[id] then
                queueSeen[id] = true
                local action, data, at = q:GetString(1), unhex(q:GetString(2) or ""), tonumber(q:GetString(3)) or 0
                CONSOLE.answer = nil
                if os.time() - at > QUEUE_MAX_AGE then
                    CONSOLE.answer = { "err", "That waited too long, so it was not done." }
                elseif not data or not (action == "status" or ACTIONS[action]) then
                    CONSOLE.answer = { "err", "The realm doesn't know that control." }
                else
                    H.Handle(CONSOLE, action, data)
                    log("console: " .. action)
                end
                local a = CONSOLE.answer or { "err", "No answer." }
                local text = (a[1] .. ":" .. a[2]):sub(1, 1000)
                charExec(string.format("UPDATE ov_host_queue SET done = 1, result = UNHEX('%s') WHERE id = %d", hex(text), id))
                n = n + 1
            end
        until not q:NextRow()
    end
    local now = os.time()
    if n == 0 and now - lastClean > 3600 then
        lastClean = now
        charExec("DELETE FROM ov_host_queue WHERE at < " .. math.floor(now - 86400))
    end
    return n
end

do
    local hostFile = io.open(FILE, "rb")
    if hostFile then
        hostFile:close()
        charExec(QUEUE_TABLE)
        if CreateLuaEvent then CreateLuaEvent(function() H.RunQueue() end, QUEUE_EVERY, 0) end
    end
end

-- for tests
H._restart, H._allow, H.RESTART_DELAY, H.GM_LEVEL = restart, allow, RESTART_DELAY, GM_LEVEL
H.CONSOLE, H.QUEUE_MAX_AGE = CONSOLE, QUEUE_MAX_AGE
H.OnLogin = onLogin
return H
