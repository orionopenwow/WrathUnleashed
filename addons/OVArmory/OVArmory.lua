-- WrathUnleashed Armory: search the realm's whole item database and take gear, in the slices
-- the realm allows (Dalaran, arenas, battlegrounds). Talks to realm\custom\lua_scripts\
-- ov_armory.lua over addon messages (prefix OVARM). /armory opens it.

local PREFIX = "OVARM"
local ROWS = 12
local ROW_H = 30

local SLOTS = {
    { 0, "Any slot" }, { 1, "Head" }, { 2, "Neck" }, { 3, "Shoulder" }, { 16, "Back" },
    { 5, "Chest" }, { 20, "Robe" }, { 9, "Wrist" }, { 10, "Hands" }, { 6, "Waist" },
    { 7, "Legs" }, { 8, "Feet" }, { 11, "Finger" }, { 12, "Trinket" }, { 17, "Two-hand" },
    { 13, "One-hand" }, { 21, "Main hand" }, { 22, "Off hand" }, { 14, "Shield" },
    { 23, "Held in off hand" }, { 15, "Ranged" }, { 26, "Wand / gun / crossbow" }, { 28, "Relic" },
}
local QUALITY = { [2] = "1eff00", [3] = "0070dd", [4] = "a335ee", [5] = "ff8000", [7] = "e6cc80" }

local results, offset, slotIndex = {}, 0, 1

local f = CreateFrame("Frame", "OVArmoryFrame", UIParent)
f:SetSize(420, 470)
f:SetPoint("CENTER")
f:SetFrameStrata("DIALOG")
f:EnableMouse(true)
f:SetMovable(true)
f:RegisterForDrag("LeftButton")
f:SetScript("OnDragStart", f.StartMoving)
f:SetScript("OnDragStop", f.StopMovingOrSizing)
f:SetBackdrop({
    bgFile = "Interface\\DialogFrame\\UI-DialogBox-Background",
    edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border",
    tile = true, tileSize = 32, edgeSize = 32,
    insets = { left = 11, right = 12, top = 12, bottom = 11 },
})
f:Hide()
tinsert(UISpecialFrames, "OVArmoryFrame")

local title = f:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
title:SetPoint("TOP", 0, -18)
title:SetText("Armory")

local close = CreateFrame("Button", nil, f, "UIPanelCloseButton")
close:SetPoint("TOPRIGHT", -6, -6)

local search = CreateFrame("EditBox", "OVArmorySearch", f, "InputBoxTemplate")
search:SetSize(200, 20)
search:SetPoint("TOPLEFT", 28, -48)
search:SetAutoFocus(false)
search:SetMaxLetters(40)

local slotButton = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
slotButton:SetSize(120, 22)
slotButton:SetPoint("LEFT", search, "RIGHT", 8, 0)
local function showSlot() slotButton:SetText(SLOTS[slotIndex][2]) end
slotButton:SetScript("OnClick", function(_, button)
    slotIndex = (button == "RightButton") and (slotIndex - 2) % #SLOTS + 1 or slotIndex % #SLOTS + 1
    showSlot()
end)
slotButton:RegisterForClicks("LeftButtonUp", "RightButtonUp")
showSlot()

local status = f:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
status:SetPoint("TOPLEFT", 28, -76)
status:SetPoint("RIGHT", -28, 0)
status:SetJustifyH("LEFT")
status:SetText("Search by name, pick a slot (right-click goes back), press Enter.")

local function send(msg)
    SendAddonMessage(PREFIX, msg, "WHISPER", UnitName("player"))
end

local function runSearch()
    wipe(results)
    offset = 0
    status:SetText("Searching...")
    send("S:" .. SLOTS[slotIndex][1] .. ":" .. (search:GetText() or ""))
end
search:SetScript("OnEnterPressed", function(self) self:ClearFocus() runSearch() end)
search:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)

local go = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
go:SetSize(50, 22)
go:SetPoint("LEFT", slotButton, "RIGHT", 4, 0)
go:SetText("Find")
go:SetScript("OnClick", runSearch)

local rows = {}
local function refresh()
    for i = 1, ROWS do
        local r, item = rows[i], results[offset + i]
        if item then
            r.item = item
            r.icon:SetTexture(GetItemIcon(item.entry) or "Interface\\Icons\\INV_Misc_QuestionMark")
            r.name:SetText("|cff" .. (QUALITY[item.quality] or "ffffff") .. item.name .. "|r")
            r.ilvl:SetText("ilvl " .. item.ilvl)
            r:Show()
        else
            r.item = nil
            r:Hide()
        end
    end
end

for i = 1, ROWS do
    local r = CreateFrame("Button", nil, f)
    r:SetSize(360, ROW_H - 2)
    r:SetPoint("TOPLEFT", 28, -96 - (i - 1) * ROW_H)
    r:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
    r.icon = r:CreateTexture(nil, "ARTWORK")
    r.icon:SetSize(26, 26)
    r.icon:SetPoint("LEFT")
    r.name = r:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    r.name:SetPoint("LEFT", r.icon, "RIGHT", 6, 0)
    r.name:SetWidth(210)
    r.name:SetJustifyH("LEFT")
    r.ilvl = r:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    r.ilvl:SetPoint("LEFT", r.name, "RIGHT", 4, 0)
    r.take = CreateFrame("Button", nil, r, "UIPanelButtonTemplate")
    r.take:SetSize(50, 20)
    r.take:SetPoint("RIGHT")
    r.take:SetText("Take")
    r.take:SetScript("OnClick", function()
        if r.item then send("G:" .. r.item.entry) end
    end)
    r:SetScript("OnEnter", function(self)
        if not self.item then return end
        GameTooltip:SetOwner(self, "ANCHOR_RIGHT")
        GameTooltip:SetHyperlink("item:" .. self.item.entry)
        GameTooltip:Show()
    end)
    r:SetScript("OnLeave", function() GameTooltip:Hide() end)
    r:Hide()
    rows[i] = r
end

local prev = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
prev:SetSize(60, 22)
prev:SetPoint("BOTTOMLEFT", 28, 18)
prev:SetText("< Prev")
prev:SetScript("OnClick", function() offset = math.max(0, offset - ROWS) refresh() end)
local nxt = CreateFrame("Button", nil, f, "UIPanelButtonTemplate")
nxt:SetSize(60, 22)
nxt:SetPoint("BOTTOMRIGHT", -28, 18)
nxt:SetText("Next >")
nxt:SetScript("OnClick", function()
    if offset + ROWS < #results then offset = offset + ROWS refresh() end
end)

f:RegisterEvent("CHAT_MSG_ADDON")
f:SetScript("OnEvent", function(_, event, prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" or sender ~= UnitName("player") then return end
    local kind, rest = msg:match("^(%a):(.*)$")
    if kind == "R" then
        local entry, quality, ilvl, inv, name = rest:match("^(%d+):(%d+):(%d+):(%d+):(.*)$")
        if entry then
            results[#results + 1] = { entry = tonumber(entry), quality = tonumber(quality),
                ilvl = tonumber(ilvl), inv = tonumber(inv), name = name }
        end
    elseif kind == "E" then
        status:SetText(#results == 0 and "Nothing found." or (#results .. " items. Hover for details, Take to get one."))
        refresh()
    elseif kind == "M" then
        status:SetText(rest)
    end
end)

SLASH_OVARMORY1 = "/armory"
SlashCmdList.OVARMORY = function()
    if f:IsShown() then f:Hide() else f:Show() search:SetFocus() end
end
