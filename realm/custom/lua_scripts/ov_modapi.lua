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

-- The Leyline brand switch (owner 2026-10-30; realm/brand.sh on|off). While it is on, the realm's scripts say
-- "Leyline" and call this realm "Dalaran Hangout" where players read it (chat tags, the welcome, the Leyline
-- window's home realm), and each login tells the addon: mod "wubrand", name "brand", data
-- "leyline\t<realm name>" (WrathUnleashedUI.lua W.Brand; the addon also asks with "wubrand"/"ask"). Off: nothing
-- is sent and every word is the old one. On = OV_LEYLINE_BRAND=1 in the world server's environment (0 forces off),
-- else the flag file OV_BRAND_FILE (default /azerothcore/lua_scripts/leyline-brand.on = the host's
-- custom/lua_scripts/leyline-brand.on), looked at no more than every BRAND_CACHE seconds: brand.sh flips it with no
-- reload and no restart. Prefixes, mod ids, saved variables and every internal name stay as they are.
local BRAND_FILE = os.getenv("OV_BRAND_FILE") or "/azerothcore/lua_scripts/leyline-brand.on"
local BRAND_CACHE = 30
local brandAt, brandOn = -1e9, false

function OVMod.BrandOn()
    local v = os.getenv("OV_LEYLINE_BRAND")
    if v == "1" then return true end
    if v == "0" then return false end
    local now = os.time()
    if now - brandAt >= BRAND_CACHE then
        brandAt = now
        local f = io.open(BRAND_FILE, "rb")
        brandOn = f ~= nil
        if f then f:close() end
    end
    return brandOn
end

local function plainName(s, fallback)
    s = type(s) == "string" and s:gsub("[%z\1-\31\127|\t]", ""):sub(1, 32) or ""
    return s ~= "" and s or fallback
end

-- { on, name = the project ("Leyline" | "WrathUnleashed"), realm = this realm's name, home = what "Back to ..."
-- says ("Dalaran Hangout" | "Wrath") }
function OVMod.Brand()
    if OVMod.BrandOn() then
        local realm = plainName(os.getenv("OV_LEYLINE_REALM_NAME"), "Dalaran Hangout")
        return { on = true, name = "Leyline", realm = realm, home = realm }
    end
    return { on = false, name = "WrathUnleashed", realm = plainName(os.getenv("OV_REALM_NAME"), "WrathUnleashed"),
             home = "Wrath" }
end

function OVMod.SendBrand(player)
    local b = OVMod.Brand()
    if not b.on or not player then return false end
    return OVMod.Send(player, "wubrand", "brand", "leyline\t" .. b.realm)
end

OVMod.On("wubrand", "ask", function(player) OVMod.SendBrand(player) end)

local function onBrandLogin(event, player)
    if not player or not OVMod.BrandOn() then return end
    -- a moment after login, when the addon listens (it also asks itself at PLAYER_ENTERING_WORLD)
    local ok = pcall(function()
        player:RegisterEvent(function(_, _, _, p) if p then OVMod.SendBrand(p) end end, 3000, 1)
    end)
    if not ok then OVMod.SendBrand(player) end
end

OVMod._pending = pending

RegisterServerEvent(30, onAddonMessage) -- ADDON_EVENT_ON_MESSAGE
RegisterPlayerEvent(4, onLogout)        -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(3, onBrandLogin)    -- PLAYER_EVENT_ON_LOGIN: the brand, while it is on

return OVMod
