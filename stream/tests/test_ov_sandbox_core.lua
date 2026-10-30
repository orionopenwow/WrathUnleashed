-- lua5.1 stream/tests/test_ov_sandbox_core.lua [ov_sandbox_core.lua]
-- The Lua side of mod-sandbox-core under a fake mod-ale and a fake module: no packet before the status row, the
-- request layout the module reads (SandboxMath.h), replies and statuses, the quaternion (the same vector the C++
-- test prints), and a module that stops answering.
local file = arg[1] or "realm/custom/lua_scripts/ov_sandbox_core.lua"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end
local function near(a, b, eps) return math.abs(a - b) <= (eps or 1e-5) end

local clock = 1000
os.time = function() return clock end
local env = {}
os.getenv = function(k) return env[k] end

-- ------------------------------------------------------------------ a WorldPacket: typed values and their sizes
local SIZES = { ULong = 4, UByte = 1, Float = 4, GUID = 8 }
local function packet(opcode)
    local p = { opcode = opcode, vals = {}, r = 1 }
    for kind in pairs(SIZES) do
        p["Write" .. kind] = function(self, v) self.vals[#self.vals + 1] = { kind = kind, v = v } end
        p["Read" .. kind] = function(self)
            local e = self.vals[self.r]
            if not e or e.kind ~= kind then error("read past the end or wrong type") end
            self.r = self.r + 1
            return e.v
        end
    end
    function p:GetSize() local n = 0; for _, e in ipairs(self.vals) do n = n + SIZES[e.kind] end; return n end
    function p:clear() self.vals, self.r = {}, 1 end
    return p
end
local created = 0
function CreatePacket(op, size) created = created + 1; return packet(op) end

-- ------------------------------------------------------------------ the fake module
local statusRow = false
local module = { on = true, status = 0, guid = 0xF110000000001000, moveGuid = nil, log = {} }
function CharDBQuery(sql)
    if sql:find("FROM sandbox_core_status") then
        if not statusRow then return nil end
        return { GetUInt32 = function() return 1 end }
    end
end
local function answer(pkt)
    local req = {}
    for i, e in ipairs(pkt.vals) do req[i] = e end
    module.log[#module.log + 1] = req
    pkt:clear()
    pkt:WriteULong(0x53425852)
    pkt:WriteUByte(module.status)
    if module.status ~= 0 then return end
    local op = req[3].v
    if op == 1 then pkt:WriteULong(1); pkt:WriteUByte(module.mode or 0)
    elseif op == 2 then pkt:WriteGUID(module.guid)
    elseif op == 3 then pkt:WriteGUID(module.moveGuid or req[4].v)
    elseif op == 6 then pkt:WriteGUID(module.guid) end
end
local wire = {}   -- packets that reached the "client"
local function player(name)
    local p = { name = name }
    function p:SendPacket(pkt, selfOnly)
        if pkt.opcode == 0x002 and module.on then return answer(pkt) end
        wire[#wire + 1] = pkt
    end
    return p
end
local online = {}
function GetPlayersInWorld() return online end

dofile(file)
local T = assert(OV_SANDBOX_CORE_TEST)
local S = assert(Sandbox)
local alice = player("Alice")

-- ------------------------------------------------------------------ no row: nothing goes anywhere
check("no status row: not available", S.Available(alice) == false)
check("no status row: no packet made, none sent", created == 0 and #wire == 0 and #module.log == 0)
local g, why = S.Move(123, 1, 2, 3, 0, 0, 0, 1, alice)
check("no module: Move says so", g == nil and why == "no module" and #wire == 0)
check("no module: Spawn says so", S.Spawn(1, 2413, 0, 1, 2, 3, 0, 0, 0, 1, 1, alice) == nil)

-- the row appears (a restart with the new image): asked again only after a minute
statusRow = true
check("a no is cached for a minute", S.Available(alice) == false and #module.log == 0)
clock = clock + 61
check("then the row and a ping", S.Available(alice) == true and #module.log == 1)
local ping = module.log[1]
check("request: magic, version, op", ping[1].kind == "ULong" and ping[1].v == 0x53425831 and ping[2].v == 1 and ping[3].v == 1)
check("ping sent on the bridge opcode only", #wire == 0)
check("yes is cached", S.Available(alice) and #module.log == 1)
check("move mode from the ping", S.MoveMode() == 0)

-- ------------------------------------------------------------------ spawn
local qx, qy, qz, qw = S.QuatFromYawPitchRoll(1.0, 0.3, -0.2)
check("quaternion matches the C++ vector", near(qx, -0.157915) and near(qy, 0.083164) and near(qz, 0.484766) and near(qw, 0.856241))
local yx, yy, yz, yw = S.QuatFromYawPitchRoll(0.75, 0, 0)
check("yaw only is about z", near(yx, 0) and near(yy, 0) and near(yz, math.sin(0.375)) and near(yw, math.cos(0.375)))

g = S.Spawn(42, 2413, 0, -9448.5, 68.2, 56.3, qx, qy, qz, qw, 1.5, alice)
check("spawn returns the module's guid", g == module.guid)
local sp = module.log[#module.log]
local kinds = {}
for i, e in ipairs(sp) do kinds[i] = e.kind end
check("spawn layout: id, entry, map, xyz, quat, size", table.concat(kinds, ",") ==
    "ULong,UByte,UByte,ULong,ULong,ULong,Float,Float,Float,Float,Float,Float,Float,Float")
check("spawn values", sp[3].v == 2 and sp[4].v == 42 and sp[5].v == 2413 and sp[6].v == 0 and sp[7].v == -9448.5 and sp[14].v == 1.5)
check("spawn refuses NaN without asking", S.Spawn(42, 2413, 0, 0 / 0, 1, 1, 0, 0, 0, 1, 1, alice) == nil and module.log[#module.log] == sp)

-- ------------------------------------------------------------------ move, scale, despawn
local before = #module.log
g = S.Move(module.guid, 1, 2, 3, 0, 0, 0, 1, alice)
local mv = module.log[#module.log]
check("move keeps the guid", g == module.guid and #module.log == before + 1)
check("move layout: guid, xyz, quat", mv[3].v == 3 and mv[4].kind == "GUID" and mv[4].v == module.guid and mv[5].v == 1 and mv[11].v == 1 and #mv == 11)
module.moveGuid = 0xF110000000002000
check("mode 1: move returns the new guid", S.Move(module.guid, 1, 2, 3, 0, 0, 0, 1, alice) == 0xF110000000002000)
module.moveGuid = nil
check("scale", S.SetScale(module.guid, 2, alice) == true and module.log[#module.log][3].v == 4 and module.log[#module.log][5].v == 2)
check("despawn forget", S.Despawn(module.guid, true, alice) == true and module.log[#module.log][5].kind == "UByte" and module.log[#module.log][5].v == 1)
check("despawn keep", S.Despawn(module.guid, false, alice) == true and module.log[#module.log][5].v == 0)

check("find: the prop's object", S.Find(42, alice) == module.guid and module.log[#module.log][3].v == 6
    and module.log[#module.log][4].kind == "ULong" and module.log[#module.log][4].v == 42)

-- statuses
module.status = 3
local okM, whyM = S.Move(999, 1, 2, 3, 0, 0, 0, 1, alice)
check("not a builder object", okM == nil and whyM == "not a builder object")
module.status = 6
check("rate", select(2, S.SetScale(module.guid, 1, alice)) == "too many changes at once")
module.status = 0
check("still available after a refusal", S.Available(alice))

-- carriers: Use(), then anyone in the world
S.Use(nil)
check("no carrier, nobody online: no call", select(2, S.SetScale(module.guid, 1)) == "no player to carry it")
online[1] = player("Bob")
check("anyone online carries it", S.SetScale(module.guid, 1) == true)
S.Use(alice)
check("Use() carries it", S.SetScale(module.guid, 1) == true)

-- the module stops answering (an old image with a leftover row): one packet, then off
module.on = false
local sentBefore = #wire
check("no answer: the call fails", S.SetScale(module.guid, 1, alice) == nil)
check("no answer: that one packet went out, then the module counts as gone", #wire == sentBefore + 1 and S.Available(alice) == false)
check("gone: no more packets", S.Move(module.guid, 1, 2, 3, 0, 0, 0, 1, alice) == nil and #wire == sentBefore + 1)

-- the off switch
module.on = true
T.reset()
env.OV_SANDBOX_CORE = "0"
check("OV_SANDBOX_CORE=0 turns it off", S.Available(alice) == false)
env.OV_SANDBOX_CORE = nil
check("and back on", S.Available(alice) == true)

-- no brand words in what players could see
local src = io.open(file):read("*a")
check("no game-brand names", not src:find("World of Warcraft") and not src:find("Blizzard") and not src:find("Warcraft"))

print(string.format("%d passed, %d failed", pass, fail))
os.exit(fail == 0 and 0 or 1)
