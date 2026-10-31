-- ov_companions.lua: Companions, bot party members for dungeons and 10-player raids (mod-ale, 3.3.5a).
-- Players always see them called bots.
--
--   .companions                     help, your bots and the limits (.companions list is the same)
--   .companions alts                the other characters on your account you can bring as bots
--   .companions save                remembers the alts with you as your usual party (per account)
--   .recruit party                  fills a 5-player group: 1 tank, 1 healer, damage
--   .recruit raid                   fills a 10-player raid: 2 tanks, 3 healers, 5 damage (minus the roles the
--                                   group already has), converting the party to a raid
--   .recruit tank|healer|dps [n]    recruits n (default 1); .recruit dps mage picks the class
--   .recruit alt <name>             one of your own characters, with its own gear, spec and level
--   .recruit usual                  brings back the alts saved with .companions save
--   .buddy [class]                  one levelling buddy: your level, follows you, re-matched when you level up
--   .dismiss [name|all]             sends bots home (alts too)
--
-- Owner decisions (final): 10-player raids only (25 behind OV_COMPANIONS_RAID25, off); bots ALWAYS pass on
-- loot, alts included. The rolls are decided by mod-playerbots' global loot keys, set in the realm profile
-- (realm/serverpass.sh, profiles/main.env): Playerbots.LootNeedRollLevel = 0 turns every NEED into PASS,
-- LootGreedRollLevel = 0 turns every GREED into PASS, LootRollDisenchant = 0 (no disenchant votes),
-- LootRollRecipe = 0, FreeMethodLoot = 0 (no looting under free-for-all). Under master loot and free-for-all
-- the bots always vote PASS (LootRollAction.cpp, e88cc40). Per bot, on arrival, we also whisper "ll normal"
-- (the bot's own loot list setting: an alt may carry "all" from an earlier session). What can't be
-- prevented: items below the group's loot threshold (grey and white by default) go round-robin, and a bot
-- picks up its turn's share like any member. Free-for-all avoids that: bots never loot under it.
--
-- This drives mod-playerbots (the realm image's core is its fork, custom/sources.lock); none of the bot AI is
-- here. Everything goes through the player's own chat commands (Player:RunCommand, run as if typed, with the
-- player's own security) and whispers to the bot (Player:Whisper reaches mod-playerbots' OnPlayerCanUseChat):
--   .playerbots bot addclass <class>    an addclass-pool character of the player's faction logs in, is levelled
--                                       and geared to the player when 4+ levels apart, and joins the player's
--                                       group (a 6th member converts the party to a raid; PlayerbotMgr.cpp)
--   .playerbots bot add <name>          an alt of the player's own account logs in as a bot (AllowAccountBots)
--   .playerbots bot init=auto <name>    re-levels / re-gears an addclass bot to the player (gear-score capped)
--   .playerbots bot remove <name>       logs it out
--   whisper "talents spec <premade>"    the role's premade spec (Playerbots.PremadeSpecName.<class>.<n>)
--   whisper "maintenance", "autogear"   spells, talents, consumables, repairs; gear up to AutoGearQualityLimit
--   whisper "summon", "follow", "ll normal"
-- Alts keep their own gear, spec and level: they get no init=auto, talents, maintenance or autogear.
-- The bot logs in asynchronously, so .recruit only queues; a timer on the player (every 2 s, 8 times) claims the
-- bots that join the group, brings them over, matches the level, sets the spec.
-- Recruits that never arrive (no free character of that class in the pool) expire with a message.
--
-- Where: not in battlegrounds or arenas, not while dead or in combat. Inside a dungeon or raid only while
-- nobody in the group is in combat (refill a slot between pulls); there a bot on the same map and instance
-- is moved to the player, any other is fetched with mod-playerbots' own "summon".
--
-- Without mod-playerbots (the stock image: no Player:IsPlayerbot method) every command answers "coming soon";
-- realm/companions-README.md lists what the build needs.
--
-- Talking to a bot: through its own PlayerbotAI:HandleCommand(CHAT_MSG_WHISPER, text, owner) when mod-ale has it
-- (the same queue a whisper reaches, without the "To <bot>: maintenance" lines in the owner's chat), else
-- Player:Whisper. Strategy switches (passive, crowd control, assist) use PlayerbotAI:ChangeStrategy, which says
-- nothing back. Never remove group members from Lua (see dismissCommand).
--
-- Who owns a bot survives a crash or a script reload: the bots in the player's group whose PlayerbotAI master is
-- the player are adopted back (adopt, on every command and 15 s after login); without GetBotAI, the table
-- mod_companions_owned (bot guid -> owner) decides. Rows go on dismiss and on a normal logout.
--
-- The Bots window (WrathUnleashedUI/Companions.lua, /companions, /comp) talks over the OVMOD channel
-- (ov_modapi.lua), mod "wucomp". Nothing goes through chat. Every request is checked here: the bot must be the
-- player's own, heavy orders wait for the end of combat, and each has a cooldown.
--   client -> server   roster                                  send me my bots
--                      order <what> <name|all>                 what: follow stay attack passive active assist
--                                                              noassist cc nocc
--                      formation <near|melee|line|circle|arrow|shield|queue|chaos>
--                      prepare                                 maintenance, autogear (not alts), rebuff
--                      fill <party|raid>  usual  dismiss <name|all>
--                      spec <name>\t<premade spec>             role <name> <tank|healer|dps>   gear <name>
--   server -> client   roster  H\t<count>\t<cap>\t<raid 0|1>\t<formation>\t<assist 0|1>\t<cc 0|1>
--                              B\t<name>\t<class id>\t<role>\t<kind bot|alt|buddy>\t<spec>\t<item level>\t<status>\t<level>
--                              S\t<class id>\t<spec>=<role>,...     (the realm's premade specs per class present)
--                      msg <text>                              the answer the chat would have had
-- After a window request, the answers to it (and the arrivals it starts) go to the window, not the chat; a typed
-- command switches them back to the chat.
--
-- Env (os.getenv at each use; "1" on, "0" off):
--   OV_COMPANIONS                 on/off                                                   default 1
--   OV_COMPANIONS_PER_PLAYER      bots one player may have in a party (buddy, alts included) default 4
--   OV_COMPANIONS_PER_PLAYER_RAID bots one player may have in a raid group                 default 9
--   OV_COMPANIONS_REALM_MAX       bots on the whole realm at once                          default 60
--   OV_COMPANIONS_GROUP_MAX       the largest group .recruit fills (5..10; ..25 with RAID25) default 10
--   OV_COMPANIONS_RAID25          1 lets .recruit raid 25 fill a 25-player raid            default 0
--   OV_COMPANIONS_COOLDOWN        seconds between two .recruit / .buddy                    default 30
--   OV_COMPANIONS_BUDDY           .buddy on/off                                            default 1
-- mod-playerbots' own Playerbots.MaxAddedBots (AC_PLAYERBOTS_MAX_ADDED_BOTS, 9) is the hard cap behind these.
-- Characters database: mod_companions_usual (account, slot, guid, name, saved_at) and mod_companions_owned
-- (bot, owner, name, role, spec, kind, at), made here if missing.
-- mod-ale events: 3 ON_LOGIN, 4 ON_LOGOUT, 13 ON_LEVEL_CHANGE, 42 ON_COMMAND (return false = handled).
--
-- Achievement lines ("<bot> has earned the achievement ...") come from the core (AchievementMgr::
-- SendAchievementEarned tells everyone in say range) when a bot is levelled, geared and taught spells and mounts
-- (init=auto, maintenance). Neither mod-playerbots (e88cc40) nor mod-ale can stop the line before it is sent, so
-- the Bots window's addon hides achievement lines from the player's own bots on the player's screen.

local OVMod
do
    -- ALE loads scripts in name order, so ov_modapi.lua has not run yet: require loads it once. Without it the
    -- window is off; every chat command still works.
    local ok, m = pcall(function() return require("ov_modapi") end)
    OVMod = (ok and type(m) == "table" and m) or _G.OVMod
end
local MOD = "wucomp"

local TAG = "|cff66ccff[Bots]|r "

------------------------------------------------------------------------------------------------
-- env
------------------------------------------------------------------------------------------------
local function flag(name, default)
    local v = os.getenv(name)
    if v == "1" then return true end
    if v == "0" then return false end
    return default
end

local function num(name, default, lo, hi)
    local v = tonumber(os.getenv(name) or "")
    if not v then v = default end
    v = math.floor(v)
    if v < lo then v = lo end
    if v > hi then v = hi end
    return v
end

local function onSwitch()      return flag("OV_COMPANIONS", true) end
local function buddyOn()       return flag("OV_COMPANIONS_BUDDY", true) end
local function raid25()        return flag("OV_COMPANIONS_RAID25", false) end
local function raidSizeMax()   return raid25() and 25 or 10 end
local function perPlayer()     return num("OV_COMPANIONS_PER_PLAYER", 4, 0, 4) end
local function perPlayerRaid() return num("OV_COMPANIONS_PER_PLAYER_RAID", 9, 0, raidSizeMax() - 1) end
local function realmMax()      return num("OV_COMPANIONS_REALM_MAX", 60, 0, 2000) end
local function groupMax()      return num("OV_COMPANIONS_GROUP_MAX", 10, 2, raidSizeMax()) end
local function cooldown()      return num("OV_COMPANIONS_COOLDOWN", 30, 0, 3600) end

local PARTY = 5

local replyTo = {}   -- [ownerGuid] = true while the answers go to the Bots window

local function say(player, text)
    if replyTo[player:GetGUIDLow()] and OVMod then
        OVMod.Send(player, MOD, "msg", text)
        return
    end
    player:SendBroadcastMessage(TAG .. text)
end

local function try(obj, method, ...)
    if not obj then return nil end
    local ok, fn = pcall(function() return obj[method] end)
    if not ok or type(fn) ~= "function" then return nil end
    local ok2, a, b = pcall(fn, obj, ...)
    if ok2 then return a, b end
    return nil
end

local function hasMethod(obj, method)
    local ok, fn = pcall(function() return obj[method] end)
    return ok and type(fn) == "function"
end

-- mod-ale registers IsPlayerbot only when built with MOD_PLAYERBOTS.
local function botsBuilt(player) return hasMethod(player, "IsPlayerbot") and hasMethod(player, "RunCommand") end

-- The bot's PlayerbotAI (mod-ale's Player:GetBotAI), or nil.
local function botAI(m)
    local ai = try(m, "GetBotAI")
    if type(ai) ~= "table" and type(ai) ~= "userdata" then return nil end
    return ai
end

local CHAT_MSG_WHISPER = 7
local BOT_STATE_COMBAT, BOT_STATE_NON_COMBAT = 0, 1

local function isBot(p)
    if try(p, "IsPlayerbot") == true or try(p, "IsBot") == true then return true end
    local name = try(p, "GetAccountName")
    return type(name) == "string" and name:upper():find("^RNDBOT") ~= nil
end

-- A bot of the addclass pool (what .recruit <role> makes); alt bots of the player's own account are not.
local function isAddclassBot(owner, m)
    local v = try(m, "IsAddclassBot")
    if v ~= nil then return v == true end
    return isBot(m) and try(m, "GetAccountId") ~= owner:GetAccountId()
end

local function inPvp(player)
    if try(player, "InBattleground") or try(player, "InArena") then return true end
    local map = try(player, "GetMap")
    return map ~= nil and (try(map, "IsBattlegroundOrArena") or try(map, "IsBattleground") or try(map, "IsBattleArena")) == true
end

-- "dungeon", "raid" or nil (open world)
local function instanceKind(player)
    local map = try(player, "GetMap")
    if not map then return nil end
    if try(map, "IsRaid") == true then return "raid" end
    if try(map, "IsDungeon") == true then return "dungeon" end
    return nil
end

local function plural(n, word) return n .. " " .. word .. (n == 1 and "" or "s") end

------------------------------------------------------------------------------------------------
-- roles
------------------------------------------------------------------------------------------------
local CLASS = {
    warrior = 1, paladin = 2, hunter = 3, rogue = 4, priest = 5, dk = 6, shaman = 7, mage = 8, warlock = 9, druid = 11,
}
local CLASS_ALIAS = { deathknight = "dk", ["death-knight"] = "dk", lock = "warlock", pally = "paladin",
    pal = "paladin", war = "warrior", sham = "shaman", hunt = "hunter" }
local CLASS_LABEL = { [1] = "Warrior", [2] = "Paladin", [3] = "Hunter", [4] = "Rogue", [5] = "Priest",
    [6] = "Death Knight", [7] = "Shaman", [8] = "Mage", [9] = "Warlock", [11] = "Druid" }

-- class -> premade spec name (mod-playerbots' playerbots.conf.dist PremadeSpecName.<class>.<n>, pve)
local ROLES = {
    tank   = { label = "tank",   picks = { { "warrior", "prot pve" }, { "paladin", "prot pve" },
                                           { "druid", "bear pve" }, { "dk", "blood pve" } } },
    healer = { label = "healer", picks = { { "priest", "holy pve" }, { "shaman", "resto pve" },
                                           { "druid", "resto pve" }, { "paladin", "holy pve" } } },
    dps    = { label = "damage", picks = { { "mage", "frost pve" }, { "hunter", "mm pve" },
                                           { "rogue", "combat pve" }, { "warlock", "affli pve" },
                                           { "shaman", "ele pve" }, { "priest", "shadow pve" },
                                           { "warrior", "fury pve" }, { "dk", "frost pve" } } },
}
local ROLE_ORDER = { "tank", "healer", "dps" }
local ROLE_ALIAS = { heal = "healer", heals = "healer", healers = "healer", tanks = "tank", damage = "dps",
    dd = "dps", melee = "dps", caster = "dps" }
local BUDDY_CLASSES = { "warrior", "paladin", "hunter", "rogue", "priest", "shaman", "mage", "warlock", "druid", "dk" }

-- What a full group of each size wants.
local SHAPE = {
    [5]  = { tank = 1, healer = 1, dps = 3 },
    [10] = { tank = 2, healer = 3, dps = 5 },
    [25] = { tank = 3, healer = 6, dps = 16 },
}

-- The premade specs a bot may be given, per class: the realm's own (AC_PLAYERBOTS_PREMADE_SPEC_NAME_<class>__<n>,
-- realm/playerbots-specs.env), pve only; these if the env has none (the pinned playerbots.conf.dist's pve names).
local FALLBACK_SPECS = {
    [1] = { "arms pve", "fury pve", "prot pve" }, [2] = { "holy pve", "prot pve", "ret pve" },
    [3] = { "bm pve", "mm pve", "surv pve" }, [4] = { "as pve", "combat pve", "subtlety pve" },
    [5] = { "disc pve", "holy pve", "shadow pve" }, [6] = { "blood pve", "frost pve", "unholy pve", "double aura blood pve" },
    [7] = { "ele pve", "enh pve", "resto pve" }, [8] = { "arcane pve", "fire pve", "frost pve", "frostfire pve" },
    [9] = { "affli pve", "demo pve", "destro pve" }, [11] = { "balance pve", "bear pve", "resto pve", "cat pve" },
}
local TANK_SPECS = { ["prot pve"] = true, ["bear pve"] = true, ["blood pve"] = true }
local HEAL_SPECS = { ["holy pve"] = true, ["resto pve"] = true, ["disc pve"] = true }

local function specRole(spec)
    if TANK_SPECS[spec] then return "tank" end
    if HEAL_SPECS[spec] then return "healer" end
    return "dps"
end

local function specsFor(cls)
    local out = {}
    for n = 0, 9 do
        local v = os.getenv("AC_PLAYERBOTS_PREMADE_SPEC_NAME_" .. tostring(cls) .. "__" .. n)
        if v and v:match("^[%a ]+ pve$") and #v <= 32 then out[#out + 1] = v end
    end
    if #out == 0 then for _, v in ipairs(FALLBACK_SPECS[cls] or {}) do out[#out + 1] = v end end
    return out
end

local function dkLevel()
    return tonumber(os.getenv("AC_START_HEROIC_PLAYER_LEVEL") or "") or 55
end

local function classOf(word)
    word = CLASS_ALIAS[word] or word
    return CLASS[word] and word or nil
end

-- How many of each role to recruit: what the shape wants minus what the group has, tanks first, then
-- healers, then damage; n slots at most, any left over go to damage.
local function planRoles(have, shape, n)
    local out = { tank = 0, healer = 0, dps = 0 }
    for _, r in ipairs(ROLE_ORDER) do
        local need = math.max(0, (shape[r] or 0) - (have[r] or 0))
        local take = math.min(need, n)
        out[r] = take
        n = n - take
    end
    out.dps = out.dps + math.max(0, n)
    return out
end

------------------------------------------------------------------------------------------------
-- state (per world server run; mod-playerbots logs a player's bots out when the player logs out)
------------------------------------------------------------------------------------------------
local companions = {}   -- [ownerGuid] = { [botGuid] = { name, cls, role, spec, buddy, alt, order, passive } }
local orders = {}       -- [ownerGuid] = { formation, assist, cc }: the window's group-wide switches
local pending = {}      -- [ownerGuid] = { { cls, word, spec, role, buddy, alt, guid, name, at }, ... }
local lastRecruit = {}  -- [ownerGuid] = os.time()
local ticking = {}      -- [ownerGuid] = the running arrival timer's number
local raidWanted = {}   -- [ownerGuid] = true while a raid fill is arriving

local ARRIVE_TICK_MS, ARRIVE_TICKS, ARRIVE_TIMEOUT = 2000, 8, 15
local TELEPORT_DISTANCE = 40

local function countOf(t) local n = 0; for _ in pairs(t or {}) do n = n + 1 end; return n end
local function mine(guid) return countOf(companions[guid]) + #(pending[guid] or {}) end
local function realmCount()
    local n = 0
    for g in pairs(companions) do n = n + countOf(companions[g]) end
    for g in pairs(pending) do n = n + #pending[g] end
    return n
end

local function groupMembers(player)
    local group = try(player, "GetGroup")
    return group, (group and try(group, "GetMembers")) or { player }
end

local function groupSize(player)
    local group = try(player, "GetGroup")
    if not group then return 1 end
    return tonumber(try(group, "GetMembersCount")) or #(try(group, "GetMembers") or {})
end

local function isRaidGroup(player)
    local group = try(player, "GetGroup")
    return group ~= nil and try(group, "IsRaidGroup") == true
end

local function groupInCombat(player)
    local _, members = groupMembers(player)
    for _, m in ipairs(members) do
        if try(m, "IsInCombat") then return true end
    end
    return false
end

local function buddyOf(guid)
    for bg, c in pairs(companions[guid] or {}) do if c.buddy then return bg, c end end
    for _, p in ipairs(pending[guid] or {}) do if p.buddy then return nil, p end end
    return nil
end

local adopt, ownForget   -- below, with the database

-- Drop companions that left the group or logged out (the player kicked them, or a server hiccup), and take back
-- the player's bots we lost track of (a crash or a script reload empties the tables; the bots stay).
local function prune(player)
    local guid = player:GetGUIDLow()
    adopt(player)
    local list = companions[guid]
    if not list then return end
    local inGroup = {}
    local _, members = groupMembers(player)
    for _, m in ipairs(members) do inGroup[m:GetGUIDLow()] = m end
    for bg in pairs(list) do
        if not inGroup[bg] then list[bg] = nil; ownForget(bg) end
    end
end

-- Character names: letters only (UTF-8 letters pass as bytes 128-255), at most 12 characters (24 bytes).
-- Never holds a quote, space or semicolon, so it is safe in a command line and an SQL string.
local function safeName(n)
    n = tostring(n or "")
    if n == "" or #n > 24 or n:find("[^%a\128-\255]") then return "" end
    return n
end

local selfCommand = false   -- true while we run our own bot command (so the raw-command guard lets it through)
local function botCommand(owner, text)
    selfCommand = true
    local ok, err = pcall(owner.RunCommand, owner, "playerbots bot " .. text)
    selfCommand = false
    if not ok then error(err, 0) end
end
local function whisper(owner, bot, text) try(owner, "Whisper", text, 0, bot) end

-- A command to one bot, as if the owner whispered it: straight into the bot's command queue when mod-ale has
-- PlayerbotAI:HandleCommand (no whisper lines in the owner's chat), else a real whisper.
local function tell(owner, bot, text)
    local ai = botAI(bot)
    if ai and hasMethod(ai, "HandleCommand") then
        local ok = pcall(function() ai:HandleCommand(CHAT_MSG_WHISPER, text, owner) end)
        if ok then return end
    end
    whisper(owner, bot, text)
end

-- A strategy change for combat and out of combat ("+passive", "-cc,+dps assist"): silent through
-- PlayerbotAI:ChangeStrategy, else the bot's own "co"/"nc" commands.
local function strategy(owner, bot, change)
    local ai = botAI(bot)
    if ai and hasMethod(ai, "ChangeStrategy") then
        local ok = pcall(function()
            ai:ChangeStrategy(change, BOT_STATE_COMBAT)
            ai:ChangeStrategy(change, BOT_STATE_NON_COMBAT)
        end)
        if ok then return end
    end
    tell(owner, bot, "co " .. change)
    tell(owner, bot, "nc " .. change)
end

-- The role a group member covers: our record for our bots, else the spec (mod-playerbots' IsTank/IsHealer
-- by talents, which works for real players too), else damage.
local function roleOf(owner, m)
    local c = (companions[owner:GetGUIDLow()] or {})[m:GetGUIDLow()]
    if c and ROLES[c.role or ""] then return c.role end
    if try(m, "IsTank", true) == true then return "tank" end
    if try(m, "IsHealer", true) == true then return "healer" end
    return "dps"
end

local function rolesInGroup(player)
    local have = { tank = 0, healer = 0, dps = 0 }
    local _, members = groupMembers(player)
    for _, m in ipairs(members) do
        local r = roleOf(player, m)
        have[r] = have[r] + 1
    end
    for _, p in ipairs(pending[player:GetGUIDLow()] or {}) do
        local r = ROLES[p.role or ""] and p.role or "dps"
        have[r] = have[r] + 1
    end
    return have
end

------------------------------------------------------------------------------------------------
-- arrival: claim the bots that joined, set them up
------------------------------------------------------------------------------------------------
local ownSave, pushRoster   -- below

local function claimed(botGuid)
    for _, list in pairs(companions) do if list[botGuid] then return true end end
    return false
end

-- Open world: move a far bot to the player. Inside an instance: only a bot already on the same map and
-- instance is moved; any other is fetched with mod-playerbots' own summon (its checks, its instance rules).
local function bringOver(owner, m)
    local sameMap = try(m, "GetMapId") == try(owner, "GetMapId")
    local d = tonumber(try(m, "GetDistance", owner))
    local far = not sameMap or (d ~= nil and d > TELEPORT_DISTANCE)
    if not far then return end
    if not instanceKind(owner) then
        try(m, "Teleport", owner:GetMapId(), owner:GetX(), owner:GetY(), owner:GetZ(), owner:GetO())
        return
    end
    local mi, oi = try(m, "GetInstanceId"), try(owner, "GetInstanceId")
    if sameMap and mi ~= nil and mi == oi then
        try(m, "Teleport", owner:GetMapId(), owner:GetX(), owner:GetY(), owner:GetZ(), owner:GetO())
    else
        tell(owner, m, "summon")
    end
end

local function setUp(owner, m, p)
    local name = safeName(m:GetName())
    bringOver(owner, m)
    if not p.alt then
        if m:GetLevel() ~= owner:GetLevel() and name ~= "" then
            botCommand(owner, "init=auto " .. name)
        end
        if p.spec then tell(owner, m, "talents spec " .. p.spec) end
        if not p.buddy then
            tell(owner, m, "maintenance")
            tell(owner, m, "autogear")
        end
    end
    tell(owner, m, "ll normal")
    tell(owner, m, "follow")
end

local function convertIfNeeded(owner)
    local guid = owner:GetGUIDLow()
    if not raidWanted[guid] then return end
    local group = try(owner, "GetGroup")
    if group and try(group, "IsRaidGroup") == false then try(group, "ConvertToRaid") end
end

local function arrivals(owner)
    local guid = owner:GetGUIDLow()
    local list = pending[guid]
    if not list or #list == 0 then return end
    convertIfNeeded(owner)
    local joined = false
    local _, members = groupMembers(owner)
    for _, m in ipairs(members) do
        local bg = m:GetGUIDLow()
        if bg ~= guid and isBot(m) and not claimed(bg) then
            local at
            if isAddclassBot(owner, m) then
                local cls = m:GetClass()
                for i, p in ipairs(list) do if not p.alt and p.cls == cls then at = i; break end end
            elseif try(m, "GetAccountId") == owner:GetAccountId() then
                for i, p in ipairs(list) do if p.alt and p.guid == bg then at = i; break end end
            end
            if at then
                local p = table.remove(list, at)
                local cls = m:GetClass()
                local role = p.role
                if p.alt then role = roleOf(owner, m) end
                companions[guid] = companions[guid] or {}
                companions[guid][bg] = { name = m:GetName(), cls = cls, role = role, spec = p.spec, buddy = p.buddy,
                    alt = p.alt, order = "follow" }
                ownSave(guid, bg, companions[guid][bg])
                setUp(owner, m, p)
                joined = true
                if p.buddy then
                    say(owner, string.format("%s the %s is your levelling buddy bot. Say 'stay' or 'follow' in party chat.",
                        m:GetName(), CLASS_LABEL[cls] or "bot"))
                elseif p.alt then
                    say(owner, string.format("%s (your %s) joins as a bot.", m:GetName(), CLASS_LABEL[cls] or "alt"))
                else
                    say(owner, string.format("%s the %s joins as a %s bot.", m:GetName(), CLASS_LABEL[cls] or "bot",
                        ROLES[role] and ROLES[role].label or role))
                end
            end
        end
    end
    if #list == 0 then raidWanted[guid] = nil end
    if joined then pushRoster(owner) end
end

local function expire(owner, final)
    local guid = owner:GetGUIDLow()
    local list = pending[guid]
    if not list then return end
    local now, kept, lost, alts = os.time(), {}, 0, {}
    for _, p in ipairs(list) do
        if final or now - p.at >= ARRIVE_TIMEOUT then
            if p.alt then alts[#alts + 1] = p.name else lost = lost + 1 end
        else
            kept[#kept + 1] = p
        end
    end
    pending[guid] = kept
    if #kept == 0 then raidWanted[guid] = nil end
    if lost > 0 then
        say(owner, string.format("%s didn't arrive (none free of that class right now). Try another class or role.",
            lost == 1 and "One bot" or (lost .. " bots")))
    end
    if #alts > 0 then
        say(owner, table.concat(alts, ", ") .. " didn't arrive. Try again in a minute.")
    end
end

-- One timer per player at a time; a newer one (a later .recruit) takes over, the older one's ticks do nothing.
local timerGen = 0
local function watchArrivals(player)
    local guid = player:GetGUIDLow()
    timerGen = timerGen + 1
    local gen, ticks = timerGen, 0
    ticking[guid] = gen
    player:RegisterEvent(function(_, _, _, p)
        if ticking[guid] ~= gen then return end
        ticks = ticks + 1
        if not p then ticking[guid] = nil; return end
        local ok, err = pcall(arrivals, p)
        if not ok then print("[ov_companions] arrival check failed: " .. tostring(err)) end
        local last = ticks >= ARRIVE_TICKS or #(pending[guid] or {}) == 0
        if last then ticking[guid] = nil end
        expire(p, ticks >= ARRIVE_TICKS)
    end, ARRIVE_TICK_MS, ARRIVE_TICKS)
end

------------------------------------------------------------------------------------------------
-- database: the usual party (alts) per account
------------------------------------------------------------------------------------------------
local function dbExec(sql)
    if not CharDBExecute then return false end
    return (pcall(CharDBExecute, sql))
end

local function dbRows(sql, cols)
    if not CharDBQuery then return {} end
    local ok, q = pcall(CharDBQuery, sql)
    if not ok or not q then return {} end
    local rows = {}
    repeat
        local row = {}
        for i, kind in ipairs(cols) do
            if kind == "n" then row[i] = tonumber(q:GetUInt32(i - 1)) else row[i] = q:GetString(i - 1) end
        end
        rows[#rows + 1] = row
    until not q:NextRow()
    return rows
end

dbExec([[CREATE TABLE IF NOT EXISTS mod_companions_usual (
  account INT UNSIGNED NOT NULL, slot TINYINT UNSIGNED NOT NULL, guid INT UNSIGNED NOT NULL,
  name VARCHAR(24) NOT NULL, saved_at INT UNSIGNED NOT NULL, PRIMARY KEY (account, slot)
)]])

-- Who owns which bot, so a crash or a script reload doesn't orphan them (the module logs them back in with
-- their master; the in-memory tables start empty).
dbExec([[CREATE TABLE IF NOT EXISTS mod_companions_owned (
  bot INT UNSIGNED NOT NULL, owner INT UNSIGNED NOT NULL, name VARCHAR(24) NOT NULL, role VARCHAR(8) NOT NULL,
  spec VARCHAR(32) NOT NULL, kind VARCHAR(6) NOT NULL, at INT UNSIGNED NOT NULL, PRIMARY KEY (bot), KEY (owner)
)]])

local ROLE_WORDS = { tank = true, healer = true, dps = true, alt = true, buddy = true }

ownSave = function(owner, bg, c)
    local name = safeName(c.name)
    local role = ROLE_WORDS[c.role or ""] and c.role or "dps"
    local spec = tostring(c.spec or "")
    if not spec:match("^[%a ]*$") or #spec > 32 then spec = "" end
    local kind = c.buddy and "buddy" or c.alt and "alt" or "bot"
    if name == "" then return end
    dbExec(string.format("REPLACE INTO mod_companions_owned (bot, owner, name, role, spec, kind, at) "
        .. "VALUES (%d, %d, '%s', '%s', '%s', '%s', %d)", bg, owner, name, role, spec, kind, os.time()))
end

ownForget = function(bg) dbExec(string.format("DELETE FROM mod_companions_owned WHERE bot = %d", bg)) end

local function ownForgetOwner(owner)
    dbExec(string.format("DELETE FROM mod_companions_owned WHERE owner = %d", owner))
end

local function ownRows(owner)
    local out = {}
    for _, r in ipairs(dbRows(string.format(
        "SELECT bot, name, role, spec, kind FROM mod_companions_owned WHERE owner = %d", owner), { "n", "s", "s", "s", "s" })) do
        if r[1] then out[r[1]] = { name = r[2], role = r[3], spec = r[4], kind = r[5] } end
    end
    return out
end

-- Takes back the bots in the player's group that are the player's: PlayerbotAI:GetMaster() is the player, or
-- (without GetBotAI) mod_companions_owned says so. Not while recruits are on the way (arrivals claims those).
-- Returns how many came back.
adopt = function(player)
    local guid = player:GetGUIDLow()
    if #(pending[guid] or {}) > 0 or not try(player, "GetGroup") then return 0 end
    local _, members = groupMembers(player)
    local rows, n = nil, 0
    for _, m in ipairs(members) do
        local bg = m:GetGUIDLow()
        if bg ~= guid and isBot(m) and not claimed(bg) then
            local mine
            local ai = botAI(m)
            local master = ai and try(ai, "GetMaster")
            if master then mine = try(master, "GetGUIDLow") == guid end
            rows = rows or ownRows(guid)
            local row = rows[bg]
            if mine == nil then mine = row ~= nil end
            if mine then
                local alt = try(m, "GetAccountId") == player:GetAccountId()
                local buddy = row ~= nil and row.kind == "buddy"
                local role = row and ROLE_WORDS[row.role or ""] and row.role or nil
                if not role then role = roleOf(player, m) end
                local spec = row and row.spec ~= "" and row.spec or nil
                companions[guid] = companions[guid] or {}
                local c = { name = m:GetName(), cls = m:GetClass(), role = role, spec = spec, buddy = buddy, alt = alt,
                    order = "follow" }
                companions[guid][bg] = c
                ownSave(guid, bg, c)
                n = n + 1
            end
        end
    end
    return n
end

-- The other characters on the player's account that are offline: { guid, name, level, class }.
local function accountAlts(player)
    local rows = dbRows(string.format(
        "SELECT guid, name, level, class FROM characters WHERE account = %d AND online = 0 AND guid <> %d "
        .. "ORDER BY level DESC, name LIMIT 20", player:GetAccountId(), player:GetGUIDLow()), { "n", "s", "n", "n" })
    local out = {}
    for _, r in ipairs(rows) do out[#out + 1] = { guid = r[1], name = r[2], level = r[3], cls = r[4] } end
    return out
end

-- One character of the player's own account, by name (the database compares names without case).
local function ownAlt(player, name)
    local rows = dbRows(string.format(
        "SELECT guid, name, level, class, online FROM characters WHERE account = %d AND name = '%s' LIMIT 1",
        player:GetAccountId(), name), { "n", "s", "n", "n", "n" })
    local r = rows[1]
    if not r then return nil end
    return { guid = r[1], name = r[2], level = r[3], cls = r[4], online = r[5] }
end

------------------------------------------------------------------------------------------------
-- commands
------------------------------------------------------------------------------------------------
local function comingSoon(player)
    say(player, "Bots are coming soon to this realm.")
end

-- Shared checks for every .recruit and .buddy. opts.raid: this command makes a raid; opts.size: the group
-- size it fills to. Returns how many may be recruited now (0 = refused, already said why) and the cap used.
local function room(player, want, opts)
    opts = opts or {}
    if not onSwitch() then say(player, "Bots are off on this realm."); return 0 end
    if try(player, "IsDead") then say(player, "Not while dead."); return 0 end
    if try(player, "IsInCombat") then say(player, "Not in combat."); return 0 end
    if inPvp(player) then say(player, "Not in battlegrounds or arenas."); return 0 end
    if instanceKind(player) and groupInCombat(player) then
        say(player, "Wait until your group is out of combat."); return 0
    end
    local group = try(player, "GetGroup")
    if group and try(group, "IsLeader", player:GetGUID()) == false then
        say(player, "Only the group leader can recruit."); return 0
    end
    local guid, now = player:GetGUIDLow(), os.time()
    local cd = cooldown()
    if lastRecruit[guid] and now - lastRecruit[guid] < cd then
        say(player, string.format("You can recruit again in %d s.", cd - (now - lastRecruit[guid]))); return 0
    end
    prune(player)
    local raiding = opts.raid or isRaidGroup(player)
    local cap = raiding and perPlayerRaid() or perPlayer()
    local size = opts.size or (raiding and groupMax() or math.min(PARTY, groupMax()))
    local have = mine(guid)
    local slots = size - groupSize(player) - #(pending[guid] or {})
    local realmLeft = realmMax() - realmCount()
    local n = math.min(want, cap - have, slots, realmLeft)
    if n <= 0 then
        if cap - have <= 0 then
            say(player, string.format("You have %s, the most allowed %s (.dismiss to make room).",
                plural(have, "bot"), raiding and "in a raid" or "in a party"))
        elseif slots <= 0 then
            say(player, string.format("Your group is full (%d players).", size))
        else
            say(player, "Every bot on the realm is out with someone right now. Try again in a few minutes.")
        end
        return 0
    end
    return n, raiding
end

local function queue(player, list)
    local guid = player:GetGUIDLow()
    pending[guid] = pending[guid] or {}
    lastRecruit[guid] = os.time()
    for _, p in ipairs(list) do
        p.at = os.time()
        table.insert(pending[guid], p)
        if p.alt then botCommand(player, "add " .. p.name) else botCommand(player, "addclass " .. p.word) end
    end
    watchArrivals(player)
end

-- The class picks for a role at the player's level (no Death Knight below its start level).
local function picksFor(player, roleWord, onlyClass)
    local picks = {}
    for _, pk in ipairs(ROLES[roleWord].picks) do
        if (not onlyClass or pk[1] == onlyClass) and (pk[1] ~= "dk" or player:GetLevel() >= dkLevel()) then
            picks[#picks + 1] = pk
        end
    end
    return picks
end

local function addRole(player, list, roleWord, n, onlyClass)
    local picks = picksFor(player, roleWord, onlyClass)
    if #picks == 0 or n <= 0 then return end
    local start = math.random(#picks)
    for i = 1, n do
        local pk = picks[(start + i - 2) % #picks + 1]
        list[#list + 1] = { cls = CLASS[pk[1]], word = pk[1], spec = pk[2], role = roleWord }
    end
end

-- Before a raid fill: a party group becomes a raid now when it will pass 5 (without a group yet, the
-- module converts it itself when the 6th member joins).
local function goRaid(player, total)
    raidWanted[player:GetGUIDLow()] = true
    local group = try(player, "GetGroup")
    if group and total > PARTY and try(group, "IsRaidGroup") == false then try(group, "ConvertToRaid") end
end

local function roleList(counts)
    local parts = {}
    if counts.tank > 0 then parts[#parts + 1] = plural(counts.tank, "tank") end
    if counts.healer > 0 then parts[#parts + 1] = plural(counts.healer, "healer") end
    if counts.dps > 0 then parts[#parts + 1] = counts.dps .. " damage" end
    return table.concat(parts, ", ")
end

local function fillCommand(player, kind, arg)
    local size, raid = PARTY, false
    if kind == "raid" then
        if groupMax() <= PARTY then return say(player, "Raids with bots are off on this realm.") end
        size, raid = math.min(10, groupMax()), true
        if arg == "25" then
            if not raid25() then return say(player, "25-player raids are off here. .recruit raid fills a 10-player raid.") end
            size = math.min(25, groupMax())
        elseif arg and arg ~= "10" then
            return say(player, "Usage: |cffffff00.recruit raid|r (a 10-player raid)")
        end
        if instanceKind(player) == "dungeon" then
            return say(player, "Inside a 5-player dungeon, use .recruit party.")
        end
        local group = try(player, "GetGroup")
        if group and (try(group, "IsLFGGroup") == true or try(group, "IsBGGroup") == true) then
            return say(player, "Not in a Dungeon Finder group. Leave it first.")
        end
    elseif isRaidGroup(player) then
        return say(player, "You are in a raid. Use .recruit raid.")
    end
    local n = room(player, size, { raid = raid, size = size })
    if n == 0 then return end
    local counts = planRoles(rolesInGroup(player), SHAPE[size] or SHAPE[10], n)
    local list = {}
    for _, r in ipairs(ROLE_ORDER) do addRole(player, list, r, counts[r]) end
    if #list == 0 then return say(player, "Your group already has what it needs.") end
    if raid then goRaid(player, groupSize(player) + #(pending[player:GetGUIDLow()] or {}) + #list) end
    queue(player, list)
    local msg = string.format("Recruiting %s for a %d-player %s: %s. They join in a few seconds.",
        plural(#list, "bot"), size, raid and "raid" or "group", roleList(counts))
    local free = size - groupSize(player) - #(pending[player:GetGUIDLow()] or {})
    if free > 0 then msg = msg .. " (The limits here leave " .. plural(free, "slot") .. " open.)" end
    say(player, msg)
end

local function roleCommand(player, roleWord, extra)
    roleWord = ROLE_ALIAS[roleWord or ""] or roleWord
    local role = ROLES[roleWord or ""]
    if not role then
        return say(player, "Usage: |cffffff00.recruit party|r, |cffffff00.recruit raid|r, "
            .. "|cffffff00.recruit tank|healer|dps [n]|r or |cffffff00.recruit alt <name>|r")
    end
    local want, onlyClass = 1, nil
    if extra then
        if tonumber(extra) then
            want = math.floor(tonumber(extra))
        else
            onlyClass = classOf(extra)
            local fits = false
            for _, pk in ipairs(role.picks) do if pk[1] == onlyClass then fits = true end end
            if not fits then
                local names = {}
                for _, pk in ipairs(role.picks) do names[#names + 1] = pk[1] end
                return say(player, "A " .. role.label .. " bot can be: " .. table.concat(names, ", ") .. ".")
            end
        end
    end
    if want < 1 then return say(player, "Recruit at least one.") end
    if #picksFor(player, roleWord, onlyClass) == 0 then return say(player, "Death Knights join from level " .. dkLevel() .. ".") end
    local n = room(player, want)
    if n == 0 then return end
    local list = {}
    addRole(player, list, roleWord, n, onlyClass)
    queue(player, list)
    local msg = string.format("Recruiting %s: they join your group in a few seconds.", plural(n, role.label .. " bot"))
    if n < want then msg = msg .. string.format(" (%d of the %d asked: the limits here.)", n, want) end
    say(player, msg)
end

local function alreadyComing(guid, charGuid)
    if (companions[guid] or {})[charGuid] then return true end
    for _, p in ipairs(pending[guid] or {}) do if p.alt and p.guid == charGuid then return true end end
    return false
end

local function altsCommand(player)
    local alts = accountAlts(player)
    if #alts == 0 then return say(player, "No other characters on your account to bring.") end
    local names = {}
    for _, a in ipairs(alts) do
        names[#names + 1] = string.format("%s (%d %s)", a.name, a.level or 0, CLASS_LABEL[a.cls] or "?")
    end
    say(player, "Your other characters: " .. table.concat(names, ", "))
    say(player, "Bring one as a bot: |cffffff00.recruit alt <name>|r")
end

-- Queues alts (rows from ownAlt / the usual list) within the limits; returns the names queued.
local function queueAlts(player, alts, label)
    local raiding = isRaidGroup(player)
    local total = groupSize(player) + #(pending[player:GetGUIDLow()] or {}) + #alts
    if not raiding and total > PARTY and groupMax() > PARTY then raiding = true end
    local n = room(player, #alts, { raid = raiding })
    if n == 0 then return {} end
    local list, names = {}, {}
    for i = 1, n do
        local a = alts[i]
        list[#list + 1] = { alt = true, guid = a.guid, name = a.name, cls = a.cls, role = "alt" }
        names[#names + 1] = a.name
    end
    if raiding then goRaid(player, groupSize(player) + #(pending[player:GetGUIDLow()] or {}) + #list) end
    queue(player, list)
    local msg = label .. table.concat(names, ", ") .. ". They join in a few seconds."
    if n < #alts then msg = msg .. string.format(" (%d of %d: the limits here.)", n, #alts) end
    say(player, msg)
    return names
end

local function altCommand(player, rawName)
    if not rawName then return altsCommand(player) end
    local name = safeName(rawName)
    if name == "" then return say(player, "Usage: |cffffff00.recruit alt <name>|r (.companions alts lists them)") end
    local a = ownAlt(player, name)
    if not a then return say(player, "You have no character called " .. name .. " on this account.") end
    if a.guid == player:GetGUIDLow() then return say(player, "That's you.") end
    if alreadyComing(player:GetGUIDLow(), a.guid) then return say(player, a.name .. " is already with you.") end
    if a.online ~= 0 then return say(player, a.name .. " is online already.") end
    queueAlts(player, { a }, "Bringing ")
end

local function saveCommand(player)
    local guid, account = player:GetGUIDLow(), player:GetAccountId()
    prune(player)
    local alts = {}
    for bg, c in pairs(companions[guid] or {}) do
        if c.alt and safeName(c.name) ~= "" then alts[#alts + 1] = { guid = bg, name = c.name } end
    end
    if #alts == 0 then
        return say(player, "No alts with you to save. Bring them first: .recruit alt <name>")
    end
    table.sort(alts, function(x, y) return x.name < y.name end)
    dbExec(string.format("DELETE FROM mod_companions_usual WHERE account = %d", account))
    local names = {}
    for i, a in ipairs(alts) do
        dbExec(string.format("INSERT INTO mod_companions_usual (account, slot, guid, name, saved_at) VALUES (%d, %d, %d, '%s', %d)",
            account, i, a.guid, a.name, os.time()))
        names[#names + 1] = a.name
    end
    say(player, "Saved your usual party: " .. table.concat(names, ", ") .. ". |cffffff00.recruit usual|r brings them back.")
end

local function usualCommand(player)
    local account = player:GetAccountId()
    local rows = dbRows(string.format(
        "SELECT c.guid, c.name, c.level, c.class, c.online FROM mod_companions_usual u JOIN characters c "
        .. "ON c.guid = u.guid AND c.account = u.account WHERE u.account = %d ORDER BY u.slot", account),
        { "n", "s", "n", "n", "n" })
    if #rows == 0 then
        return say(player, "No usual party saved. Bring alts with .recruit alt <name>, then .companions save.")
    end
    local guid, ready, busy = player:GetGUIDLow(), {}, {}
    for _, r in ipairs(rows) do
        local a = { guid = r[1], name = r[2], level = r[3], cls = r[4], online = r[5] }
        if a.guid ~= guid and not alreadyComing(guid, a.guid) then
            if a.online == 0 then ready[#ready + 1] = a else busy[#busy + 1] = a.name end
        end
    end
    if #ready == 0 then
        if #busy > 0 then return say(player, table.concat(busy, ", ") .. " are online already.") end
        return say(player, "Your usual party is already with you.")
    end
    queueAlts(player, ready, "Bringing your usual party: ")
    if #busy > 0 then say(player, "Online already: " .. table.concat(busy, ", ") .. ".") end
end

local function buddyCommand(player, arg)
    if not buddyOn() then return say(player, "The levelling buddy is off on this realm. Try .recruit.") end
    local guid = player:GetGUIDLow()
    prune(player)
    local bg, b = buddyOf(guid)
    if arg == "off" or arg == "dismiss" or arg == "bye" then
        if not bg then return say(player, "You have no buddy with you.") end
        local _, members = groupMembers(player)
        for _, m in ipairs(members) do
            if m:GetGUIDLow() == bg then tell(player, m, "leave"); break end
        end
        local nm = safeName(b.name)
        if nm ~= "" then
            player:RegisterEvent(function(_, _, _, p) if p then botCommand(p, "remove " .. nm) end end, 2500, 1)
        end
        companions[guid][bg] = nil
        ownForget(bg)
        return say(player, b.name .. " heads home.")
    end
    if b then
        if not bg then return say(player, "Your buddy is on the way.") end
        return say(player, string.format("Your buddy is %s the %s, a bot that keeps to your level. (.buddy off to send it home)",
            b.name, CLASS_LABEL[b.cls] or "bot"))
    end
    local word
    if arg then
        word = classOf(arg)
        if not word then return say(player, "Usage: |cffffff00.buddy [class]|r  (warrior, paladin, hunter, rogue, priest, "
            .. "shaman, mage, warlock, druid, dk)") end
        if word == "dk" and player:GetLevel() < dkLevel() then
            return say(player, "Death Knights join from level " .. dkLevel() .. ".")
        end
    else
        local all = {}
        for _, w in ipairs(BUDDY_CLASSES) do
            if w ~= "dk" or player:GetLevel() >= dkLevel() then all[#all + 1] = w end
        end
        word = all[math.random(#all)]
    end
    if room(player, 1) == 0 then return end
    queue(player, { { cls = CLASS[word], word = word, role = "buddy", buddy = true } })
    say(player, "Your levelling buddy bot is on the way.")
end

local function dismissCommand(player, arg)
    local guid = player:GetGUIDLow()
    prune(player)
    local list = companions[guid] or {}
    local n = countOf(list)
    if n == 0 then
        pending[guid] = nil
        raidWanted[guid] = nil
        return say(player, "You have no bots with you.")
    end
    local gone = {}
    -- Each bot leaves the group itself first (its own "leave" command, the module's LeaveOrDisbandGroup), then
    -- logs out 2.5 s later. A bot that only logs out stays behind as an offline member and fills the slot
    -- ("Your group is full"). Never remove members from the group in Lua: on 2026-10-26 calling the group's
    -- RemoveMember next to the module's own logout clean-up crashed the world server.
    local _, members = groupMembers(player)
    local byGuid = {}
    for _, m in ipairs(members) do byGuid[m:GetGUIDLow()] = m end
    local later = {}
    local function send(bg, c)
        gone[#gone + 1] = c.name; list[bg] = nil; ownForget(bg)
        if byGuid[bg] then tell(player, byGuid[bg], "leave") end
        local nm = safeName(c.name)
        if nm ~= "" then later[#later + 1] = nm end
    end
    if arg == "all" then
        for bg, c in pairs(list) do send(bg, c) end
        pending[guid] = nil
        raidWanted[guid] = nil
    elseif arg == "buddy" then
        return buddyCommand(player, "off")
    elseif arg or n == 1 then
        for bg, c in pairs(list) do
            if not arg or c.name:lower() == arg then send(bg, c); break end
        end
        if #gone == 0 then return say(player, "None of your bots is called " .. arg .. ".") end
    else
        local names = {}
        for _, c in pairs(list) do names[#names + 1] = c.name end
        table.sort(names)
        return say(player, "Dismiss which? |cffffff00.dismiss <name>|r or |cffffff00.dismiss all|r: " .. table.concat(names, ", "))
    end
    if #later > 0 then
        player:RegisterEvent(function(_, _, _, p)
            if not p then return end
            for _, nm in ipairs(later) do botCommand(p, "remove " .. nm) end
            pushRoster(p)
        end, 2500, 1)
    end
    table.sort(gone)
    say(player, table.concat(gone, ", ") .. (#gone == 1 and " heads" or " head") .. " home.")
end

local function showHelp(player)
    say(player, "Bots: party members who fight, heal and follow you. They always pass on loot.")
    say(player, "  |cffffff00.recruit party|r  fill a 5-player group (1 tank, 1 healer, damage)")
    if groupMax() > PARTY then
        say(player, "  |cffffff00.recruit raid|r  fill a 10-player raid (2 tanks, 3 healers, 5 damage)")
    end
    say(player, "  |cffffff00.recruit tank|healer|dps [n]|r  add bots of one role (.recruit dps mage)")
    say(player, "  |cffffff00.recruit alt <name>|r  bring one of your own characters (|cffffff00.companions alts|r lists them)")
    say(player, "  |cffffff00.companions save|r  remember the alts with you; |cffffff00.recruit usual|r brings them back")
    if buddyOn() then say(player, "  |cffffff00.buddy [class]|r  a levelling buddy that keeps to your level") end
    say(player, "  |cffffff00.dismiss [name|all]|r  send bots home")
    say(player, string.format("  Limits: %s in a party, %s in a raid, .recruit every %d s.",
        plural(perPlayer(), "bot"), plural(perPlayerRaid(), "bot"), cooldown()))
    say(player, "  In party chat: follow, stay, attack, summon.")
    prune(player)
    local names = {}
    for _, c in pairs(companions[player:GetGUIDLow()] or {}) do
        names[#names + 1] = c.name .. " (" .. (c.buddy and "buddy" or c.alt and "alt" or (ROLES[c.role] and ROLES[c.role].label or c.role)) .. ")"
    end
    table.sort(names)
    if #names > 0 then say(player, "  With you: " .. table.concat(names, ", ")) end
    if OVMod then say(player, "  The Bots window: |cffffff00/comp|r") end
end

------------------------------------------------------------------------------------------------
-- the Bots window (WrathUnleashedUI/Companions.lua) over OVMOD, mod "wucomp"
------------------------------------------------------------------------------------------------
local FORMATIONS = { near = true, melee = true, line = true, circle = true, arrow = true, shield = true, queue = true,
    chaos = true }
local PREPARE_COOLDOWN = 60   -- seconds between two "Prepare for raid"
local BOT_COOLDOWN = 10       -- seconds between two spec / role / gear changes of one bot
local PER_SECOND = 4          -- window requests answered per player per second
local ILVL_CACHE = 15         -- seconds an item level is reused
local GEAR_SLOTS = { 0, 1, 2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17 }   -- not the shirt (3) or tabard (18)

local rate, lastPrepare, botBusy, ilvlCache = {}, {}, {}, {}

local function clean(s) return (tostring(s or ""):gsub("[\t\n|]", "")) end

local function flooding(guid)
    local now = os.time()
    local r = rate[guid]
    if not r or r.at ~= now then rate[guid] = { at = now, n = 1 }; return false end
    r.n = r.n + 1
    return r.n > PER_SECOND
end

-- Average item level of what the bot wears (cached a few seconds; 17 slots per bot).
local function itemLevel(m)
    local bg, now = m:GetGUIDLow(), os.time()
    local hit = ilvlCache[bg]
    if hit and now - hit.at < ILVL_CACHE then return hit.v end
    local sum, n = 0, 0
    for _, slot in ipairs(GEAR_SLOTS) do
        local it = try(m, "GetEquippedItemBySlot", slot)
        local lv = it and tonumber(try(it, "GetItemLevel"))
        if lv and lv > 0 then sum = sum + lv; n = n + 1 end
    end
    local v = n > 0 and math.floor(sum / n + 0.5) or 0
    ilvlCache[bg] = { v = v, at = now }
    return v
end

local function statusOf(m, c)
    if try(m, "IsDead") then return "dead" end
    if c.passive then return "passive" end
    if c.order == "stay" then return "stay" end
    return "follow"
end

-- The player's bots that are in the group now, tanks first, then healers, then damage, then by name.
local RANK = { tank = 1, healer = 2, dps = 3 }
local function myBots(player)
    prune(player)
    local _, members = groupMembers(player)
    local byGuid = {}
    for _, m in ipairs(members) do byGuid[m:GetGUIDLow()] = m end
    local out = {}
    for bg, c in pairs(companions[player:GetGUIDLow()] or {}) do
        if byGuid[bg] then out[#out + 1] = { bg = bg, c = c, m = byGuid[bg], role = roleOf(player, byGuid[bg]) } end
    end
    table.sort(out, function(a, b)
        local ra, rb = RANK[a.role] or 4, RANK[b.role] or 4
        if ra ~= rb then return ra < rb end
        return a.c.name < b.c.name
    end)
    return out
end

local function findBot(player, name)
    name = tostring(name or ""):lower()
    if name == "" then return nil end
    for _, e in ipairs(myBots(player)) do if e.c.name:lower() == name then return e end end
    return nil
end

pushRoster = function(player)
    if not OVMod or not player then return end
    local guid = player:GetGUIDLow()
    local state = (not botsBuilt(player)) and "soon" or (not onSwitch()) and "off" or "on"
    local list = state == "on" and myBots(player) or {}
    local o = orders[guid] or {}
    local raiding = isRaidGroup(player)
    local lines = { table.concat({ "H", #list, raiding and perPlayerRaid() or perPlayer(), raiding and 1 or 0,
        o.formation or "chaos", o.assist and 1 or 0, o.cc and 1 or 0, state }, "\t") }
    local classes, seen = {}, {}
    for _, e in ipairs(list) do
        local c, m = e.c, e.m
        local cls = c.cls or m:GetClass()
        lines[#lines + 1] = table.concat({ "B", clean(c.name), cls, e.role, c.buddy and "buddy" or c.alt and "alt" or "bot",
            clean(c.spec or ""), itemLevel(m), statusOf(m, c), m:GetLevel() }, "\t")
        if not seen[cls] then seen[cls] = true; classes[#classes + 1] = cls end
    end
    table.sort(classes)
    for _, cls in ipairs(classes) do
        local parts = {}
        for _, s in ipairs(specsFor(cls)) do parts[#parts + 1] = s .. "=" .. specRole(s) end
        lines[#lines + 1] = "S\t" .. cls .. "\t" .. table.concat(parts, ",")
    end
    OVMod.Send(player, MOD, "roster", table.concat(lines, "\n"))
end

local function later(player, ms, fn)
    player:RegisterEvent(function(_, _, _, p) if p then fn(p) end end, ms, 1)
end

-- Every window action: answers go to the window from now on; bots on this realm, and on.
local function windowReady(player)
    if isBot(player) or flooding(player:GetGUIDLow()) then return false end
    replyTo[player:GetGUIDLow()] = true
    if not botsBuilt(player) then comingSoon(player); return false end
    if not onSwitch() then say(player, "Bots are off on this realm."); return false end
    return true
end

-- Orders that teach, re-gear or re-spec wait for a quiet moment.
local function calm(player)
    if try(player, "IsDead") then say(player, "Not while dead."); return false end
    if try(player, "IsInCombat") or groupInCombat(player) then say(player, "Wait until your group is out of combat."); return false end
    return true
end

local function busy(player, e)
    local now = os.time()
    if botBusy[e.bg] and now - botBusy[e.bg] < BOT_COOLDOWN then
        say(player, string.format("%s is still busy. Try again in %d s.", e.c.name, BOT_COOLDOWN - (now - botBusy[e.bg])))
        return true
    end
    botBusy[e.bg] = now
    return false
end

-- order <what> <name|all>
local ORDERS = {
    follow  = { said = "Following you.", fn = function(p, e) tell(p, e.m, "follow"); e.c.order = "follow"; e.c.passive = nil end },
    stay    = { said = "Staying here.", fn = function(p, e) tell(p, e.m, "stay"); e.c.order = "stay"; e.c.passive = nil end },
    attack  = { said = "Attacking your target.", fn = function(p, e) tell(p, e.m, "attack") end },
    passive = { said = "Passive: they won't attack.", fn = function(p, e) strategy(p, e.m, "+passive"); e.c.passive = true end },
    active  = { said = "They fight again.", fn = function(p, e) strategy(p, e.m, "-passive"); e.c.passive = nil end },
    -- Tanks mark their target with the skull; damage focuses one target at a time (dps assist, not dps aoe) and
    -- the skull first (mod-playerbots' DpsTargetValue takes the RTI target first).
    assist  = { said = "Damage bots focus the tank's skull target.", group = "assist", on = true, fn = function(p, e)
        if e.role == "tank" then strategy(p, e.m, "+mark rti")
        elseif e.role == "dps" then strategy(p, e.m, "+dps assist"); tell(p, e.m, "rti skull") end
    end },
    noassist = { said = "Assist tank off.", group = "assist", on = false, fn = function(p, e)
        if e.role == "tank" then strategy(p, e.m, "-mark rti") end
    end },
    cc      = { said = "Crowd control on: bots that can will keep extra enemies busy.", group = "cc", on = true,
        fn = function(p, e) strategy(p, e.m, "+cc") end },
    nocc    = { said = "Crowd control off.", group = "cc", on = false, fn = function(p, e) strategy(p, e.m, "-cc") end },
}

local function onOrder(player, data)
    if not windowReady(player) then return end
    local what, target = tostring(data or ""):lower():match("^(%a+) (%S+)$")
    local o = ORDERS[what or ""]
    if not o then return say(player, "That order isn't known.") end
    if what == "attack" and not try(player, "GetSelection") then return say(player, "Target something first.") end
    local list = myBots(player)
    if #list == 0 then return say(player, "You have no bots with you.") end
    local done
    for _, e in ipairs(list) do
        if target == "all" or e.c.name:lower() == target then o.fn(player, e); done = done or e.c.name end
    end
    if not done then return say(player, "None of your bots is called " .. clean(target) .. ".") end
    if o.group and target == "all" then
        local guid = player:GetGUIDLow()
        orders[guid] = orders[guid] or {}
        orders[guid][o.group] = o.on
    end
    say(player, target == "all" and o.said or (done .. ": " .. o.said))
    pushRoster(player)
end

local function onFormation(player, data)
    if not windowReady(player) then return end
    local f = tostring(data or ""):lower():match("^(%a+)$")
    if not FORMATIONS[f or ""] then return say(player, "That formation isn't known.") end
    local list = myBots(player)
    if #list == 0 then return say(player, "You have no bots with you.") end
    for _, e in ipairs(list) do tell(player, e.m, "formation " .. f) end
    local guid = player:GetGUIDLow()
    orders[guid] = orders[guid] or {}
    orders[guid].formation = f
    say(player, "Formation: " .. f .. ".")
    pushRoster(player)
end

-- Maintenance (spells, talents, consumables, repairs) and autogear for recruited bots; alts keep their own gear;
-- everyone rebuffs.
local function onPrepare(player)
    if not windowReady(player) or not calm(player) then return end
    local guid, now = player:GetGUIDLow(), os.time()
    if lastPrepare[guid] and now - lastPrepare[guid] < PREPARE_COOLDOWN then
        return say(player, string.format("They are getting ready. Again in %d s.", PREPARE_COOLDOWN - (now - lastPrepare[guid])))
    end
    local list = myBots(player)
    if #list == 0 then return say(player, "You have no bots with you.") end
    lastPrepare[guid] = now
    for _, e in ipairs(list) do
        if not e.c.alt then
            tell(player, e.m, "maintenance")
            tell(player, e.m, "autogear")
            ilvlCache[e.bg] = nil
        end
        tell(player, e.m, "rebuff")
    end
    say(player, "Getting ready: spells, gear and buffs. Give them a few seconds.")
    later(player, 5000, function(p) for _, e in ipairs(list) do ilvlCache[e.bg] = nil end; pushRoster(p) end)
end

-- A premade spec (one of the realm's for that class), then maintenance and autogear for the new talents.
local function learnSpec(player, e, spec)
    tell(player, e.m, "talents spec " .. spec)
    tell(player, e.m, "maintenance")
    tell(player, e.m, "autogear")
    e.c.spec = spec
    if not e.c.buddy then e.c.role = specRole(spec) end
    ownSave(player:GetGUIDLow(), e.bg, e.c)
    ilvlCache[e.bg] = nil
    pushRoster(player)
    later(player, 4000, function(p) ilvlCache[e.bg] = nil; pushRoster(p) end)   -- the new gear's item level
end

local function specLabel(spec) return (spec:gsub(" pve$", "")) end

local function changeable(player, e)
    if not e then say(player, "That bot isn't with you."); return false end
    if e.c.alt then say(player, e.c.name .. " is your own character: it keeps its own talents and gear."); return false end
    return true
end

local function onSpec(player, data)
    if not windowReady(player) then return end
    local name, spec = tostring(data or ""):match("^(%S+)\t([%a ]+)$")
    local e = findBot(player, name)
    if not changeable(player, e) then return end
    local fits = false
    for _, s in ipairs(specsFor(e.c.cls)) do if s == spec then fits = true end end
    if not fits then return say(player, "That spec isn't one " .. e.c.name .. " can learn.") end
    if not calm(player) or busy(player, e) then return end
    learnSpec(player, e, spec)
    say(player, string.format("%s learns %s.", e.c.name, specLabel(spec)))
end

local function onRole(player, data)
    if not windowReady(player) then return end
    local name, role = tostring(data or ""):lower():match("^(%S+) (%a+)$")
    role = ROLE_ALIAS[role or ""] or role
    if not ROLES[role or ""] then return say(player, "Pick tank, healer or damage.") end
    local e = findBot(player, name)
    if not changeable(player, e) then return end
    -- the class's usual pick for the role (ROLES), else any of the realm's specs for that role
    local word, spec
    for w, id in pairs(CLASS) do if id == e.c.cls then word = w end end
    local have = {}
    for _, s in ipairs(specsFor(e.c.cls)) do have[s] = specRole(s) == role end
    for _, pk in ipairs(ROLES[role].picks) do if pk[1] == word and have[pk[2]] then spec = pk[2] end end
    if not spec then for _, s in ipairs(specsFor(e.c.cls)) do if not spec and have[s] then spec = s end end end
    if not spec then
        return say(player, string.format("A %s can't be a %s.", CLASS_LABEL[e.c.cls] or "bot", ROLES[role].label))
    end
    if not calm(player) or busy(player, e) then return end
    learnSpec(player, e, spec)
    say(player, string.format("%s is now a %s (%s).", e.c.name, ROLES[role].label, specLabel(spec)))
end

local function onGear(player, data)
    if not windowReady(player) then return end
    local e = findBot(player, tostring(data or ""):match("^(%S+)$"))
    if not changeable(player, e) or not calm(player) or busy(player, e) then return end
    tell(player, e.m, "autogear")
    ilvlCache[e.bg] = nil
    say(player, e.c.name .. " is picking better gear.")
    later(player, 4000, function(p) ilvlCache[e.bg] = nil; pushRoster(p) end)
end

if OVMod then
    OVMod.On(MOD, "roster", function(player)
        if isBot(player) or flooding(player:GetGUIDLow()) then return end
        pushRoster(player)
    end)
    OVMod.On(MOD, "order", onOrder)
    OVMod.On(MOD, "formation", onFormation)
    OVMod.On(MOD, "prepare", onPrepare)
    OVMod.On(MOD, "spec", onSpec)
    OVMod.On(MOD, "role", onRole)
    OVMod.On(MOD, "gear", onGear)
    OVMod.On(MOD, "fill", function(player, data)
        if not windowReady(player) then return end
        if data == "party" or data == "raid" then fillCommand(player, data) else say(player, "Fill a party or a raid.") end
    end)
    OVMod.On(MOD, "usual", function(player) if windowReady(player) then usualCommand(player) end end)
    OVMod.On(MOD, "dismiss", function(player, data)
        if not windowReady(player) then return end
        local arg = tostring(data or ""):lower():match("^(%S+)$")
        if not arg then return say(player, "Dismiss whom?") end
        dismissCommand(player, arg)
        pushRoster(player)
    end)
end

------------------------------------------------------------------------------------------------
-- events
------------------------------------------------------------------------------------------------
local COMMANDS = { companions = true, companion = true, recruit = true, buddy = true, dismiss = true }

-- The module's own chat commands (.playerbots bot add <name> / addclass <class> / addaccount / init=...) from a
-- player who isn't a GM would skip every limit above (per player, per realm, group size, cooldown). They go
-- through the same checks as .recruit instead; the rest (list, remove, logout, help) passes through.
local RAW_BOT = { playerbots = true, playerbot = true, bot = true }
local RAW_PASS = { list = true, ls = true, remove = true, rm = true, logout = true, help = true }

local function isGM(player)
    local rank = tonumber(try(player, "GetGMRank") or 0) or 0
    return rank > 0 or try(player, "IsGM") == true
end

local function rawBotCommand(player, words, rawWords)
    local sub, at = nil, nil
    if words[1] == "bot" then sub, at = words[2], 3
    elseif words[2] == "bot" then sub, at = words[3], 4
    else return nil end                                 -- other module commands keep their own security levels
    if selfCommand or not sub or RAW_PASS[sub] or isGM(player) or isBot(player) then return nil end
    replyTo[player:GetGUIDLow()] = nil
    if not botsBuilt(player) then comingSoon(player); return false end
    if not onSwitch() then say(player, "Bots are off on this realm."); return false end
    if sub == "add" and rawWords[at] and not rawWords[at + 1] and not rawWords[at]:find(",", 1, true) then
        altCommand(player, rawWords[at])              -- one of the player's own characters, as .recruit alt
    elseif sub == "addclass" and words[at] and not words[at + 1] then
        local cls = classOf(words[at])
        if not cls then return say(player, "Usage: |cffffff00.recruit tank|healer|dps <class>|r") or false end
        if cls == "dk" and player:GetLevel() < dkLevel() then
            say(player, "Death Knights join from level " .. dkLevel() .. "."); return false
        end
        local role, spec
        for _, r in ipairs(ROLE_ORDER) do
            for _, pk in ipairs(ROLES[r].picks) do
                if not role and pk[1] == cls then role, spec = r, pk[2] end
            end
        end
        if not role then return say(player, "Usage: |cffffff00.recruit tank|healer|dps <class>|r") or false end
        if room(player, 1) == 0 then return false end
        queue(player, { { cls = CLASS[cls], word = cls, spec = spec, role = role } })
        say(player, string.format("Recruiting a %s bot: it joins your group in a few seconds.", CLASS_LABEL[CLASS[cls]] or cls))
    else
        say(player, "Bring bots with |cffffff00.recruit|r (party, raid, tank, healer, dps, alt <name>) or the Bots window.")
    end
    return false
end

local function onCommand(event, player, command)
    if not player then return end
    local raw = (command or ""):gsub("^[%.!]", "")
    local text = raw:lower()
    local words, rawWords = {}, {}
    for w in text:gmatch("%S+") do words[#words + 1] = w end
    for w in raw:gmatch("%S+") do rawWords[#rawWords + 1] = w end
    local cmd = words[1]
    if RAW_BOT[cmd] then return rawBotCommand(player, words, rawWords) end
    if not COMMANDS[cmd] then return end
    if isBot(player) then return false end
    replyTo[player:GetGUIDLow()] = nil   -- typed: the answers go to the chat
    if not botsBuilt(player) then comingSoon(player); return false end
    if cmd == "companions" or cmd == "companion" then
        if words[2] == "alts" then altsCommand(player)
        elseif words[2] == "save" then saveCommand(player)
        else showHelp(player) end
    elseif not onSwitch() then
        say(player, "Bots are off on this realm.")
    elseif cmd == "recruit" then
        local w = words[2]
        if w == "party" or w == "raid" then fillCommand(player, w, words[3])
        elseif w == "alt" then altCommand(player, rawWords[3])
        elseif w == "usual" then usualCommand(player)
        else roleCommand(player, w, words[3]) end
    elseif cmd == "buddy" then
        buddyCommand(player, words[2])
    elseif cmd == "dismiss" then
        dismissCommand(player, words[2])
    end
    return false
end

-- The buddy keeps to the player's level (mod-playerbots re-levels and re-gears it with init=auto).
local function onLevelChange(event, player, oldLevel)
    if not player or isBot(player) then return end
    local guid = player:GetGUIDLow()
    if not buddyOf(guid) then return end
    player:RegisterEvent(function(_, _, _, p)
        if not p then return end
        prune(p)
        local bg, b = buddyOf(guid)
        if not bg then return end
        local _, members = groupMembers(p)
        for _, m in ipairs(members) do
            if m:GetGUIDLow() == bg and m:GetLevel() ~= p:GetLevel() then
                if try(p, "IsInCombat") or try(m, "IsInCombat") then
                    say(p, b.name .. " catches up to your level after the fight (.buddy, or level again).")
                else
                    botCommand(p, "init=auto " .. safeName(b.name))
                    tell(p, m, "follow")
                    say(p, string.format("%s keeps up: level %d.", b.name, p:GetLevel()))
                end
            end
        end
    end, 3000, 1)
end

-- After a crash the module logs the player's bots back in with the player as their master (seen live
-- 2026-10-26: a 10-player raid came back, our tables were empty). Look for them a few times after login.
local LOGIN_LOOKS, LOGIN_LOOK_MS = 3, 15000
local function onLogin(event, player)
    if not player or isBot(player) or not botsBuilt(player) then return end
    local looks, found = 0, false
    player:RegisterEvent(function(_, _, _, p)
        looks = looks + 1
        if not p or found or isBot(p) then return end
        local n = adopt(p)
        if n > 0 then
            found = true
            say(p, plural(n, "bot") .. (n == 1 and " is" or " are") .. " back with you. (.dismiss all sends them home)")
            pushRoster(p)
        end
    end, LOGIN_LOOK_MS, LOGIN_LOOKS)
end

local function onLogout(event, player)
    if not player then return end
    local guid = player:GetGUIDLow()
    companions[guid], pending[guid], ticking[guid], raidWanted[guid] = nil, nil, nil, nil
    orders[guid], replyTo[guid], lastPrepare[guid], rate[guid] = nil, nil, nil, nil
    -- A normal logout: the module logs the bots out with the player, so the ownership rows go. (A crash never
    -- gets here: the rows stay for adopt.)
    if not isBot(player) then ownForgetOwner(guid) end
end

RegisterPlayerEvent(3, onLogin)         -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, onLogout)        -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(13, onLevelChange)  -- PLAYER_EVENT_ON_LEVEL_CHANGE
RegisterPlayerEvent(42, onCommand)      -- PLAYER_EVENT_ON_COMMAND

-- for stream/tests/test_ov_companions.lua (read only)
OV_COMPANIONS_TEST = { companions = companions, pending = pending, realmCount = realmCount, ROLES = ROLES,
    planRoles = planRoles, SHAPE = SHAPE, specsFor = specsFor, specRole = specRole, adopt = adopt, orders = orders,
    pushRoster = pushRoster, window = OVMod ~= nil }
