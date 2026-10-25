-- ov_companions.lua: Companions, bot party members for solo players and small groups (mod-ale, 3.3.5a).
--
--   .companions                     help, your companions and the limits (.companions list is the same)
--   .recruit tank|healer|dps [n]    recruits n (default 1) into your group at your level; .recruit dps mage picks
--                                   the class. A 5-player party by default (OV_COMPANIONS_GROUP_MAX).
--   .buddy [class]                  one levelling buddy: your level, follows you, re-matched when you level up;
--                                   .buddy shows it once you have one, .buddy off dismisses it
--   .dismiss [name|all]             sends companions home (alone: the only one, or a list to pick from)
--
-- This drives mod-playerbots (the realm image's core is its fork, custom/sources.lock); none of the bot AI is
-- here. Everything goes through the player's own chat commands (Player:RunCommand, run as if typed, with the
-- player's own security) and whispers to the bot (Player:Whisper reaches mod-playerbots' OnPlayerCanUseChat):
--   .playerbots bot addclass <class>    an addclass-pool character of the player's faction logs in, is levelled
--                                       and geared to the player when 4+ levels apart, and joins the player's
--                                       group (mod-playerbots PlayerbotMgr.cpp, e88cc40)
--   .playerbots bot init=auto <name>    re-levels / re-gears an addclass bot to the player (gear-score capped)
--   .playerbots bot remove <name>       logs it out
--   whisper "talents spec <premade>"    the role's premade spec (Playerbots.PremadeSpecName.<class>.<n>)
--   whisper "follow"
-- The bot logs in asynchronously, so .recruit only queues; a timer on the player (every 2 s, 8 times) claims the
-- addclass bots that join the group, teleports them over in the open world, matches the level, sets the spec.
-- Recruits that never arrive (no free character of that class in the pool) expire with a message.
--
-- Without mod-playerbots (the stock image: no Player:IsPlayerbot method) every command answers "Companions are
-- coming soon"; realm/companions-README.md lists what the build needs.
--
-- Env (os.getenv at each use; "1" on, "0" off; defaults = the main profile's conservative values):
--   OV_COMPANIONS                on/off                                         default 1
--   OV_COMPANIONS_PER_PLAYER     companions one player may have (buddy included) default 4
--   OV_COMPANIONS_REALM_MAX      companions on the whole realm at once          default 40
--   OV_COMPANIONS_GROUP_MAX      the group size .recruit fills up to (5 party, up to 40 raid)  default 5
--   OV_COMPANIONS_COOLDOWN       seconds between two .recruit / .buddy         default 30
--   OV_COMPANIONS_BUDDY          .buddy on/off                                  default 1
--   OV_REALM_NAME / OV_NETWORK_NAME  names shown to players                     "Wrath" / "Leyline"
-- mod-playerbots' own Playerbots.MaxAddedBots (AC_PLAYERBOTS_MAX_ADDED_BOTS) is the hard cap behind these.
-- mod-ale events: 4 ON_LOGOUT, 13 ON_LEVEL_CHANGE, 42 ON_COMMAND (return false = handled).

local TAG = "|cff66ccff[Companions]|r "

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

local function onSwitch()    return flag("OV_COMPANIONS", true) end
local function buddyOn()     return flag("OV_COMPANIONS_BUDDY", true) end
local function perPlayer()   return num("OV_COMPANIONS_PER_PLAYER", 4, 0, 39) end
local function realmMax()    return num("OV_COMPANIONS_REALM_MAX", 40, 0, 2000) end
local function groupMax()    return num("OV_COMPANIONS_GROUP_MAX", 5, 2, 40) end
local function cooldown()    return num("OV_COMPANIONS_COOLDOWN", 30, 0, 3600) end
local function realmName()
    local n = os.getenv("OV_REALM_NAME")
    if n and n ~= "" then return n end
    return "Wrath"
end
local function networkName()
    local n = os.getenv("OV_NETWORK_NAME")
    if n and n ~= "" then return n end
    return "Leyline"
end

local function say(player, text) player:SendBroadcastMessage(TAG .. text) end

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

local function isBot(p)
    if try(p, "IsPlayerbot") == true or try(p, "IsBot") == true then return true end
    local name = try(p, "GetAccountName")
    return type(name) == "string" and name:upper():find("^RNDBOT") ~= nil
end

-- A bot of the addclass pool (the only kind .recruit makes); alt bots of the player's own account are theirs.
local function isAddclassBot(owner, m)
    local v = try(m, "IsAddclassBot")
    if v ~= nil then return v == true end
    return isBot(m) and try(m, "GetAccountId") ~= owner:GetAccountId()
end

local function inInstance(player)
    if try(player, "InBattleground") or try(player, "InArena") then return true end
    local map = try(player, "GetMap")
    return map ~= nil and (try(map, "IsBattlegroundOrArena") or try(map, "IsDungeon") or try(map, "IsRaid")) == true
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
    dps    = { label = "damage dealer", picks = { { "mage", "frost pve" }, { "hunter", "mm pve" },
                                           { "rogue", "combat pve" }, { "warlock", "affli pve" },
                                           { "shaman", "ele pve" }, { "priest", "shadow pve" },
                                           { "warrior", "fury pve" }, { "dk", "frost pve" } } },
}
local ROLE_ALIAS = { heal = "healer", heals = "healer", healers = "healer", tanks = "tank", damage = "dps",
    dd = "dps", melee = "dps", caster = "dps" }
