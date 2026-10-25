-- ov_reports.lua: WrathUnleashed bug reports and small quality-of-life commands (mod-ale).
--
--   .bug <what happened>    files a bug report with where you are (map, zone, position, level), stored in
--                           acore_characters.ov_bug_reports for the GM console; .report is the same.
--   .stuck                  hearths you home when you are stuck (not in combat; once per 10 minutes).
--   .wu (or .commands)      lists the WrathUnleashed commands (ov_qol.lua's .learnall, .respec, .xp, .hearth,
--                           .summon and .qol on a second line).
--   .guide                  the level 80 guide: what to do at 80 on this realm. Shown by itself when a
--                           character reaches 80 (the boost included); 80s get a one-line pointer at login.
--   .mounts                 every mount for level 80s: learns every mount spell (ground and flying) the player
--                           doesn't have yet. Runs by itself once per character on reaching 80 (the boost included)
--                           or at the first login at 80, marked in acore_characters.ov_unlocks; .mounts re-runs it
--                           (once per 10 minutes, like .stuck).
--
-- Reports are rate-limited per account (REPORTS_PER_HOUR) and capped in length; the text is escaped before
-- it reaches SQL. Nothing is sent anywhere else: staff read them in the GM console or with SQL.
-- mod-ale events used: 3 ON_LOGIN, 13 ON_LEVEL_CHANGE, 42 ON_COMMAND (return false = handled, no "no such command").

local TAG = "|cff66ccff[WrathUnleashed]|r "
local REPORTS_PER_HOUR = 6
local MAX_TEXT = 500
local STUCK_COOLDOWN = 600
local HEARTHSTONE_SPELL = 8690

local ON = (os.getenv("OV_REPORTS") or "1") ~= "0"

CharDBExecute("CREATE TABLE IF NOT EXISTS ov_bug_reports ("
    .. "id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
    .. "account_id INT UNSIGNED NOT NULL, char_guid INT UNSIGNED NOT NULL, char_name VARCHAR(12) NOT NULL, "
    .. "level TINYINT UNSIGNED NOT NULL, class TINYINT UNSIGNED NOT NULL, "
    .. "map_id SMALLINT UNSIGNED NOT NULL, zone_id INT UNSIGNED NOT NULL, area_id INT UNSIGNED NOT NULL, "
    .. "pos_x FLOAT NOT NULL, pos_y FLOAT NOT NULL, pos_z FLOAT NOT NULL, "
    .. "text VARCHAR(500) NOT NULL, status VARCHAR(16) NOT NULL DEFAULT 'new', "
    .. "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, "
    .. "KEY status (status), KEY created_at (created_at))")

CharDBExecute("CREATE TABLE IF NOT EXISTS ov_unlocks ("
    .. "guid INT UNSIGNED NOT NULL, kind VARCHAR(16) NOT NULL, "
    .. "done_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (guid, kind))")

local recent = {}   -- account id -> { times }
local stuckAt = {}  -- char guid -> os.time() of the last .stuck
local mountsAt = {} -- char guid -> os.time() of the last .mounts

local function say(player, msg) player:SendBroadcastMessage(TAG .. msg) end

-- SQL string literal body: backslash and quote escaped, control characters dropped.
local function esc(s)
    s = tostring(s or ""):gsub("[%z\1-\31]", " ")
    return (s:gsub("\\", "\\\\"):gsub("'", "''"))
end

