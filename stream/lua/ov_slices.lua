-- Open Vanilla / WrathUnleashed: keep "play in the browser" (streamed) accounts inside the streamed
-- mini slice (mod-ale).
--
-- A browser player's client only has the files of the slice (Dalaran, the capitals, the starter
-- areas and the instances of the tiers the owner streams), so their character must stay there.
-- The website's sign-in gate (wrath_portal.py, GET /wrath/play) marks the account through SOAP:
--     ovstream mark <ACCOUNT> <slice> <maxTier> <seconds>      ovstream clear <ACCOUNT>
-- (console only), which writes acore_auth.ov_stream_accounts. On login, zone, area and map change
-- (and every few seconds, for the box-bounded starter areas), a marked player who is outside the
-- slice is sent home with a whisper and a centre-screen message saying the full world needs their
-- own game files.
--
-- The tiers come from slices/mini.json through tiers_lua.py (ov_slices_tiers.lua, the global
-- OV_STREAM_TIERS), read when needed, so reordering mini.json reorders the realm too. Without that
-- file only tier 0 and Dalaran exist.
--
-- Streamed characters by level (lowLevel, 15 by default):
--   below 15   live in their faction's starter area (Northshire Valley for the Alliance, the Valley of
--              Trials for the Horde) and capital (Stormwind City, Orgrimmar), as far as the slice
--              holds them; anywhere else sends them to their starter area. .play lists those two.
--              No Dungeon Finder.
--   15 and up  every streamed tier: the Dungeon Finder for the streamed dungeons of their level
--              (Specific Dungeons), .play for their capital, starter area, Dalaran and the streamed
--              instances. Home is their capital (Dalaran from level 68, or when the capital is not
--              streamed).
--   Death Knights start at 55 in Ebon Hold (map 609, streamed as a starter area).
--   The main realm's "Boost to level 80" (ov_main.lua) works unchanged: it sets level 80 and
--   teleports to Dalaran, which is always inside the slice.
--
-- APIs (mod-ale, checked against src/LuaEngine/Hooks.h, LuaFunctions.cpp and the method headers):
--   RegisterPlayerEvent 3 LOGIN (event, player), 13 LEVEL_CHANGE (event, player, oldLevel),
--   27 UPDATE_ZONE (event, player, newZone, newArea), 28 MAP_CHANGE (event, player), 42 COMMAND
--   (event, player, command, chatHandler; player nil from the console/SOAP; return false =
--   handled), 47 UPDATE_AREA (event, player, oldArea, newArea), 50 CAN_JOIN_LFG (event, player,
--   roles, dungeons, comment; return false = refuse). AuthDBQuery/AuthDBExecute, Player:Teleport(map,
--   x, y, z, o), Player:GetTeam (TeamId: 0 Alliance, 1 Horde), Unit:GetLevel, Unit:GetClass,
--   WorldObject:GetX/GetY/GetMapId/GetZoneId, Player:SendBroadcastMessage,
--   Player:SendAreaTriggerMessage, WorldObject:RegisterEvent(fn, delay, repeats; 0 = forever; fn gets
--   eventId, delay, repeats, worldobject) and RemoveEventById, Player:GossipClearMenu/
--   GossipMenuAddItem/GossipSendMenu/GossipComplete, RegisterPlayerGossipEvent(menu, 2, fn),
--   ChatHandler:SendSysMessage, Player:GetGroup, Group:IsRaidGroup.

local MENU_ID = 61700
local TEXT_ID = 100
local CLASS_DK = 6
local TEAM_HORDE = 1
local NORTHREND_LEVEL = 68     -- from here on, home is Dalaran
local CHECK_EVERY_MS = 5000    -- the position check for box-bounded areas
local GOSSIP_MAX = 30          -- 3.3.5a shows at most 32 gossip items

local DISCORD = "https://discord.gg/hVeUxYwbkr"
local BYOC = "This part of the world isn't streamed to the browser. To go everywhere, play with your own "
    .. "3.3.5a game files. Need help finding or setting up your own 3.3.5a game folder? Join our "
    .. "Discord and people will help: " .. DISCORD
