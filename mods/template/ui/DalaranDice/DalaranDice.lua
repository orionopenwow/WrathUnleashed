-- DalaranDice: shows the last rolls from the realm's ".dice" command (WrathUnleashed mod "dalaran-dice").
-- The realm sends each roll as an OVMOD addon message (see realm/dalaran_dice.lua):
--   "dalaran-dice\troll\t1/1\t<name>,<count>,<sides>,<total>,<faces separated by spaces>"
-- /dicelog shows or hides the box.

local MOD_ID = "dalaran-dice"
local PREFIX = "OVMOD"
local MAX_LINES = 5
local rolls = {}

-- Returns a display line for an OVMOD message from this mod, or nil for anything else.
function DalaranDice_Parse(prefix, msg)
    if prefix ~= PREFIX or type(msg) ~= "string" then return nil end
    local modId, name, part, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+/%d+)\t(.*)$")
    if modId ~= MOD_ID or name ~= "roll" or part ~= "1/1" then return nil end
    local who, count, sides, total, faces = data:match("^([^,]+),(%d+),(%d+),(%d+),([%d ]*)$")
    if not who then return nil end
    local line = string.format("%s: %sd%s = |cffffff00%s|r", who, count, sides, total)
    if tonumber(count) > 1 then line = line .. " (" .. faces .. ")" end
    return line
end

function DalaranDice_Add(line)
    table.insert(rolls, 1, line)
    while #rolls > MAX_LINES do table.remove(rolls) end
    DalaranDiceFrameText:SetText(table.concat(rolls, "\n"))
    DalaranDiceFrame:Show()
end

function DalaranDice_OnLoad(self)
    self:SetBackdrop({
        bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        tile = true, tileSize = 16, edgeSize = 16,
        insets = { left = 4, right = 4, top = 4, bottom = 4 },
    })
    self:SetBackdropColor(0, 0, 0, 0.7)
    self:RegisterEvent("CHAT_MSG_ADDON")
end

function DalaranDice_OnEvent(self, event, prefix, msg)
    if event ~= "CHAT_MSG_ADDON" then return end
    local line = DalaranDice_Parse(prefix, msg)
    if line then DalaranDice_Add(line) end
end

SLASH_DALARAN_DICE1 = "/dicelog"
SlashCmdList["DALARAN_DICE"] = function()
    if DalaranDiceFrame:IsShown() then DalaranDiceFrame:Hide() else DalaranDiceFrame:Show() end
end
