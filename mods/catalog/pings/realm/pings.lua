-- pings, realm part (mod-ale): passes a party member's map ping on to the rest of the group.
--
-- Rides on the realm's OVMOD addon-message channel (ov_modapi.lua, the OVMod global). Mod "pings":
--   client -> realm   map      <kind>,<area>,<floor>,<x>,<y>
--   realm -> client   map      <kind>,<area>,<floor>,<x>,<y>,<sender name>
--   realm -> client   denied   rate | nogroup | bad
-- kind: look | attack | danger | assist | onmyway. area: the world map area id the ping is on
-- (GetCurrentMapAreaID), floor: its dungeon level (0 outside), x and y: 0-1 on that map (4 decimals).
--
-- The ping goes to group members on the sender's map and instance, never back to the sender (the
-- addon draws its own ping when it sends one). 5 pings per 5 seconds per player.
-- Permissions (mod.json): chat (OVMod.On / OVMod.Send), timers (one retry while ov_modapi.lua loads).

local MOD = "pings"
local KINDS = { look = true, attack = true, danger = true, assist = true, onmyway = true }
local RATE_COUNT, RATE_WINDOW = 5, 5
local MAX_AREA, MAX_FLOOR = 99999, 32

local recent = {}   -- [guidLow] = { times of the last pings }
local tracked = 0

local function deny(player, reason)
    OVMod.Send(player, MOD, "denied", reason)
end

-- "0.4512" -> 0.4512 for 0 <= v <= 1 with at most 4 decimals; anything else -> nil
local function unit(s)
    if type(s) ~= "string" or not s:match("^[01]%.?%d?%d?%d?%d?$") and not s:match("^%.%d%d?%d?%d?$") then
        return nil
    end
    local v = tonumber(s)
    if not v or v < 0 or v > 1 then return nil end
    return v
end

local function whole(s, hi)
    if type(s) ~= "string" or not s:match("^%d%d?%d?%d?%d?$") then return nil end
    local v = tonumber(s)
    if v > hi then return nil end
    return v
end

local function allow(player)
    local guid, now = player:GetGUIDLow(), os.time()
    local kept = {}
    for _, t in ipairs(recent[guid] or {}) do
        if now - t < RATE_WINDOW then kept[#kept + 1] = t end
    end
    if #kept >= RATE_COUNT then
        recent[guid] = kept
        return false
    end
    kept[#kept + 1] = now
    if not recent[guid] then tracked = tracked + 1 end
    recent[guid] = kept
    if tracked > 2000 then   -- forget players who stopped pinging (no logout hook needed)
        for g, list in pairs(recent) do
            if not list[#list] or now - list[#list] >= RATE_WINDOW then
                recent[g] = nil
                tracked = tracked - 1
            end
        end
    end
    return true
end

-- "attack,1429,0,0.4512,0.6230" -> the cleaned fields, or nil
local function parse(data)
    if type(data) ~= "string" or #data > 64 then return nil end
    local kind, area, floor, x, y = data:match("^(%a+),(%d+),(%d+),([%d%.]+),([%d%.]+)$")
    if not kind or not KINDS[kind] then return nil end
    area, floor, x, y = whole(area, MAX_AREA), whole(floor, MAX_FLOOR), unit(x), unit(y)
    if not (area and floor and x and y) or area == 0 then return nil end
    return kind, area, floor, x, y
end

local function onMap(player, data)
    local kind, area, floor, x, y = parse(data)
    if not kind then return deny(player, "bad") end
    local group = player:GetGroup()
    if not group then return deny(player, "nogroup") end
    if not allow(player) then return deny(player, "rate") end
    local out = string.format("%s,%d,%d,%.4f,%.4f,%s", kind, area, floor, x, y, player:GetName())
    local map, inst, me = player:GetMapId(), player:GetInstanceId(), player:GetGUIDLow()
    local sent = 0
    for _, member in ipairs(group:GetMembers() or {}) do
        if member:GetGUIDLow() ~= me and member:IsInWorld() and member:GetMapId() == map
                and member:GetInstanceId() == inst then
            OVMod.Send(member, MOD, "map", out)
            sent = sent + 1
        end
    end
    return sent
end

local registered = false
local function register()
    if registered or not OVMod then return end
    registered = true
    OVMod.On(MOD, "map", onMap)
end

if OVMod then
    register()
else
    CreateLuaEvent(register, 1000, 1) -- ov_modapi.lua loads after this folder: try again in a second
end