local BYOC_SHORT = "Not streamed: play with your own game files to go here (help: " .. DISCORD .. ")"
local TAG = "|cffff9933[Browser play]|r "

-- Dalaran (game_tele "Dalaran") is home at every tier: tier 1 of every slice.
local HOME = { 571, 5807.98, 588.487, 660.94, 1.66594 }

-- Without ov_slices_tiers.lua: the base and Dalaran only.
local FALLBACK = {
    slice = "mini", count = 2, lowLevel = 15,
    [0] = { key = "base", name = "base", kind = "base", maps = {} },
    [1] = { key = "dalaran", name = "Dalaran", kind = "home", maps = { { id = 571, zone = 4395 } },
            play = { { "Dalaran: the city centre", 571, 5807.98, 588.487, 660.94, 1.66594, false },
                     { "Dalaran: the Visitor Center", 571, 5757.44, 621.777, 650.091, 0.460362, false },
                     { "Dalaran: the Underbelly (sewers)", 571, 5804.89, 640.08, 609.887, 1.00618, false } } },
}

local function tiers()
    local t = rawget(_G, "OV_STREAM_TIERS")
    if type(t) == "table" and type(t[0]) == "table" and type(t[1]) == "table" and t[1].kind == "home" then
        return t
    end
    return FALLBACK
end

local function lowLevel() return tonumber(tiers().lowLevel) or 15 end

-- account id -> { slice, tier, exp (os.time) }
local flagged = {}
local lastSent = {}
local pendingHome = {}
local watching = {}

local function now() return os.time() end

local function flagOf(accountId)
    local f = flagged[accountId]
    if f and f.exp <= now() then
        flagged[accountId] = nil
        return nil
    end
    return f
end

local function factionOf(p) return p:GetTeam() == TEAM_HORDE and "horde" or "alliance" end
local function isDK(p) return p:GetClass() == CLASS_DK end
local function isLow(p) return p:GetLevel() < lowLevel() end

-- The highest tier number open to a mark (Dalaran, tier 1, always: it is home).
local function topTier(f)
    local T = tiers()
    local top = math.max(tonumber(f and f.tier) or 0, 1)
    return math.min(top, (tonumber(T.count) or 2) - 1)
end

local function ownFaction(t, p)
    if t.faction == "deathknight" then return isDK(p) end
    return t.faction == nil or t.faction == factionOf(p)
end

-- May this player be in tier t at all? Below lowLevel: only Dalaran, its own starter area and
-- capital. From lowLevel on: everything streamed.
local function tierOpen(t, p)
    if t.kind == "base" then return false end
    if t.kind == "home" or not p then return true end
    if isLow(p) then
        return (t.kind == "starter" or t.kind == "city") and ownFaction(t, p)
    end
    return true
end

local function inEntry(m, map, zone, x, y)
    if m.id ~= map then return false end
    if m.zone then return zone == m.zone end
    if m.box then
        local b = m.box
        return x ~= nil and y ~= nil and x >= b[1] and x <= b[2] and y >= b[3] and y <= b[4]
    end
    return true
end

local function inSlice(f, p, map, zone, x, y)
    local T = tiers()
    for n = 1, topTier(f) do
        local t = T[n]
        if t and tierOpen(t, p) then
            for _, m in ipairs(t.maps or {}) do
                if inEntry(m, map, zone, x, y) then return true end
            end
        end
    end
    return false
end

-- Whole instance maps the player may enter (the Dungeon Finder, .play).
local function allowedMaps(f, p)
    local set, T = {}, tiers()
    for n = 1, topTier(f) do
        local t = T[n]
        if t and tierOpen(t, p) then
            for _, m in ipairs(t.maps or {}) do
                if not m.zone and not m.box then set[m.id] = true end
            end
        end
    end
    return set
end

local function findTier(f, p, kind)
    local T = tiers()
    for n = 2, topTier(f) do
        local t = T[n]
        if t and t.kind == kind and ownFaction(t, p) and t.faction ~= "deathknight" then return t end
    end
end

