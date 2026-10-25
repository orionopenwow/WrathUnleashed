-- WrathUnleashed quality of life, server half (mod-ale, AzerothCore 3.3.5a build 12340).
-- Type .qol in chat to see what is on for this realm.
--
--   Welcome message at login (realm name, .ov, .armory, .qol)
--   .qol                  what is on here, and the commands
--   .qol learn            learn every class spell you qualify for now (when auto-learn is on)
--   .qol repair           repair all gear for free (when free repair is on)
--   .qol hub [place]      teleport to a hub (Brawl): dalaran, gurubashi, maul, circle, amphitheater
--   .hub <place>          same as .qol hub; non-GM players may also type .tele <place> for these
--   .qol bots             a short how-to for grouping with playerbots
--   Auto-learn on level up, and after a duel both players get health, power and cooldowns back.
--
-- Env-var gates (read with os.getenv at each use; "1" = on, "0" = off, unset = the default shown):
--   OV_REALM_NAME     realm name shown in the welcome          default "WrathUnleashed"
--   OV_QOL_WELCOME    login welcome message                    default on
--   OV_AUTOLEARN      class spells on level up / first login   default on when OV_BRAWL=1, else off
--   OV_DUEL_RESET     restore health/power/cooldowns at duel end  default on only with OV_BRAWL=1:
--                     ResetAllCooldowns also clears the Hearthstone and long cooldowns, which
--                     only matters on a progression realm (AzerothCore master has no core
--                     duel-reset setting; mod-duel-reset would be the exact alternative).
--   OV_QOL_HUB        hub teleports (.qol hub/.hub/.tele)      default on when OV_BRAWL=1, else off
--   OV_FREE_REPAIR    .qol repair (free, anywhere, out of combat) default on when OV_BRAWL=1, else off
--   OV_QOL_BOTHELP    .qol bots help text                      default on
--   OV_BRAWL          set by the brawl profile (shared with ov_brawl.lua)
--
-- Things Lua cannot do safely, left to worldserver.conf instead:
--   free vendor repairs  -> Rate.RepairCost = 0   (no Eluna hook on the vendor repair packet)
--   instant mail         -> MailDeliveryDelay = 0 (seconds an item/COD mail waits; no Eluna hook)
--   duel reset (better)  -> ResetDuelCooldowns = 1, ResetDuelHealthMana = 1 restore the pre-duel
--                           state exactly; if you turn those on, set OV_DUEL_RESET=0.
--
-- Compatible with the other scripts: ov_services.lua owns .ov and gossip menu 61000; this file
-- uses no gossip menu at all. ov_armory.lua owns .armory and the OVARM addon prefix.
--
-- API and schema sources used (checked 2026-10-24):
--   https://www.azerothcore.org/eluna/Global/RegisterPlayerEvent.html
--       3 ON_LOGIN (event, player); 11 ON_DUEL_END (event, winner, loser, type);
--       13 ON_LEVEL_CHANGE (event, player, oldLevel); 30 ON_FIRST_LOGIN (event, player);
--       42 ON_COMMAND (event, player, command, chatHandler), player nil from console, return false
--       to stop the core handling the command.
--   https://www.azerothcore.org/eluna/Player/index.html (LearnSpell(spellId), HasSpell, HasSkill,
--       GetSkillValue, ResetAllCooldowns(), DurabilityRepairAll(takeCost, discountMod, guildBank),
--       Teleport(map, x, y, z, o), GetGMRank(), GetTeam()), Unit/SetPower.html (SetPower(amount, type)),
--       Global/index.html GetSpellInfo(id) + SpellInfo/HasEffect.html (HasEffect(effect))
--   azerothcore-wotlk src/server/game/Entities/Creature/Trainer.cpp (how a trainer teaches/casts)
--   https://github.com/azerothcore/mod-ale (the Eluna-compatible engine)
--   https://www.azerothcore.org/wiki/trainer, /wiki/trainer_spell, /wiki/creature_default_trainer,
--   /wiki/npc_trainer, and data/sql/base/db_world/{trainer,trainer_spell,npc_trainer,game_tele}.sql
--       on azerothcore-wotlk master: trainer(Id, Type, Requirement) with Type 0 = class trainer and
--       Requirement = class id; trainer_spell(TrainerId, SpellId, MoneyCost, ReqSkillLine,
--       ReqSkillRank, ReqAbility1..3, ReqLevel). The legacy npc_trainer(ID, SpellID, MoneyCost,
--       ReqSkillLine, ReqSkillRank, ReqLevel, ReqSpell) with negative SpellID template references is
--       used only when the new tables are missing.
--   Faction-only spell ids below were checked against that trainer_spell data (alliance and
--   horde class trainers 3/4, 14 and the mage portal trainers 18-29).

