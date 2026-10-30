-- lua5.1 stream/tests/test_ov_admin.lua [lua_scripts dir]
-- The Admin Console's realm half (ov_admin.lua) under a fake mod-ale, after ov_modapi.lua and ov_workshop.lua (ALE's
-- name order loads ov_admin.lua first: it looks the Workshop up when a command arrives). Covers: console only (a
-- player gets nothing), GM level, the Workshop list / set / edit / check (nothing deleted), bug reports list / set /
-- count, bad arguments refused, nothing a form sends reaching SQL as written.
local scripts = arg[1] or "realm/custom/lua_scripts"

local pass, fail = 0, 0
local realPrint = print
local function check(name, ok)
    if ok then pass = pass + 1; realPrint("PASS " .. name) else fail = fail + 1; realPrint("FAIL " .. name) end
end
print = function() end

local clock = 3000000
os.time = function() return clock end

local events, serverEvents = {}, {}
function RegisterPlayerEvent(id, fn) events[id] = events[id] or {}; table.insert(events[id], fn) end
function RegisterServerEvent(id, fn) serverEvents[id] = fn end
function CreateLuaEvent() end

local sql, authSqlSeen = {}, {}
local bugs = {
    { 7, "new", 1700000000, "Ann", 12, 0, 12, "the quest giver\tin Northshire |cffff0000has no mark" },
    { 6, "seen", 1699990000, "Bob", 80, 571, 4395, "stuck in a wall" },
}
local function result(rows)
    if not rows or #rows == 0 then return nil end
    local r = { rows = rows, i = 1 }
    function r:GetUInt32(c) return tonumber(self.rows[self.i][c + 1]) end
    function r:GetString(c) return tostring(self.rows[self.i][c + 1] or "") end
    function r:NextRow() self.i = self.i + 1; return self.i <= #self.rows end
    return r