-- Where a stream character belongs: its starter area below lowLevel, its capital below Northrend
-- levels, else Dalaran (also whenever the slice does not hold the place).
local function homeOf(f, p)
    local lvl = p:GetLevel()
    if lvl < lowLevel() then
        local s = findTier(f, p, "starter")
        if s and s.home then return s.home end
    end
    if lvl < NORTHREND_LEVEL then
        local c = findTier(f, p, "city")
        local e = c and c.play and c.play[1]
        if e then return { e[2], e[3], e[4], e[5], e[6] } end
    end
    return HOME
end

local function tell(p, guid, long)
    local t = now()
    if (lastSent[guid] or 0) + 5 <= t then
        lastSent[guid] = t
        p:SendBroadcastMessage(TAG .. (long or BYOC))
        p:SendAreaTriggerMessage(BYOC_SHORT)
    end
end

local function here(p)
    return p:GetMapId(), p:GetZoneId(), p:GetX(), p:GetY()
end

-- Deferred (teleporting from inside a login/zone/map hook is unsafe). The decision made in the
-- hook stands unless the player has changed maps or level meanwhile (a boost); the zone a hook
-- reports can be newer than what GetZoneId() says at that moment.
local function sendHome(player, why)
    local guid, seenMap, seenLevel = player:GetGUIDLow(), player:GetMapId(), player:GetLevel()
    if pendingHome[guid] then return end
    pendingHome[guid] = true
    player:RegisterEvent(function(_, _, _, p)
        pendingHome[guid] = nil
        local f = flagOf(p:GetAccountId())
        if not f or p:IsGM() then return end
        if (p:GetMapId() ~= seenMap or p:GetLevel() ~= seenLevel) and inSlice(f, p, here(p)) then return end
        if p:IsDead() then p:ResurrectPlayer(100, false) end
        local h = homeOf(f, p)
        p:Teleport(h[1], h[2], h[3], h[4], h[5])
        tell(p, guid)
    end, why == "login" and 1500 or 250, 1)
end

local function check(player, map, zone, why)
    local f = flagOf(player:GetAccountId())
    if not f or player:IsGM() then return end
    local m0, z0, x, y = here(player)
    if not inSlice(f, player, map or m0, zone or z0, x, y) then
        sendHome(player, why)
    end
end

-- A box (Northshire, the Valley of Trials) can be left without any zone or area change, so a
-- marked player is also checked every few seconds while online and marked.
local function watch(player)
    local guid = player:GetGUIDLow()
    if watching[guid] then return end
    watching[guid] = true
    player:RegisterEvent(function(eventId, _, _, p)
        if not flagOf(p:GetAccountId()) then
            watching[guid] = nil
            p:RemoveEventById(eventId)
            return
        end
        check(p, nil, nil, "tick")
    end, CHECK_EVERY_MS, 0)
end

local function loadAccount(accountId)
    local q = AuthDBQuery(string.format(
        "SELECT slice, max_tier, expires_at - UNIX_TIMESTAMP() FROM ov_stream_accounts "
        .. "WHERE account_id = %d AND expires_at > UNIX_TIMESTAMP()", accountId))
    if q then
        flagged[accountId] = { slice = q:GetString(0), tier = q:GetUInt32(1), exp = now() + q:GetInt32(2) }
    end
    -- No row: keep what this process marked itself (the write may still be queued).
end

local function loadAll()
    local q = AuthDBQuery("SELECT account_id, slice, max_tier, expires_at - UNIX_TIMESTAMP() "
        .. "FROM ov_stream_accounts WHERE expires_at > UNIX_TIMESTAMP()")
    if q then
        repeat
            flagged[q:GetUInt32(0)] = { slice = q:GetString(1), tier = q:GetUInt32(2), exp = now() + q:GetInt32(3) }
        until not q:NextRow()
    end
end

local function onlineByAccount(accountId)
    for _, p in ipairs(GetPlayersInWorld() or {}) do
        if p:GetAccountId() == accountId then return p end
    end
end