local TAG = "|cff66ccff[QoL]|r "

------------------------------------------------------------------------------------------------
-- env gates
------------------------------------------------------------------------------------------------
local function flag(name, default)
    local v = os.getenv(name)
    if v == "1" then return true end
    if v == "0" then return false end
    return default
end

local function isBrawl() return os.getenv("OV_BRAWL") == "1" end
local function realmName()
    local n = os.getenv("OV_REALM_NAME")
    if n and n ~= "" then return n end
    return "WrathUnleashed"
end

local function welcomeOn()  return flag("OV_QOL_WELCOME", true) end
local function autolearnOn() return flag("OV_AUTOLEARN", isBrawl()) end
local function duelResetOn() return flag("OV_DUEL_RESET", os.getenv("OV_BRAWL") == "1") end
local function hubOn()       return flag("OV_QOL_HUB", isBrawl()) end
local function repairOn()    return flag("OV_FREE_REPAIR", isBrawl()) end
local function botHelpOn()   return flag("OV_QOL_BOTHELP", true) end

local function say(player, text)
    player:SendBroadcastMessage(TAG .. text)
end

-- Call a method only if this build of mod-ale has it; never let a missing method kill the event.
local function try(obj, method, ...)
    if not obj then return nil end
    local ok, fn = pcall(function() return obj[method] end)
    if not ok or type(fn) ~= "function" then return nil end
    local ok2, a, b = pcall(fn, obj, ...)
    if ok2 then return a, b end
    return nil
end

local function sqlString(s)
    -- Only used on names from the fixed lists in this file, but escape anyway.
    s = tostring(s or ""):gsub("[^%w%s'%-]", ""):sub(1, 60)
    return (s:gsub("'", "''"))
end

------------------------------------------------------------------------------------------------
-- auto-learn class spells
------------------------------------------------------------------------------------------------
local TEAM_ALLIANCE, TEAM_HORDE = 0, 1

-- Class-trainer spells that belong to one faction. The class trainers of both factions share a
-- Requirement (class id), so without this a mage would learn every city's portal.
local FACTION_ONLY = {}
for _, id in ipairs({
    3561, 3562, 3565, 32271, 49359, 33690,       -- mage teleports: SW, IF, Darn, Exodar, Theramore, Shatt
    10059, 11416, 11419, 32266, 49360, 33691,    -- mage portals, same cities
    32182,                                        -- shaman Heroism
    31801,                                        -- paladin Seal of Vengeance
    13820, 23214,                                 -- paladin Warhorse / Charger
}) do FACTION_ONLY[id] = TEAM_ALLIANCE end
for _, id in ipairs({
    3563, 3566, 3567, 32272, 49358, 35715,       -- mage teleports: UC, TB, Org, Silvermoon, Stonard, Shatt
    11418, 11420, 11417, 32267, 49361, 35717,    -- mage portals, same cities
    2825,                                         -- shaman Bloodlust
    53736,                                        -- paladin Seal of Corruption
    34767, 34768,                                 -- paladin Thalassian Charger / Warhorse
}) do FACTION_ONLY[id] = TEAM_HORDE end

local schema          -- "trainer", "npc_trainer" or "none"; decided on first use
local classSpells = {} -- [classId] = { {id, lvl, skill, rank, r1, r2, r3}, ... } sorted by level

local function countOf(sql)
    local q = WorldDBQuery(sql)
    if not q then return 0 end
    return q:GetUInt32(0)
end

local function tableExists(name)
    return countOf(string.format(
        "SELECT COUNT(*) AS n FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = '%s'",
        sqlString(name))) > 0
