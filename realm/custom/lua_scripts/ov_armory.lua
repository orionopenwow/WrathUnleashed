-- WrathUnleashed Armory, server half (mod-ale). Search the whole item database and take what you
-- want, inside the slices where Armory gear is allowed. Chat commands for now; the Armory window
-- (an addon) will talk to the same functions.
--
--   .armory <words>      search item names (rare and better, best item level first)
--   .armory give <id>    put that item in your bags
--
-- Rules: only where a slice allows it (SLICES below); never GM, test or unobtainable items; at
-- most one item a second. Every item given is recorded in characters.ov_armory_items, so a
-- progression slice can tell Armory gear from earned gear.

local SLICES = {
    -- Brawl slice: Dalaran (zone 4395), plus arenas and battlegrounds (checked by map type).
    zones = { [4395] = true },
    arenas_and_battlegrounds = true,
}
local MIN_QUALITY = 2      -- uncommon and better
local MAX_ITEM_LEVEL = 284 -- highest real 3.3.5a item level; everything above is a QA/test item
local MAX_RESULTS = 15
local MAX_PER_DAY = 100
local last_give = {}
local last_search = {}

-- One filter for search AND give, so an id typed by hand can't fetch GM/QA/placeholder items
-- (e.g. 24358 "QATest +1000 Spell Dmg Ring", 38484 "QA Test +2000 Spell Power Ring").
-- Plain SQL (no string.format), so single % signs.
local ARMORY_FILTER = string.format("class IN (2, 4) AND InventoryType > 0 AND Quality >= %d AND Quality <> 6 AND ItemLevel <= %d", MIN_QUALITY, MAX_ITEM_LEVEL) ..
    -- "test" only at a word start, so Slatesteel and Hatestrike stay in.
    " AND name NOT REGEXP '(^|[^[:alpha:]])(qa)?test' AND name NOT LIKE '%Deprecated%' AND name NOT LIKE '%Monster -%'" ..
    " AND name NOT LIKE '%[PH]%' AND name NOT LIKE 'PH %' AND name NOT LIKE 'zz%' AND name NOT LIKE '%(OLD)%'" ..
    " AND name NOT LIKE '% PH %' AND name NOT LIKE 'Obsolete%' AND name NOT LIKE '%Unused%' AND name NOT LIKE 'Alex''s %'" ..
    " AND name NOT LIKE 'Foror''s %' AND name NOT LIKE '%Art Demo%' AND name <> 'Hammer of the Naaru'"

local function say(player, text)
    player:SendBroadcastMessage("|cff66ccff[Armory]|r " .. text)
    player:SendAddonMessage("OVARM", "M:" .. text:gsub("|c%x%x%x%x%x%x%x%x", ""):gsub("|r", ""):gsub("|H.-|h", ""):gsub("|h", ""), 7, player)
end

-- Main realm (profiles/main.env, OV_MAIN=1): the Armory is for level 80 characters only, so level-1 characters
-- play the normal game and the free gear is an end-game (boost or levelled) convenience.
local MAIN_MIN_LEVEL = 80
local function mainLevelOk(player)
    return os.getenv("OV_MAIN") ~= "1" or player:GetLevel() >= MAIN_MIN_LEVEL
end

local function inArmorySlice(player)
    if not mainLevelOk(player) then return false end
    if SLICES.zones[player:GetZoneId()] then return true end
    if SLICES.arenas_and_battlegrounds then
        local map = player:GetMap()
        if map and (map:IsArena() or map:IsBattleground()) then return true end
    end
    return false
end

local QUALITY_COLOR = { [2] = "1eff00", [3] = "0070dd", [4] = "a335ee", [5] = "ff8000", [7] = "e6cc80" }

local function link(entry, name, quality)
    return string.format("|cff%s|Hitem:%d:0:0:0:0:0:0:0:80|h[%s]|h|r", QUALITY_COLOR[quality] or "ffffff", entry, name)
end

local function searchAllowed(player)
    local guid, now = player:GetGUIDLow(), os.time()
    if last_search[guid] == now then return false end
    last_search[guid] = now
    return true
end

local function parseEntry(s)
    s = s and s:match("^%s*(%d+)%s*$")
    if not s or #s > 9 then return nil end
    return tonumber(s)
end

local function search(player, words)
    if not searchAllowed(player) then return say(player, "One search a second.") end
    local clean = words:gsub("[^%w%s'%-]", ""):sub(1, 40)
    if #clean < 3 then return say(player, "Type at least three letters: .armory <words>") end
    clean = clean:gsub("'", "''")
    -- (The old string lacked a space before AND: "Quality <> 6AND name ..." failed in MySQL.)
    local q = WorldDBQuery("SELECT entry, name, Quality, ItemLevel FROM item_template " ..
        "WHERE name LIKE '%" .. clean .. "%' AND " .. ARMORY_FILTER ..
        " ORDER BY ItemLevel DESC LIMIT " .. MAX_RESULTS)
    if not q then return say(player, "Nothing found for \"" .. words .. "\".") end
    repeat
        local entry, name, quality, ilvl = q:GetUInt32(0), q:GetString(1), q:GetUInt32(2), q:GetUInt32(3)
        say(player, string.format("%s  ilvl %d  — .armory give %d", link(entry, name, quality), ilvl, entry))
    until not q:NextRow()
end

