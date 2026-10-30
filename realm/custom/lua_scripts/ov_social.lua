-- ov_social.lua: the game side of Leyline friends and messages (mod-ale). The portal (stream/social.py, in wu-portal)
-- keeps the friends, requests, blocks and messages; it talks to this script over SOAP only, like ov_discord.lua (no
-- shared files, no DB login, no new ports). docs/SOCIAL.md has the whole picture.
--
--   Presence      logins and logouts are queued for the portal ("I"/"O"); "ovsocial pull ... 1" also lists everyone
--                 online ("P"), so a portal restart or a realm restart settles by itself.
--   .lm <friend> <text>    a Leyline message to a friend wherever they are (game, launcher); shown here at once as
--                 "To [Friend]: text". The portal finds the friend by name, Name#1234, main or current character.
--   .lr <text>    reply to the last Leyline message.
--   .lf           your Leyline friends (from the list the portal sent); .lf add|accept|decline|remove|block|unblock
--                 <name>, .lf offline|online (appear offline), .lf report <friend> <spam|harassment|hate|cheating|other>.
--   Incoming      the portal runs "ovsocial msg <ACCOUNT> <id> <hex from> <hex text>": a whisper-style line tagged
--                 [Leyline]; "ovsocial tell <ACCOUNT> <hex text>" a notice; "ovsocial fr <ACCOUNT> <part> <of> <hex>" the
--                 friends list for the addon panel (WrathUnleashedUI/Social.lua) and for .lf.
--
-- Never trust the client: every event carries the account of the character that typed it (looked up here, from
-- the auth DB), never a name the client sent. Bots (RNDBOT accounts, IsBot) never appear and can't use it.
-- Nothing is queued unless the portal pulled in the last ACTIVE_SECS. OV_SOCIAL=0 turns it off.
-- Names and texts cross SOAP hex-encoded, so nothing typed can change a command.
--
-- Addon messages, prefix WUSO, whispered to yourself (the panel, WrathUnleashedUI/Social.lua):
--   client -> server   L                       send me my list
--                      S:<friend>:<text>       the same as .lm
--                      F:<verb>:<arg>          the same as .lf <verb> <arg>
--   server -> client   B:<count>               a list begins
--                      R:<status>:<unread>:<name>:<tag>:<where>   one row; status g (in game) l (launcher) o (offline)
--                                              q (wants to be your friend) p (your request, waiting)
--                      E                       the list is complete
--                      M:<from>:<text>         a message arrived;  O:<to>:<text> one you sent (echo)
--                      T:<text>                a notice;  X:<text> Leyline is offline right now
-- mod-ale events: player 3 ON_LOGIN, 4 ON_LOGOUT, 42 ON_COMMAND; server 30 ADDON_EVENT_ON_MESSAGE.

local ON = (os.getenv("OV_SOCIAL") or "1") ~= "0"
local PREFIX = "WUSO"
local WHISPER = 7
local TAG = "|cff66ccff[Leyline]|r "
local PINK = "|cffff80ff"
local ACTIVE_SECS = 60       -- the portal counts as running this long after its last pull
local QUEUE_MAX = 500
local PULL_MAX = 40
local MAX_TEXT = 255
local MAX_NAME = 40
local WINDOW, PER_WINDOW = 30, 8   -- .lm/.lr/.lf actions per character per 30 s
local MAX_PARTS = 32
local OFFLINE = "Leyline friends are offline right now. Try again in a minute."

local BOOT = os.time()
local seq, queue = 0, {}
local lastPull = nil
local accounts = {}   -- account id -> { name = "WR000123", bot = false }
local lists = {}      -- ACCOUNT -> { rows }
local partial = {}    -- ACCOUNT -> { of = n, parts = {} }
local lastFrom = {}   -- ACCOUNT -> the last friend who messaged
local wants = {}      -- ACCOUNT -> true once the panel asked
local recent = {}     -- char guid -> { times }

local function now() return os.time() end
local function active() return lastPull ~= nil and now() - lastPull <= ACTIVE_SECS end

local function hex(s)
    return (tostring(s or ""):gsub(".", function(c) return string.format("%02x", c:byte()) end))
end

local function unhex(h)
    if type(h) ~= "string" or #h % 2 ~= 0 or h:find("[^%x]") then return nil end
    return (h:gsub("%x%x", function(x) return string.char(tonumber(x, 16)) end))
end

local function cut(s, cap)
    if #s <= cap then return s end
    s = s:sub(1, cap)
    while #s > 0 and s:byte(#s) >= 0x80 and s:byte(#s) < 0xC0 do s = s:sub(1, #s - 1) end
    if #s > 0 and s:byte(#s) >= 0xC0 then s = s:sub(1, #s - 1) end
    return s
