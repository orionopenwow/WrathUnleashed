-- OVQoL: small quality-of-life addon for WrathUnleashed (WoW 3.3.5a, Interface 30300).
-- Runs in the stock 3.3.5a client and in the browser client (same addon API). Lua 5.1 only.
--
--   /qol                 show every feature and whether it is on
--   /qol sell            toggle: sell gray items when a merchant opens
--   /qol repair          toggle: repair all when a merchant can repair
--   /qol guild           toggle: try the guild bank first when repairing
--   /qol coords          toggle: player coordinates under the minimap
--   /qol loot            toggle: auto loot (sets the autoLootDefault CVar)
--   /qol quests          toggle: auto-accept and auto-turn-in quests (hold Shift for manual)
--   /qol gryphons        toggle: hide the gryphons at the ends of the main action bar
--   /qol reset           back to the defaults
--
-- Safety: nothing here is a secure/protected action. No Blizzard function is replaced or hooked.
-- The only Blizzard UI touched is the two gryphon textures, and only outside combat. Every API is
-- checked before use so a client missing one just skips that feature.
-- Not included on purpose: auto-releasing or hiding the "Release Spirit" popup. Hiding it can
-- leave a player with no button to release, and auto-release throws away soulstones, Reincarnation
-- and battle resurrections, so it was judged too risky.

local ADDON = "OVQoL"
local TAG = "|cff66ccffOVQoL|r: "

local DEFAULTS = {
    sell = true,
    repair = true,
    guild = true,
    coords = true,
    loot = false,      -- only touches the CVar once you toggle it
    quests = false,    -- off by default: it changes how every quest NPC behaves
    gryphons = false,  -- false = gryphons shown (stock look)
}

local FEATURES = {
    { key = "sell",     label = "Sell gray items at merchants" },
    { key = "repair",   label = "Auto-repair at merchants" },
    { key = "guild",    label = "  ...using the guild bank first" },
    { key = "coords",   label = "Coordinates under the minimap" },
    { key = "loot",     label = "Auto loot (autoLootDefault CVar)" },
    { key = "quests",   label = "Auto-accept / turn-in quests (Shift = manual)" },
    { key = "gryphons", label = "Hide main bar gryphons" },
}

local db
local frame = CreateFrame("Frame", "OVQoLEventFrame")
local wipe = wipe or function(t) for k in pairs(t) do t[k] = nil end return t end

local function msg(text)
    if DEFAULT_CHAT_FRAME and DEFAULT_CHAT_FRAME.AddMessage then
        DEFAULT_CHAT_FRAME:AddMessage(TAG .. text)
    end
end

local reported = {}
local function safe(name, fn, ...)
    local ok, err = pcall(fn, ...)
    if not ok and not reported[name] then
        reported[name] = true
        msg("|cffff6060" .. name .. " turned itself off for this session: " .. tostring(err) .. "|r")
    end
    return ok
end

local function money(c)
    c = math.floor(tonumber(c) or 0)
    local g, s, cp = math.floor(c / 10000), math.floor((c % 10000) / 100), c % 100
    if g > 0 then return string.format("%dg %ds %dc", g, s, cp) end
    if s > 0 then return string.format("%ds %dc", s, cp) end
    return string.format("%dc", cp)
end

local function inCombat()
    return InCombatLockdown and InCombatLockdown()
end

