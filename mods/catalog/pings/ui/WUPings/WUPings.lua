-- WUPings: ping a spot for your party (WrathUnleashed mod "pings").
--   Alt-click on the world map     pings that spot
--   Alt-click in the world, /ping  pings where you stand (with an enemy targeted: "attack", a friend: "assist")
--   /ping attack|danger|assist|onmyway|look
-- Your party sees a marker on their world map, an on-screen line and a sound. The realm part
-- (realm/pings.lua) passes the ping on over OVMOD addon messages:
--   sent      "pings\tmap\t1/1\t<kind>,<area>,<floor>,<x>,<y>"            whispered to yourself
--   received  "pings\tmap\t1/1\t<kind>,<area>,<floor>,<x>,<y>,<name>"     from the realm
local MOD, PREFIX = "pings", "OVMOD"
local SHOW_SECONDS = 8
local KINDS = {
    look    = { label = "Look here",   icon = 1, r = 1.0, g = 0.9, b = 0.3 },
    attack  = { label = "Attack",      icon = 8, r = 1.0, g = 0.3, b = 0.2 },
    danger  = { label = "Danger",      icon = 7, r = 1.0, g = 0.5, b = 0.1 },
    assist  = { label = "Help here",   icon = 6, r = 0.3, g = 0.7, b = 1.0 },
    onmyway = { label = "On my way",   icon = 4, r = 0.4, g = 1.0, b = 0.4 },
}
WUPINGS_KINDS = KINDS

local pins, nextPin = {}, 1

-- The text for one ping, or nil when the fields are not a valid ping.
function WUPings_Build(kind, area, floor, x, y)
    if not KINDS[kind] or type(area) ~= "number" or area < 1 or type(x) ~= "number" or type(y) ~= "number" then
        return nil
    end
    if x < 0 or x > 1 or y < 0 or y > 1 then return nil end
    return string.format("%s,%d,%d,%.4f,%.4f", kind, area, floor or 0, x, y)
end

-- A received OVMOD message -> { kind, area, floor, x, y, from } for a ping from the realm, else nil.
-- Only whispers from yourself count: the realm answers that way and players cannot fake it.
function WUPings_Parse(prefix, msg, channel, sender, me)
    if prefix ~= PREFIX or type(msg) ~= "string" then return nil end
    if channel ~= "WHISPER" or (me and sender ~= me) then return nil end
    local modId, name, part, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+/%d+)\t(.*)$")
    if modId ~= MOD or name ~= "map" or part ~= "1/1" then return nil end
    local kind, area, floor, x, y, from = data:match("^(%a+),(%d+),(%d+),([%d%.]+),([%d%.]+),([^,]+)$")
    if not kind or not KINDS[kind] then return nil end
    x, y = tonumber(x), tonumber(y)
    if not x or not y or x < 0 or x > 1 or y < 0 or y > 1 then return nil end
    return { kind = kind, area = tonumber(area), floor = tonumber(floor), x = x, y = y, from = from }
end

-- "/ping attack" -> "attack"; "" -> nil (pick from the target); anything unknown -> false
function WUPings_KindFor(text)
    text = (text or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
    if text == "" then return nil end
    if text == "help" then return "assist" end
    if text == "omw" or text == "coming" then return "onmyway" end
    return KINDS[text] and text or false
end

-- The kind for a ping without a word: your target decides.
function WUPings_TargetKind()
    if UnitExists and UnitExists("target") then
        if UnitCanAttack and UnitCanAttack("player", "target") then return "attack" end
        return "assist"
    end
    return "look"
end

function WUPings_Line(p)
    local k = KINDS[p.kind]
    return string.format("%s: %s (%d, %d)", p.from, k.label, math.floor(p.x * 100 + 0.5), math.floor(p.y * 100 + 0.5))
end

local function pinFrame()
    local pin = pins[nextPin]
    if not pin then
        pin = CreateFrame("Frame", nil, WorldMapButton)
        pin:SetWidth(24); pin:SetHeight(24)
        pin:SetFrameLevel((WorldMapButton:GetFrameLevel() or 1) + 5)
        pin.icon = pin:CreateTexture(nil, "OVERLAY")
        pin.icon:SetAllPoints(pin)
        pins[nextPin] = pin
    end
    nextPin = nextPin % 8 + 1
    return pin
end

-- Puts the marker on the world map (shown while the map shows that area and floor).
function WUPings_Show(p)
    local k = KINDS[p.kind]
    if WorldMapButton then
        local pin = pinFrame()
        pin.ping, pin.until_ = p, (GetTime and GetTime() or 0) + SHOW_SECONDS * 4
        pin.icon:SetTexture("Interface\\TargetingFrame\\UI-RaidTargetingIcon_" .. k.icon)
        pin:ClearAllPoints()
        pin:SetPoint("CENTER", WorldMapButton, "TOPLEFT", p.x * WorldMapButton:GetWidth(), -p.y * WorldMapButton:GetHeight())
        WUPings_UpdatePins()
    end
    local line = WUPings_Line(p)
    if RaidNotice_AddMessage and RaidWarningFrame then
        RaidNotice_AddMessage(RaidWarningFrame, line, { r = k.r, g = k.g, b = k.b })
    end
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Ping]|r " .. line) end
    if PlaySound then PlaySound("MapPing") end
    return line