local function give(player, entry)
    if not mainLevelOk(player) then
        return say(player, "On this realm the Armory opens at level " .. MAIN_MIN_LEVEL .. ".")
    end
    if not inArmorySlice(player) then
        return say(player, "The Armory works in Dalaran, arenas and battlegrounds.")
    end
    local now = os.time()
    if last_give[player:GetGUIDLow()] == now then return say(player, "One item a second.") end
    last_give[player:GetGUIDLow()] = now
    local given = CharDBQuery(string.format("SELECT COUNT(*) AS n FROM ov_armory_items WHERE owner_guid = %d AND given_at > %d",
        player:GetGUIDLow(), now - 86400))
    if given and given:GetUInt32(0) >= MAX_PER_DAY then
        return say(player, "That's " .. MAX_PER_DAY .. " Armory items today; more tomorrow.")
    end
    local q = WorldDBQuery(string.format("SELECT name, Quality FROM item_template WHERE entry = %d AND ", entry) ..
        ARMORY_FILTER)
    if not q then return say(player, "That item isn't in the Armory.") end
    local item = player:AddItem(entry, 1)
    -- mod-ale's AddItem returns without pushing a value when the bags are full, so the caller
    -- gets the last argument back (the number 1), not nil. Only an Item userdata is a success.
    if type(item) ~= "userdata" then return say(player, "No room in your bags.") end
    item:SetBinding(true)
    -- IGNORE: a stackable item merges into an existing stack and comes back with that stack's guid.
    CharDBExecute(string.format(
        "INSERT IGNORE INTO ov_armory_items (item_guid, owner_guid, item_entry, given_at) VALUES (%d, %d, %d, %d)",
        item:GetGUIDLow(), player:GetGUIDLow(), entry, now))
    say(player, "Added " .. link(entry, q:GetString(0), q:GetUInt32(1)) .. ".")
end

-- The Armory window's channel: addon messages with prefix OVARM, to and from the player.
--   client -> server   S:<slot>:<words>   search (slot = InventoryType number, 0 = any)
--                      G:<entry>          take an item
--   server -> client   R:<entry>:<quality>:<ilvl>:<invtype>:<name>   one result
--                      E:<count>          end of results
--                      M:<text>           a message to show
local PREFIX = "OVARM"
local WHISPER = 7

local function reply(player, msg)
    player:SendAddonMessage(PREFIX, msg, WHISPER, player)
end

local function addonSearch(player, slot, words)
    local clean = (words or ""):gsub("[^%w%s'%-]", ""):sub(1, 40):gsub("'", "''")
    local where = { ARMORY_FILTER }
    if #clean >= 2 then where[#where + 1] = "name LIKE '%" .. clean .. "%'" end
    slot = math.floor(tonumber(slot) or 0)
    if slot < 0 or slot > 28 then slot = 0 end
    if slot > 0 then where[#where + 1] = "InventoryType = " .. slot end
    if #clean < 2 and slot == 0 then
        return reply(player, "M:Type a name or pick a slot.")
    end
    if not searchAllowed(player) then return reply(player, "M:One search a second.") end
    local q = WorldDBQuery("SELECT entry, Quality, ItemLevel, InventoryType, name FROM item_template WHERE " ..
        table.concat(where, " AND ") .. " ORDER BY ItemLevel DESC, Quality DESC LIMIT 40")
    local n = 0
    if q then
        repeat
            n = n + 1
            reply(player, string.format("R:%d:%d:%d:%d:%s", q:GetUInt32(0), q:GetUInt32(1), q:GetUInt32(2),
                q:GetUInt32(3), q:GetString(4)))
        until not q:NextRow()
    end
    reply(player, "E:" .. n)
end

local function onAddonMessage(event, sender, msgType, prefix, msg, target)
    if prefix ~= PREFIX then return end
    if not sender or type(msg) ~= "string" or #msg > 200 then return false end
    local kind, rest = msg:match("^(%a):(.*)$")
    if kind == "S" then
        local slot, words = rest:match("^(%d+):(.*)$")
        if slot then addonSearch(sender, slot, words) end
    elseif kind == "G" and parseEntry(rest) then
        give(sender, parseEntry(rest))
    end
    return false
end

local function onCommand(event, player, command)
    if not player then return end
    local cmd = (command or ""):gsub("^[%.!]", "")
    local head, rest = cmd:match("^(%S+)%s*(.*)$")
    if not head or head:lower() ~= "armory" then return end
    local sub, arg = rest:match("^(%S+)%s*(.*)$")
    if sub and sub:lower() == "give" and parseEntry(arg) then
        give(player, parseEntry(arg))
    elseif rest ~= "" then
        search(player, rest)
    else
        say(player, "Search: .armory <words>   Take: .armory give <id>")
    end
    return false
end

CharDBExecute([[CREATE TABLE IF NOT EXISTS ov_armory_items (
    item_guid INT UNSIGNED NOT NULL PRIMARY KEY,
    owner_guid INT UNSIGNED NOT NULL,
    item_entry INT UNSIGNED NOT NULL,
    given_at INT UNSIGNED NOT NULL,
    KEY owner (owner_guid)
)]])
RegisterPlayerEvent(42, onCommand) -- PLAYER_EVENT_ON_COMMAND
RegisterServerEvent(30, onAddonMessage) -- ADDON_EVENT_ON_MESSAGE