end

local function columnExists(tbl, col)
    return countOf(string.format(
        "SELECT COUNT(*) AS n FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() " ..
        "AND TABLE_NAME = '%s' AND COLUMN_NAME = '%s'", sqlString(tbl), sqlString(col))) > 0
end

local function detectSchema()
    if schema then return schema end
    if tableExists("trainer") and tableExists("trainer_spell")
        and countOf("SELECT COUNT(*) AS n FROM trainer WHERE Type = 0") > 0 then
        schema = "trainer"
    elseif tableExists("npc_trainer") and columnExists("creature_template", "trainer_class")
        and columnExists("creature_template", "trainer_type") then
        schema = "npc_trainer"
    else
        schema = "none"
    end
    print("[ov_qol] auto-learn trainer schema: " .. schema)
    return schema
end

local function loadClass(classId)
    classId = math.floor(tonumber(classId) or 0)
    if classId < 1 or classId > 11 then return {} end
    if classSpells[classId] then return classSpells[classId] end

    local list, sql = {}, nil
    local s = detectSchema()
    if s == "trainer" then
        sql = string.format(
            "SELECT ts.SpellId, MIN(ts.ReqLevel) AS lvl, MAX(ts.ReqSkillLine) AS sk, MAX(ts.ReqSkillRank) AS rk, " ..
            "MAX(ts.ReqAbility1) AS r1, MAX(ts.ReqAbility2) AS r2, MAX(ts.ReqAbility3) AS r3 " ..
            "FROM trainer t JOIN trainer_spell ts ON ts.TrainerId = t.Id " ..
            "WHERE t.Type = 0 AND t.Requirement = %d AND ts.SpellId > 0 " ..
            "GROUP BY ts.SpellId ORDER BY 2, 1", classId)
    elseif s == "npc_trainer" then
        -- Rows on the class trainers themselves, plus one level of negative-SpellID template refs.
        local reqSpell = columnExists("npc_trainer", "ReqSpell") and "MAX(s.ReqSpell) AS r1" or "0"
        sql = string.format(
            "SELECT s.SpellID, MIN(s.ReqLevel) AS lvl, MAX(s.ReqSkillLine) AS sk, MAX(s.ReqSkillRank) AS rk, %s, 0, 0 " ..
            "FROM npc_trainer s WHERE s.SpellID > 0 AND (" ..
            "s.ID IN (SELECT entry FROM creature_template WHERE trainer_type = 0 AND trainer_class = %d) " ..
            "OR s.ID IN (SELECT -t.SpellID FROM npc_trainer t JOIN creature_template ct ON ct.entry = t.ID " ..
            "WHERE t.SpellID < 0 AND ct.trainer_type = 0 AND ct.trainer_class = %d)) " ..
            "GROUP BY s.SpellID ORDER BY 2, 1", reqSpell, classId, classId)
    end

    if sql then
        local q = WorldDBQuery(sql)
        if q then
            repeat
                list[#list + 1] = {
                    id = q:GetUInt32(0), lvl = q:GetUInt32(1), skill = q:GetUInt32(2), rank = q:GetUInt32(3),
                    r1 = q:GetUInt32(4), r2 = q:GetUInt32(5), r3 = q:GetUInt32(6),
                }
            until not q:NextRow()
        end
    end
    classSpells[classId] = list
    return list
end

-- Some trainer entries are "teacher" spells with a LEARN_SPELL effect (class mounts and similar):
-- a real trainer casts those, and LearnSpell on them would put the teacher spell itself in the
-- spellbook. Detect them with mod-ale's GetSpellInfo(id):HasEffect(36) and leave them to the trainer.
local SPELL_EFFECT_LEARN_SPELL = 36
local KNOWN_TEACHERS = { [13820] = true, [34768] = true } -- paladin Warhorse (A) / Thalassian Warhorse (H)
local teacherCache = {}

local function isTeacherSpell(id)
    if KNOWN_TEACHERS[id] then return true end
    if teacherCache[id] ~= nil then return teacherCache[id] end
    local result = false
    if type(GetSpellInfo) == "function" then
        local ok, info = pcall(GetSpellInfo, id)
        if ok and info then result = try(info, "HasEffect", SPELL_EFFECT_LEARN_SPELL) == true end
    end
    teacherCache[id] = result
    return result