end

function WUPings_UpdatePins()
    local area = GetCurrentMapAreaID and GetCurrentMapAreaID() or 0
    local floor = GetCurrentMapDungeonLevel and GetCurrentMapDungeonLevel() or 0
    local now = GetTime and GetTime() or 0
    for _, pin in ipairs(pins) do
        local p = pin.ping
        if p and now < pin.until_ and p.area == area and p.floor == floor then pin:Show() else pin:Hide() end
    end
end

local function send(kind, area, floor, x, y)
    local text = WUPings_Build(kind, area, floor, x, y)
    if not text then return false end
    local me = UnitName("player")
    WUPings_Show({ kind = kind, area = area, floor = floor or 0, x = x, y = y, from = me })
    if (GetNumPartyMembers and GetNumPartyMembers() or 0) + (GetNumRaidMembers and GetNumRaidMembers() or 0) == 0 then
        return true   -- alone: only you see it
    end
    SendAddonMessage(PREFIX, MOD .. "\tmap\t1/1\t" .. text, "WHISPER", me)
    return true
end

-- Ping where you stand (the world map is put on your zone first unless it is open).
function WUPings_PingHere(kind)
    if not (WorldMapFrame and WorldMapFrame:IsShown()) and SetMapToCurrentZone then SetMapToCurrentZone() end
    local x, y = GetPlayerMapPosition("player")
    if not x or (x == 0 and y == 0) then
        if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Ping]|r No map here to ping on.") end
        return false
    end
    return send(kind or WUPings_TargetKind(), GetCurrentMapAreaID(), GetCurrentMapDungeonLevel(), x, y)
end

-- Ping the spot under the cursor on the world map.
function WUPings_PingMap(kind)
    local cx, cy = GetCursorPosition()
    local s = WorldMapButton:GetEffectiveScale()
    local x = (cx / s - WorldMapButton:GetLeft()) / WorldMapButton:GetWidth()
    local y = (WorldMapButton:GetTop() - cy / s) / WorldMapButton:GetHeight()
    return send(kind or "look", GetCurrentMapAreaID(), GetCurrentMapDungeonLevel(), x, y)
end

local f = CreateFrame("Frame", "WUPingsFrame", UIParent)
f:RegisterEvent("CHAT_MSG_ADDON")
f:RegisterEvent("PLAYER_LOGIN")
f:RegisterEvent("WORLD_MAP_UPDATE")
f:SetScript("OnEvent", function(self, event, prefix, msg, channel, sender)
    if event == "CHAT_MSG_ADDON" then
        local p = WUPings_Parse(prefix, msg, channel, sender, UnitName("player"))
        if p then WUPings_Show(p) end
    elseif event == "WORLD_MAP_UPDATE" then
        WUPings_UpdatePins()
    elseif event == "PLAYER_LOGIN" then
        if WorldMapButton then
            local click = WorldMapButton:GetScript("OnClick")
            WorldMapButton:SetScript("OnClick", function(btn, mouse, ...)
                if IsAltKeyDown() then WUPings_PingMap() elseif click then click(btn, mouse, ...) end
            end)
        end
        if WorldFrame and WorldFrame.HookScript then
            pcall(WorldFrame.HookScript, WorldFrame, "OnMouseUp", function(_, mouse)
                if IsAltKeyDown() and mouse == "LeftButton" then WUPings_PingHere() end
            end)
        end
    end
end)

SLASH_WUPINGS1 = "/ping"
SlashCmdList["WUPINGS"] = function(msg)
    local kind = WUPings_KindFor(msg)
    if kind == false then
        DEFAULT_CHAT_FRAME:AddMessage("|cff66ccff[Ping]|r /ping, or /ping attack | danger | assist | onmyway | look. "
            .. "Alt-click the world map to ping a spot.")
        return
    end
    WUPings_PingHere(kind)
end