end
local lastBugQuery
function CharDBExecute(s) sql[#sql + 1] = s end
function CharDBQuery(q)
    if q:find("FROM ov_bug_reports", 1, true) then
        lastBugQuery = q
        if q:find("GROUP BY status", 1, true) then return result({ { "new", 1 }, { "seen", 1 } }) end
        return result(bugs)
    end
    return nil
end
function AuthDBExecute(s) end
function AuthDBQuery(q)
    authSqlSeen[#authSqlSeen + 1] = q
    if q:find("username = 'WR000001'", 1, true) then return result({ { 1, "3" } }) end
    if q:find("username = 'WR000002'", 1, true) then return result({ { 2, "0" } }) end
    return nil
end

package.path = scripts .. "/?.lua;" .. package.path
local ADMIN = dofile(scripts .. "/ov_admin.lua")          -- first, as ALE loads it
local OVMod = dofile(scripts .. "/ov_modapi.lua")
package.loaded["ov_modapi"] = OVMod
local WS = dofile(scripts .. "/ov_workshop.lua")

local out = {}
local console = { SendSysMessage = function(_, m) out[#out + 1] = m end }
local function soap(text)
    out = {}
    for _, fn in ipairs(events[42] or {}) do
        if fn(42, nil, text, console) == false then break end
    end
    return out
end
local function has(lines, pat) for _, l in ipairs(lines) do if l:find(pat, 1, true) then return true end end end
local function last(lines) return lines[#lines] or "" end

check("a global for tests and other scripts", OVAdmin == ADMIN and type(ADMIN.Console) == "function")

-- console only
local playerSaw = {}
local player = { SendBroadcastMessage = function(_, t) playerSaw[#playerSaw + 1] = t end }
local handled = false
for _, fn in ipairs(events[42] or {}) do if fn(42, player, "ovadmin ping") == false then handled = true end end
check("a player typing ovadmin gets nothing", not handled and #playerSaw == 0)
check("ping", has(soap("ovadmin ping"), "ovadmin ok") and last(out) == "ovadmin end 0")
check("other console commands pass through", #soap("server info") == 0)

-- GM level
check("gm: the account's level", has(soap("ovadmin gm wr000001"), "ovadmin gm WR000001 3"))
check("gm: a player account is 0", has(soap("ovadmin gm WR000002"), "ovadmin gm WR000002 0"))
check("gm: unknown account is 0", has(soap("ovadmin gm NOBODY"), "ovadmin gm NOBODY 0"))
local before = #authSqlSeen
check("gm: a bad name is refused before SQL", has(soap("ovadmin gm x';DROP"), "ovadmin error") and #authSqlSeen == before)

-- the Workshop
local b1 = WS.Published("build", "ABCDEF", "Cozy Inn", nil, 11, "Ann")
local b2 = WS.Published("build", "GHJKLM", "Tower", nil, 12, "Bob")
b2.descr = "a shit tower"
check("builds wait for review", b1.state == "pending" and b2.state == "pending")
local l = soap("ovadmin ws list pending")
check("ws list: one ROW per pending item, newest first", l[1]:find("^ROW\t2\tbuild\tpending") and l[2]:find("^ROW\t1\tbuild\tpending")
    and last(l) == "ovadmin end 2")
check("ws list: flagged column", select(2, l[1]:gsub("\t", "\t")) == 11 and l[1]:find("\tBob\t1\tTower\t", 1, true)
    and l[2]:find("\tAnn\t0\tCozy Inn\t", 1, true))
check("ws list: n caps the rows", last(soap("ovadmin ws list all 1")) == "ovadmin end 1")
check("ws list: bad state refused", has(soap("ovadmin ws list everything"), "ovadmin error"))
local nsql = #sql
check("ws set approve", has(soap("ovadmin ws set 1 approve"), "ovadmin ok: #1 approved") and b1.state == "approved" and #sql > nsql)
check("ws set pending: off the list, nothing deleted", has(soap("ovadmin ws set 1 pending"), "#1 pending") and WS._items[1] == b1)
check("ws set reject keeps the row", has(soap("ovadmin ws set 2 reject"), "#2 rejected") and WS._items[2] == b2)
local deleted = false
for _, s in ipairs(sql) do if s:find("DELETE FROM mod_workshop", 1, true) then deleted = true end end
check("no DELETE ever", not deleted)
check("ws set: unknown word refused", has(soap("ovadmin ws set 1 unpublish"), "ovadmin error") and b1.state == "pending")
check("ws set: unknown item", has(soap("ovadmin ws set 99 approve"), "ovadmin error: no such item"))
check("ws edit title (cleaned)", has(soap("ovadmin ws edit 1 title The 'Cozy' Inn;"), "ovadmin ok: #1 The Cozy Inn") and b1.title == "The Cozy Inn")
check("ws edit descr", has(soap("ovadmin ws edit 1 descr A warm place."), "#1 A warm place.") and b1.descr == "A warm place.")
check("ws edit: filtered words refused", has(soap("ovadmin ws edit 1 title shit inn"), "ovadmin error") and b1.title == "The Cozy Inn")
check("ws edit: empty title refused", has(soap("ovadmin ws edit 1 title '''"), "ovadmin error"))
check("ws edit: other fields refused", has(soap("ovadmin ws edit 1 author Bob"), "ovadmin error") and b1.author == "Ann")
local f = soap("ovadmin ws check 2")
check("ws check: the description's filtered word", has(f, "FINDING\tdescription: filtered word") and last(f) == "ovadmin end 1")
check("ws check: clean item", last(soap("ovadmin ws check 1")) == "ovadmin end 0")

-- bug reports
local bl = soap("ovadmin bugs list open 20")
check("bugs list: rows, flattened text", bl[1] == "ROW\t7\tnew\t1700000000\tAnn\t12\t0\t12\tthe quest giver in Northshire  cffff0000has no mark"
    and last(bl) == "ovadmin end 2")
check("bugs list open = new and seen", lastBugQuery:find("status IN ('new', 'seen')", 1, true) and lastBugQuery:find("LIMIT 20", 1, true))
soap("ovadmin bugs list all 999")
check("bugs list: at most 200", lastBugQuery:find("LIMIT 200", 1, true) ~= nil)
check("bugs list: bad status refused", has(soap("ovadmin bugs list x'"), "ovadmin error"))
nsql = #sql
check("bugs set resolved", has(soap("ovadmin bugs set 7 resolved"), "bug 7 resolved")
    and sql[#sql] == "UPDATE ov_bug_reports SET status = 'resolved' WHERE id = 7")
check("bugs set: bad status refused before SQL", has(soap("ovadmin bugs set 7 gone"), "ovadmin error") and #sql == nsql + 1)
local c = soap("ovadmin bugs count")
check("bugs count", has(c, "COUNT\tnew\t1") and has(c, "COUNT\tseen\t1"))
check("unknown words: usage", has(soap("ovadmin nope"), "ovadmin error: usage"))

realPrint(string.format("%d passed, %d failed", pass, fail))
if fail > 0 then os.exit(1) end