end

local function requirementsMet(player, e, team)
    local side = FACTION_ONLY[e.id]
    if side ~= nil and side ~= team then return false end
    -- ReqAbility: the previous rank, or a talent. A talent the player doesn't have blocks the
    -- spell, which is how talent-dependent ranks (Mortal Strike 2, ...) are left out.
    for _, req in ipairs({ e.r1, e.r2, e.r3 }) do
        if req and req > 0 and not player:HasSpell(req) then return false end
    end
    if e.skill and e.skill > 0 then
        if not try(player, "HasSkill", e.skill) then return false end
        if (try(player, "GetSkillValue", e.skill) or 0) < (e.rank or 0) then return false end
    end
    return true
end

local function learnClassSpells(player, quiet)
    local level = player:GetLevel()
    local list = loadClass(player:GetClass())
    if #list == 0 then
        if not quiet then say(player, "Auto-learn has no trainer data on this realm; visit your trainer.") end
        return 0
    end
    local team = try(player, "GetTeam")
    local learned, teachers = 0, {}
    -- A few passes so a rank learned now unlocks the next rank in the same call.
    for _ = 1, 4 do
        local progress = false
        for _, e in ipairs(list) do
            if e.lvl > level then break end -- list is sorted by level
            if not player:HasSpell(e.id) and requirementsMet(player, e, team) then
                if isTeacherSpell(e.id) then
                    teachers[e.id] = true
                else
                    player:LearnSpell(e.id)
                    if player:HasSpell(e.id) then
                        learned = learned + 1
                        progress = true
                    end
                end
            end
        end
        if not progress then break end
    end
    local left = 0
    for _ in pairs(teachers) do left = left + 1 end
    if learned > 0 then
        say(player, string.format("Learned %d new class spell%s for level %d.", learned, learned == 1 and "" or "s", level))
    elseif not quiet then
        say(player, "You already know every class spell auto-learn can teach at your level.")
    end
    if left > 0 and (learned > 0 or not quiet) then
        say(player, string.format("%d more (class mounts and similar) %s from your class trainer.", left, left == 1 and "comes" or "come"))
    end
    return learned
end

local function onLevelChange(event, player, oldLevel)
    if not player or not autolearnOn() then return end
    if player:GetLevel() <= (oldLevel or 0) then return end
    learnClassSpells(player, true)
end

local function onFirstLogin(event, player)
    -- Characters that start high (the level-80 Dalaran profile) never fire a level change.
    if not player or not autolearnOn() then return end
    if player:GetLevel() > 1 then learnClassSpells(player, true) end
end

------------------------------------------------------------------------------------------------
-- duel reset
------------------------------------------------------------------------------------------------
local POWER_MANA, POWER_RAGE, POWER_ENERGY, POWER_RUNIC = 0, 1, 3, 6

local function restoreAfterDuel(player)
    if not player then return end
    if try(player, "IsDead") then return end
    local maxHp = try(player, "GetMaxHealth")
    if maxHp then try(player, "SetHealth", maxHp) end
    local ptype = try(player, "GetPowerType")
    if ptype == POWER_MANA or ptype == POWER_ENERGY then
        local maxP = try(player, "GetMaxPower", ptype)
        if maxP then try(player, "SetPower", maxP, ptype) end
    elseif ptype == POWER_RAGE or ptype == POWER_RUNIC then
        try(player, "SetPower", 0, ptype) -- back to the out-of-combat state
    end
    -- Druids in forms keep a mana pool too.
    if ptype ~= POWER_MANA then
        local maxMana = try(player, "GetMaxPower", POWER_MANA)
        if maxMana and maxMana > 0 then try(player, "SetPower", maxMana, POWER_MANA) end
    end
    try(player, "ResetAllCooldowns")
end

local function onDuelEnd(event, winner, loser, duelType)
    if not duelResetOn() then return end
    restoreAfterDuel(winner)
    restoreAfterDuel(loser)
end

