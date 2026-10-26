-- Open Mod API, server half (mod-ale). Carries the client's Mod.Packet transport: addon messages
-- with prefix OVMOD, whispered to yourself, one message per part:
--
--   <modId>\t<name>\t<partIndex>/<partCount>\t<data>        partIndex is 1-based
--
-- Other scripts use it through require (ALE loads each file once, so this is safe):
--
--   local OVMod = require("ov_modapi")
--   OVMod.On("pings", "ping", function(player, data) ... end)
--   OVMod.Send(player, "pings", "ping", "1,2,3,0,attack")
--
-- Messages for a modId/name nobody registered are dropped before they are buffered. OVMOD
-- messages are never relayed by the core to anyone (the hook returns false), so one player
-- cannot whisper fake OVMOD traffic to another. See MOD-PACKETS.md for the full protocol.

if OVMod and OVMod._loaded then return OVMod end

local OVMod = OVMod or {}
_G.OVMod = OVMod
OVMod._loaded = true

local PREFIX = "OVMOD"
local WHISPER = 7              -- CHAT_MSG_WHISPER, as ov_armory sends
local SEND_CHUNK = 2000        -- server -> client data bytes per part
local MAX_PARTS = 64           -- client -> server parts per message
local MAX_BYTES = 16384        -- client -> server reassembled size
local MAX_PENDING = 8          -- unfinished messages per player
local STALE_SECONDS = 30       -- an unfinished message older than this is dropped
local MAX_PARTS_PER_SECOND = 40
local ID_MAX = 32

OVMod.PREFIX = PREFIX
OVMod.SEND_CHUNK = SEND_CHUNK

local handlers = {}  -- [modId][name] = fn(player, data)
local pending = {}   -- [guidLow] = { n = count, [key] = { total, got, bytes, at, parts = {} } }
local flood = {}     -- [guidLow] = { sec, count }

local function validId(s)
    return type(s) == "string" and #s >= 1 and #s <= ID_MAX and s:match("^[%w_%-%.]+$") ~= nil
end

function OVMod.On(modId, name, fn)
    assert(validId(modId), "OVMod.On: bad modId")
    assert(validId(name), "OVMod.On: bad name")
    assert(type(fn) == "function", "OVMod.On: handler must be a function")
    handlers[modId] = handlers[modId] or {}
    handlers[modId][name] = fn
end

function OVMod.Off(modId, name)
    if handlers[modId] then handlers[modId][name] = nil end
end

function OVMod.Send(player, modId, name, data)
    if not player or not validId(modId) or not validId(name) then return false end
    data = tostring(data or "")
    local total = math.max(1, math.ceil(#data / SEND_CHUNK))
    local head = modId .. "\t" .. name .. "\t"
    for i = 1, total do
        local part = data:sub((i - 1) * SEND_CHUNK + 1, i * SEND_CHUNK)
        player:SendAddonMessage(PREFIX, head .. i .. "/" .. total .. "\t" .. part, WHISPER, player)
    end
    return true
end

local function dispatch(player, modId, name, data)
    local fn = handlers[modId] and handlers[modId][name]
    if not fn then return end
    local ok, err = pcall(fn, player, data)
    if not ok then
        print(string.format("[ov_modapi] %s/%s handler error: %s", modId, name, tostring(err)))
    end
end

-- Server scripts only: hand a message to a handler as if the player had sent it (ov_workshop.lua's Play
-- starts a course, a mode or a build through the same checks as that script's own window).
function OVMod.Dispatch(player, modId, name, data)
    if not player or not (handlers[modId] and handlers[modId][name]) then return false end
    dispatch(player, modId, name, tostring(data or ""))
    return true
end

local function flooding(guid, now)
    local f = flood[guid]
    if not f or f.sec ~= now then
        flood[guid] = { sec = now, count = 1 }
        return false
    end
    f.count = f.count + 1
    return f.count > MAX_PARTS_PER_SECOND
end

local function purgeStale(box, now)
    for key, buf in pairs(box) do
        if key ~= "n" and now - buf.at > STALE_SECONDS then
            box[key] = nil
            box.n = box.n - 1
        end
    end
end

local function receive(player, msg)
    local modId, name, idx, total, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
    if not modId or not validId(modId) or not validId(name) then return end
    if not (handlers[modId] and handlers[modId][name]) then return end
    if #idx > 3 or #total > 3 then return end
    idx, total = tonumber(idx), tonumber(total)
    if total < 1 or total > MAX_PARTS or idx < 1 or idx > total then return end

    local guid, now = player:GetGUIDLow(), os.time()
    if flooding(guid, now) then return end

    if total == 1 then
        local box = pending[guid]
        local key = modId .. "\t" .. name
        if box and box[key] then box[key] = nil box.n = box.n - 1 end
        return dispatch(player, modId, name, data)
    end

    local box = pending[guid]
    if not box then
        box = { n = 0 }
        pending[guid] = box
    end
    purgeStale(box, now)

    local key = modId .. "\t" .. name
    local buf = box[key]
    if buf and (buf.total ~= total or idx == 1) then
        box[key] = nil
        box.n = box.n - 1
        buf = nil
    end
    if not buf then
        if idx ~= 1 or box.n >= MAX_PENDING then return end
        buf = { total = total, got = 0, bytes = 0, at = now, parts = {} }
        box[key] = buf
        box.n = box.n + 1
    end
    if buf.parts[idx] then return end
    if buf.bytes + #data > MAX_BYTES then
        box[key] = nil
        box.n = box.n - 1
        return
    end
    buf.parts[idx] = data
    buf.got = buf.got + 1
    buf.bytes = buf.bytes + #data
    buf.at = now
    if buf.got == buf.total then
        box[key] = nil
        box.n = box.n - 1
        return dispatch(player, modId, name, table.concat(buf.parts, "", 1, buf.total))
    end
end

local function onAddonMessage(event, sender, msgType, prefix, msg, target)
    if prefix ~= PREFIX then return end
    if sender and type(msg) == "string" then receive(sender, msg) end
    return false
end

local function onLogout(event, player)
    local guid = player:GetGUIDLow()
    pending[guid] = nil
    flood[guid] = nil
end

OVMod._pending = pending

RegisterServerEvent(30, onAddonMessage) -- ADDON_EVENT_ON_MESSAGE
RegisterPlayerEvent(4, onLogout)        -- PLAYER_EVENT_ON_LOGOUT

return OVMod