end

-- Text shown in game: control characters out, "|" doubled (no colour codes, links or textures), trimmed, capped.
local function gameSafe(s, cap)
    s = tostring(s or ""):gsub("[%z\1-\31\127]", " "):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
    return (cut(s, cap):gsub("|", "||"))
end

-- An addon message field: no ":" (the separator), no "|", no control characters.
local function field(s, cap)
    s = tostring(s or ""):gsub("[%z\1-\31\127|:]", " "):gsub("%s+", " "):gsub("^ ", ""):gsub(" $", "")
    return cut(s, cap)
end

local function account(player)
    local id = player:GetAccountId()
    local a = accounts[id]
    if a == nil then
        local name = ""
        local ok, q = pcall(AuthDBQuery, string.format("SELECT username FROM account WHERE id = %d", id))
        if ok and q then name = q:GetString(0):upper() end
        a = { name = name, bot = name == "" or name:find("^RNDBOT") ~= nil or not name:match("^[A-Z0-9]+$") }
        for _, m in ipairs({ "IsBot", "IsPlayerbot" }) do
            local fn = player[m]
            if type(fn) == "function" then
                local okb, v = pcall(fn, player)
                if okb and v == true then a.bot = true end
            end
        end
        accounts[id] = a
    end
    return a
end

local function send(player, msg) player:SendAddonMessage(PREFIX, cut(msg, 250), WHISPER, player) end
local function tell(player, msg) player:SendBroadcastMessage(TAG .. msg) end

local function playerOf(acct)
    local ok, list = pcall(GetPlayersInWorld)
    if not ok or type(list) ~= "table" then return nil end
    for _, p in ipairs(list) do
        local a = account(p)
        if not a.bot and a.name == acct then return p end
    end
    return nil
end

