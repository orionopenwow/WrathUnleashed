-- WrathUnleashed quality of life, server half (mod-ale, AzerothCore 3.3.5a build 12340).
-- Type .qol in chat to see what is on for this realm.
--
--   Instant spell learn   on reaching a new level (and once at login, to catch up) a character learns every class
--                         spell and rank its class trainer teaches up to its level: no trainer visit, no gold.
--   .learnall             runs that now (once a minute; .qol learn is the same)
--   .respec confirm       resets the active spec's talents, free, with no cost escalation
--   .xp off | .xp on      freezes / resumes experience (twinks); .xp shows which
--   .hearth               clears the hearthstone cooldown (once an hour)
--   .summon               teleports the playerbots in your group to you (open world; .summon bots for GMs)
--   Rested note at login  how much rested XP is banked (below 80, XP not frozen); a frozen-XP reminder
--   Welcome message, .qol help, .qol bots, and the Brawl extras: .qol repair, .hub <place>, duel reset.
--
-- Env-var gates (read with os.getenv at each use; "1" = on, "0" = off, unset = the default shown):
--   OV_AUTOLEARN      instant spell learn (+ .learnall)         default on
--   OV_FREE_RESPEC    .respec                                   default on
--   OV_XP_TOGGLE      .xp off|on                                default on
--   OV_RESTED_NOTE    rested-XP / frozen-XP line at login       default on
--   OV_HEARTH_RESET   .hearth                                   default on
--   OV_BOT_SUMMON     .summon                                   default on
--   OV_REALM_NAME     realm name shown in the welcome           default "WrathUnleashed"
--                     (while the Leyline brand is on: OV_LEYLINE_REALM_NAME, default "Wrath Unleashed")
--   OV_QOL_WELCOME    login welcome message                     default on
--   OV_QOL_BOTHELP    .qol bots help text                       default on
--   OV_DUEL_RESET     restore health/power/cooldowns at duel end  default on only with OV_BRAWL=1
--   OV_QOL_HUB        hub teleports (.qol hub/.hub/.tele)       default on only with OV_BRAWL=1
--   OV_FREE_REPAIR    .qol repair (free, anywhere)              default on only with OV_BRAWL=1
--
-- Left to worldserver config (AC_* lines in the profile; no Lua hook for them):
--   instant mail     AC_MAIL_DELIVERY_DELAY=0       (MailDeliveryDelay, seconds an item / COD mail waits; 3600)
--   free trainer respec  AC_NO_RESET_TALENTS_COST=1 (NoResetTalentsCost: the trainer's reset costs nothing too)
--   free vendor repairs  Rate.RepairCost = 0;  duel reset ResetDuelCooldowns / ResetDuelHealthMana.
--
-- Instant spell learn: the data (azerothcore-wotlk 3f2969d, the core in realm/custom/sources.lock)
--   That core loads trainers from the newer tables: trainer(Id, Type, Requirement), Type 0 = class trainer and
--   Requirement = class id (ids 1-34; Type 3 = the pet trainers 125/126, never read here), and
--   trainer_spell(TrainerId, SpellId, MoneyCost, ReqSkillLine, ReqSkillRank, ReqAbility1..3, ReqLevel).
--   Trainer::TeachSpell learns SpellId directly unless its spell has a LEARN_SPELL effect (IsCastable), in
--   which case it casts it. In the class data SpellId is the learned spell for every row but the two paladin
--   level-20 mounts: 13820 teaches Summon Warhorse 13819 (the Charger row 23214 has ReqAbility1 = 13819) and
--   34768 teaches Summon Thalassian Warhorse 34769 (Thalassian Charger 34767 needs 34769). TEACHES maps those.
--   The older npc_trainer(ID, SpellID, ..., ReqLevel, ReqSpell) with negative SpellID = "the rows of npc_trainer
--   ID -SpellID" (class from creature_template.trainer_class / trainer_type 0) is used only when trainer /
--   trainer_spell are missing; there SpellID can be a teach spell too (the old loader read the learned spell from
--   the spell's effects), and ReqLevel 0 meant "the spell's level", which Lua can't read, so those rows are left
--   out. mod-ale's SpellInfo has HasEffect but no trigger-spell getter: any other teach spell (HasEffect(36))
--   that TEACHES does not map is skipped and logged once, never learned itself (that would put the teaching
--   spell in the spellbook).
--   Rules (as Trainer::GetDefaultSpellState): ReqLevel <= level; ReqAbility1..3 known (previous ranks and
--   talents: Mortal Strike rank 2 needs the talent, so a warrior without it never gets it); the previous rank
--   (world spell_ranks) known; no profession or riding spells (ReqSkillLine set, the riding ids, or
--   SpellInfo:IsProfessionOrRiding); spells of the other faction left out (FACTION_ONLY: the trainers of both
--   factions share the class Requirement). One query at script load, cached per class.
--   Learning is spread over ticks (player:RegisterEvent, LEARN_BATCH spells a tick) so a login at 80 doesn't stall.
--
-- mod-ale API (84b85cc: LuaFunctions.cpp, methods/*.h): RegisterPlayerEvent 3 LOGIN, 11 DUEL_END, 13 LEVEL_CHANGE
--   (event, player, oldLevel), 42 COMMAND (return false = handled); Player:LearnSpell, HasSpell, ResetTalents(noCost)
--   (resetTalents + SendTalentsInfoData), SetPlayerFlag / RemovePlayerFlag, Object:HasFlag(150 = PLAYER_FLAGS,
--   flag), GetRestBonus, ResetSpellCooldown(spell, update), HasSpellCooldown, GetGroup + Group:GetMembers,
--   Teleport, GetGMRank, GetAccountId, GetAccountName, InBattleground, InArena; GetSpellInfo(id):HasEffect /
--   IsProfessionOrRiding. Player::GiveXP returns at once with PLAYER_FLAGS_NO_XP_GAIN (0x02000000) set, the
--   flag the core's Experience Eliminator uses; it is saved with the character (characters.playerFlags).
--
-- Compatible with the other scripts: ov_services.lua owns .ov and gossip menu 61000; this file uses no gossip
-- menu. ov_main.lua's boost (SetLevel 80) teaches its own spells; the level change here then finds nothing to
-- learn and says nothing.

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
    -- the Leyline brand switch (ov_modapi.lua OVMod.Brand, realm/brand.sh): OVMod.OFFICIAL_NAME while it is on
    local m = rawget(_G, "OVMod")
    if m and m.Brand then return m.Brand().realm end
    if os.getenv("OV_LEYLINE_BRAND") == "1" then
        local b = os.getenv("OV_LEYLINE_REALM_NAME")
        return (b and b ~= "") and b or "Wrath Unleashed"   -- ov_modapi.lua OVMod.OFFICIAL_NAME
    end
    local n = os.getenv("OV_REALM_NAME")
    if n and n ~= "" then return n end
    return "WrathUnleashed"
end

local function welcomeOn()   return flag("OV_QOL_WELCOME", true) end
local function autolearnOn() return flag("OV_AUTOLEARN", true) end
local function respecOn()    return flag("OV_FREE_RESPEC", true) end
local function xpToggleOn()  return flag("OV_XP_TOGGLE", true) end
local function restedOn()    return flag("OV_RESTED_NOTE", true) end
local function hearthOn()    return flag("OV_HEARTH_RESET", true) end
local function summonOn()    return flag("OV_BOT_SUMMON", true) end
local function duelResetOn() return flag("OV_DUEL_RESET", isBrawl()) end
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
    s = tostring(s or ""):gsub("[^%w%s'%-_]", ""):sub(1, 60)
    return (s:gsub("'", "''"))
end

local function isBot(player)
    if try(player, "IsBot") == true or try(player, "IsPlayerbot") == true then return true end
    local name = try(player, "GetAccountName")
    return type(name) == "string" and name:upper():find("^RNDBOT") ~= nil
end

local MAX_LEVEL = 80

------------------------------------------------------------------------------------------------
-- instant spell learn
------------------------------------------------------------------------------------------------
local TEAM_ALLIANCE, TEAM_HORDE = 0, 1

-- Class-trainer spells that belong to one faction (checked against trainer_spell: alliance and horde class
-- trainers 3/4, 14 and the mage portal trainers 18-29). Without this a mage would learn every city's portal.
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

-- Teach spells in the class trainer data -> the spell they teach (see the header).
local TEACHES = { [13820] = 13819, [34768] = 34769 }
local RIDING = { [33388] = true, [33391] = true, [34090] = true, [34091] = true, [54197] = true }
local SPELL_EFFECT_LEARN_SPELL = 36

local LEARN_BATCH, LEARN_TICK_MS = 25, 150
local LEARN_LOGIN_DELAY_MS, LEARN_LEVEL_DELAY_MS = 3000, 1000
local LEARN_MAX_TICKS = 60
local LEARNALL_COOLDOWN = 60

local schema = "none"      -- "trainer", "npc_trainer" or "none"
local classSpells = {}     -- [classId] = { { id, lvl, skill, r1, r2, r3, prev }, ... } sorted by level

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

-- The previous rank of a spell (spell_ranks): one join, part of the same query.
local PREV_JOIN = "LEFT JOIN spell_ranks sr ON sr.spell_id = %s " ..
    "LEFT JOIN spell_ranks sp ON sp.first_spell_id = sr.first_spell_id AND sp.`rank` = sr.`rank` - 1 "

local function spellsQuery()
    if tableExists("trainer") and tableExists("trainer_spell") then
        schema = "trainer"
        return "SELECT t.Requirement AS cls, ts.SpellId AS id, MIN(ts.ReqLevel) AS lvl, MAX(ts.ReqSkillLine) AS sk, " ..
            "MAX(ts.ReqAbility1) AS r1, MAX(ts.ReqAbility2) AS r2, MAX(ts.ReqAbility3) AS r3, MAX(sp.spell_id) AS prev " ..
            "FROM trainer t JOIN trainer_spell ts ON ts.TrainerId = t.Id " .. string.format(PREV_JOIN, "ts.SpellId") ..
            "WHERE t.Type = 0 AND t.Requirement BETWEEN 1 AND 11 AND ts.SpellId > 0 " ..
            "GROUP BY t.Requirement, ts.SpellId ORDER BY 1, 3, 2"
    end
    if tableExists("npc_trainer") and columnExists("creature_template", "trainer_class")
        and columnExists("creature_template", "trainer_type") then
        schema = "npc_trainer"
        local reqSpell = columnExists("npc_trainer", "ReqSpell") and "MAX(s.ReqSpell)" or "0"
        -- Rows on the class trainers themselves, plus one level of negative-SpellID references.
        return "SELECT c.cls AS cls, s.SpellID AS id, MIN(s.ReqLevel) AS lvl, MAX(s.ReqSkillLine) AS sk, " ..
            reqSpell .. " AS r1, 0 AS r2, 0 AS r3, MAX(sp.spell_id) AS prev FROM npc_trainer s JOIN (" ..
            "SELECT ct.entry AS tid, ct.trainer_class AS cls FROM creature_template ct " ..
            "WHERE ct.trainer_type = 0 AND ct.trainer_class BETWEEN 1 AND 11 " ..
            "UNION SELECT -t.SpellID AS tid, ct.trainer_class AS cls FROM npc_trainer t " ..
            "JOIN creature_template ct ON ct.entry = t.ID " ..
            "WHERE t.SpellID < 0 AND ct.trainer_type = 0 AND ct.trainer_class BETWEEN 1 AND 11" ..
            ") c ON c.tid = s.ID " .. string.format(PREV_JOIN, "s.SpellID") ..
            "WHERE s.SpellID > 0 AND s.ReqLevel > 0 GROUP BY c.cls, s.SpellID ORDER BY 1, 3, 2"
    end
    schema = "none"
    return nil
end

local function loadSpells()
    local ok, sql = pcall(spellsQuery)
    if not ok then schema, sql = "none", nil end
    local rows = 0
    if sql then
        local okq, q = pcall(WorldDBQuery, sql)
        if okq and q then
            repeat
                local cls = q:GetUInt32(0)
                classSpells[cls] = classSpells[cls] or {}
                local list = classSpells[cls]
                list[#list + 1] = { id = q:GetUInt32(1), lvl = q:GetUInt32(2), skill = q:GetUInt32(3),
                    r1 = q:GetUInt32(4), r2 = q:GetUInt32(5), r3 = q:GetUInt32(6), prev = q:GetUInt32(7) }
                rows = rows + 1
            until not q:NextRow()
        end
    end
    print(string.format("[ov_qol] instant spell learn: trainer schema %s, %d class spells", schema, rows))
end
loadSpells()

local infoCache = {}   -- [spellId] = { teach = bool, profOrRiding = bool }
local warned = {}
local function spellFacts(id)
    local f = infoCache[id]
    if f then return f end
    f = { teach = false, profOrRiding = false }
    if type(GetSpellInfo) == "function" then
        local ok, info = pcall(GetSpellInfo, id)
        if ok and info then
            f.teach = try(info, "HasEffect", SPELL_EFFECT_LEARN_SPELL) == true
            f.profOrRiding = try(info, "IsProfessionOrRiding") == true
        end
    end
    infoCache[id] = f
    return f
end

-- The spell this row makes the character know, or nil when it is left out for everyone.
local function targetOf(e)
    if TEACHES[e.id] then return TEACHES[e.id] end
    if RIDING[e.id] or (e.skill or 0) > 0 then return nil end
    local f = spellFacts(e.id)
    if f.profOrRiding then return nil end
    if f.teach then
        if not warned[e.id] then
            warned[e.id] = true
            print(string.format("[ov_qol] trainer spell %d teaches another spell (no mapping here): left to the trainer", e.id))
        end
        return nil
    end
    return e.id
end

local function requirementsMet(player, e, team)
    local side = FACTION_ONLY[e.id]
    if side ~= nil and side ~= team then return false end
    for _, req in ipairs({ e.r1, e.r2, e.r3, e.prev }) do
        if req and req > 0 and not player:HasSpell(req) then return false end
    end
    return true
end

local learning = {}    -- [guid] = true while a run is spread over ticks
local learnAgain = {}  -- [guid] = true when a level came in during a run
local learnAllAt = {}  -- [guid] = os.time() of the last .learnall

-- Learns up to LEARN_BATCH spells; returns how many (0 = nothing left).
local function learnBatch(player, list, tried, team)
    local level, n = player:GetLevel(), 0
    for _, e in ipairs(list) do
        if e.lvl > level or n >= LEARN_BATCH then break end   -- sorted by level
        local id = targetOf(e)
        if id and not tried[id] and not player:HasSpell(id) and requirementsMet(player, e, team) then
            tried[id] = true
            player:LearnSpell(id)
            if player:HasSpell(id) then n = n + 1 end
        end
    end
    return n
end

-- why: "level", "login" (quiet when nothing is new) or "command" (always answers)
local function startLearn(player, why, delay)
    local guid = player:GetGUIDLow()
    if learning[guid] then
        if why == "level" then learnAgain[guid] = true end
        return false
    end
    local list = classSpells[player:GetClass()]
    if not list or #list == 0 then
        if why == "command" then say(player, "Instant spell learn has no trainer data on this realm; visit your trainer.") end
        return false
    end
    learning[guid] = true
    local tried, learned, ticks = {}, 0, 0
    local team = try(player, "GetTeam")
    local function tick(_, _, _, p)
        if not p then learning[guid] = nil; return end
        ticks = ticks + 1
        local ok, n = pcall(learnBatch, p, list, tried, team)
        if not ok then
            print("[ov_qol] instant spell learn failed: " .. tostring(n))
            n = 0
        end
        learned = learned + n
        if n > 0 and ticks < LEARN_MAX_TICKS then
            p:RegisterEvent(tick, LEARN_TICK_MS, 1)
            return
        end
        learning[guid] = nil
        if learned > 0 then
            say(p, string.format("You learned %d new spell%s for level %d.", learned, learned == 1 and "" or "s", p:GetLevel()))
        elseif why == "command" then
            say(p, string.format("You already know every class spell for level %d.", p:GetLevel()))
        end
        if learnAgain[guid] then
            learnAgain[guid] = nil
            startLearn(p, "level", LEARN_TICK_MS)
        end
    end
    player:RegisterEvent(tick, delay or LEARN_TICK_MS, 1)
    return true
end

local function learnAllCommand(player)
    if not autolearnOn() then return say(player, "Instant spell learn is off on this realm; visit your class trainer.") end
    local guid, now = player:GetGUIDLow(), os.time()
    if learning[guid] then return say(player, "Already learning your spells; a moment.") end
    local last = learnAllAt[guid]
    if last and now - last < LEARNALL_COOLDOWN then
        return say(player, string.format(".learnall is ready again in %d s.", LEARNALL_COOLDOWN - (now - last)))
    end
    learnAllAt[guid] = now
    startLearn(player, "command", LEARN_TICK_MS)
end

local function onLevelChange(event, player, oldLevel)
    if not player or not autolearnOn() or isBot(player) then return end
    if player:GetLevel() <= (oldLevel or 0) then return end
    startLearn(player, "level", LEARN_LEVEL_DELAY_MS)
end

------------------------------------------------------------------------------------------------
-- free respec
------------------------------------------------------------------------------------------------
local respecAt = {}
local RESPEC_COOLDOWN = 10

local function inInstance(player)
    if try(player, "InBattleground") or try(player, "InArena") then return true end
    local map = try(player, "GetMap")
    return map ~= nil and (try(map, "IsBattlegroundOrArena") or try(map, "IsDungeon") or try(map, "IsRaid")) == true
end

local function respecCommand(player, arg)
    if not respecOn() then return say(player, "Free respec is off on this realm; reset talents at your class trainer.") end
    if arg ~= "confirm" then
        return say(player, "|cffffff00.respec confirm|r resets the talents of your active spec, free. Spend them again with N.")
    end
    if try(player, "IsInCombat") then return say(player, "Not in combat.") end
    if inInstance(player) then return say(player, "Not inside a dungeon, raid, battleground or arena.") end
    local guid, now = player:GetGUIDLow(), os.time()
    if respecAt[guid] and now - respecAt[guid] < RESPEC_COOLDOWN then return say(player, "A moment between resets.") end
    respecAt[guid] = now
    player:ResetTalents(true)   -- noCost: no gold, and the trainer's cost doesn't go up
    say(player, "Your talents are reset, free. Press N to spend them.")
end

------------------------------------------------------------------------------------------------
-- .xp off | on
------------------------------------------------------------------------------------------------
local PLAYER_FLAGS = 150                    -- UpdateFields.h: UNIT_END (148) + 2
local PLAYER_FLAGS_NO_XP_GAIN = 0x02000000

local function xpFrozen(player)
    return try(player, "HasFlag", PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN) == true
end

local function xpCommand(player, arg)
    if not xpToggleOn() then return say(player, "The XP toggle is off on this realm.") end
    if arg == "off" or arg == "freeze" or arg == "stop" then
        player:SetPlayerFlag(PLAYER_FLAGS_NO_XP_GAIN)
        say(player, string.format("Experience frozen at level %d. |cffffff00.xp on|r to level again.", player:GetLevel()))
    elseif arg == "on" or arg == "resume" then
        player:RemovePlayerFlag(PLAYER_FLAGS_NO_XP_GAIN)
        say(player, "Experience is on again.")
    else
        say(player, "Experience is " .. (xpFrozen(player) and "|cffff8000frozen|r" or "on") ..
            ".  |cffffff00.xp off|r freezes it (twinks), |cffffff00.xp on|r resumes.")
    end
end

------------------------------------------------------------------------------------------------
-- .hearth
------------------------------------------------------------------------------------------------
local HEARTHSTONE_SPELL = 8690
local HEARTH_COOLDOWN = 3600
local hearthAt = {}

local function hearthCommand(player)
    if not hearthOn() then return say(player, "The hearthstone reset is off on this realm.") end
    if try(player, "IsInCombat") then return say(player, "Not in combat.") end
    if try(player, "HasSpellCooldown", HEARTHSTONE_SPELL) == false then
        return say(player, "Your hearthstone is ready already.")
    end
    local guid, now = player:GetGUIDLow(), os.time()
    local last = hearthAt[guid]
    if last and now - last < HEARTH_COOLDOWN then
        return say(player, string.format(".hearth is ready again in %d min.", math.ceil((HEARTH_COOLDOWN - (now - last)) / 60)))
    end
    hearthAt[guid] = now
    player:ResetSpellCooldown(HEARTHSTONE_SPELL, true)
    say(player, "Your hearthstone is ready. (.hearth again in an hour.)")
end

------------------------------------------------------------------------------------------------
-- .summon (your group's bots)
------------------------------------------------------------------------------------------------
local SUMMON_COOLDOWN = 30
local summonAt = {}

-- A bot of this player: a random bot, or one of the player's own characters logged in as a bot (a person
-- can't have two characters of one account online, so any other one on the same account is a bot).
local function isBotOf(player, m)
    if isBot(m) then return true end
    return try(m, "GetAccountId") == player:GetAccountId()
end

local function summonCommand(player)
    if not summonOn() then return say(player, "Bot summon is off on this realm.") end
    local group = try(player, "GetGroup")
    if not group then return say(player, "You're not in a group. Invite bots first (.qol bots).") end
    if try(player, "IsInCombat") then return say(player, "Not in combat.") end
    if try(player, "IsDead") then return say(player, "Not while dead.") end
    if inInstance(player) then return say(player, "Only in the open world (in dungeons, say 'summon' in party chat).") end
    local guid, now = player:GetGUIDLow(), os.time()
    if summonAt[guid] and now - summonAt[guid] < SUMMON_COOLDOWN then
        return say(player, string.format(".summon is ready again in %d s.", SUMMON_COOLDOWN - (now - summonAt[guid])))
    end
    local n = 0
    for _, m in ipairs(try(group, "GetMembers") or {}) do
        if m ~= player and m:GetGUIDLow() ~= guid and isBotOf(player, m)
            and not try(m, "IsInCombat") and not try(m, "IsDead") then
            m:Teleport(player:GetMapId(), player:GetX(), player:GetY(), player:GetZ(), player:GetO())
            n = n + 1
        end
    end
    if n == 0 then return say(player, "No bots in your group to summon (bots in combat or dead stay put).") end
    summonAt[guid] = now
    say(player, string.format("Summoned %d bot%s.", n, n == 1 and "" or "s"))
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
-- free repair (Brawl)
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
-- help text, login
------------------------------------------------------------------------------------------------
local function onOff(b) return b and "|cff00ff00on|r" or "|cff808080off|r" end

local function showHelp(player)
    say(player, realmName() .. " quality of life:")
    say(player, "  Instant spell learn on level up: " .. onOff(autolearnOn()) .. (autolearnOn() and "  (.learnall to catch up)" or ""))
    say(player, "  Free respec: " .. onOff(respecOn()) .. (respecOn() and "  (.respec confirm)" or ""))
    say(player, "  XP toggle: " .. onOff(xpToggleOn()) .. (xpToggleOn() and "  (.xp off / .xp on)" or ""))
    say(player, "  Hearthstone reset: " .. onOff(hearthOn()) .. (hearthOn() and "  (.hearth, hourly)" or ""))
    say(player, "  Summon your bots: " .. onOff(summonOn()) .. (summonOn() and "  (.summon)" or ""))
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
    say(player, ".qol  what's switched on here (instant spell learn, .respec, .xp, .hearth, .summon, ...)")
end

-- One line at login: XP frozen, or the rested XP banked (below 80 only).
local function restedNote(player)
    if not restedOn() or player:GetLevel() >= MAX_LEVEL then return end
    if xpToggleOn() and xpFrozen(player) then
        return say(player, "Your experience is frozen (|cffffff00.xp on|r to level again).")
    end
    local rest = math.floor(tonumber(try(player, "GetRestBonus")) or 0)
    if rest > 0 then
        say(player, string.format("Rested: %d bonus XP banked; kills give double XP until it is used up.", rest))
    end
end

local function onLogin(event, player)
    if not player or isBot(player) then return end
    if welcomeOn() then showWelcome(player) end
    restedNote(player)
    if autolearnOn() then startLearn(player, "login", LEARN_LOGIN_DELAY_MS) end
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
            learnAllCommand(player)
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
    elseif cmd == "learnall" then
        learnAllCommand(player)
        return false
    elseif cmd == "respec" then
        respecCommand(player, arg)
        return false
    elseif cmd == "xp" then
        xpCommand(player, arg)
        return false
    elseif cmd == "hearth" then
        hearthCommand(player)
        return false
    elseif cmd == "summon" then
        -- GMs keep the core's .summon <name>; .summon bots is this one for everyone.
        local gm = (try(player, "GetGMRank") or 0) > 0
        if arg == "bots" or (#words == 1 and not gm) then
            summonCommand(player)
            return false
        end
        return
    elseif cmd == "hub" then
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
RegisterPlayerEvent(42, onCommand)     -- PLAYER_EVENT_ON_COMMAND

-- for tests/test_ov_qol.lua (read only)
OV_QOL_TEST = { classSpells = classSpells, schema = function() return schema end, TEACHES = TEACHES,
    LEARN_BATCH = LEARN_BATCH, PLAYER_FLAGS = PLAYER_FLAGS, NO_XP = PLAYER_FLAGS_NO_XP_GAIN }
