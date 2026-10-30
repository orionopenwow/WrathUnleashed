-- ov_sandbox_core.lua: the Lua side of mod-sandbox-core (realm/custom/modules/mod-sandbox-core), the global Sandbox.
-- The module moves, turns, tilts and resizes builder props in place, keeping their GUID; ov_build.lua uses it when
-- it is there and falls back to despawn + respawn when it isn't (the stock image).
--
--   Sandbox.Available([player])                     true once the module has answered (cached; see below)
--   Sandbox.Spawn(propId, entry, map, x, y, z, qx, qy, qz, qw, size [, player])   -> guid | nil, why
--        (size 0: the prop's own size; below 0: the size the module kept for propId)
--   Sandbox.Move(guid, x, y, z, qx, qy, qz, qw [, player])                         -> guid | nil, why
--        (the same guid, unless the realm runs SandboxCore.MoveMode = 1: then a fresh one)
--   Sandbox.SetScale(guid, size [, player])          -> true | nil, why   (0: back to the prop's own size)
--   Sandbox.Despawn(guid [, forget [, player]])      -> true | nil, why   (forget: drop its kept size too)
--   Sandbox.Find(propId [, player])                  -> guid of the prop's object already in the world | nil
--        (after a Lua reload the script has forgotten its objects; the module hasn't)
--   Sandbox.QuatFromYawPitchRoll(yaw, pitch, roll)   -> qx, qy, qz, qw   (radians; R = Rz(yaw) Ry(pitch) Rx(roll),
--        the rotation GameObject::SetWorldRotationAngles builds)
--   Sandbox.MoveMode()                               -> 0 in place, 1 fresh GUID per move
--   Sandbox.Use(player)                              the player whose session carries the next calls (ov_build
--        sets it per command); without one, any player in the world does
--
-- The bridge (the module's README): each call is a packet with opcode CMSG_DBLOOKUP (0x002) that Lua sends to a
-- player's own session. The module answers inside player:SendPacket, rewriting the packet with the reply, and
-- keeps it off the wire. Before sending anything, Lua reads the row the module writes at startup
-- (sandbox_core_status); with no row there is no module and no packet is ever sent. OV_SANDBOX_CORE=0 turns the
-- whole thing off.

local OPCODE = 0x002
local REQUEST_MAGIC, REPLY_MAGIC, VERSION = 0x53425831, 0x53425852, 1
local OP = { PING = 1, SPAWN = 2, MOVE = 3, SCALE = 4, DESPAWN = 5, FIND = 6 }
local STATUS = { [1] = "bad request", [2] = "off on this realm", [3] = "not a builder object", [4] = "bad value",
    [5] = "out of bounds", [6] = "too many changes at once", [7] = "the realm refused", [8] = "too many props" }
local RECHECK = 60   -- seconds before a "no module" answer is asked again

Sandbox = rawget(_G, "Sandbox") or {}
local S = Sandbox
S.OP, S.STATUS = OP, STATUS

local known = { ok = false, at = nil, mode = 0, version = 0 }
local carrier

function S.Use(player) carrier = player end

local function finite(v) return type(v) == "number" and v == v and v ~= math.huge and v ~= -math.huge end

local function anyPlayer()
    if not GetPlayersInWorld then return nil end
    local ok, list = pcall(GetPlayersInWorld)
    if ok and type(list) == "table" then return list[1] end
    return nil
end

-- One request: write(pkt) adds the op's arguments, read(pkt) takes the results (need = their bytes).
local function call(player, op, write, read, need)
    if not CreatePacket then return nil, "no packets" end
    local pl = player or carrier or anyPlayer()
    if not pl then return nil, "no player to carry it" end
    local ok, pkt = pcall(CreatePacket, OPCODE, 64)
    if not ok or not pkt then return nil, "no packet" end
    local wrote = pcall(function()
        pkt:WriteULong(REQUEST_MAGIC)
        pkt:WriteUByte(VERSION)
        pkt:WriteUByte(op)
        if write then write(pkt) end
    end)
    if not wrote then return nil, "bad arguments" end
    if not pcall(pl.SendPacket, pl, pkt, true) then return nil, "not sent" end
    local size = tonumber((select(2, pcall(pkt.GetSize, pkt)))) or 0
    if size < 5 then return nil, "no answer" end
    local okR, magic, status = pcall(function() return pkt:ReadULong(), pkt:ReadUByte() end)
    if not okR or magic ~= REPLY_MAGIC then
        known.ok, known.at = false, os.time()   -- nobody answered: the module is gone
        return nil, "no answer"
    end
    if status ~= 0 then return nil, STATUS[status] or ("status " .. tostring(status)), status end
    if not read then return true end
    if size < 5 + (need or 0) then return nil, "short answer" end
    local okV, a, b = pcall(read, pkt)
    if not okV then return nil, "bad answer" end
    return a, b
end

function S.Available(player)
    if os.getenv and os.getenv("OV_SANDBOX_CORE") == "0" then return false end
    if known.ok then return true end
    if known.at and os.time() - known.at < RECHECK then return false end
    -- The row first: without it no packet goes anywhere.
    local row = false
    if CharDBQuery then
        local ok, q = pcall(CharDBQuery, "SELECT version, move_mode FROM sandbox_core_status WHERE id = 1")
        row = ok and q ~= nil
    end
    if not row then known.at = os.time(); return false end
    local version, mode = call(player, OP.PING, nil, function(p) return p:ReadULong(), p:ReadUByte() end, 5)
    if not version then
        -- No player to ask yet: decide later. Otherwise the module isn't answering.
        if mode ~= "no player to carry it" then known.at = os.time() end
        return false
    end
    known.ok, known.at, known.version, known.mode = true, os.time(), tonumber(version) or 0, tonumber(mode) or 0
    return true
end

function S.MoveMode() return known.mode end
function S.Version() return known.version end

function S.QuatFromYawPitchRoll(yaw, pitch, roll)
    yaw, pitch, roll = tonumber(yaw) or 0, tonumber(pitch) or 0, tonumber(roll) or 0
    local cy, sy = math.cos(yaw / 2), math.sin(yaw / 2)
    local cp, sp = math.cos(pitch / 2), math.sin(pitch / 2)
    local cr, sr = math.cos(roll / 2), math.sin(roll / 2)
    return sr * cp * cy - cr * sp * sy,     -- x
        cr * sp * cy + sr * cp * sy,        -- y
        cr * cp * sy - sr * sp * cy,        -- z
        cr * cp * cy + sr * sp * sy         -- w
end

local function allFinite(...)
    for i = 1, select("#", ...) do if not finite((select(i, ...))) then return false end end
    return true
end

function S.Spawn(propId, entry, map, x, y, z, qx, qy, qz, qw, size, player)
    if not S.Available(player) then return nil, "no module" end
    size = tonumber(size) or 0
    if not allFinite(x, y, z, qx, qy, qz, qw, size) then return nil, "bad value" end
    return call(player, OP.SPAWN, function(p)
        p:WriteULong(math.floor(tonumber(propId) or 0)); p:WriteULong(math.floor(tonumber(entry) or 0))
        p:WriteULong(math.floor(tonumber(map) or 0))
        p:WriteFloat(x); p:WriteFloat(y); p:WriteFloat(z)
        p:WriteFloat(qx); p:WriteFloat(qy); p:WriteFloat(qz); p:WriteFloat(qw)
        p:WriteFloat(size)
    end, function(p) return p:ReadGUID() end, 8)
end

function S.Move(guid, x, y, z, qx, qy, qz, qw, player)
    if guid == nil then return nil, "no object" end
    if not S.Available(player) then return nil, "no module" end
    if not allFinite(x, y, z, qx, qy, qz, qw) then return nil, "bad value" end
    return call(player, OP.MOVE, function(p)
        p:WriteGUID(guid)
        p:WriteFloat(x); p:WriteFloat(y); p:WriteFloat(z)
        p:WriteFloat(qx); p:WriteFloat(qy); p:WriteFloat(qz); p:WriteFloat(qw)
    end, function(p) return p:ReadGUID() end, 8)
end

function S.SetScale(guid, size, player)
    if guid == nil then return nil, "no object" end
    if not S.Available(player) then return nil, "no module" end
    if not finite(size) then return nil, "bad value" end
    return call(player, OP.SCALE, function(p) p:WriteGUID(guid); p:WriteFloat(size) end)
end

function S.Despawn(guid, forget, player)
    if guid == nil then return nil, "no object" end
    if not S.Available(player) then return nil, "no module" end
    return call(player, OP.DESPAWN, function(p) p:WriteGUID(guid); p:WriteUByte(forget and 1 or 0) end)
end

function S.Find(propId, player)
    if not S.Available(player) then return nil, "no module" end
    return call(player, OP.FIND, function(p) p:WriteULong(math.floor(tonumber(propId) or 0)) end,
        function(p) return p:ReadGUID() end, 8)
end

-- for stream/tests/test_ov_sandbox_core.lua
OV_SANDBOX_CORE_TEST = { known = known, OPCODE = OPCODE, REQUEST_MAGIC = REQUEST_MAGIC, REPLY_MAGIC = REPLY_MAGIC,
    reset = function() known.ok, known.at, known.mode, known.version = false, nil, 0, 0; carrier = nil end }