local function push(kind, a, player, ...)
    seq = seq + 1
    local parts = { kind, tostring(seq), a.name, hex(player:GetName()) }
    for _, v in ipairs({ ... }) do parts[#parts + 1] = hex(v) end
    queue[#queue + 1] = { seq = seq, line = table.concat(parts, " ") }
    while #queue > QUEUE_MAX do table.remove(queue, 1) end
end

local function allow(guid)
    local t, kept = now(), {}
    for _, x in ipairs(recent[guid] or {}) do if t - x < WINDOW then kept[#kept + 1] = x end end
    recent[guid] = kept
    if #kept >= PER_WINDOW then return false end
    kept[#kept + 1] = t
    return true
end

-- ------------------------------------------------------------------------------------------------- the list
local STATUS_WORD = { g = "in game", l = "in the launcher", o = "offline", q = "wants to be friends", p = "request sent" }

local function sendList(player, acct)
    local rows = lists[acct] or {}
    send(player, "B:" .. #rows)
    for _, r in ipairs(rows) do
        send(player, string.format("R:%s:%d:%s:%s:%s", r.status, r.unread, field(r.name, 24), field(r.tag, 4), field(r.where, 80)))
    end
    send(player, "E")
end

local function printList(player, acct)
    local rows = lists[acct]
    if not rows then return tell(player, "Your friends list is on its way. Type .lf again in a moment.") end
    if #rows == 0 then
        return tell(player, "No Leyline friends yet. |cffffff00.lf add Name#1234|r sends a request (your own name is in the Friends panel).")
    end
    for _, r in ipairs(rows) do
        local unread = r.unread > 0 and string.format(" |cffff80ff(%d new)|r", r.unread) or ""
        local where = r.where ~= "" and (" - " .. gameSafe(r.where, 80)) or ""
        tell(player, string.format("%s%s: %s%s%s", gameSafe(r.name, 24), r.tag ~= "" and ("#" .. r.tag) or "",
            STATUS_WORD[r.status] or r.status, where, unread))
    end
end

local function parseList(text)
    local rows = {}
    for line in (text .. "\n"):gmatch("([^\n]*)\n") do
        local name, tag, status, where, unread = line:match("^([^\t]*)\t([^\t]*)\t([glopq])\t([^\t]*)\t(%d+)$")
        if name and name ~= "" and #rows < 200 then
            rows[#rows + 1] = { name = name, tag = tag, status = status, where = where, unread = tonumber(unread) or 0 }
        end
    end
    return rows
end

-- ------------------------------------------------------------------------------------------------- the player's side
local function lm(player, a, to, text)
    to, text = field(to or "", MAX_NAME), tostring(text or ""):gsub("^%s+", ""):gsub("%s+$", "")
    if to == "" or text == "" then return tell(player, "Type |cffffff00.lm <friend> <message>|r.") end
    if not active() then return tell(player, OFFLINE) end
    if not allow(player:GetGUIDLow()) then return tell(player, "Slow down a little.") end
    text = cut(text, MAX_TEXT)
    push("M", a, player, to, text)
    player:SendBroadcastMessage(TAG .. PINK .. "To [" .. gameSafe(to, MAX_NAME) .. "]: " .. gameSafe(text, MAX_TEXT) .. "|r")
    send(player, "O:" .. field(to, 24) .. ":" .. cut(tostring(text):gsub("[%z\1-\31\127|]", " "), 200))
end

local VERBS = { add = true, accept = true, decline = true, remove = true, block = true, unblock = true, offline = true,
    online = true, report = true }

local function lf(player, a, verb, arg)
    verb = (verb or ""):lower()
    if verb == "" or verb == "list" then
        if active() then push("F", a, player, "list", "") end
        return printList(player, a.name)
    end
    if not VERBS[verb] then
        return tell(player, ".lf add|accept|decline|remove|block|unblock <name>, .lf offline|online, .lf report <friend> <reason>")
    end
    if not active() then return tell(player, OFFLINE) end
    if not allow(player:GetGUIDLow()) then return tell(player, "Slow down a little.") end
    push("F", a, player, verb, cut(field(arg or "", 60), 60))
end

local function playerCommand(player, verb, rest)
    local a = account(player)
    if a.bot then return end
    if verb == "lm" then
        local to, text = rest:match("^(%S+)%s+(.+)$")
        lm(player, a, to, text)
    elseif verb == "lr" then
        if not lastFrom[a.name] then return tell(player, "No Leyline message to reply to yet.") end
        lm(player, a, lastFrom[a.name], rest)
    elseif verb == "lf" or verb == "lfriends" then
        local v, arg = rest:match("^(%S*)%s*(.-)%s*$")
        lf(player, a, v, arg)
    end
end

local function onLogin(event, player)
    if not ON then return end
    local a = account(player)
    if a.bot then return end
    if active() then push("I", a, player) end
end

local function onLogout(event, player)
    if not ON then return end
    local a = account(player)
    recent[player:GetGUIDLow()] = nil
    if a.bot then return end
    wants[a.name] = nil
    if active() then push("O", a, player) end
end

local function onAddonMessage(event, sender, msgType, prefix, msg, target)
    if prefix ~= PREFIX then return end
    if not ON or not sender or type(msg) ~= "string" or #msg > 255 then return false end
    local a = account(sender)
    if a.bot then return false end
    if msg == "L" then
        wants[a.name] = true
        if not active() then send(sender, "X:" .. OFFLINE) end
        sendList(sender, a.name)
        if active() and not lists[a.name] then push("F", a, sender, "list", "") end
    elseif msg:sub(1, 2) == "S:" then
        local to, text = msg:match("^S:([^:]+):(.+)$")
        lm(sender, a, to, text)
    elseif msg:sub(1, 2) == "F:" then
        local verb, arg = msg:match("^F:(%a+):?(.*)$")
        lf(sender, a, verb, arg)
    end
    return false
end

-- ------------------------------------------------------------------------------------------------- console (SOAP)
local function pull(rest, reply)
    local after, boot, full = rest:match("^(%d+)%s+(%d+)%s+([01])%s*$")
    if not after then reply("ovsocial: usage: ovsocial pull <after-seq> <boot> <0|1>"); return end
    after = tonumber(after)
    lastPull = now()
    -- a portal whose sequence belongs to an earlier boot (restart or .reload ale) gets everything queued
    if tonumber(boot) ~= BOOT or after > seq then after = 0 end
    -- what the portal asks after, it has: drop it (an answer lost on the way is simply sent again)
    local kept = {}
    for _, e in ipairs(queue) do if e.seq > after then kept[#kept + 1] = e end end
    queue = kept
    local lines, last = {}, after
    for _, e in ipairs(queue) do
        if #lines < PULL_MAX then lines[#lines + 1] = e.line; last = e.seq end
    end
    local events = #lines
    if full == "1" then
        local ok, list = pcall(GetPlayersInWorld)
        if ok and type(list) == "table" then
            for _, p in ipairs(list) do
                local a = account(p)
                if not a.bot then lines[#lines + 1] = string.format("P %s %s %d", a.name, hex(p:GetName()), p:GetGUIDLow()) end
            end
        end
    end
    reply(string.format("ovsocial ok %d %d %d", BOOT, last, events))
    for _, l in ipairs(lines) do reply(l) end
end

local function deliver(rest, reply)
    local acct, id, hf, ht = rest:match("^([A-Z0-9]+)%s+(%d+)%s+(%x+)%s+(%x+)%s*$")
    local from, text = unhex(hf), unhex(ht)
    if not acct or not from or not text then reply("ovsocial: usage: ovsocial msg <ACCOUNT> <id> <hex from> <hex text>"); return end
    local p = playerOf(acct)
    if not p then reply("ovsocial none"); return end
    from = field(from, MAX_NAME)
    lastFrom[acct] = from
    p:SendBroadcastMessage(TAG .. PINK .. "[" .. gameSafe(from, MAX_NAME) .. "] whispers: " .. gameSafe(text, 500) .. "|r")
    send(p, "M:" .. field(from, 24) .. ":" .. cut(tostring(text):gsub("[%z\1-\31\127|]", " "), 200))
    reply("ovsocial ok shown " .. id)
end

local function notice(rest, reply)
    local acct, ht = rest:match("^([A-Z0-9]+)%s+(%x+)%s*$")
    local text = unhex(ht)
    if not acct or not text then reply("ovsocial: usage: ovsocial tell <ACCOUNT> <hex text>"); return end
    local p = playerOf(acct)
    if not p then reply("ovsocial none"); return end
    tell(p, gameSafe(text, 300))
    send(p, "T:" .. cut(tostring(text):gsub("[%z\1-\31\127|]", " "), 240))
    reply("ovsocial ok told")
end

local function friendsList(rest, reply)
    local acct, part, of, h = rest:match("^([A-Z0-9]+)%s+(%d+)%s+(%d+)%s+(%S+)%s*$")
    part, of = tonumber(part), tonumber(of)
    if not acct or not part or not of or part < 1 or of < 1 or part > of or of > MAX_PARTS then
        reply("ovsocial: usage: ovsocial fr <ACCOUNT> <part> <of> <hex|->"); return
    end
    local chunk = h == "-" and "" or unhex(h)
    if not chunk then reply("ovsocial: bad hex"); return end
    if part == 1 or not partial[acct] or partial[acct].of ~= of then partial[acct] = { of = of, parts = {} } end
    partial[acct].parts[part] = chunk
    for i = 1, of do if partial[acct].parts[i] == nil then reply("ovsocial ok part " .. part); return end end
    lists[acct] = parseList(table.concat(partial[acct].parts))
    partial[acct] = nil
    if wants[acct] then
        local p = playerOf(acct)
        if p then sendList(p, acct) end
    end
    reply("ovsocial ok fr " .. #lists[acct])
end

local function console(command, handler)
    local verb, rest = command:match("^ovsocial%s+(%a+)%s*(.*)$")
    if not verb then return nil end
    local function reply(m) if handler then handler:SendSysMessage(m) end end
    if not ON then reply("ovsocial off (OV_SOCIAL=0)"); return false end
    if verb == "pull" then pull(rest, reply)
    elseif verb == "msg" then deliver(rest, reply)
    elseif verb == "tell" then notice(rest, reply)
    elseif verb == "fr" then friendsList(rest, reply)
    elseif verb == "status" then
        reply(string.format("ovsocial status active=%s queued=%d seq=%d boot=%d", tostring(active()), #queue, seq, BOOT))
    else reply("ovsocial: unknown verb " .. verb) end
    return false
end

local function onCommand(event, player, command, handler)
    command = command or ""
    if not player then return console(command, handler) end
    if not ON then return end
    local verb, rest = command:gsub("^[%.!]", ""):match("^(%S+)%s*(.*)$")
    verb = verb and verb:lower()
    if verb == "lm" or verb == "lr" or verb == "lf" or verb == "lfriends" then
        playerCommand(player, verb, rest or "")
        return false
    end
end

RegisterPlayerEvent(3, onLogin)          -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(4, onLogout)         -- PLAYER_EVENT_ON_LOGOUT
RegisterPlayerEvent(42, onCommand)       -- PLAYER_EVENT_ON_COMMAND
RegisterServerEvent(30, onAddonMessage)  -- ADDON_EVENT_ON_MESSAGE

-- for tests
OV_SOCIAL_TEST = { hex = hex, unhex = unhex, gameSafe = gameSafe, parseList = parseList, onCommand = onCommand,
    onLogin = onLogin, onLogout = onLogout, onAddonMessage = onAddonMessage, queue = function() return queue end,
    lists = function() return lists end, BOOT = BOOT }