local BUDDY_CLASSES = { "warrior", "paladin", "hunter", "rogue", "priest", "shaman", "mage", "warlock", "druid", "dk" }

local function dkLevel()
    return tonumber(os.getenv("AC_START_HEROIC_PLAYER_LEVEL") or "") or 55
end

local function classOf(word)
    word = CLASS_ALIAS[word] or word
    return CLASS[word] and word or nil
end

------------------------------------------------------------------------------------------------
-- state (per world server run; mod-playerbots logs a player's bots out when the player logs out)
------------------------------------------------------------------------------------------------
local companions = {}   -- [ownerGuid] = { [botGuid] = { name, cls, role, buddy } }
local pending = {}      -- [ownerGuid] = { { cls, word, spec, role, buddy, at }, ... }
local lastRecruit = {}  -- [ownerGuid] = os.time()
local ticking = {}      -- [ownerGuid] = the running arrival timer's number

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

local function buddyOf(guid)
    for bg, c in pairs(companions[guid] or {}) do if c.buddy then return bg, c end end
    for _, p in ipairs(pending[guid] or {}) do if p.buddy then return nil, p end end
    return nil
end

-- Drop companions that left the group or logged out (the player kicked them, or a server hiccup).
local function prune(player)
    local guid = player:GetGUIDLow()
    local list = companions[guid]
    if not list then return end
    local inGroup = {}
    local _, members = groupMembers(player)
    for _, m in ipairs(members) do inGroup[m:GetGUIDLow()] = m end
    for bg in pairs(list) do
        if not inGroup[bg] then list[bg] = nil end
    end
end

local function safeName(n) return (tostring(n or ""):gsub("[^%a]", ""):sub(1, 12)) end

local function botCommand(owner, text) owner:RunCommand("playerbots bot " .. text) end
local function whisper(owner, bot, text) try(owner, "Whisper", text, 0, bot) end

------------------------------------------------------------------------------------------------
-- arrival: claim the addclass bots that joined, set them up
------------------------------------------------------------------------------------------------
local function claimed(botGuid)
    for _, list in pairs(companions) do if list[botGuid] then return true end end
    return false
end

local function setUp(owner, m, p)
    local name = safeName(m:GetName())
    if not inInstance(owner) then
        local far = try(m, "GetMapId") ~= try(owner, "GetMapId")
        local d = tonumber(try(m, "GetDistance", owner))
        if far or (d and d > TELEPORT_DISTANCE) then
            try(m, "Teleport", owner:GetMapId(), owner:GetX(), owner:GetY(), owner:GetZ(), owner:GetO())
        end
    end
    if m:GetLevel() ~= owner:GetLevel() and name ~= "" then
        botCommand(owner, "init=auto " .. name)
    end
    if p.spec then whisper(owner, m, "talents spec " .. p.spec) end
    whisper(owner, m, "follow")
end

local function arrivals(owner)
    local guid = owner:GetGUIDLow()
    local list = pending[guid]
    if not list or #list == 0 then return end
    local _, members = groupMembers(owner)
    for _, m in ipairs(members) do
        local bg = m:GetGUIDLow()
        if bg ~= guid and isAddclassBot(owner, m) and not claimed(bg) then
            local cls, at = m:GetClass(), nil
            for i, p in ipairs(list) do if p.cls == cls then at = i; break end end
            if at then
                local p = table.remove(list, at)
                companions[guid] = companions[guid] or {}
                companions[guid][bg] = { name = m:GetName(), cls = cls, role = p.role, buddy = p.buddy }
                setUp(owner, m, p)
                if p.buddy then
                    say(owner, string.format("%s the %s is your levelling buddy. Say 'stay' or 'follow' in party chat.",
                        m:GetName(), CLASS_LABEL[cls] or "companion"))
                else
                    say(owner, string.format("%s the %s joins you as your %s.", m:GetName(), CLASS_LABEL[cls] or "companion",
                        ROLES[p.role] and ROLES[p.role].label or p.role))
                end
            end
        end
    end
end

local function expire(owner, final)
    local guid = owner:GetGUIDLow()
    local list = pending[guid]
    if not list then return end
    local now, kept, lost = os.time(), {}, 0
    for _, p in ipairs(list) do
        if final or now - p.at >= ARRIVE_TIMEOUT then lost = lost + 1 else kept[#kept + 1] = p end
    end
    pending[guid] = kept
    if lost > 0 then
        say(owner, string.format("%s didn't arrive (none free of that class right now). Try another class or role.",
            lost == 1 and "One companion" or (lost .. " companions")))
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
-- commands
------------------------------------------------------------------------------------------------
local function comingSoon(player)
    say(player, "Companions are coming soon to " .. realmName() .. " on " .. networkName() .. ".")
end

-- Shared checks for .recruit and .buddy; returns how many may be recruited now (0 = refused, already said why).
local function room(player, want)
    if not onSwitch() then say(player, "Companions are off on this realm."); return 0 end
    if try(player, "IsInCombat") then say(player, "Not in combat."); return 0 end
    if try(player, "IsDead") then say(player, "Not while dead."); return 0 end
    if inInstance(player) then say(player, "Recruit in the open world, before you go in."); return 0 end
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
    local cap, have = perPlayer(), mine(guid)
    local slots = groupMax() - groupSize(player) - #(pending[guid] or {})
    local realmLeft = realmMax() - realmCount()
    local n = math.min(want, cap - have, slots, realmLeft)
    if n <= 0 then
        if cap - have <= 0 then
            say(player, string.format("You have %s, the most allowed here (.dismiss to make room).", plural(have, "companion")))
        elseif slots <= 0 then
            say(player, string.format("Your group is full (%d players).", groupMax()))
        else
            say(player, "Every companion on the realm is out with someone right now; try again in a few minutes.")
        end
        return 0
    end
    return n
end

local function queue(player, list)
    local guid = player:GetGUIDLow()
    pending[guid] = pending[guid] or {}
    lastRecruit[guid] = os.time()
    for _, p in ipairs(list) do
        p.at = os.time()
        table.insert(pending[guid], p)
        botCommand(player, "addclass " .. p.word)
    end
    watchArrivals(player)
end

local function recruitCommand(player, roleWord, extra)
    roleWord = ROLE_ALIAS[roleWord or ""] or roleWord
    local role = ROLES[roleWord or ""]
    if not role then
        return say(player, "Usage: |cffffff00.recruit tank|healer|dps [n]|r  (or a class: .recruit dps mage)")
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
                return say(player, "A " .. role.label .. " can be: " .. table.concat(names, ", ") .. ".")
            end
        end
    end
    if want < 1 then return say(player, "Recruit at least one.") end
    local n = room(player, want)
    if n == 0 then return end
    local picks = {}
    for _, pk in ipairs(role.picks) do
        if (not onlyClass or pk[1] == onlyClass) and (pk[1] ~= "dk" or player:GetLevel() >= dkLevel()) then
            picks[#picks + 1] = pk
        end
    end
    if #picks == 0 then return say(player, "Death Knights join from level " .. dkLevel() .. ".") end
    local start = math.random(#picks)
    local list = {}
    for i = 1, n do
        local pk = picks[(start + i - 2) % #picks + 1]
        list[#list + 1] = { cls = CLASS[pk[1]], word = pk[1], spec = pk[2], role = roleWord }
    end
    queue(player, list)
    local msg = string.format("Recruiting %s: they join your group in a few seconds.", plural(n, role.label))
    if n < want then msg = msg .. string.format(" (%d of the %d asked: the limits here.)", n, want) end
    say(player, msg)
end

local function buddyCommand(player, arg)
    if not buddyOn() then return say(player, "The levelling buddy is off on this realm; try .recruit.") end
    local guid = player:GetGUIDLow()
    prune(player)
    local bg, b = buddyOf(guid)
    if arg == "off" or arg == "dismiss" or arg == "bye" then
        if not bg then return say(player, "You have no buddy with you.") end
        botCommand(player, "remove " .. safeName(b.name))
        companions[guid][bg] = nil
        return say(player, b.name .. " heads home.")
    end
    if b then
        if not bg then return say(player, "Your buddy is on the way.") end
        return say(player, string.format("Your buddy is %s the %s; they keep to your level. (.buddy off to send them home)",
            b.name, CLASS_LABEL[b.cls] or "companion"))
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
    say(player, "Your levelling buddy is on the way.")
end

local function dismissCommand(player, arg)
    local guid = player:GetGUIDLow()
    prune(player)
    local list = companions[guid] or {}
    local n = countOf(list)
    if n == 0 then
        pending[guid] = nil
        return say(player, "You have no companions with you.")
    end
    local gone = {}
    if arg == "all" then
        for bg, c in pairs(list) do gone[#gone + 1] = c.name; list[bg] = nil; botCommand(player, "remove " .. safeName(c.name)) end
        pending[guid] = nil
    elseif arg == "buddy" then
        return buddyCommand(player, "off")
    elseif arg or n == 1 then
        for bg, c in pairs(list) do
            if not arg or c.name:lower() == arg then
                gone[#gone + 1] = c.name; list[bg] = nil; botCommand(player, "remove " .. safeName(c.name))
                break
            end
        end
        if #gone == 0 then return say(player, "None of your companions is called " .. arg .. ".") end
    else
        local names = {}
        for _, c in pairs(list) do names[#names + 1] = c.name end
        table.sort(names)
        return say(player, "Dismiss which? |cffffff00.dismiss <name>|r or |cffffff00.dismiss all|r: " .. table.concat(names, ", "))
    end
    table.sort(gone)
    say(player, table.concat(gone, ", ") .. (#gone == 1 and " heads" or " head") .. " home.")
end

local function showHelp(player)
    say(player, "Companions on " .. realmName() .. ": party members who fight, heal and follow you.")
    say(player, "  |cffffff00.recruit tank|healer|dps [n]|r  recruit into your group, at your level (.recruit dps mage)")
    if buddyOn() then say(player, "  |cffffff00.buddy [class]|r  a levelling buddy who follows you and keeps to your level") end
    say(player, "  |cffffff00.dismiss [name|all]|r  send companions home")
    say(player, string.format("  Limits: %s per player, groups up to %d, .recruit every %d s.",
        plural(perPlayer(), "companion"), groupMax(), cooldown()))
    say(player, "  In party chat: follow, stay, attack, summon (or .summon).")
    prune(player)
    local names = {}
    for _, c in pairs(companions[player:GetGUIDLow()] or {}) do
        names[#names + 1] = c.name .. " (" .. (c.buddy and "buddy" or c.role) .. ")"
    end
    table.sort(names)
    if #names > 0 then say(player, "  With you: " .. table.concat(names, ", ")) end
end

------------------------------------------------------------------------------------------------
-- events
------------------------------------------------------------------------------------------------
local COMMANDS = { companions = true, companion = true, recruit = true, buddy = true, dismiss = true }

local function onCommand(event, player, command)
    if not player then return end
    local text = (command or ""):gsub("^[%.!]", ""):lower()
    local words = {}
    for w in text:gmatch("%S+") do words[#words + 1] = w end
    local cmd = words[1]
    if not COMMANDS[cmd] then return end
    if isBot(player) then return false end
    if not botsBuilt(player) then comingSoon(player); return false end
    if cmd == "companions" or cmd == "companion" then
        showHelp(player)
    elseif not onSwitch() then
        say(player, "Companions are off on this realm.")
    elseif cmd == "recruit" then
        recruitCommand(player, words[2], words[3])
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
                    whisper(p, m, "follow")
                    say(p, string.format("%s keeps up: level %d.", b.name, p:GetLevel()))
                end
            end
        end
    end, 3000, 1)
end

local function onLogout(event, player)
    if not player then return end
    local guid = player:GetGUIDLow()
    companions[guid], pending[guid], ticking[guid] = nil, nil, nil
end

RegisterPlayerEvent(4, onLogout)        -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(13, onLevelChange)  -- PLAYER_EVENT_ON_LEVEL_CHANGE
RegisterPlayerEvent(42, onCommand)      -- PLAYER_EVENT_ON_COMMAND

-- for stream/tests/test_ov_companions.lua (read only)
OV_COMPANIONS_TEST = { companions = companions, pending = pending, realmCount = realmCount, ROLES = ROLES }
