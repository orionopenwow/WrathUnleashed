-- Wrath Brawl (WrathUnleashed): professions maxed at first login. Runs on the custom realm
-- image (mod-ale) when the "brawl" profile is on (profiles/brawl.env sets OV_BRAWL=1).
-- brawl_world_2.sql teaches the Grand Master ranks and recipes; this raises each skill to 450.

local PROFESSIONS = {
    164, 165, 171, 182, 186, 197, 202, 333, 393, 755, 773, -- primary
    185, 129, 356,                                           -- cooking, first aid, fishing
}
local GRAND_MASTER_STEP = 6
local MAX_VALUE = 450

local function onFirstLogin(event, player)
    if os.getenv("OV_BRAWL") ~= "1" then return end
    for _, skill in ipairs(PROFESSIONS) do
        if player:HasSkill(skill) then
            player:SetSkill(skill, GRAND_MASTER_STEP, MAX_VALUE, MAX_VALUE)
        end
    end
    player:SaveToDB()
end

RegisterPlayerEvent(30, onFirstLogin) -- PLAYER_EVENT_ON_FIRST_LOGIN