------------------------------------------------------------------------------------------------
-- hub teleports (Brawl)
------------------------------------------------------------------------------------------------
-- Only these game_tele names can be reached. Coordinates are looked up in game_tele at runtime;
-- the fallback numbers are the same rows copied from azerothcore-wotlk master game_tele.sql.
local HUBS = {
    dalaran      = { label = "Dalaran",                 tele = "Dalaran",               fb = { 571, 5807.98, 588.487, 660.94, 1.66594 } },
    gurubashi    = { label = "Gurubashi Arena",         tele = "GurubashiArena",        fb = { 0, -13277.4, 127.372, 26.1418, 1.11878 } },
    maul         = { label = "The Maul (Dire Maul)",    tele = "TheMaul",               fb = { 1, -3739.86, 1093.8, 131.969, 3.09301 } },
    circle       = { label = "Circle of Blood",         tele = "CircleOfBloodArena",    fb = { 530, 2839.44, 5930.17, 11.1002, 3.16284 } },
    amphitheater = { label = "Amphitheater of Anguish", tele = "AmphitheaterOfAnguish", fb = { 571, 5754.5, -2939.17, 286.276, 5.17592 } },
}
local HUB_ORDER = { "dalaran", "gurubashi", "maul", "circle", "amphitheater" }
local HUB_ALIAS = {
    dal = "dalaran", dala = "dalaran", guru = "gurubashi", gurubashiarena = "gurubashi", stv = "gurubashi",
    diremaul = "maul", themaul = "maul", dm = "maul", circleofblood = "circle", bem = "circle",
    amph = "amphitheater", anguish = "amphitheater",
}
local HUB_COOLDOWN = 10 -- seconds
local lastHub = {}
local hubCache = {}

local function hubPosition(key)
    if hubCache[key] then return hubCache[key] end
    local hub = HUBS[key]
    local pos = hub.fb
    local q = WorldDBQuery(string.format(
        "SELECT map, position_x, position_y, position_z, orientation FROM game_tele WHERE name = '%s' LIMIT 1",
        sqlString(hub.tele)))
    if q then
        pos = { q:GetUInt32(0), q:GetFloat(1), q:GetFloat(2), q:GetFloat(3), q:GetFloat(4) }
    end
    hubCache[key] = pos
    return pos
end

