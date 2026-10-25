-- Bar layout fixes on top of Forever UI (3.3.5a API), from live screenshots (2026-10-25 01:15):
--  * Bottom left / bottom right bars: Forever UI puts them side by side with offsets from a fixed
--    main-bar width, which drift right of our main bar. Here they stack straight above the main
--    bar's 12 buttons, like today's default layout (bar 2 above bar 1, bar 3 above bar 2), and the
--    stance, pet and totem bars rise above both rows (MultiBars.Lift).
--  * Right bars: 9 units further in, so their key labels stay on screen.
--  * Totem bar: only for a shaman from level 30 (Call of the Elements); before that it showed as
--    a stray "Fire" button.
-- A bar the player moved in edit mode keeps its place (Layout.IsDefault). Secure frames: out of
-- combat only.

local ROW_Y, ROW_STEP = 84, 45 + 4
local RIGHT_X, RIGHT_GAP = -14, 5

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
    if b1 then b1.x, b1.y = x, ROW_Y end
    if b2 then b2.x, b2.y = x, ROW_Y + ROW_STEP end
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

-- Both bottom bars shown: the bars above them rise two rows, not one.
local function patchLift()
    local M = F() and F().MultiBars
    if not M or M.wuLift then return end
    M.wuLift = true
    M.Lift = function()
        local L, n = F().Layout, 0
        for k = 1, 2 do
            local bar = M.bars[k]
            if bar and bar.frame and bar.frame:IsShown() and (not L or not L.IsDefault or L.IsDefault(bar.id)) then
                n = n + 1
            end
        end
        return n * ROW_STEP
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
local wait, pending = 0, false
f:SetScript("OnEvent", function(_, event)
    if event == "PLAYER_REGEN_ENABLED" and not pending then return end
    pending, wait = true, 0
    -- a moment after Forever UI has placed its main bar
    f:SetScript("OnUpdate", function(self, elapsed)
        wait = wait + elapsed
        if wait < 1.5 then return end
        self:SetScript("OnUpdate", nil)
        if apply() ~= false then pending = false end
    end)
end)

WrathUnleashedUI = WrathUnleashedUI or {}
WrathUnleashedUI.FixBars = apply
