-- ov_workshop.lua: the Leyline Workshop, the realm half (mod-ale / Eluna, 3.3.5a).
--
-- One list of what players made, so others can find it and play it in one click: minigolf courses
-- (ov_golf.lua), modes (ov_modes.lua) and builds (ov_build.lua share codes). Each is a Workshop item:
--   id, kind (course | mode | build), ref (the course key, the mode key or the 6-letter build code), title,
--   author (the character's name, nothing else), version, created, plays, thumbs up and down (one vote per
--   account), state (pending | approved | rejected) and a short description.
-- This script never runs anything players send. Play hands the item to its own script exactly as if the player
-- had pressed Play there (OVMod.Dispatch): ov_golf.lua starts the course and invites the party, ov_modes.lua
-- hosts the mode (the mode's code runs only in the host's client sandbox), ov_build.lua pastes the build in the
-- player's build area. Each of those scripts checks role, area, budget and rate itself.
--
-- How items appear:
--   course   when a course is published from the editor (ov_golf.lua calls OVWorkshop.Published). Courses are
--            geometry only and were already public in /golf, so a new one is approved at once, unless its title
--            trips the word filter: then it waits for a GM.
--   mode     when a mode is published (ov_modes.lua). A mode is code: it waits for a GM. .modes approve and
--            .workshop approve are the same thing.
--   build    .workshop publish <code> [title] (or the Workshop tab): a build you shared with .build share.
--            Waits for a GM.
-- Publishing again (the same course or mode key) is a new version of the same item: plays and votes stay.
--
-- OVMOD channel (ov_modapi.lua), mod "wuws":
--   client -> server   list <all|course|mode|build> <plays|rating|new> <page>   approved items, 8 a page
--                      mine                                                    your own items, any state
--                      rate <id> <up|down|none>                                one vote per account
--                      play <id>                                               start it (see above)
--                      publish <code> <title>                                  a shared build
--   server -> client   items  <kind> <sort> <page> <pages>\n<row>\n<row>...
--                             row: id \t kind \t title \t author \t version \t plays \t up \t down \t myvote \t state \t description
--                      rated  <id> <up> <down> <myvote>        playing <id> <kind> <title>        msg <text>
-- Commands: .workshop [help] | play <id> | publish <code> [title] | describe <id> <text> | mine
--   GM:     .workshop pending | approve <id> | reject <id> | unpublish <id>
-- Console / SOAP only (the website's Play button, stream/creations.py through wrath_portal.remember_go):
--   ovws go <ACCOUNT> <id>    plays the item on that account's next login (or now if online); 30 minutes
-- Tables: characters DB mod_workshop_items, mod_workshop_votes; auth DB ov_ws_intents. The website reads the
-- approved items from a file realm/custom/workshop-export.py writes every 5 minutes; it never writes here.
-- mod-ale events: 3 ON_LOGIN, 42 ON_COMMAND (return false = handled).

local OVMod
do
    local ok, m = pcall(function() return require("ov_modapi") end)
    OVMod = (ok and type(m) == "table" and m) or rawget(_G, "OVMod")
    if not OVMod then
        print("[ov_workshop] ov_modapi.lua is missing: the Workshop needs the OVMOD channel; not loaded")
        return
    end
end

local MOD = "wuws"
local TAG = "|cffffc94a[Workshop]|r "
local KINDS = { course = true, mode = true, build = true }
local KIND_NAME = { course = "course", mode = "mode", build = "build" }
local PAGE = 8
local MAX_TITLE = 40
local MAX_DESC = 140
local MAX_BUILDS = 10            -- builds one character may have in the Workshop
local INTENT_TTL = 1800
local LOGIN_DELAY = 6000         -- after ov_go.lua's 5 s and ov_slices.lua
local PLAY_COUNT_GAP = 1800      -- one account counts as one play of an item per 30 minutes
-- seconds between one player's actions of a kind
local GAP = { list = 1, mine = 2, rate = 2, play = 5, publish = 30, describe = 10, cmd = 1 }

OVWorkshopHooks = rawget(_G, "OVWorkshopHooks") or {}
local hooks = OVWorkshopHooks
local W = {}
OVWorkshop = W

local items = {}       -- id -> item
local byRef = {}       -- "kind:ref" -> id
local votes = {}       -- id -> { [account] = 1 | -1 }
local counted = {}     -- "id:account" -> os.time() of the last counted play
local last = {}        -- "guid:what" -> os.time()
local intents = {}     -- account -> { id, exp }
local nextId = 1

local function now() return os.time() end
local function try(obj, method, ...)
    if not obj then return nil end
    local okf, fn = pcall(function() return obj[method] end)
    if not okf or type(fn) ~= "function" then return nil end
    local ok, a = pcall(fn, obj, ...)
    if ok then return a end
end
local function say(player, text) try(player, "SendBroadcastMessage", TAG .. text) end
local function send(player, name, data) if player then OVMod.Send(player, MOD, name, data or "") end end
local function isGM(player) return (tonumber(try(player, "GetGMRank")) or 0) > 0 end
local function exec(sql) if CharDBExecute then pcall(CharDBExecute, sql) end end
local function query(sql)
    if not CharDBQuery then return nil end
    local ok, q = pcall(CharDBQuery, sql)
    if ok then return q end
end
local function authExec(sql) if AuthDBExecute then pcall(AuthDBExecute, sql) end end
local function authQuery(sql)
    if not AuthDBQuery then return nil end
    local ok, q = pcall(AuthDBQuery, sql)
    if ok then return q end
end

-- Too soon since this player's last <what>? (and marks it)
local function tooSoon(player, what)
    local key = tostring(player:GetGUIDLow()) .. ":" .. what
    local t = now()
    if last[key] and t - last[key] < (GAP[what] or 1) then return true end
    last[key] = t
    return false
end

-- ------------------------------------------------------------------------------------- text and filter

-- Titles and descriptions: letters, digits, spaces and plain punctuation. No quotes, backslashes, pipes (colour
-- codes) or control characters, so nothing needs escaping in SQL and nothing can restyle the screen.
local function cleanText(s, max)
    s = tostring(s or ""):gsub("[\r\n\t]", " "):gsub("[^%w %-!&%.,%?:%(%)]", ""):gsub("%s+", " ")
    s = s:gsub("^ ", ""):gsub(" $", "")
    return s:sub(1, max)
end

-- A short list on purpose: slurs and the worst words, after undoing simple disguises (l33t digits, repeated
-- letters, dots or spaces between letters). GMs review modes and builds anyway; this keeps the worst titles off
-- the list before anyone sees them.
local BAD = {
    "fuck", "shit", "cunt", "bitch", "whore", "slut", "nigger", "nigga", "faggot", "fag", "retard", "rape",
    "rapist", "kike", "spic", "chink", "tranny", "nazi", "hitler", "cock", "dick", "pussy", "porn", "penis",
    "vagina", "twat", "wank", "dildo", "kys",
}
local BAD_INSIDE = { fuck = true, shit = true, nigger = true, nigga = true, faggot = true, whore = true,
    rapist = true, hitler = true, porn = true, dildo = true }
local LEET = { ["0"] = "o", ["1"] = "i", ["3"] = "e", ["4"] = "a", ["5"] = "s", ["7"] = "t", ["8"] = "b", ["9"] = "g",
    ["@"] = "a", ["$"] = "s", ["!"] = "i", ["|"] = "l" }
local function squash(s)   -- "shiiit" -> "shit"
    local out, prev = {}, nil
    for c in s:gmatch(".") do if c ~= prev then out[#out + 1] = c end; prev = c end
    return table.concat(out)
end
local function badWord(text)
    local low = tostring(text or ""):lower():gsub(".", function(c) return LEET[c] or c end)
    local words = {}
    for w in low:gmatch("%a+") do words[#words + 1] = w end
    local joined = table.concat(words)
    local set = {}
    for _, w in ipairs(words) do set[w] = true; set[squash(w)] = true end
    for _, b in ipairs(BAD) do
        if set[b] or set[b .. "s"] then return b end
        if BAD_INSIDE[b] and (joined:find(b, 1, true) or squash(joined):find(b, 1, true)) then return b end
    end
    -- spaced out: "f u c k" -> single letters joined
    local singles = low:match("^[%a%s%.%-_]+$") and low:gsub("[^%a]", "") or ""
    if #singles >= 3 and #singles <= 12 then
        for b in pairs(BAD_INSIDE) do if squash(singles):find(b, 1, true) then return b end end
    end
    return nil
end
W.BadWord = badWord

-- --------------------------------------------------------------------------------------------- storage

exec([[CREATE TABLE IF NOT EXISTS mod_workshop_items (
  id INT UNSIGNED NOT NULL PRIMARY KEY, kind VARCHAR(8) NOT NULL, ref VARCHAR(32) NOT NULL,
  title VARCHAR(48) NOT NULL, author VARCHAR(12) NOT NULL, author_guid INT UNSIGNED NOT NULL,
  version SMALLINT UNSIGNED NOT NULL DEFAULT 1, created_at INT UNSIGNED NOT NULL, updated_at INT UNSIGNED NOT NULL,
  plays INT UNSIGNED NOT NULL DEFAULT 0, up INT UNSIGNED NOT NULL DEFAULT 0, down INT UNSIGNED NOT NULL DEFAULT 0,
  state VARCHAR(8) NOT NULL DEFAULT 'pending', descr VARCHAR(160) NOT NULL DEFAULT '',
  UNIQUE KEY kind_ref (kind, ref), KEY state (state), KEY author (author_guid))]])
exec([[CREATE TABLE IF NOT EXISTS mod_workshop_votes (
  item_id INT UNSIGNED NOT NULL, account_id INT UNSIGNED NOT NULL, vote TINYINT NOT NULL, voted_at INT UNSIGNED NOT NULL,
  PRIMARY KEY (item_id, account_id))]])
authExec("CREATE TABLE IF NOT EXISTS ov_ws_intents (account_id INT UNSIGNED NOT NULL PRIMARY KEY, "
    .. "item_id INT UNSIGNED NOT NULL, expires_at INT UNSIGNED NOT NULL, KEY expires_at (expires_at))")

local STATES = { pending = true, approved = true, rejected = true }
local function validRef(kind, ref)
    if type(ref) ~= "string" then return false end
    if kind == "build" then return #ref == 6 and ref:match("^[A-HJ-NP-Z2-9]+$") ~= nil end
    return #ref >= 1 and #ref <= 32 and ref:match("^[%w_]+$") ~= nil
end

local function remember(it)
    items[it.id] = it
    byRef[it.kind .. ":" .. it.ref] = it.id
    if it.id >= nextId then nextId = it.id + 1 end
end

local function save(it)
    exec(string.format("REPLACE INTO mod_workshop_items (id, kind, ref, title, author, author_guid, version, created_at, "
        .. "updated_at, plays, up, down, state, descr) VALUES (%d, '%s', '%s', '%s', '%s', %d, %d, %d, %d, %d, %d, %d, '%s', '%s')",
        it.id, it.kind, it.ref, cleanText(it.title, MAX_TITLE), (it.author:gsub("[^%a]", "")), it.guid, it.version,
        it.created, it.updated, it.plays, it.up, it.down, it.state, cleanText(it.descr, MAX_DESC)))
end

do
    local q = query("SELECT id, kind, ref, title, author, author_guid, version, created_at, updated_at, plays, up, down, state, descr "
        .. "FROM mod_workshop_items")
    if q then
        repeat
            local it = { id = q:GetUInt32(0), kind = q:GetString(1), ref = q:GetString(2), title = cleanText(q:GetString(3), MAX_TITLE),
                author = (q:GetString(4):gsub("[^%a]", "")), guid = q:GetUInt32(5), version = q:GetUInt32(6),
                created = q:GetUInt32(7), updated = q:GetUInt32(8), plays = q:GetUInt32(9), up = q:GetUInt32(10),
                down = q:GetUInt32(11), state = q:GetString(12), descr = cleanText(q:GetString(13), MAX_DESC) }
            if it.id > 0 and KINDS[it.kind] and validRef(it.kind, it.ref) and STATES[it.state] then remember(it) end
        until not q:NextRow()
    end
    q = query("SELECT item_id, account_id, vote FROM mod_workshop_votes")
    if q then
        repeat
            local id, acc, v = q:GetUInt32(0), q:GetUInt32(1), tonumber(q:GetString(2)) or 0
            if items[id] and (v == 1 or v == -1) then votes[id] = votes[id] or {}; votes[id][acc] = v end
        until not q:NextRow()
    end
end

local function itemOf(kind, ref) local id = byRef[kind .. ":" .. tostring(ref)]; return id and items[id] end

-- --------------------------------------------------------------------------------- the publish hooks

-- Called by ov_golf.lua / ov_modes.lua after they stored a publish (and by .workshop publish for builds).
-- Returns the item. title is checked again here; author is the character's name only.
function W.Published(kind, ref, title, player, guid, name)
    if not KINDS[kind] or not validRef(kind, ref) then return nil end
    guid = guid or (player and player:GetGUIDLow()) or 0
    name = ((name or (player and player:GetName()) or "Leyline"):gsub("[^%a]", "")):sub(1, 12)
    title = cleanText(title, MAX_TITLE)
    if title == "" then title = "Untitled " .. KIND_NAME[kind] end
    local flagged = badWord(title) ~= nil
    local t = now()
    local it = itemOf(kind, ref)
    if it then
        it.version, it.updated, it.title = it.version + 1, t, title
        -- a mode is new code and a flagged title needs eyes; an approved course stays up
        if kind ~= "course" or flagged or it.state ~= "approved" then it.state = "pending" end
    else
        it = { id = nextId, kind = kind, ref = ref, title = title, author = name, guid = guid, version = 1, created = t,
            updated = t, plays = 0, up = 0, down = 0, descr = "",
            state = (kind == "course" and not flagged) and "approved" or "pending" }
        remember(it)
    end
    save(it)
    if player then
        if it.state == "approved" then
            say(player, string.format("%s is in the Workshop (#%d): everyone can find it and play it.", title, it.id))
        else
            say(player, string.format("%s is in the Workshop (#%d), waiting for a GM to look at it.", title, it.id))
        end
    end
    return it
end

local function drop(it)
    items[it.id] = nil
    byRef[it.kind .. ":" .. it.ref] = nil
    votes[it.id] = nil
    exec(string.format("DELETE FROM mod_workshop_items WHERE id = %d", it.id))
    exec(string.format("DELETE FROM mod_workshop_votes WHERE item_id = %d", it.id))
end

-- ov_modes.lua's .modes approve / reject / unlist, and ov_golf.lua's .golf unpublish, keep the Workshop in step.
function W.Reviewed(kind, ref, word)
    local it = itemOf(kind, ref)
    if not it then return end
    if word == "approve" then
        it.state = "approved"; save(it)
    elseif word == "reject" or word == "unlist" or word == "unpublish" then
        drop(it)
    end
end

-- The source scripts' own approval, kept in step with the Workshop's review (modes only: courses and builds
-- have no approval of their own).
local function applyReview(it, approved)
    if it.kind ~= "mode" then return end
    local m = type(hooks.mode) == "table" and hooks.mode[it.ref]
    if m then m.approved = approved end
    exec(string.format("UPDATE mod_modes SET approved = %d WHERE mkey = '%s'", approved and 1 or 0, (it.ref:gsub("[^%w_]", ""))))
end

-- Items made before the Workshop existed (or while this script was off): every published course and mode.
local function backfill()
    local added = 0
    local golf = type(hooks.course) == "table" and hooks.course.COURSES
    for _, e in ipairs(type(golf) == "table" and golf or {}) do
        if e.guid and e.course and validRef("course", e.key) and not itemOf("course", e.key) then
            W.Published("course", e.key, e.course.title, nil, e.guid, e.author)
            added = added + 1
        end
    end
    local modes = type(hooks.mode) == "table" and hooks.mode or {}
    for key, m in pairs(modes) do
        if type(m) == "table" and (m.guid or 0) ~= 0 and validRef("mode", key) and not itemOf("mode", key) then
            local it = W.Published("mode", key, m.title, nil, m.guid, m.author)
            if it and m.approved then it.state = "approved"; save(it) end
            added = added + 1
        end
    end
    return added
end
W.Backfill = backfill

-- -------------------------------------------------------------------------------------------- listing

local function score(it) return it.up - it.down end
local SORTS = {
    plays = function(a, b) if a.plays ~= b.plays then return a.plays > b.plays end return a.id > b.id end,
    rating = function(a, b) if score(a) ~= score(b) then return score(a) > score(b) end
        if a.up ~= b.up then return a.up > b.up end return a.id > b.id end,
    new = function(a, b) if a.created ~= b.created then return a.created > b.created end return a.id > b.id end,
}

local function row(it, account)
    local mine = (votes[it.id] or {})[account] or 0
    local function f(s) return (tostring(s):gsub("[\t\n]", " ")) end
    return table.concat({ it.id, it.kind, f(it.title), f(it.author), it.version, it.plays, it.up, it.down, mine, it.state,
        f(it.descr) }, "\t")
end

function W.List(kind, sort, page)
    kind = KINDS[kind] and kind or "all"
    sort = SORTS[sort] and sort or "plays"
    local l = {}
    for _, it in pairs(items) do
        if it.state == "approved" and (kind == "all" or it.kind == kind) then l[#l + 1] = it end
    end
    table.sort(l, SORTS[sort])
    local pages = math.max(1, math.ceil(#l / PAGE))
    page = math.max(1, math.min(tonumber(page) or 1, pages))
    local out = {}
    for i = (page - 1) * PAGE + 1, math.min(#l, page * PAGE) do out[#out + 1] = l[i] end
    return out, kind, sort, page, pages
end

local function listCommand(player, data)
    if tooSoon(player, "list") then return end
    local kind, sort, page = tostring(data or ""):match("^(%a*)%s*(%a*)%s*(%d*)")
    local l, k, s, p, pages = W.List(kind, sort, page)
    local acc = player:GetAccountId()
    local rows = {}
    for _, it in ipairs(l) do rows[#rows + 1] = row(it, acc) end
    send(player, "items", string.format("%s %s %d %d", k, s, p, pages) .. (#rows > 0 and ("\n" .. table.concat(rows, "\n")) or ""))
end

local function mine(player)
    local guid, l = player:GetGUIDLow(), {}
    for _, it in pairs(items) do if it.guid == guid then l[#l + 1] = it end end
    table.sort(l, SORTS.new)
    return l
end

local function mineCommand(player)
    if tooSoon(player, "mine") then return end
    local acc, rows = player:GetAccountId(), {}
    for _, it in ipairs(mine(player)) do rows[#rows + 1] = row(it, acc) end
    send(player, "items", "mine new 1 1" .. (#rows > 0 and ("\n" .. table.concat(rows, "\n")) or ""))
end

-- ------------------------------------------------------------------------------------------- rating

function W.Rate(player, id, how)
    local it = items[tonumber(id) or -1]
    if not it or it.state ~= "approved" then return nil, "That isn't in the Workshop." end
    if it.guid == player:GetGUIDLow() then return nil, "You can't rate your own." end
    local v = (how == "up" and 1) or (how == "down" and -1) or (how == "none" and 0) or nil
    if v == nil then return nil, "Rate up, down or none." end
    local acc = player:GetAccountId()
    votes[it.id] = votes[it.id] or {}
    local old = votes[it.id][acc] or 0
    if old == 1 then it.up = math.max(0, it.up - 1) elseif old == -1 then it.down = math.max(0, it.down - 1) end
    if v == 1 then it.up = it.up + 1 elseif v == -1 then it.down = it.down + 1 end
    votes[it.id][acc] = (v ~= 0) and v or nil
    if v == 0 then
        exec(string.format("DELETE FROM mod_workshop_votes WHERE item_id = %d AND account_id = %d", it.id, acc))
    else
        exec(string.format("REPLACE INTO mod_workshop_votes (item_id, account_id, vote, voted_at) VALUES (%d, %d, %d, %d)",
            it.id, acc, v, now()))
    end
    exec(string.format("UPDATE mod_workshop_items SET up = %d, down = %d WHERE id = %d", it.up, it.down, it.id))
    return it, v
end

local function rateCommand(player, data)
    if tooSoon(player, "rate") then return say(player, "One vote every couple of seconds.") end
    local id, how = tostring(data or ""):match("^(%d+)%s+(%a+)")
    local it, v = W.Rate(player, id, how and how:lower())
    if not it then return say(player, v) end
    send(player, "rated", string.format("%d %d %d %d", it.id, it.up, it.down, v))
end

-- --------------------------------------------------------------------------------------------- play

-- The message each kind's own script takes when its own Play is pressed.
local START = {
    course = function(it) return "wugolf", "start", it.ref end,
    mode = function(it) return "wumodes", "host", it.ref end,
    build = function(it) return "wubuild", "cmd", "load " .. it.ref end,
}

function W.Play(player, id, why)
    local it = items[tonumber(id) or -1]
    local guid = player:GetGUIDLow()
    if not it or (it.state ~= "approved" and it.guid ~= guid and not isGM(player)) then
        say(player, "That isn't in the Workshop (or isn't approved yet).")
        return false
    end
    if not OVMod.Dispatch then
        say(player, "The Workshop can't start things on this realm yet.")
        return false
    end
    local acc = player:GetAccountId()
    local key = it.id .. ":" .. acc
    if it.state == "approved" and it.guid ~= guid and (not counted[key] or now() - counted[key] >= PLAY_COUNT_GAP) then
        counted[key] = now()
        it.plays = it.plays + 1
        exec(string.format("UPDATE mod_workshop_items SET plays = %d WHERE id = %d", it.plays, it.id))
    end
    send(player, "playing", string.format("%d %s %s", it.id, it.kind, it.title))
    say(player, string.format("Starting %s by %s.", it.title, it.author))
    local modId, name, data = START[it.kind](it)
    OVMod.Dispatch(player, modId, name, data)
    return true
end

local function playCommand(player, data)
    if tooSoon(player, "play") then return say(player, "One Play every few seconds.") end
    W.Play(player, tostring(data or ""):match("^%s*(%d+)"), "play")
end

-- ------------------------------------------------------------------------------------- publish (builds)

local function publishBuild(player, code, title)
    code = tostring(code or ""):upper()
    if not validRef("build", code) then return say(player, "Give the 6-letter code from |cffffff00.build share <name>|r.") end
    local q = query(string.format("SELECT owner, name FROM mod_builder_builds WHERE code = '%s'", code))
    if not q then return say(player, "No build has the code " .. code .. ".") end
    if q:GetUInt32(0) ~= player:GetGUIDLow() then return say(player, "Only the builder who saved it can publish it.") end
    local it = itemOf("build", code)
    if not it then
        local n = 0
        for _, e in pairs(items) do if e.guid == player:GetGUIDLow() and e.kind == "build" then n = n + 1 end end
        if n >= MAX_BUILDS then return say(player, "You have " .. MAX_BUILDS .. " builds in the Workshop already.") end
    end
    title = cleanText(title, MAX_TITLE)
    if title == "" then title = cleanText(q:GetString(1), MAX_TITLE) end
    if badWord(title) then return say(player, "Pick another title.") end
    local item = W.Published("build", code, title, player)
    if item then send(player, "published", tostring(item.id)) end
end

local function publishCommand(player, data)
    if tooSoon(player, "publish") then return say(player, "One publish every 30 seconds.") end
    local code, title = tostring(data or ""):match("^%s*(%S+)%s*(.*)$")
    publishBuild(player, code, title)
end

local function describeCommand(player, id, text)
    if tooSoon(player, "describe") then return say(player, "One change every 10 seconds.") end
    local it = items[tonumber(id) or -1]
    if not it or it.guid ~= player:GetGUIDLow() then return say(player, "That isn't one of yours (|cffffff00.workshop mine|r).") end
    text = cleanText(text, MAX_DESC)
    if badWord(text) then return say(player, "Try other words.") end
    it.descr = text
    save(it)
    say(player, "Description saved.")
end

-- ------------------------------------------------------------------------------------------------- GM

local function gmCommand(player, word, id)
    if not isGM(player) then return say(player, "That's for GMs.") end
    if word == "pending" then
        local l = {}
        for _, it in pairs(items) do if it.state == "pending" then l[#l + 1] = it end end
        table.sort(l, function(a, b) return a.id < b.id end)
        if #l == 0 then return say(player, "Nothing waiting for review.") end
        for i = 1, math.min(#l, 15) do
            local it = l[i]
            say(player, string.format("#%d %s: %s by %s (v%d)%s", it.id, it.kind, it.title, it.author, it.version,
                badWord(it.title) and " - title flagged" or ""))
        end
        if #l > 15 then say(player, (#l - 15) .. " more.") end
        return
    end
    local it = items[tonumber(id) or -1]
    if not it then return say(player, "No Workshop item #" .. tostring(id) .. ".") end
    if word == "approve" then
        it.state = "approved"; save(it); applyReview(it, true)
        say(player, string.format("#%d %s approved: everyone can play it.", it.id, it.title))
    elseif word == "reject" then
        it.state = "rejected"; save(it); applyReview(it, false)
        say(player, string.format("#%d %s rejected.", it.id, it.title))
    elseif word == "unpublish" then
        applyReview(it, false)
        if it.kind == "course" and type(hooks.course) == "table" and type(hooks.course.run) == "function" then
            pcall(hooks.course.run, player, "unpublish " .. it.ref)   -- takes it out of /golf too (ov_golf checks GM)
        end
        drop(it)
        say(player, string.format("#%d %s taken down.", it.id, it.title))
    end
end

-- ------------------------------------------------------------------- the website's admin console
-- ov_admin.lua (console/SOAP "ovadmin ws ...", from stream/admin.py) reviews here. Unlike .workshop unpublish, nothing
-- is dropped: "pending" takes an item off the list until it is approved again; plays, votes and the row stay.
function W.Admin(id, action, text)
    local it = items[tonumber(id) or -1]
    if not it then return nil, "no such item" end
    if action == "approve" then it.state = "approved"; applyReview(it, true)
    elseif action == "reject" then it.state = "rejected"; applyReview(it, false)
    elseif action == "pending" then it.state = "pending"; applyReview(it, false)
    elseif action == "title" or action == "descr" then
        local t = cleanText(text, action == "title" and MAX_TITLE or MAX_DESC)
        if (action == "title" and t == "") or badWord(t) then return nil, "pick other words" end
        it[action] = t
    else return nil, "unknown action" end
    it.updated = now()
    save(it)
    return it
end

-- The automatic checks, again: what a GM should look at before approving.
function W.Check(it)
    local f = {}
    local w = badWord(it.title); if w then f[#f + 1] = "title: filtered word" end
    w = badWord(it.descr); if w then f[#f + 1] = "description: filtered word" end
    if not validRef(it.kind, it.ref) then f[#f + 1] = "reference: not a valid " .. it.kind end
    if it.kind == "mode" then f[#f + 1] = "mode: new code, runs only in the host's client sandbox; play it once first" end
    return f
end
W.Items = function() return items end

-- --------------------------------------------------------------------------------- the website's Play

local function forget(account)
    intents[account] = nil
    authExec(string.format("DELETE FROM ov_ws_intents WHERE account_id = %d", account))
end

local function intentOf(account)
    local g = intents[account]
    if not g then
        local q = authQuery(string.format("SELECT item_id, expires_at - UNIX_TIMESTAMP() FROM ov_ws_intents "
            .. "WHERE account_id = %d AND expires_at > UNIX_TIMESTAMP()", account))
        if q then
            local id, left = q:GetUInt32(0), tonumber(q:GetString(1)) or 0
            if left > 0 then g = { id = id, exp = now() + math.min(left, INTENT_TTL) }; intents[account] = g end
        end
    end
    if g and g.exp <= now() then forget(account); return nil end
    return g
end

local function actIntent(player)
    local acc = player:GetAccountId()
    local g = intentOf(acc)
    if not g then return end
    forget(acc)   -- used once
    if try(player, "IsInCombat") then return say(player, "Out of combat, type |cffffff00.workshop play " .. g.id .. "|r.") end
    W.Play(player, g.id, "site")
end

-- Deferred: never start anything from inside a login or command hook.
local function later(player, delay)
    try(player, "RegisterEvent", function(_, _, _, p) actIntent(p) end, delay, 1)
end

local function onlineByAccount(account)
    for _, p in ipairs((GetPlayersInWorld and GetPlayersInWorld()) or {}) do
        if p:GetAccountId() == account then return p end
    end
end

-- console: ovws go <ACCOUNT> <id>
local function consoleCommand(command, handler)
    local rest = command:match("^ovws%s+(.*)$")
    if not rest then return nil end
    local function reply(msg) if handler then pcall(handler.SendSysMessage, handler, msg) end end
    local name, id = rest:match("^go%s+(%w+)%s+(%d+)%s*$")
    id = tonumber(id)
    if not name or #name > 16 or not id then
        reply("ovws: usage: ovws go <account> <workshop id>")
        return false
    end
    local it = items[id]
    if not it or it.state ~= "approved" then
        reply("ovws: no approved Workshop item " .. id)
        return false
    end
    name = name:upper()
    local q = authQuery(string.format("SELECT id FROM account WHERE username = '%s'", name))
    if not q then
        reply("ovws: no such account " .. name)
        return false
    end
    local acc = q:GetUInt32(0)
    intents[acc] = { id = id, exp = now() + INTENT_TTL }
    authExec(string.format("REPLACE INTO ov_ws_intents (account_id, item_id, expires_at) VALUES (%d, %d, UNIX_TIMESTAMP() + %d)",
        acc, id, INTENT_TTL))
    local p = onlineByAccount(acc)
    if p then later(p, 500) end
    reply(string.format("ovws ok: %s -> %d (%d min)%s", name, id, INTENT_TTL / 60, p and ", online now" or ""))
    return false
end

-- ------------------------------------------------------------------------------------------ commands

local function help(player)
    say(player, "Play what others made: Esc > Mods & Workshop > Workshop, or play.openvanilla.app/wrath/workshop.")
    say(player, "  |cffffff00.workshop play <id>|r  |cffffff00.workshop mine|r  |cffffff00.workshop describe <id> <text>|r")
    say(player, "  Builds: |cffffff00.build share <name>|r, then |cffffff00.workshop publish <code> [title]|r. "
        .. "Courses and modes join by themselves when you publish them.")
    if isGM(player) then say(player, "  GM: |cffffff00.workshop pending|r | approve <id> | reject <id> | unpublish <id>") end
end

local function mineSay(player)
    local l = mine(player)
    if #l == 0 then return say(player, "Nothing of yours in the Workshop yet.") end
    for i = 1, math.min(#l, 12) do
        local it = l[i]
        say(player, string.format("#%d %s: %s (v%d, %s, %d plays, +%d -%d)", it.id, it.kind, it.title, it.version, it.state,
            it.plays, it.up, it.down))
    end
end

local function onCommand(event, player, command, handler)
    if not player then return consoleCommand(command or "", handler) end
    local text = (command or ""):gsub("^[%.!]", "")
    local verb, rest = text:match("^(%S+)%s*(.*)$")
    if not verb or verb:lower() ~= "workshop" then return nil end
    if tooSoon(player, "cmd") then return false end
    local word, a, b = rest:match("^(%S*)%s*(%S*)%s*(.*)$")
    word = (word or ""):lower()
    if word == "pending" or word == "approve" or word == "reject" or word == "unpublish" then gmCommand(player, word, a)
    elseif word == "play" then playCommand(player, a)
    elseif word == "publish" then publishCommand(player, a .. " " .. (b or ""))
    elseif word == "describe" then describeCommand(player, a, b)
    elseif word == "mine" then mineSay(player)
    elseif word == "rate" then rateCommand(player, a .. " " .. (b or ""))
    else help(player) end
    return false
end

local function onLogin(event, player)
    if intentOf(player:GetAccountId()) then later(player, LOGIN_DELAY) end
end

local channel = {
    list = listCommand, mine = mineCommand, rate = rateCommand, play = playCommand, publish = publishCommand,
}
for name, fn in pairs(channel) do
    OVMod.On(MOD, name, function(player, data) if #(data or "") <= 200 then fn(player, data or "") end end)
end

backfill()

RegisterPlayerEvent(3, onLogin)     -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(42, onCommand)  -- PLAYER_EVENT_ON_COMMAND

-- for stream/tests/test_ov_workshop.lua
W._items, W._votes, W._intents, W._byRef, W._last = items, votes, intents, byRef, last
W._actIntent = actIntent
return W