-- console: ovstream mark <ACCOUNT> <slice> <tier> <seconds> | ovstream clear <ACCOUNT>
local function consoleCommand(command, handler)
    local verb, rest = command:match("^ovstream%s+(%a+)%s*(.*)$")
    if not verb then return nil end
    local function reply(msg) if handler then handler:SendSysMessage(msg) end end
    local name, slice, tier, secs = rest:match("^(%w+)%s+([%l%d%-]+)%s+(%d+)%s+(%d+)%s*$")
    if verb == "clear" then name = rest:match("^(%w+)%s*$") end
    if not name or #name > 16 or (verb == "mark" and (#slice > 32 or tonumber(secs) > 7 * 86400 or tonumber(tier) > 255)) then
        reply("ovstream: usage: ovstream mark <account> <slice> <tier> <seconds> | ovstream clear <account>")
        return false
    end
    name = name:upper()
    local q = AuthDBQuery(string.format("SELECT id FROM account WHERE username = '%s'", name))
    if not q then
        reply("ovstream: no such account " .. name)
        return false
    end
    local id = q:GetUInt32(0)
    if verb == "mark" then
        tier, secs = tonumber(tier), tonumber(secs)
        AuthDBExecute(string.format(
            "REPLACE INTO ov_stream_accounts (account_id, slice, max_tier, expires_at) "
            .. "VALUES (%d, '%s', %d, UNIX_TIMESTAMP() + %d)", id, slice, tier, secs))
        flagged[id] = { slice = slice, tier = tier, exp = now() + secs }
        local p = onlineByAccount(id)
        if p then check(p, nil, nil, "mark"); watch(p) end
        reply(string.format("ovstream ok: %s marked (%s, tier %d, %d s)", name, slice, tier, secs))
    elseif verb == "clear" then
        AuthDBExecute(string.format("DELETE FROM ov_stream_accounts WHERE account_id = %d", id))
        flagged[id] = nil
        reply("ovstream ok: " .. name .. " cleared")
    else
        reply("ovstream: unknown verb " .. verb)
    end
    return false
end

-- .play menu -------------------------------------------------------------------------------------
-- intids: 99 close, 98 the level-15 note, 2000 the top menu, 2000 + group (a submenu),
-- 10000 + tier * 100 + entry (a teleport), 500 + tier (how to queue for arenas / battlegrounds).

local GROUPS = {
    { "home", "Dalaran" },
    { "places", "Your capital and starting area" },
    { "classic", "Dungeons: Azeroth" },
    { "outland", "Dungeons: Outland" },
    { "northrend", "Dungeons: Northrend" },
    { "raids", "Raids" },
    { "pvp", "Arenas and battlegrounds" },
}

local function groupOf(t)
    if t.kind == "home" then return "home" end
    if t.kind == "city" or t.kind == "starter" then return "places" end
    if t.kind == "raid" then return "raids" end
    if t.kind == "arena" or t.kind == "battleground" then return "pvp" end
    local hi = t.levels and t.levels[2]
    if hi and hi <= 60 then return "classic" end
    if hi and hi <= 70 then return "outland" end
    return "northrend"
end

