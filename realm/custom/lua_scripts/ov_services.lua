-- Open Vanilla WotLK realm: free player services (mod-ale).
-- Type .ov in chat for the menu. Nothing here is sold; every service is free.
--
--   Change faction / race / appearance: applied at your next login (the client's own screens).
--   Boost to 70: only when the realm profile sets OV_BOOST_TO_70=1 (the "casual" profile).

local MENU_ID = 61000
local TEXT_ID = 100 -- AzerothCore's stock "Greetings, $N" gossip text

local AT_LOGIN_CUSTOMIZE      = 0x08
local AT_LOGIN_CHANGE_FACTION = 0x40
local AT_LOGIN_CHANGE_RACE    = 0x80

local BOOST_LEVEL = 70
local BOOST_SPELLS = { 33388, 33391, 34090 } -- Apprentice, Journeyman, Expert Riding
local BOOST_BAG = 41599                      -- Frostweave Bag (20 slots)
local BOOST_GOLD = 500 * 10000
local BOOST_KITS_PER_ACCOUNT = 10

local function boostEnabled()
    return os.getenv("OV_BOOST_TO_70") == "1"
end

local function showMenu(player)
    player:GossipClearMenu()
    player:GossipMenuAddItem(0, "Change my faction (at next login)", 0, 1)
    player:GossipMenuAddItem(0, "Change my race (at next login)", 0, 2)
    player:GossipMenuAddItem(0, "Change my appearance and name (at next login)", 0, 3)
    if boostEnabled() and player:GetLevel() < BOOST_LEVEL then
        player:GossipMenuAddItem(0, "Boost this character to " .. BOOST_LEVEL, 0, 4)
    end
    player:GossipMenuAddItem(0, "Close", 0, 99)
    player:GossipSendMenu(TEXT_ID, player, MENU_ID)
end

local function relogNote(player, what)
    player:SaveToDB()
    player:SendBroadcastMessage("|cff66ccff[Open Vanilla]|r " .. what .. " is ready: log out to the character list to use it.")
end

local function onSelect(event, player, object, sender, intid, code, menuId)
    if intid == 1 then
        player:SetAtLoginFlag(AT_LOGIN_CHANGE_FACTION)
        relogNote(player, "Faction change")
    elseif intid == 2 then
        player:SetAtLoginFlag(AT_LOGIN_CHANGE_RACE)
        relogNote(player, "Race change")
    elseif intid == 3 then
        player:SetAtLoginFlag(AT_LOGIN_CUSTOMIZE)
        relogNote(player, "Appearance change")
    elseif intid == 4 and boostEnabled() and player:GetLevel() < BOOST_LEVEL then
        player:SetLevel(BOOST_LEVEL)
        for _, spell in ipairs(BOOST_SPELLS) do
            if not player:HasSpell(spell) then player:LearnSpell(spell) end
        end
        local account = player:GetAccountId()
        local kits = CharDBQuery(string.format("SELECT COUNT(*) AS n FROM ov_boosts WHERE account_id = %d", account))
        local withKit = not kits or kits:GetUInt32(0) < BOOST_KITS_PER_ACCOUNT
        CharDBExecute(string.format("INSERT IGNORE INTO ov_boosts (char_guid, account_id, boosted_at) VALUES (%d, %d, %d)",
            player:GetGUIDLow(), account, os.time()))
        if withKit then
            player:AddItem(BOOST_BAG, 4)
            player:ModifyMoney(BOOST_GOLD)
        end
        player:SaveToDB()
        player:SendBroadcastMessage("|cff66ccff[Open Vanilla]|r Boosted to " .. BOOST_LEVEL .. ". Visit your class trainer for your spells." ..
            (withKit and "" or " (This account has had its " .. BOOST_KITS_PER_ACCOUNT .. " boost gold and bag kits.)"))
    end
    player:GossipComplete()
end

local function onCommand(event, player, command)
    if not player then return end
    local cmd = (command or ""):gsub("^[%.!]", ""):lower()
    if cmd == "ov" or cmd == "services" then
        showMenu(player)
        return false
    end
end

CharDBExecute([[CREATE TABLE IF NOT EXISTS ov_boosts (
    char_guid INT UNSIGNED NOT NULL PRIMARY KEY,
    account_id INT UNSIGNED NOT NULL,
    boosted_at INT UNSIGNED NOT NULL,
    KEY account (account_id)
)]])
RegisterPlayerEvent(42, onCommand)
RegisterPlayerGossipEvent(MENU_ID, 2, onSelect)
