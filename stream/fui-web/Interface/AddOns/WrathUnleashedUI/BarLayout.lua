-- Bar layout fixes on top of Forever UI (3.3.5a API), from live screenshots (2026-10-25 01:15):
--  * Bottom left / bottom right bars: Forever UI puts them side by side with offsets from a fixed
--    main-bar width, which drift right of our main bar. Here they sit side by side in ONE row just
--    above the main bar (owner, 03:27: "next to each other", not stacked): the Shift bar starts at
--    the main bar's left edge, the Ctrl bar right after it, both measured from the real frames.
--    The stance, pet and totem bars rise above that one row (MultiBars.Lift).
--  * Right bars: 9 units further in, so their key labels stay on screen.
--  * Totem bar: only for a shaman from level 30 (Call of the Elements); before that it showed as
--    a stray "Fire" button.
-- A bar the player moved in edit mode keeps its place (Layout.IsDefault). Secure frames: out of
-- combat only.
-- "Bars are broken sometimes" (2026-10-30):
--  * the main bar could not be measured yet 1.5 s after the event (a slow first load in the browser): the layout
--    gave up until the next event and the two bars stayed where Forever UI puts them, off our main bar. It now
--    tries again every 1.5 s, up to TRIES times;
--  * the one-row Lift replaced Forever UI's own, which keeps the last height while a vehicle bar replaces the
--    player's bars (the client hides the bottom bars then): leaving a vehicle in combat, the stance and pet bars
--    came back one row low. That case is Forever UI's again.

local ROW_Y, ROW_STEP, COL_GAP = 70, 45 + 4, 6
local BUTTONS, PITCH = 12, 47   -- fallback width when a bar frame can't be measured yet
local RIGHT_X, RIGHT_GAP = -14, 5

local TRIES = 8

local function F() return ForeverUI end

local function stacked()
    local M = F() and F().MultiBars
    if not M or not M.bars then return end
    local holder = _G["ForeverUIActionBarHolder"]
    local left = holder and holder:GetLeft()
    local width = UIParent:GetWidth()
    if not left or not width or width <= 0 then return end
    local x = left * (holder:GetEffectiveScale() / UIParent:GetEffectiveScale()) - width / 2
    local b1, b2, r1, r2 = M.bars[1], M.bars[2], M.bars[3], M.bars[4]
    -- bar 1's width in UIParent units (its own frame when it has one, else 12 buttons)
    local w1 = BUTTONS * PITCH
    local fr = b1 and b1.frame
    if fr and fr.GetWidth and fr:GetWidth() and fr:GetWidth() > 0 then
        w1 = fr:GetWidth() * (fr:GetEffectiveScale() / UIParent:GetEffectiveScale())
    end
    if b1 then b1.x, b1.y = x, ROW_Y end
    if b2 then b2.x, b2.y = x + w1 + COL_GAP, ROW_Y end
    if r1 then r1.x = RIGHT_X end
    if r2 then r2.x = RIGHT_X - 45 - RIGHT_GAP end
    local L = F().Layout
    if L and L.SetDefaults then
        for _, b in ipairs({ b1, b2 }) do
            if b and b.id then pcall(L.SetDefaults, b.id, "BOTTOMLEFT", "BOTTOM", b.x, b.y) end
        end
    end
    return true
end

-- The bottom bars share one row: the bars above them rise one row when either is shown.
local function patchLift()
    local M = F() and F().MultiBars
    if not M or M.wuLift then return end
    M.wuLift = true
    local own = M.Lift
    M.Lift = function()
        -- in a vehicle (or a client swap before Vehicle.lua heard of it) Forever UI keeps the last height
        if own and (F().VehicleArt or (MainMenuBar and MainMenuBar.state == "vehicle")) then return own() end
        local L, n = F().Layout, 0
        for k = 1, 2 do
            local bar = M.bars[k]
            if bar and bar.frame and bar.frame:IsShown() and (not L or not L.IsDefault or L.IsDefault(bar.id)) then
                n = n + 1
            end
        end
        return n > 0 and ROW_STEP or 0
    end
end

local function totems()
    local bar = _G["MultiCastActionBarFrame"]
    if not bar then return end
    local _, class = UnitClass("player")
    local want = class == "SHAMAN" and (UnitLevel("player") or 0) >= 30
    if not want and bar:IsShown() then bar:Hide() end
    if not bar.wuHooked then
        bar.wuHooked = true
        bar:HookScript("OnShow", function(self)
            local _, c = UnitClass("player")
            if not (c == "SHAMAN" and (UnitLevel("player") or 0) >= 30) and not InCombatLockdown() then self:Hide() end
        end)
    end
end

local function apply()
    if InCombatLockdown() or not ForeverUI then return false end
    patchLift()
    local ok = stacked()
    totems()
    local M = ForeverUI.MultiBars
    if M and M.Restack then pcall(M.Restack) end
    return ok
end

local f = CreateFrame("Frame")
for _, e in ipairs({ "PLAYER_ENTERING_WORLD", "DISPLAY_SIZE_CHANGED", "UI_SCALE_CHANGED", "PLAYER_LEVEL_UP", "PLAYER_REGEN_ENABLED" }) do
    f:RegisterEvent(e)
end
local wait, pending, tries = 0, false, 0
-- apply() is false in combat (again after the fight: PLAYER_REGEN_ENABLED), nil while the main bar can't be
-- measured yet (again in 1.5 s, TRIES times), true once placed.
local function schedule()
    wait = 0
    -- a moment after Forever UI has placed its main bar
    f:SetScript("OnUpdate", function(self, elapsed)
        wait = wait + elapsed
        if wait < 1.5 then return end
        self:SetScript("OnUpdate", nil)
        local ok = apply()
        if ok == true then
            pending = false
        elseif ok == nil then
            tries = tries + 1
            if tries < TRIES then schedule() else pending = false end
        end
    end)
end
f:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_REGEN_ENABLED" and not pending then return end
    pending, tries = true, 0
    schedule()
end)

WrathUnleashedUI = WrathUnleashedUI or {}
WrathUnleashedUI.FixBars = apply
