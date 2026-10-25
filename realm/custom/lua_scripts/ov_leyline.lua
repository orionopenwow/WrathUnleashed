-- ov_leyline.lua: the Leyline realm list for the in-game Leyline window (mod-ale).
--
-- The client can't make HTTP calls, so this realm hands it the list. A host-side cron
-- (realm/custom/leyline-fetch.py) reads the relay's listing (https://relay.openvanilla.app/api/listing/realms.json)
-- every few minutes and writes a small Lua data file next to the scripts:
--   host       /srv/wrath/custom/lua_scripts/leyline-realms.dat
--   container  /azerothcore/lua_scripts/leyline-realms.dat   (OV_LEYLINE_FILE overrides)
-- The .dat extension keeps ALE from loading it as a script. It is read as data only: loadstring in an empty
-- environment, every field checked, at most once a minute (CACHE_SECONDS).
--
-- Addon messages, prefix WULY, whispered to yourself (as ov_armory's OVARM):
--   client -> server   L                                             send me the list
--   server -> client   B:<count>:<age seconds>                       a list begins
--                      R:<id>:<live 0|1>:<players|->:<bots|->:<ruleset>:<name>   one realm per message
--                                                                    (id "this" = this realm, always first)
--                      E:<count>                                     the list is complete
--                      U:Realm list unavailable                      the file is missing or unreadable
--   client -> server   H:<id|wrath>                                  hop there (the window's Join / Back to Wrath)
--   server -> client   H:<id|wrath>                                  the same, echoed: the browser page sees this
--                                                                    CHAT_MSG_ADDON and reloads the game on that
--                                                                    realm (stream/www-files/wrath-page.js)
-- One request per player every REQUEST_COOLDOWN seconds. The hook returns false: WULY is never relayed.
-- mod-ale events used: server 30 ADDON_EVENT_ON_MESSAGE, player 4 ON_LOGOUT.

local PREFIX = "WULY"
local WHISPER = 7
local FILE = os.getenv("OV_LEYLINE_FILE") or "/azerothcore/lua_scripts/leyline-realms.dat"
local REALM_NAME = os.getenv("OV_REALM_NAME") or "WrathUnleashed"
local CACHE_SECONDS = 60
local REQUEST_COOLDOWN = 5
local MAX_REALMS = 60
local MAX_FILE_BYTES = 262144
local UNAVAILABLE = "Realm list unavailable"
local RULESETS = { main = true, brawl = true, progression = true, casual = true, dalaran = true, custom = true }

local ON = (os.getenv("OV_LEYLINE") or "1") ~= "0"

-- Names players never see, whatever a host calls a realm.
local function anyCase(word)
    return (word:gsub("%a", function(c) return "[" .. c:lower() .. c:upper() .. "]" end))
end
local BRANDS = {}
for _, w in ipairs({ "world of warcraft", "warcraft", "lich king", "blizzard", "wow" }) do
    BRANDS[#BRANDS + 1] = "%f[%w]" .. anyCase(w):gsub(" ", "%%s+") .. "%f[%W]"
end

local function cleanName(s)
    if type(s) ~= "string" then return nil end
    s = s:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("[%z\1-\31\127|:]", " ")
    for _, p in ipairs(BRANDS) do s = s:gsub(p, "") end
    s = s:gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
    if #s > 32 then s = s:sub(1, 32):gsub("[\128-\191]*$", ""):gsub("[\192-\255]$", "") end
    return s ~= "" and s or "Unnamed realm"
end

local function count(v)
    v = tonumber(v)
    if not v or v < 0 or v >= 1000000 then return nil end
    return math.floor(v)
end

local DATA_WORDS = { ["return"] = true, ["true"] = true, ["false"] = true, updated = true, realms = true, id = true,
    name = true, ruleset = true, live = true, players = true, bots = true }

local cache = { at = -1e9, list = nil, updated = nil }

-- The file as { updated = epoch, realms = { {id, name, ruleset, live, players, bots}, ... } }, or nil.
local function readFile()
    local f = io.open(FILE, "rb")
    if not f then return nil end
    local text = f:read(MAX_FILE_BYTES + 1)
    f:close()
    if not text or #text > MAX_FILE_BYTES then return nil end
    -- Data only: the writer escapes every quote and backslash in a string as \ddd, so a backslash is only ever
    -- followed by three digits; outside the strings, nothing but DATA_WORDS. The file can never run code.
    if text:gsub("\\%d%d%d", ""):find("\\", 1, true) then return nil end
    for word in text:gsub('"[^"\n]*"', '""'):gmatch("[%a_][%w_]*") do
        if not DATA_WORDS[word] then return nil end
    end
    local chunk
    if setfenv then   -- LuaJIT / 5.1; 5.2+ takes the empty environment in load
        chunk = loadstring(text, "=leyline-realms")
        if chunk then setfenv(chunk, {}) end
    else
        chunk = load(text, "=leyline-realms", "t", {})
    end
    if not chunk then return nil end
    local ok, doc = pcall(chunk)
    if not ok or type(doc) ~= "table" or type(doc.realms) ~= "table" then return nil end
    local list, seen = {}, {}
    for _, r in ipairs(doc.realms) do
        if #list >= MAX_REALMS then break end
        if type(r) == "table" and type(r.id) == "string" and r.id:match("^[a-z2-7]+$") and #r.id == 16
            and not seen[r.id] then
            seen[r.id] = true
            list[#list + 1] = { id = r.id, name = cleanName(r.name), live = r.live == true,
                ruleset = RULESETS[r.ruleset] and r.ruleset or "custom", players = count(r.players), bots = count(r.bots) }
        end
    end
    return list, count(doc.updated)
end

local function realms()
    local t = os.time()
    if t - cache.at >= CACHE_SECONDS then
        cache.at = t
        cache.list, cache.updated = readFile()
    end
    return cache.list, cache.updated
end

local function isBot(p)
    for _, m in ipairs({ "IsBot", "IsPlayerbot" }) do
        local fn = p[m]
        if type(fn) == "function" then
            local ok, v = pcall(fn, p)
            if ok and v == true then return true end
        end
    end
    return false
end

-- This realm's own numbers (real players and bots in the world).
local function here()
    local people, bots = 0, 0
    local ok, list = pcall(GetPlayersInWorld)
    if ok and type(list) == "table" then
        for _, p in ipairs(list) do
            if isBot(p) then bots = bots + 1 else people = people + 1 end
        end
    end
    return people, bots
end

local function send(player, msg) player:SendAddonMessage(PREFIX, msg, WHISPER, player) end

local function dash(n) return n and tostring(n) or "-" end

local function sendList(player)
    local list, updated = realms()
    if not list then return send(player, "U:" .. UNAVAILABLE) end
    local age = updated and math.max(0, os.time() - updated) or 0
    send(player, string.format("B:%d:%d", #list + 1, age))
    local people, bots = here()
    send(player, string.format("R:this:1:%d:%d:main:%s", people, bots, cleanName(REALM_NAME)))
    for _, r in ipairs(list) do
        send(player, string.format("R:%s:%d:%s:%s:%s:%s", r.id, r.live and 1 or 0, dash(r.players), dash(r.bots),
            r.ruleset, r.name))
    end
    send(player, "E:" .. (#list + 1))
end

local askedAt = {} -- char guid -> os.time() of the last request
local hopAt = {}   -- char guid -> os.time() of the last hop echo
local HOP_COOLDOWN = 2

-- "wrath" (back home) or a relay realm id. The page checks it again and the portal only hops to a live listed realm.
local function hopTarget(msg)
    local t = msg:match("^H:([%w]+)$")
    if t and (t == "wrath" or (#t == 16 and t:match("^[a-z2-7]+$"))) then return t end
    return nil
end

local function onAddonMessage(event, sender, msgType, prefix, msg, target)
    if prefix ~= PREFIX then return end
    if not ON or not sender or type(msg) ~= "string" or #msg > 32 then return false end
    if msg == "L" then
        local guid, t = sender:GetGUIDLow(), os.time()
        if askedAt[guid] and t - askedAt[guid] < REQUEST_COOLDOWN then return false end
        askedAt[guid] = t
        sendList(sender)
    elseif msg:sub(1, 2) == "H:" then
        local target, guid, t = hopTarget(msg), sender:GetGUIDLow(), os.time()
        if target and not (hopAt[guid] and t - hopAt[guid] < HOP_COOLDOWN) then
            hopAt[guid] = t
            send(sender, "H:" .. target)
        end
    end
    return false
end

local function onLogout(event, player) askedAt[player:GetGUIDLow()] = nil; hopAt[player:GetGUIDLow()] = nil end

RegisterServerEvent(30, onAddonMessage) -- ADDON_EVENT_ON_MESSAGE
RegisterPlayerEvent(4, onLogout)        -- PLAYER_EVENT_ON_LOGOUT

-- for tests
OV_LEYLINE_TEST = { cleanName = cleanName, readFile = readFile, sendList = sendList, onAddonMessage = onAddonMessage,
    cache = cache, hopTarget = hopTarget }