-- A tiny delay helper (3.3.5 has no C_Timer).
local timers = {}
local timerFrame = CreateFrame("Frame")
timerFrame:Hide()
timerFrame:SetScript("OnUpdate", function(self, elapsed)
    local now = GetTime and GetTime() or 0
    for i = #timers, 1, -1 do
        local t = timers[i]
        if now >= t.at then
            table.remove(timers, i)
            safe(t.name, t.fn)
        end
    end
    if #timers == 0 then self:Hide() end
end)
local function after(seconds, name, fn)
    if not GetTime then return end
    timers[#timers + 1] = { at = GetTime() + seconds, name = name, fn = fn }
    timerFrame:Show()
end

------------------------------------------------------------------------------------------------
-- Sell gray items
------------------------------------------------------------------------------------------------
local merchantOpen = false
local sellQueue = {}
local sellTotal, sellCount = 0, 0
local sellFrame = CreateFrame("Frame")
sellFrame:Hide()

local function merchantStillOpen()
    if not merchantOpen then return false end
    if MerchantFrame and MerchantFrame.IsShown and not MerchantFrame:IsShown() then return false end
    return true
end

local SELL_INTERVAL = 0.2
local sellElapsed = 0
sellFrame:SetScript("OnUpdate", function(self, elapsed)
    sellElapsed = sellElapsed + elapsed
    if sellElapsed < SELL_INTERVAL then return end
    sellElapsed = 0
    -- Never call UseContainerItem without a merchant: it would use/equip the item instead.
    if not merchantStillOpen() then
        wipe(sellQueue)
        self:Hide()
        return
    end
    local job = table.remove(sellQueue, 1)
    if job then
        local link = GetContainerItemLink(job.bag, job.slot)
        local _, _, locked = GetContainerItemInfo(job.bag, job.slot)
        if link == job.link and not locked then
            UseContainerItem(job.bag, job.slot)
            sellTotal = sellTotal + job.value
            sellCount = sellCount + 1
        end
    end
    if #sellQueue == 0 then
        self:Hide()
        if sellCount > 0 then
            msg(string.format("Sold %d gray item%s for %s.", sellCount, sellCount == 1 and "" or "s", money(sellTotal)))
        end
    end
end)

local function sellGrays()
    if not (GetContainerNumSlots and GetContainerItemLink and GetContainerItemInfo and UseContainerItem and GetItemInfo) then
        return
    end
    wipe(sellQueue)
    sellTotal, sellCount, sellElapsed = 0, 0, 0
    local lastBag = NUM_BAG_SLOTS or 4
    for bag = 0, lastBag do
        local slots = GetContainerNumSlots(bag) or 0
        for slot = 1, slots do
            local link = GetContainerItemLink(bag, slot)
            if link then
                local _, count, locked = GetContainerItemInfo(bag, slot)
                -- Quality and vendor price from GetItemInfo: 3rd and 11th returns in 3.3.5.
                local _, _, quality, _, _, _, _, _, _, _, price = GetItemInfo(link)
                if quality == 0 and price and price > 0 and not locked then
                    sellQueue[#sellQueue + 1] = { bag = bag, slot = slot, link = link, value = price * (count or 1) }
                end
            end
        end
    end
    if #sellQueue > 0 then sellFrame:Show() end
end

------------------------------------------------------------------------------------------------
-- Auto-repair
------------------------------------------------------------------------------------------------
local durabilityChanged = false

local function guildCanCover(cost)
    if not (CanGuildBankRepair and CanGuildBankRepair()) then return false end
    if GetGuildBankWithdrawMoney then
        local left = GetGuildBankWithdrawMoney()
        -- -1 (or a huge number) means no daily limit, e.g. the guild master.
        if left and left >= 0 and left < cost then return false end
    end
    if GetGuildBankMoney then
        local bank = GetGuildBankMoney()
        -- 0 can also mean "not loaded yet"; let the server decide in that case.
        if bank and bank > 0 and bank < cost then return false end
    end
    return true
end

local function repairWithOwnGold(note)
    if not (GetRepairAllCost and RepairAllItems and GetMoney) then return end
    if not merchantStillOpen() then return end
    local cost, canRepair = GetRepairAllCost()
    if not canRepair or not cost or cost <= 0 then return end
    if GetMoney() < cost then
        msg("Not enough gold to repair (" .. money(cost) .. ").")
        return
    end
    RepairAllItems()
    msg("Repaired for " .. money(cost) .. (note or "") .. ".")
end

local function autoRepair()
    if not (CanMerchantRepair and CanMerchantRepair()) then return end
    if not (GetRepairAllCost and RepairAllItems) then return end
    local cost, canRepair = GetRepairAllCost()
    if not canRepair or not cost or cost <= 0 then return end

    if db.guild and IsInGuild and IsInGuild() and guildCanCover(cost) then
        durabilityChanged = false
        RepairAllItems(1) -- 1 = pay from the guild bank
        msg("Repairing for " .. money(cost) .. " from the guild bank.")
        -- A successful repair sends UPDATE_INVENTORY_DURABILITY. If none came and the bill is
        -- unchanged, the guild bank refused (limit or funds): pay ourselves.
        after(1.5, "Auto-repair", function()
            if durabilityChanged then return end
            local now = GetRepairAllCost()
            if now and now == cost then repairWithOwnGold(" (the guild bank could not cover it)") end
        end)
        return
    end
    repairWithOwnGold()
end

------------------------------------------------------------------------------------------------
-- Coordinates under the minimap
------------------------------------------------------------------------------------------------
local coordFrame, coordText
local coordElapsed = 0

local function coordsUpdate(self, elapsed)
    coordElapsed = coordElapsed + elapsed
    if coordElapsed < 0.2 then return end
    coordElapsed = 0
    local x, y = GetPlayerMapPosition("player")
    if not x or not y or (x == 0 and y == 0) then
        coordText:SetText("--, --")
    else
        coordText:SetFormattedText("%.1f, %.1f", x * 100, y * 100)
    end
end

local function mapToZone()
    -- Only when the world map is closed, so we never yank the map the player is looking at.
    if SetMapToCurrentZone and not (WorldMapFrame and WorldMapFrame:IsShown()) then
        SetMapToCurrentZone()
    end
end

local function applyCoords()
    if not GetPlayerMapPosition or not Minimap then return end
    if not coordFrame then
        coordFrame = CreateFrame("Frame", "OVQoLCoords", UIParent)
        coordFrame:SetWidth(90)
        coordFrame:SetHeight(16)
        coordFrame:SetPoint("TOP", Minimap, "BOTTOM", 0, -14)
        coordFrame:SetFrameStrata("LOW")
        coordText = coordFrame:CreateFontString(nil, "OVERLAY", "GameFontNormalSmall")
        coordText:SetPoint("CENTER")
        coordText:SetText("--, --")
    end
    if db.coords then
        mapToZone()
        coordFrame:SetScript("OnUpdate", coordsUpdate)
        coordFrame:Show()
    else
        coordFrame:SetScript("OnUpdate", nil)
        coordFrame:Hide()
    end
end

------------------------------------------------------------------------------------------------
-- Auto loot CVar
------------------------------------------------------------------------------------------------
local function applyLoot()
    if SetCVar then SetCVar("autoLootDefault", db.loot and "1" or "0") end
end

------------------------------------------------------------------------------------------------
-- Gryphons
------------------------------------------------------------------------------------------------
local gryphonsPending = false
local function applyGryphons()
    if inCombat() then
        gryphonsPending = true -- do it when combat ends
        return
    end
    gryphonsPending = false
    for _, name in ipairs({ "MainMenuBarLeftEndCap", "MainMenuBarRightEndCap" }) do
        local tex = _G[name]
        if tex and tex.Hide and tex.Show then
            if db.gryphons then tex:Hide() else tex:Show() end
        end
    end
end

------------------------------------------------------------------------------------------------
-- Quests: auto-accept and auto-turn-in, Shift held = do it yourself
------------------------------------------------------------------------------------------------
local function questsActive()
    if not db.quests then return false end
    if IsShiftKeyDown and IsShiftKeyDown() then return false end
    return true
end

local function onGossipShow()
    -- Turn in finished quests first. GetGossipActiveQuests returns 4 values per quest in 3.3:
    -- title, level, isTrivial, isComplete. If the count doesn't fit that shape, skip turn-ins.
    if GetGossipActiveQuests and SelectGossipActiveQuest then
        local n = select("#", GetGossipActiveQuests())
        if n > 0 and n % 4 == 0 then
            local data = { GetGossipActiveQuests() }
            for i = 1, n / 4 do
                if data[(i - 1) * 4 + 4] then
                    SelectGossipActiveQuest(i)
                    return
                end
            end
        end
    end
    if GetNumGossipAvailableQuests and SelectGossipAvailableQuest then
        if (GetNumGossipAvailableQuests() or 0) > 0 then
            SelectGossipAvailableQuest(1)
        end
    end
end

local function onQuestGreeting()
    if GetNumAvailableQuests and SelectAvailableQuest and (GetNumAvailableQuests() or 0) > 0 then
        SelectAvailableQuest(1)
        return
    end
    -- The greeting frame doesn't say which active quests are done; only open the single one.
    if GetNumActiveQuests and SelectActiveQuest and (GetNumActiveQuests() or 0) == 1 then
        SelectActiveQuest(1)
    end
end

local function onQuestDetail()
    if AcceptQuest then AcceptQuest() end
end

local function onQuestProgress()
    if IsQuestCompletable and CompleteQuest and IsQuestCompletable() then
        CompleteQuest()
    end
end

local function onQuestComplete()
    if not GetQuestReward then return end
    local choices = GetNumQuestChoices and GetNumQuestChoices() or 0
    if choices > 1 then
        msg("Pick your reward (more than one choice).")
        return
    end
    -- 3.3.5 QuestFrame passes 0 when there is nothing to choose, 1 for a single choice.
    GetQuestReward(choices == 1 and 1 or 0)
end

------------------------------------------------------------------------------------------------
-- Settings and slash command
------------------------------------------------------------------------------------------------
local function applyAll(fromToggle)
    safe("Coordinates", applyCoords)
    safe("Gryphons", applyGryphons)
    if fromToggle == "loot" then safe("Auto loot", applyLoot) end
end

local function status()
    msg("settings (type /qol <name> to toggle):")
    for _, f in ipairs(FEATURES) do
        local on = db[f.key] and "|cff00ff00on|r" or "|cff808080off|r"
        DEFAULT_CHAT_FRAME:AddMessage(string.format("  |cffffd100%s|r  %s  %s", f.key, on, f.label))
    end
    DEFAULT_CHAT_FRAME:AddMessage("  |cffffd100reset|r  restore defaults.  Server side: type .qol")
end

local ALIASES = {
    grays = "sell", grey = "sell", gray = "sell", junk = "sell",
    repairs = "repair", gbank = "guild", coord = "coords", coordinates = "coords",
    autoloot = "loot", quest = "quests", gryphon = "gryphons", endcaps = "gryphons",
}

local function slash(input)
    input = string.lower(input or ""):gsub("^%s+", ""):gsub("%s+$", "")
    local key = ALIASES[input] or input
    if key == "" or key == "help" or key == "status" then
        status()
        return
    end
    if key == "reset" then
        for k, v in pairs(DEFAULTS) do db[k] = v end
        applyAll()
        msg("defaults restored.")
        return
    end
    if DEFAULTS[key] == nil then
        msg("unknown option '" .. input .. "'.")
        status()
        return
    end
    db[key] = not db[key]
    applyAll(key)
    msg(key .. " is now " .. (db[key] and "|cff00ff00on|r" or "|cff808080off|r") ..
        ((key == "gryphons" and inCombat()) and " (after combat)" or "") .. ".")
end

SLASH_OVQOL1 = "/qol"
SlashCmdList["OVQOL"] = slash

------------------------------------------------------------------------------------------------
-- Events
------------------------------------------------------------------------------------------------
local handlers = {}

function handlers.ADDON_LOADED(name)
    if name ~= ADDON then return end
    if type(OVQoLDB) ~= "table" then OVQoLDB = {} end
    for k, v in pairs(DEFAULTS) do
        if OVQoLDB[k] == nil then OVQoLDB[k] = v end
    end
    db = OVQoLDB
end

function handlers.PLAYER_LOGIN()
    applyAll()
end

function handlers.MERCHANT_SHOW()
    merchantOpen = true
    if db.repair then safe("Auto-repair", autoRepair) end -- repair before selling
    if db.sell then safe("Sell grays", sellGrays) end
end

function handlers.MERCHANT_CLOSED()
    merchantOpen = false
    wipe(sellQueue)
end

function handlers.UPDATE_INVENTORY_DURABILITY()
    durabilityChanged = true
end

function handlers.ZONE_CHANGED_NEW_AREA()
    if db.coords then safe("Coordinates", mapToZone) end
end

function handlers.PLAYER_REGEN_ENABLED()
    if gryphonsPending then safe("Gryphons", applyGryphons) end
end

function handlers.GOSSIP_SHOW()     if questsActive() then safe("Quests", onGossipShow) end end
function handlers.QUEST_GREETING()  if questsActive() then safe("Quests", onQuestGreeting) end end
function handlers.QUEST_DETAIL()    if questsActive() then safe("Quests", onQuestDetail) end end
function handlers.QUEST_PROGRESS()  if questsActive() then safe("Quests", onQuestProgress) end end
function handlers.QUEST_COMPLETE()  if questsActive() then safe("Quests", onQuestComplete) end end

frame:SetScript("OnEvent", function(self, event, ...)
    if event ~= "ADDON_LOADED" and not db then return end
    local h = handlers[event]
    if h then h(...) end
end)

for event in pairs(handlers) do
    frame:RegisterEvent(event)
end
