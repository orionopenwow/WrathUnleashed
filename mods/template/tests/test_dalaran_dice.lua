-- lua5.1 tests/test_dalaran_dice.lua realm/dalaran_dice.lua
-- Fake-ALE test: stubs the few mod-ale functions the script calls, then drives its events.
local file = assert(arg[1], "path to realm/dalaran_dice.lua")
local sql, events, sent = {}, {}, {}
local clock = 1000000
local dice = {}
os.time = function() return clock end
math.random = function(lo, hi) local v = table.remove(dice, 1) or lo; assert(v >= lo and v <= hi); return v end
function CharDBExecute(q) sql[#sql + 1] = q end
function RegisterPlayerEvent(id, fn) events[id] = fn end
OVMod = { Send = function(p, mod, name, data) sent[#sent + 1] = { to = p:GetName(), mod = mod, name = name, data = data } end }
dofile(file)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local function player(over)
    local p = { msgs = {}, near = {}, zone = 4395, guid = 5, name = "Tester" }
    for k, v in pairs(over or {}) do p[k] = v end
    function p:SendBroadcastMessage(m) self.msgs[#self.msgs + 1] = m end
    function p:GetGUIDLow() return self.guid end
    function p:GetName() return self.name end
    function p:GetZoneId() return self.zone end
    function p:GetPlayersInRange(r) self.range = r; return self.near end
    return p
end
local function last(p) return p.msgs[#p.msgs] or "" end
local cmd = events[42]

check("table created on load", sql[1]:match("^CREATE TABLE IF NOT EXISTS mod_dalaran_dice_rolls"))
check("command event registered", type(cmd) == "function")

local friend = player({ guid = 6, name = "Friend" })
local p = player()
p.near = { friend, p } -- some cores include the caller in range results; it must still get one message
dice = { 3, 5 }
local n0 = #sql
check(".dice handled", cmd(42, p, "dice") == false)
check("2d6 by default, shown with faces", last(p):match("Tester rolls 2d6: |cffffff003 %+ 5 = 8|r"))
check("roller gets one message", #p.msgs == 1)
check("nearby player sees it", last(friend):match("Tester rolls 2d6"))
check("range is 30 yards", p.range == 30)
check("addon message to both", #sent == 2 and sent[1].to == "Tester" and sent[2].to == "Friend")
check("addon message format", sent[1].mod == "dalaran-dice" and sent[1].name == "roll" and sent[1].data == "Tester,2,6,8,3 5")
check("one insert", #sql == n0 + 1 and sql[#sql]:match("^INSERT INTO mod_dalaran_dice_rolls"))
check("insert values", sql[#sql]:match("VALUES %(5, 'Tester', 2, 6, 8%)$"))

local before = #sql
cmd(42, p, "dice")
check("cooldown", #sql == before and last(p):match("Wait a moment"))
clock = clock + 5
dice = { 20, 1, 7 }
cmd(42, p, "dice 3D20")
check("3d20 after the cooldown", #sql == before + 1 and last(p):match("rolls 3d20: |cffffff0020 %+ 1 %+ 7 = 28|r"))
clock = clock + 5
dice = { 12 }
cmd(42, p, "dice d20")
check("d20 means one die, no faces shown", last(p):match("rolls 1d20: |cffffff0012|r$"))

local q = player({ guid = 7 })
for _, bad in ipairs({ "dice 11d6", "dice 2d1", "dice 2d101", "dice 0d6", "dice lots" }) do
    local c = #sql
    check(bad .. " shows help, no roll", cmd(42, q, bad) == false and #sql == c and last(q):match("%.dice 3d20"))
end
check(".dice help", cmd(42, q, "dice help") == false and last(q):match("up to 10 dice"))

local away = player({ guid = 8, zone = 1519 })
local c = #sql
check("refused outside Dalaran", cmd(42, away, "dice") == false and #sql == c and last(away):match("only roll in Dalaran"))

local quote = player({ guid = 9, name = "O'Neil" })
cmd(42, quote, "dice")
check("name escaped in SQL", sql[#sql]:match("'O''Neil'"))

check("other commands untouched", cmd(42, p, "dicey") == nil and cmd(42, p, "gm on") == nil)
check("console command ignored", cmd(42, nil, "dice") == nil)

OVMod = nil
clock = clock + 10
local solo = player({ guid = 10 })
check("works without ov_modapi loaded", pcall(cmd, 42, solo, "dice") and last(solo):match("rolls 2d6"))

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
