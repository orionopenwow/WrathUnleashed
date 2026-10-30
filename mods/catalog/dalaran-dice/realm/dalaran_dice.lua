-- dalaran-dice, realm part (mod-ale). The WrathUnleashed mod package template.
--
--   .dice            rolls 2d6
--   .dice 3d20       rolls three 20-sided dice (1-10 dice, 2-100 sides); ".dice d20" is 1d20
--   .dice help       shows the help
--
-- Rolls work in Dalaran only (zone 4395). Everyone within 30 yards sees the result as a system
-- message. Players with the DalaranDice addon also get it as an OVMOD addon message (ov_modapi.lua):
--   mod "dalaran-dice", name "roll", data "<name>,<count>,<sides>,<total>,<faces separated by spaces>"
-- One roll per 5 seconds per character. Every roll is stored in mod_dalaran_dice_rolls (characters DB).
--
-- Permissions (mod.json): commands (event 42), chat (messages to nearby players, OVMod.Send), db.
-- mod-ale API used: RegisterPlayerEvent 42 ON_COMMAND (return false = handled), CharDBExecute,
-- Player:GetZoneId / GetGUIDLow / GetName / GetPlayersInRange / SendBroadcastMessage.

local MOD_ID = "dalaran-dice"
local TAG = "|cff9966ff[Dice]|r "
local DALARAN_ZONE = 4395
local RANGE = 30
local COOLDOWN = 5
local DEFAULT_COUNT, DEFAULT_SIDES = 2, 6
local MAX_COUNT, MIN_SIDES, MAX_SIDES = 10, 2, 100

CharDBExecute("CREATE TABLE IF NOT EXISTS mod_dalaran_dice_rolls ("
    .. "id INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY, "
    .. "char_guid INT UNSIGNED NOT NULL, char_name VARCHAR(12) NOT NULL, "
    .. "dice TINYINT UNSIGNED NOT NULL, sides TINYINT UNSIGNED NOT NULL, total SMALLINT UNSIGNED NOT NULL, "
    .. "created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP, KEY char_guid (char_guid))")

local lastRoll = {} -- char guid -> os.time() of the last roll

local function say(player, msg) player:SendBroadcastMessage(TAG .. msg) end

-- SQL string literal body: backslash and quote escaped, control characters dropped.
local function esc(s)
    s = tostring(s or ""):gsub("[%z\1-\31]", " ")
    return (s:gsub("\\", "\\\\"):gsub("'", "''"))
end

local function help(player)
    say(player, "|cffffff00.dice|r rolls 2d6, |cffffff00.dice 3d20|r rolls three d20 (up to 10 dice, 2-100 sides). "
        .. "Everyone within " .. RANGE .. " yards sees the roll.")
end

-- "" -> 2, 6; "3d20" -> 3, 20; "d20" -> 1, 20; anything else -> nil
local function parseDice(text)
    if text == "" then return DEFAULT_COUNT, DEFAULT_SIDES end
    local count, sides = text:lower():match("^(%d*)d(%d+)$")
    if not sides then return nil end
    count, sides = tonumber(count) or 1, tonumber(sides)
    if count < 1 or count > MAX_COUNT or sides < MIN_SIDES or sides > MAX_SIDES then return nil end
    return count, sides
end

-- The roller first, then everyone else in range, each once.
local function audience(player)
    local list, seen = { player }, { [player:GetGUIDLow()] = true }
    for _, other in ipairs(player:GetPlayersInRange(RANGE) or {}) do
        local g = other:GetGUIDLow()
        if not seen[g] then
            seen[g] = true
            list[#list + 1] = other
        end
    end
    return list
end

local function roll(player, count, sides)
    local faces, total = {}, 0
    for i = 1, count do
        faces[i] = math.random(1, sides)
        total = total + faces[i]
    end
    local name = player:GetName()
    local shown = count == 1 and tostring(total) or (table.concat(faces, " + ") .. " = " .. total)
    local text = string.format("%s rolls %dd%d: |cffffff00%s|r", name, count, sides, shown)
    local data = string.format("%s,%d,%d,%d,%s", name, count, sides, total, table.concat(faces, " "))
    for _, p in ipairs(audience(player)) do
        say(p, text)
        if OVMod then OVMod.Send(p, MOD_ID, "roll", data) end
    end
    CharDBExecute(string.format(
        "INSERT INTO mod_dalaran_dice_rolls (char_guid, char_name, dice, sides, total) VALUES (%d, '%s', %d, %d, %d)",
        player:GetGUIDLow(), esc(name), count, sides, total))
end

local function onCommand(event, player, command)
    if not player then return end -- typed in the server console
    local word, rest = command:match("^(%S+)%s*(.-)%s*$")
    if not word or word:lower() ~= "dice" then return end

    if rest:lower() == "help" then
        help(player)
        return false
    end
    if player:GetZoneId() ~= DALARAN_ZONE then
        say(player, "The dice only roll in Dalaran.")
        return false
    end
    local count, sides = parseDice(rest)
    if not count then
        help(player)
        return false
    end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastRoll[guid] and now - lastRoll[guid] < COOLDOWN then
        say(player, "Wait a moment before rolling again.")
        return false
    end
    lastRoll[guid] = now
    roll(player, count, sides)
    return false
end

RegisterPlayerEvent(42, onCommand) -- PLAYER_EVENT_ON_COMMAND
