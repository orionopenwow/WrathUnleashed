-- ov_reports.lua: WrathUnleashed bug reports and small quality-of-life commands (mod-ale).
--
--   .bug <what happened>    files a bug report with where you are (map, zone, position, level), stored in
--                           acore_characters.ov_bug_reports for the GM console; .report is the same.
--   .stuck                  hearths you home when you are stuck (not in combat; once per 10 minutes).
--   .wu (or .commands)      lists the WrathUnleashed commands.
--   .guide                  the level 80 guide: what to do at 80 on this realm. Shown by itself when a
--                           character reaches 80 (the boost included); 80s get a one-line pointer at login.
--
-- Reports are rate-limited per account (REPORTS_PER_HOUR) and capped in length; the text is escaped before
-- it reaches SQL. Nothing is sent anywhere else: staff read them in the GM console or with SQL.
-- mod-ale events used: 3 ON_LOGIN, 42 ON_COMMAND (return false = handled, no "no such command").

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

local recent = {}   -- account id -> { times }
local stuckAt = {}  -- char guid -> os.time() of the last .stuck

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

local GUIDE = {
    "|cffffd100Level 80: where to go from here|r",
    "1. |cffffff00Dungeon Finder|r (I, or the eye on the minimap): Random Lich King Dungeon, then Heroic. Bots fill "
        .. "the group in seconds, and dungeons scale to your group (autobalance).",
    "2. |cffffff00Gear|r: heroics give Emblems of Triumph; the first random dungeon each day gives extra. Spend them "
        .. "in Dalaran (the emblem quartermasters in the Silver Enclave / Sunreaver's Sanctuary).",
    "3. |cffffff00Raids|r: Naxxramas, Ulduar, Trial of the Crusader, Icecrown Citadel. Form a raid group, "
        .. "then |cffffff00.play|r > Dungeons and raids.",
    "4. |cffffff00PvP|r: |cffffff00.play|r > Arenas and battlegrounds, or the Dungeon Finder's PvP tab.",
    "5. |cffffff00Look|r: transmogrify your gear at the transmogrifier; mounts and pets are in your spellbook.",
    "6. |cffffff00Your screen|r: Esc > Mods & Workshop for UI size, every action bar, and addons. "
        .. "|cffffff00/wubars|r puts spells you just learned on your bars.",
    "Hang out in Dalaran. Found a bug? |cffffff00.bug|r and what happened. All commands: |cffffff00.wu|r",
}

local function showGuide(player)
    for _, line in ipairs(GUIDE) do say(player, line) end
end

local function listCommands(player)
    say(player, "Commands: |cffffff00.boost|r (level 80 boost, new characters), |cffffff00.play|r (places and dungeons), "
        .. "|cffffff00.bug <text>|r (report a bug), |cffffff00.stuck|r (go home if stuck), "
        .. "|cffffff00.guide|r (what to do at 80).")
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
    end
end

-- Reaching 80 (levelling or the boost): the guide, a moment later so it lands after the boost's own lines.
local function onLevel(event, player, oldLevel)
    if not ON or not player or player:GetLevel() < 80 or (oldLevel or 0) >= 80 then return end
    player:RegisterEvent(function(_, _, _, p) showGuide(p) end, 4000, 1)
end

RegisterPlayerEvent(42, onCommand) -- PLAYER_EVENT_ON_COMMAND
RegisterPlayerEvent(3, onLogin)    -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(13, onLevel)   -- PLAYER_EVENT_ON_LEVEL_CHANGE

-- for tests
OV_REPORTS_TEST = { esc = esc, allowReport = allowReport, fileReport = fileReport, unstick = unstick,
    onCommand = onCommand, onLevel = onLevel, GUIDE = GUIDE }