local function hubList()
    local names = {}
    for _, k in ipairs(HUB_ORDER) do names[#names + 1] = k end
    return table.concat(names, ", ")
end

local function canLeave(player)
    if try(player, "IsInCombat") then return "not in combat" end
    if try(player, "IsDead") then return "not while dead" end
    if try(player, "InBattleground") or try(player, "InArena") then return "not from a battleground or arena" end
    local map = try(player, "GetMap")
    if map and (try(map, "IsBattlegroundOrArena") or try(map, "IsArena") or try(map, "IsBattleground")
        or try(map, "IsDungeon") or try(map, "IsRaid")) then
        return "not from inside an instance"
    end
    return nil
end

local function hubTeleport(player, which)
    if not hubOn() then return say(player, "Hub teleports are off on this realm.") end
    local key = HUB_ALIAS[which or ""] or which
    local hub = key and HUBS[key]
    if not hub then return say(player, "Hubs: " .. hubList() .. ".  Usage: .hub <place>") end
    local why = canLeave(player)
    if why then return say(player, "Hub teleport: " .. why .. ".") end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastHub[guid] and now - lastHub[guid] < HUB_COOLDOWN then
        return say(player, string.format("Hub teleport again in %ds.", HUB_COOLDOWN - (now - lastHub[guid])))
    end
    lastHub[guid] = now
    local p = hubPosition(key)
    say(player, "Off to " .. hub.label .. ".")
    player:Teleport(p[1], p[2], p[3], p[4], p[5])
end

------------------------------------------------------------------------------------------------
-- free repair
------------------------------------------------------------------------------------------------
local lastRepair = {}

local function freeRepair(player)
    if not repairOn() then
        return say(player, "Free repair is off here. Repair at any vendor with the anvil icon.")
    end
    if try(player, "IsInCombat") then return say(player, "Not in combat.") end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastRepair[guid] and now - lastRepair[guid] < 5 then return say(player, "Once every 5 seconds.") end
    lastRepair[guid] = now
    try(player, "DurabilityRepairAll", false) -- takeCost = false
    say(player, "All your gear is repaired, free.")
end

------------------------------------------------------------------------------------------------
-- help text
------------------------------------------------------------------------------------------------
local function onOff(b) return b and "|cff00ff00on|r" or "|cff808080off|r" end

local function showHelp(player)
    say(player, realmName() .. " quality of life:")
    say(player, "  Auto-learn class spells on level up: " .. onOff(autolearnOn()) .. (autolearnOn() and "  (.qol learn to catch up)" or ""))
    say(player, "  Duel reset (health, power, cooldowns): " .. onOff(duelResetOn()))
    say(player, "  Free repair anywhere: " .. onOff(repairOn()) .. (repairOn() and "  (.qol repair)" or ""))
    say(player, "  Hub teleports: " .. onOff(hubOn()) .. (hubOn() and ("  (.hub " .. hubList() .. ")") or ""))
    if botHelpOn() then say(player, "  Playing with bots: .qol bots") end
    say(player, "  Also: .ov (faction/race/appearance services), .armory (gear), /qol in the OVQoL addon.")
end

local function showBotHelp(player)
    if not botHelpOn() then return say(player, "Bot help is off on this realm.") end
    say(player, "Playerbots (if this realm runs them):")
    say(player, "  .playerbots bot add <name>      log in one of your own characters as a bot")
    say(player, "  .playerbots bot addclass <class> a bot of that class (if the realm allows it)")
    say(player, "  .playerbots bot remove <name>   log it out;  .playerbots bot list")
    say(player, "  Whisper or party-chat your bots: follow, stay, attack, summon, release, revive, autogear")
    say(player, "  Going AFK? Say 'stay' first so they don't wander, and 'follow' when you're back.")
end

local function showWelcome(player)
    say(player, "Welcome to |cffffd100" .. realmName() .. "|r, " .. player:GetName() .. ".")
    say(player, ".ov  free faction, race and appearance changes   |   .armory  gear search")
    say(player, ".qol  what's switched on here (auto-learn, duel reset, hubs, ...)")
end

local function onLogin(event, player)
    if player and welcomeOn() then showWelcome(player) end
end

------------------------------------------------------------------------------------------------
-- commands
------------------------------------------------------------------------------------------------
local function onCommand(event, player, command)
    if not player then return end -- console
    local text = (command or ""):gsub("^[%.!]", ""):lower()
    local words = {}
    for w in text:gmatch("%S+") do words[#words + 1] = w end
    local cmd, arg = words[1], words[2]

    if cmd == "qol" then
        if arg == nil or arg == "help" then
            showHelp(player)
        elseif arg == "learn" then
            if autolearnOn() then learnClassSpells(player, false)
            else say(player, "Auto-learn is off on this realm; visit your class trainer.") end
        elseif arg == "repair" then
            freeRepair(player)
        elseif arg == "hub" or arg == "tele" then
            hubTeleport(player, words[3])
        elseif arg == "bots" or arg == "bot" then
            showBotHelp(player)
        else
            showHelp(player)
        end
        return false
    end

    if cmd == "hub" then
        hubTeleport(player, arg)
        return false
    end

    -- .tele <hub> for ordinary players only; GMs keep the real .tele untouched.
    if cmd == "tele" and #words == 2 and hubOn() and (try(player, "GetGMRank") or 0) == 0 then
        local key = HUB_ALIAS[arg] or arg
        if HUBS[key] then
            hubTeleport(player, key)
            return false
        end
    end
end

RegisterPlayerEvent(3, onLogin)        -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(11, onDuelEnd)     -- PLAYER_EVENT_ON_DUEL_END
RegisterPlayerEvent(13, onLevelChange) -- PLAYER_EVENT_ON_LEVEL_CHANGE
RegisterPlayerEvent(30, onFirstLogin)  -- PLAYER_EVENT_ON_FIRST_LOGIN
RegisterPlayerEvent(42, onCommand)     -- PLAYER_EVENT_ON_COMMAND