local function allowReport(account)
    local now, kept = os.time(), {}
    for _, t in ipairs(recent[account] or {}) do
        if now - t < 3600 then kept[#kept + 1] = t end
    end
    recent[account] = kept
    if #kept >= REPORTS_PER_HOUR then return false end
    kept[#kept + 1] = now
    return true
end

local function fileReport(player, text)
    text = (text or ""):gsub("^%s+", ""):gsub("%s+$", "")
    if #text < 3 then
        say(player, "Type .bug and what happened, e.g. |cffffff00.bug the quest giver in Northshire has no ! over his head|r")
        return
    end
    if #text > MAX_TEXT then text = text:sub(1, MAX_TEXT) end
    local account = player:GetAccountId()
    if not allowReport(account) then
        say(player, "Thanks! You've sent " .. REPORTS_PER_HOUR .. " reports this hour; please wait a little before the next.")
        return
    end
    CharDBExecute(string.format(
        "INSERT INTO ov_bug_reports (account_id, char_guid, char_name, level, class, map_id, zone_id, area_id, "
        .. "pos_x, pos_y, pos_z, text) VALUES (%d, %d, '%s', %d, %d, %d, %d, %d, %.2f, %.2f, %.2f, '%s')",
        account, player:GetGUIDLow(), esc(player:GetName()), player:GetLevel(), player:GetClass(),
        player:GetMapId(), player:GetZoneId(), player:GetAreaId(), player:GetX(), player:GetY(), player:GetZ(),
        esc(text)))
    say(player, "Bug report sent, thank you. We saved where you are so we can find it.")
end

local function unstick(player)
    if player:IsInCombat() then
        say(player, "You can't use .stuck in combat.")
        return
    end
    if player:IsDead() then
        say(player, "You're dead: release your spirit, or ask a party member for a resurrection.")
        return
    end
    local guid, now = player:GetGUIDLow(), os.time()
    local last = stuckAt[guid]
    if last and now - last < STUCK_COOLDOWN then
        say(player, string.format(".stuck is ready again in %d min.", math.ceil((STUCK_COOLDOWN - (now - last)) / 60)))
        return
    end
    stuckAt[guid] = now
    say(player, "Taking you home (your hearthstone location).")
    player:CastSpell(player, HEARTHSTONE_SPELL, true)
end

-- Every mount for level 80s ------------------------------------------------------------------------------------
-- The mount spells come from item_template's mount items (class 15 Miscellaneous, subclass 5 Mount), ground and
-- flying alike (the drakes, gryphons, wind riders, nether rays, rockets and machines are all subclass 5): an item
-- teaches spellid_2 when spellid_1 is the generic "learn" spell (483 or 55884), otherwise spellid_1. One query,
-- at script load. Mounts with no item (the tailoring carpets) are added by hand. Faction: AzerothCore's
-- Player::learnSpell / _addSpell check only that the spell exists (no race or faction mask; that check is only
-- for trainers, IsSpellFitByClassAndRace), so a Horde character learns Alliance mounts too and they work. Every
-- mount is learned. Class mounts (paladin, warlock, death knight) stay with their class trainers / quests.
local LEARN_SPELLS = { [483] = true, [55884] = true }
local EXTRA_MOUNTS = { 61451, 61309, 75596 } -- Flying Carpet, Magnificent Flying Carpet, Frosty Flying Carpet
local ARTISAN_RIDING, COLD_WEATHER_FLYING = 34091, 54197
local MOUNTS_PER_TICK, MOUNTS_TICK_MS = 40, 250
local MOUNTS_START_MS = 5000 -- after reaching 80 / logging in, so the boost and login lines land first

local function loadMountSpells()
    local list, seen = {}, {}
    local function add(id)
        if id and id > 0 and not LEARN_SPELLS[id] and not seen[id] then seen[id] = true; list[#list + 1] = id end
    end
    local q = WorldDBQuery("SELECT spellid_1, spellid_2 FROM item_template WHERE class = 15 AND subclass = 5 "
        .. "AND name NOT LIKE '%[PH]%' AND name NOT LIKE 'Test%' AND name NOT LIKE '%Deprecated%' "
        .. "AND name NOT LIKE '%Unused%' ORDER BY entry")
    if q then
        repeat
            local s1, s2 = q:GetUInt32(0), q:GetUInt32(1)
            if LEARN_SPELLS[s1] then add(s2) else add(s1) end
        until not q:NextRow()
    end
    for _, id in ipairs(EXTRA_MOUNTS) do add(id) end
    return list
end
local MOUNT_SPELLS = loadMountSpells()

local mountsDone = {}    -- char guid -> true once ov_unlocks says so (saves the query on later logins)
local mountsRunning = {} -- char guid -> true while learning is spread over ticks

local function mountsMarked(guid)
    if mountsDone[guid] then return true end
    local q = CharDBQuery(string.format("SELECT 1 FROM ov_unlocks WHERE guid = %d AND kind = 'mounts'", guid))
    if q then mountsDone[guid] = true end
    return mountsDone[guid] == true
end

-- Learns every mount the player lacks, MOUNTS_PER_TICK per tick, then marks the character and says one line.
local function unlockMounts(player, delay)
    local guid = player:GetGUIDLow()
    if mountsRunning[guid] then return false end
    mountsRunning[guid] = true
    local i, total = 1, #MOUNT_SPELLS
    local ticks = math.max(1, math.ceil(total / MOUNTS_PER_TICK))
    local function tick(_, _, _, p)
        if i == 1 then
            if not p:HasSpell(ARTISAN_RIDING) then p:LearnSpell(ARTISAN_RIDING) end
            if not p:HasSpell(COLD_WEATHER_FLYING) then p:LearnSpell(COLD_WEATHER_FLYING) end
        end
        local stop = math.min(total, i + MOUNTS_PER_TICK - 1)
        for k = i, stop do
            local id = MOUNT_SPELLS[k]
            if not p:HasSpell(id) then p:LearnSpell(id) end
        end
        i = stop + 1
        if i > total then
            mountsRunning[guid] = nil
            mountsDone[guid] = true
            CharDBExecute(string.format("INSERT INTO ov_unlocks (guid, kind) VALUES (%d, 'mounts') "
                .. "ON DUPLICATE KEY UPDATE done_at = CURRENT_TIMESTAMP", guid))
            say(p, "Every mount is in your spellbook (Mounts tab).")
        end
    end
    player:RegisterEvent(function(_, _, _, p)
        tick(nil, nil, nil, p)
        if i <= total then p:RegisterEvent(tick, MOUNTS_TICK_MS, ticks - 1) end
    end, delay or MOUNTS_START_MS, 1)
    return true
end

local function maybeUnlockMounts(player)
    if player:GetLevel() < 80 or mountsMarked(player:GetGUIDLow()) then return end
    unlockMounts(player)
end

local function mountsCommand(player)
    if player:GetLevel() < 80 then
        say(player, "Every mount unlocks at level 80.")
        return
    end
    local guid, now = player:GetGUIDLow(), os.time()
    local last = mountsAt[guid]
    if last and now - last < STUCK_COOLDOWN then
        say(player, string.format(".mounts is ready again in %d min.", math.ceil((STUCK_COOLDOWN - (now - last)) / 60)))
        return
    end
    if not unlockMounts(player, 500) then
        say(player, "Already learning your mounts; a moment.")
        return
    end
    mountsAt[guid] = now
end

local GUIDE = {
    "|cffffd100Level 80: where to go from here|r",
    "1. |cffffff00Dungeon Finder|r (I, or the eye on the minimap): the random dungeon at the top, then its Heroic. Bots fill "
        .. "the group in seconds, and dungeons scale to your group (autobalance).",
    "2. |cffffff00Gear|r: heroics give Emblems of Triumph; the first random dungeon each day gives extra. Spend them "
        .. "in Dalaran (the emblem quartermasters in the Silver Enclave / Sunreaver's Sanctuary).",
    "3. |cffffff00Raids|r: Naxxramas, Ulduar, Trial of the Crusader, Icecrown Citadel. Form a raid group, "
        .. "then |cffffff00.play|r > Dungeons and raids.",
    "4. |cffffff00PvP|r: |cffffff00.play|r > Arenas and battlegrounds, or the Dungeon Finder's PvP tab.",
    "5. |cffffff00Look|r: transmogrify your gear at the transmogrifier; every mount and pet is in your spellbook "
        .. "(Shift-P: Collections).",
    "6. |cffffff00Your screen|r: Esc > Mods & Workshop for UI size, every action bar, and addons. "
        .. "|cffffff00/wubars|r puts spells you just learned on your bars.",
    "7. |cffffff00Quality of life|r: |cffffff00.respec confirm|r resets your talents free, |cffffff00.hearth|r "
        .. "readies your hearthstone (hourly), |cffffff00.summon|r brings your bots to you.",
    "Hang out in Dalaran. Found a bug? |cffffff00.bug|r and what happened. All commands: |cffffff00.wu|r",
}

local function showGuide(player)
    for _, line in ipairs(GUIDE) do say(player, line) end
end

local function listCommands(player)
    say(player, "Commands: |cffffff00.boost|r (level 80 boost, new characters), |cffffff00.play|r (places and dungeons), "
        .. "|cffffff00.bug <text>|r (report a bug), |cffffff00.stuck|r (go home if stuck), "
        .. "|cffffff00.guide|r (what to do at 80), |cffffff00.mounts|r (every mount, at 80).")
    say(player, "Quality of life: |cffffff00.learnall|r (class spells; they come by themselves on level up), "
        .. "|cffffff00.respec confirm|r (free talent reset), |cffffff00.xp off|r / |cffffff00.xp on|r (freeze XP), "
        .. "|cffffff00.hearth|r (hearthstone ready, hourly), |cffffff00.summon|r (your bots), |cffffff00.qol|r (what's on).")
end

local function onCommand(event, player, command)
    if not ON or not player then return end
    local raw = (command or ""):gsub("^[%.!]", "")
    local verb, rest = raw:match("^(%S+)%s*(.*)$")
    verb = (verb or ""):lower()
    if verb == "bug" or verb == "report" then
        fileReport(player, rest)
        return false
    elseif verb == "stuck" or verb == "unstuck" then
        unstick(player)
        return false
    elseif verb == "mounts" then
        mountsCommand(player)
        return false
    elseif verb == "guide" or verb == "help80" then
        showGuide(player)
        return false
    elseif verb == "wu" or verb == "commands" then
        listCommands(player)
        return false
    end
end

local function onLogin(event, player)
    if not ON or not player then return end
    say(player, "Found a bug? Type |cffffff00.bug|r and what happened. Stuck? |cffffff00.stuck|r. All commands: |cffffff00.wu|r")
    if player:GetLevel() >= 80 then
        say(player, "At 80: |cffffff00.guide|r shows where to go (dungeons, gear, raids, PvP).")
        maybeUnlockMounts(player)
    end
end

-- Reaching 80 (levelling or the boost): the guide, a moment later so it lands after the boost's own lines.
local function onLevel(event, player, oldLevel)
    if not ON or not player or player:GetLevel() < 80 or (oldLevel or 0) >= 80 then return end
    player:RegisterEvent(function(_, _, _, p) showGuide(p) end, 4000, 1)
    maybeUnlockMounts(player)
end

RegisterPlayerEvent(42, onCommand) -- PLAYER_EVENT_ON_COMMAND
RegisterPlayerEvent(3, onLogin)    -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(13, onLevel)   -- PLAYER_EVENT_ON_LEVEL_CHANGE

-- for tests
OV_REPORTS_TEST = { esc = esc, allowReport = allowReport, fileReport = fileReport, unstick = unstick,
    onCommand = onCommand, onLevel = onLevel, GUIDE = GUIDE, MOUNT_SPELLS = MOUNT_SPELLS,
    MOUNTS_PER_TICK = MOUNTS_PER_TICK }
