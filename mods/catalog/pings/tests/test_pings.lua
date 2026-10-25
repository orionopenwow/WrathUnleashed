-- lua5.1 tests/test_pings.lua realm/pings.lua
-- Fake-ALE test: a fake OVMod and group, then pings through the "map" handler.
local file = assert(arg[1], "path to realm/pings.lua")
local clock = 1000000
os.time = function() return clock end
local timers, handlers, sent = {}, {}, {}

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- 1. loaded before ov_modapi.lua: it waits a second, then registers
OVMod = nil
function CreateLuaEvent(fn, ms, n) timers[#timers + 1] = { fn = fn, ms = ms, n = n } end
dofile(file)
check("waits for ov_modapi.lua", #timers == 1 and timers[1].ms == 1000 and timers[1].n == 1)
OVMod = {
    On = function(mod, name, fn) handlers[mod .. "/" .. name] = fn end,
    Send = function(p, mod, name, data) sent[#sent + 1] = { to = p:GetName(), mod = mod, name = name, data = data } end,
}
timers[1].fn()
local onMap = handlers["pings/map"]
check("registers pings/map once ov_modapi.lua is there", type(onMap) == "function")
timers[1].fn()
check("registers only once", onMap == handlers["pings/map"])

local function player(over)
    local p = { name = "Tester", guid = 5, map = 571, inst = 0, world = true }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:GetName() return self.name end
    function p:GetGUIDLow() return self.guid end
    function p:GetMapId() return self.map end
    function p:GetInstanceId() return self.inst end
    function p:IsInWorld() return self.world end
    function p:GetGroup() return self.group end
    return p
end
local me = player()
local friend = player({ name = "Friend", guid = 6 })
local far = player({ name = "Faraway", guid = 7, map = 0 })
local dungeon = player({ name = "Delver", guid = 8, inst = 42 })
local offline = player({ name = "Gone", guid = 9, world = false })
local group = { members = { me, friend, far, dungeon, offline } }
function group:GetMembers() return self.members end
for _, p in ipairs(group.members) do p.group = group end

local function last() return sent[#sent] end
sent = {}
local n = onMap(me, "attack,504,0,0.4512,0.6230")
check("relayed to one member", n == 1 and #sent == 1)
check("only the member on the same map and instance", last().to == "Friend")
check("not back to the sender", sent[1].to ~= "Tester")
check("message names", last().mod == "pings" and last().name == "map")
check("data carries the sender", last().data == "attack,504,0,0.4512,0.6230,Tester")

sent = {}
onMap(me, "look,504,2,1,0")
check("edges 0 and 1 and a floor", last().data == "look,504,2,1.0000,0.0000,Tester")

for _, bad in ipairs({ "nuke,504,0,0.5,0.5", "attack,504,0,1.5,0.5", "attack,504,0,0.5", "attack,0,0,0.5,0.5",
                       "attack,504,0,-0.1,0.5", "attack,504,0,0.5,0.5,extra", "attack,999999,0,0.5,0.5",
                       "attack,504,99,0.5,0.5", "attack,504,0,0x1,0.5", "attack,504,0,1e0,0.5", "",
                       "attack,504,0,0.12345,0.5", string.rep("a", 80) }) do
    sent = {}
    onMap(me, bad)
    check("refused: " .. bad:sub(1, 30), #sent == 1 and sent[1].to == "Tester" and sent[1].name == "denied" and sent[1].data == "bad")
end

local solo = player({ name = "Solo", guid = 10 })
sent = {}
onMap(solo, "look,504,0,0.5,0.5")
check("no group: denied nogroup", #sent == 1 and sent[1].data == "nogroup")

clock = clock + 100
local ok = 0
for i = 1, 7 do
    sent = {}
    onMap(me, "danger,504,0,0.5,0.5")
    if sent[1] and sent[1].name == "map" then ok = ok + 1 end
end
check("5 pings per 5 seconds", ok == 5 and last().data == "rate")
clock = clock + 5
sent = {}
onMap(me, "danger,504,0,0.5,0.5")
check("allowed again after the window", last().name == "map")

group.members = { me }
sent = {}
check("alone in the group: nobody to send to", onMap(me, "assist,504,0,0.5,0.5") == 0 and #sent == 0)

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