-- What the menu offers this player: tiers it may use, and only its own faction's places.
local function menuTiers(player, f)
    local T, out = tiers(), {}
    local gm = player:IsGM() and not f
    local top = gm and ((tonumber(T.count) or 2) - 1) or topTier(f)
    for n = 1, top do
        local t = T[n]
        if t and (gm or tierOpen(t, player)) then
            local g = groupOf(t)
            local ok = true
            if g == "places" then ok = gm or ownFaction(t, player) end
            if g == "home" and not gm and isLow(player) then ok = false end   -- below 15: starter + capital
            if ok and ((t.play and #t.play > 0) or t.text) then out[#out + 1] = { n = n, t = t, g = g } end
        end
    end
    return out
end

local function showMenu(player, group)
    local f = flagOf(player:GetAccountId())
    local list = menuTiers(player, f)
    player:GossipClearMenu()
    if not group then
        local have = {}
        for _, e in ipairs(list) do have[e.g] = (have[e.g] or 0) + 1 end
        for i, g in ipairs(GROUPS) do
            if have[g[1]] then
                player:GossipMenuAddItem(g[1] == "pvp" and 9 or 2, g[2], 0, 2000 + i)
            end
        end
        if f and isLow(player) then
            player:GossipMenuAddItem(0, "At level " .. lowLevel() .. ": the Dungeon Finder and more places", 0, 98)
        end
    else
        local key, count = GROUPS[group] and GROUPS[group][1], 0
        -- dungeons by level, whatever their place in the tier order; the rest in tier order
        table.sort(list, function(a, b)
            local la = a.t.levels and a.t.levels[1] or 999
            local lb = b.t.levels and b.t.levels[1] or 999
            if la ~= lb then return la < lb end
            return a.n < b.n
        end)
        for _, e in ipairs(list) do
            if e.g == key then
                if e.t.text and count < GOSSIP_MAX then
                    player:GossipMenuAddItem(9, (e.t.name ~= "" and e.t.name or "PvP") .. ": how to play", 0, 500 + e.n)
                    count = count + 1
                end
                for i, p in ipairs(e.t.play or {}) do
                    if count < GOSSIP_MAX and i < 100 then
                        local label = p[1]
                        if e.t.kind == "raid" or p[7] then label = "Raid: " .. label
                        elseif e.t.kind == "dungeon" then label = "Dungeon: " .. label end
                        player:GossipMenuAddItem(2, label, 0, 10000 + e.n * 100 + i)
                        count = count + 1
                    end
                end
            end
        end
        player:GossipMenuAddItem(0, "Back", 0, 2000)
    end
    player:GossipMenuAddItem(0, "Close", 0, 99)
    player:GossipSendMenu(TEXT_ID, player, MENU_ID)
end

local function onSelect(event, player, object, sender, intid, code, menuId)
    intid = tonumber(intid) or 0
    local f = flagOf(player:GetAccountId())
    if not f and not player:IsGM() then return player:GossipComplete() end
    if intid == 2000 then return showMenu(player) end
    if intid > 2000 and intid <= 2000 + #GROUPS then return showMenu(player, intid - 2000) end
    player:GossipComplete()
    if intid == 98 then
        player:SendBroadcastMessage(TAG .. "Below level " .. lowLevel() .. " you live in your starting area and your capital. "
            .. "At " .. lowLevel() .. " the Dungeon Finder opens for the streamed dungeons of your level, and .play takes you to them.")
        return
    end
    local allowed = {}
    for _, e in ipairs(menuTiers(player, f)) do allowed[e.n] = e.t end
    if intid >= 500 and intid < 600 then
        local t = allowed[intid - 500]
        if t and t.text then player:SendBroadcastMessage(TAG .. t.text) end
        return
    end
    if intid < 10000 then return end
    local n, i = math.floor((intid - 10000) / 100), (intid - 10000) % 100
    local t = allowed[n]
    local d = t and t.play and t.play[i]
    if not d then return end
    local raid = t.kind == "raid" or d[7]
    local group = player:GetGroup()
    if raid and not (group and group:IsRaidGroup()) then
        player:SendBroadcastMessage(TAG .. d[1] .. " is a raid: form a raid group first, then use .play again.")
        return
    end
    if not player:Teleport(d[2], d[3], d[4], d[5], d[6]) then
        player:SendBroadcastMessage(TAG .. "You can't enter " .. d[1] .. " yet (level, heroic key or group requirement).")
    elseif group and (t.kind == "dungeon" or raid) then
        player:SendBroadcastMessage(TAG .. "Your group members join you with .play too: you share one instance.")
    end
end

-- hooks -----------------------------------------------------------------------------------------

local function onCommand(event, player, command, handler)
    if not player then
        return consoleCommand(command or "", handler)
    end
    local cmd = (command or ""):gsub("^[%.!]", ""):lower():gsub("%s+$", "")
    if cmd == "play" then
        if flagOf(player:GetAccountId()) or player:IsGM() then
            showMenu(player)
        else
            player:SendBroadcastMessage(TAG .. ".play is the menu for players in the browser.")
        end
        return false
    end
end

local function placeNames(f, p)
    local s, c = findTier(f, p, "starter"), findTier(f, p, "city")
    local names = {}
    if s then names[#names + 1] = s.name end
    if c then names[#names + 1] = c.name end
    return #names > 0 and table.concat(names, " and ") or "Dalaran"
end

local function onLogin(event, player)
    -- A player's timed events end at logout: forget the ones of an earlier session.
    pendingHome[player:GetGUIDLow()], watching[player:GetGUIDLow()] = nil, nil
    loadAccount(player:GetAccountId())
    local f = flagOf(player:GetAccountId())
    if not f then return end
    check(player, nil, nil, "login")
    watch(player)
    if isLow(player) and not player:IsGM() then
        player:SendBroadcastMessage(TAG .. "In the browser you live in " .. placeNames(f, player) .. " until level "
            .. lowLevel() .. "; then the Dungeon Finder opens. Type .play for the menu. To go everywhere, play with "
            .. "your own game files (help: " .. DISCORD .. ").")
    end
end

local function onZone(event, player, newZone, newArea)
    check(player, player:GetMapId(), newZone, "zone")
end

local function onArea(event, player, oldArea, newArea)
    check(player, nil, nil, "area")
end

local function onMap(event, player)
    check(player, nil, nil, "map")
end

local function onLevel(event, player, oldLevel)
    if not flagOf(player:GetAccountId()) then return end
    local lvl = player:GetLevel()
    if (tonumber(oldLevel) or 0) < lowLevel() and lvl >= lowLevel() and lvl < 80 then
        player:SendBroadcastMessage(TAG .. "Level " .. lowLevel() .. "! The Dungeon Finder (I) now queues you for the "
            .. "streamed dungeons of your level (Specific Dungeons), and .play has more places.")
    end
end

local function onCanJoinLfg(event, player, roles, dungeons, comment)
    local f = flagOf(player:GetAccountId())
    if not f then return end
    if isLow(player) then
        player:SendBroadcastMessage(TAG .. "In the browser the Dungeon Finder opens at level " .. lowLevel() .. ".")
        return false
    end
    local lfg = rawget(_G, "OV_STREAM_LFG")
    local levels = rawget(_G, "OV_STREAM_LFG_LEVEL")
    local maps = allowedMaps(f, player)
    local lvl = player:GetLevel()
    for _, id in ipairs(dungeons or {}) do
        local map = lfg and lfg[id]
        if not map or not maps[map] then
            player:SendBroadcastMessage(TAG .. "In the browser the Dungeon Finder only "
                .. "queues for the streamed dungeons (choose them under Specific Dungeons; random queues "
                .. "can send you anywhere). " .. BYOC)
            player:SendAreaTriggerMessage(BYOC_SHORT)
            return false
        end
        local r = levels and levels[id]
        if r and (lvl < r[1] or lvl > r[2]) then
            player:SendBroadcastMessage(TAG .. string.format("That dungeon is for levels %d to %d in the Dungeon Finder.", r[1], r[2]))
            return false
        end
    end
end

AuthDBExecute("CREATE TABLE IF NOT EXISTS ov_stream_accounts ("
    .. "account_id INT UNSIGNED NOT NULL PRIMARY KEY, slice VARCHAR(32) NOT NULL, "
    .. "max_tier TINYINT UNSIGNED NOT NULL DEFAULT 1, expires_at INT UNSIGNED NOT NULL, "
    .. "updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, "
    .. "KEY expires_at (expires_at))")
loadAll()

RegisterPlayerEvent(3, onLogin)       -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(13, onLevel)      -- PLAYER_EVENT_ON_LEVEL_CHANGE
RegisterPlayerEvent(27, onZone)       -- PLAYER_EVENT_ON_UPDATE_ZONE
RegisterPlayerEvent(28, onMap)        -- PLAYER_EVENT_ON_MAP_CHANGE
RegisterPlayerEvent(42, onCommand)    -- PLAYER_EVENT_ON_COMMAND
RegisterPlayerEvent(47, onArea)       -- PLAYER_EVENT_ON_UPDATE_AREA
RegisterPlayerEvent(50, onCanJoinLfg) -- PLAYER_EVENT_ON_CAN_JOIN_LFG
RegisterPlayerGossipEvent(MENU_ID, 2, onSelect)

-- for tests (tests/test_ov_slices.lua loads this file under a fake ALE)
OV_SLICES_TEST = { tiers = tiers, flagged = flagged, inSlice = inSlice, allowedMaps = allowedMaps,
                   homeOf = homeOf, BYOC = BYOC, FALLBACK = FALLBACK }
