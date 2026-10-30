-- ov_admin.lua: the realm half of the Leyline Admin Console (stream/admin.py on the website), mod-ale / Eluna, 3.3.5a.
--
-- Console / SOAP only: a player typing these gets nothing (no reply, not handled here). The website reaches the realm
-- only through SOAP with its own GM login, and this script is the one place that answers the console's admin words.
-- Every argument is checked here again (ids are digits, words come from fixed lists, text is cleaned by the script
-- that owns the row), so nothing a web form sends reaches SQL as written.
--
--   ovadmin ping                                    -> "ovadmin ok"
--   ovadmin gm <ACCOUNT>                            -> "ovadmin gm <ACCOUNT> <level>"   (the account's highest GM level)
--   ovadmin ws list <pending|approved|rejected|all> [n]
--        -> one "ROW" line per Workshop item (ov_workshop.lua), newest first, at most n (default 50, at most 200):
--           ROW \t id \t kind \t state \t version \t plays \t up \t down \t author \t flagged(0|1) \t title \t descr
--   ovadmin ws set <id> <approve|reject|pending>    (pending = taken off the list; nothing is deleted)
--   ovadmin ws edit <id> <title|descr> <text>
--   ovadmin ws check <id>                           -> "FINDING \t <text>" lines (the word filter and reference checks)
--   ovadmin bugs list <new|seen|resolved|wontfix|open|all> [n]
--        -> ROW \t id \t status \t created \t char name \t level \t map \t zone \t text          (ov_reports.lua's .bug)
--   ovadmin bugs set <id> <new|seen|resolved|wontfix>
--   ovadmin bugs count                              -> "COUNT \t <status> \t <n>" lines
-- Every answer ends with "ovadmin end <rows>" or starts with "ovadmin error: ...".
-- mod-ale event: 42 ON_COMMAND (player is nil for the console; return false = handled).

local A = {}
OVAdmin = A

local WS_STATES = { pending = true, approved = true, rejected = true, all = true }
local WS_ACTIONS = { approve = true, reject = true, pending = true }
local BUG_STATES = { new = true, seen = true, resolved = true, wontfix = true }
local MAX_ROWS = 200

local function flat(s) return (tostring(s or ""):gsub("[%c|]", " ")) end

local function charQuery(sql)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, sql)
    if ok then return q end
end
local function charExec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end
local function authQuery(sql)
    if not AuthDBQuery then return nil end
    local ok, q = pcall(AuthDBQuery, sql)
    if ok then return q end
end

local function count(n)
    n = tonumber(n) or 50
    if n < 1 then n = 1 end
    if n > MAX_ROWS then n = MAX_ROWS end
    return math.floor(n)
end

-- ------------------------------------------------------------------------------------------------- GM level
function A.GM(out, name)
    if not name or not name:match("^%w+$") or #name > 16 then return out("ovadmin error: usage: ovadmin gm <account>") end
    name = name:upper()
    local q = authQuery(string.format("SELECT a.id, IFNULL(MAX(aa.gmlevel), 0) FROM account a "
        .. "LEFT JOIN account_access aa ON aa.id = a.id WHERE a.username = '%s' GROUP BY a.id", name))
    local level = q and tonumber(q:GetString(1)) or 0
    out(string.format("ovadmin gm %s %d", name, level))
    out("ovadmin end 1")
end

-- ------------------------------------------------------------------------------------------- the Workshop
local function workshop() return rawget(_G, "OVWorkshop") end

function A.Workshop(out, args)
    local W = workshop()
    if type(W) ~= "table" or type(W.Admin) ~= "function" then return out("ovadmin error: the Workshop is not loaded") end
    local word, rest = args:match("^(%S*)%s*(.*)$")
    if word == "list" then
        local state, n = rest:match("^(%a*)%s*(%d*)")
        if not WS_STATES[state] then return out("ovadmin error: state is pending, approved, rejected or all") end
        local l = {}
        for _, it in pairs(W.Items()) do if state == "all" or it.state == state then l[#l + 1] = it end end
        table.sort(l, function(a, b) return a.id > b.id end)
        local rows = math.min(#l, count(n))
        for i = 1, rows do
            local it = l[i]
            local flagged = (W.BadWord(it.title) or W.BadWord(it.descr)) and 1 or 0
            out(table.concat({ "ROW", it.id, it.kind, it.state, it.version, it.plays, it.up, it.down, flat(it.author),
                flagged, flat(it.title), flat(it.descr) }, "\t"))
        end
        return out("ovadmin end " .. rows)
    end
    if word == "set" then
        local id, action = rest:match("^(%d+)%s+(%a+)%s*$")
        if not id or not WS_ACTIONS[action] then return out("ovadmin error: usage: ovadmin ws set <id> approve|reject|pending") end
        local it, why = W.Admin(id, action)
        if not it then return out("ovadmin error: " .. why) end
        out(string.format("ovadmin ok: #%d %s", it.id, it.state))
        return out("ovadmin end 0")
    end
    if word == "edit" then
        local id, field, text = rest:match("^(%d+)%s+(%a+)%s+(.-)%s*$")
        if not id or (field ~= "title" and field ~= "descr") then
            return out("ovadmin error: usage: ovadmin ws edit <id> title|descr <text>")
        end
        local it, why = W.Admin(id, field, text)
        if not it then return out("ovadmin error: " .. why) end
        out(string.format("ovadmin ok: #%d %s", it.id, flat(it[field])))
        return out("ovadmin end 0")
    end
    if word == "check" then
        local id = tonumber(rest:match("^(%d+)%s*$") or "")
        local it = id and W.Items()[id]
        if not it then return out("ovadmin error: no such item") end
        local f = W.Check(it)
        for _, x in ipairs(f) do out("FINDING\t" .. flat(x)) end
        return out("ovadmin end " .. #f)
    end
    out("ovadmin error: usage: ovadmin ws list|set|edit|check")
end

-- ------------------------------------------------------------------------------------------- bug reports
function A.Bugs(out, args)
    local word, rest = args:match("^(%S*)%s*(.*)$")
    if word == "list" then
        local state, n = rest:match("^(%a*)%s*(%d*)")
        local where
        if state == "all" then where = ""
        elseif state == "open" then where = "WHERE status IN ('new', 'seen') "
        elseif BUG_STATES[state] then where = "WHERE status = '" .. state .. "' "
        else return out("ovadmin error: status is new, seen, resolved, wontfix, open or all") end
        local q = charQuery("SELECT id, status, UNIX_TIMESTAMP(created_at), char_name, level, map_id, zone_id, text "
            .. "FROM ov_bug_reports " .. where .. "ORDER BY id DESC LIMIT " .. count(n))
        local rows = 0
        if q then
            repeat
                rows = rows + 1
                out(table.concat({ "ROW", q:GetUInt32(0), flat(q:GetString(1)), q:GetUInt32(2), flat(q:GetString(3)),
                    q:GetUInt32(4), q:GetUInt32(5), q:GetUInt32(6), flat(q:GetString(7)) }, "\t"))
            until not q:NextRow()
        end
        return out("ovadmin end " .. rows)
    end
    if word == "set" then
        local id, state = rest:match("^(%d+)%s+(%a+)%s*$")
        if not id or not BUG_STATES[state] then return out("ovadmin error: usage: ovadmin bugs set <id> new|seen|resolved|wontfix") end
        charExec(string.format("UPDATE ov_bug_reports SET status = '%s' WHERE id = %d", state, tonumber(id)))
        out(string.format("ovadmin ok: bug %d %s", tonumber(id), state))
        return out("ovadmin end 0")
    end
    if word == "count" then
        local q = charQuery("SELECT status, COUNT(*) FROM ov_bug_reports GROUP BY status")
        local rows = 0
        if q then
            repeat
                rows = rows + 1
                out("COUNT\t" .. flat(q:GetString(0)) .. "\t" .. q:GetUInt32(1))
            until not q:NextRow()
        end
        return out("ovadmin end " .. rows)
    end
    out("ovadmin error: usage: ovadmin bugs list|set|count")
end

-- ------------------------------------------------------------------------------------------------ console
function A.Console(command, handler)
    local rest = (command or ""):match("^ovadmin%s*(.*)$")
    if not rest then return nil end
    local function out(msg) if handler then pcall(handler.SendSysMessage, handler, msg) end end
    local word, args = rest:match("^(%S*)%s*(.*)$")
    if word == "ping" then out("ovadmin ok"); out("ovadmin end 0")
    elseif word == "gm" then A.GM(out, args:match("^(%S+)"))
    elseif word == "ws" then A.Workshop(out, args)
    elseif word == "bugs" then A.Bugs(out, args)
    else out("ovadmin error: usage: ovadmin ping|gm|ws|bugs") end
    return false
end

local function onCommand(event, player, command, handler)
    if player then return nil end   -- console and SOAP only: players never reach the admin words
    return A.Console(command, handler)
end

RegisterPlayerEvent(42, onCommand)  -- PLAYER_EVENT_ON_COMMAND

return A
