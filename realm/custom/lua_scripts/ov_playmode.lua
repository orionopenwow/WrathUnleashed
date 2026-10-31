-- ov_playmode.lua: one click to play a Leyline mode (mod-ale / Eluna, 3.3.5a).
--
-- The launcher's Modes page and the site's /wrath/modes list the game modes (stream/playmodes.json). Play on a
-- realm mode arrives here one of two ways, and both end in the same start:
--   * the browser: /wrath?go=mode:<id>. The portal's sign-in records it for the game account over SOAP
--     (stream/playmodes.py go_intent):   ovplay go <ACCOUNT> <id>     (console / SOAP only)
--     The reply starts "ovplay ok" when it was taken. It is acted on at once if a character is online, else at the
--     account's first login after it was saved, and only if that is within LOGIN_FRESH (5 minutes) of the click;
--     used once, and forgotten after TTL (10 minutes). A later login (a reconnect after a disconnect, another
--     character, a click from long ago) never starts a round by itself: it says "Waiting for you: ... type
--     .playmode <id>" (smoke 2026-10-30: a character was dropped into Bumper Balls on entering the world).
--   * the desktop launcher: it writes a small addon into the player's own client (LeylinePlay, see
--     docs/leyline-modes-play.md) that asks once, after login, on the OVMOD channel: mod "wuplay", "go <id>".
--     That is the same as typing .playmode <id>: a player asking to play a minigame, which anyone may do.
-- The id is checked against MODES below (never trusted from anyone); each mode's own script then checks the rest
-- (combat, battlegrounds, rates) exactly as when its own window's button is pressed (OVMod.Dispatch):
--   minigolf       ov_golf.lua "start" (the first course). Alone: it tees off at once. In a party: the party
--                  nearby is invited, the window opens (Golf.lua "open") and the host presses Tee off.
--   bumper-balls   ov_modes.lua: alone, "solo" (runs at once in your client); in a party, "host" (a lobby, its
--                  window opened with Modes.lua "open").
--   coin-dash      the same.
--   community      opens the Leyline Modes window (Modes.lua "open"), where the published modes are.
-- Player commands: .playmode (the list), .playmode <id>, .playmode cancel. A brand new character's first login
-- is never interrupted: the mode waits for .playmode.
-- Table (auth DB, created here): ov_playmode_intents (account_id, mode, expires_at), so an intent survives a restart.
-- mod-ale events: 3 ON_LOGIN, 30 ON_FIRST_LOGIN, 42 ON_COMMAND (return false = handled).

local OVMod
do
    local ok, m = pcall(function() return require("ov_modapi") end)
    OVMod = (ok and type(m) == "table" and m) or rawget(_G, "OVMod")
    if not OVMod then
        print("[ov_playmode] ov_modapi.lua is missing: Play needs the OVMOD channel; not loaded")
        return
    end
end

local MOD = "wuplay"
local TAG = "|cff66ccff[Play]|r "
local TTL = 600              -- seconds an intent waits (for .playmode)
local LOGIN_FRESH = 300      -- seconds after the click within which the first login starts it by itself
local LOGIN_DELAY = 7000     -- after ov_go.lua (5 s) and ov_workshop.lua (6 s)
local GAP = 5                -- seconds between one player's starts

-- The live realm modes of stream/playmodes.json (stream/tests/test_playmodes.py keeps the ids equal).
-- solo / party: { name, data } of the mode's own OVMOD message; go: sent after a solo start that needs it.
local MODES = {
    ["minigolf"] = { title = "Minigolf", mod = "wugolf", solo = { "start", "" }, party = { "start", "" }, go = "go" },
    ["bumper-balls"] = { title = "Bumper Balls", mod = "wumodes", solo = { "solo", "bumper" }, party = { "host", "bumper" } },
    ["coin-dash"] = { title = "Coin Dash", mod = "wumodes", solo = { "solo", "coindash" }, party = { "host", "coindash" } },
    ["community"] = { title = "Community modes", open = true },
}

local pending = {}   -- account -> { mode, exp, set (when it was saved), seen (a login has had its turn) }
local last = {}      -- guid -> os.time() of the last start
local fresh = {}     -- guid -> true during a character's first login

local function now() return os.time() end
local function try(obj, method, ...)
    if not obj then return nil end
    local okf, fn = pcall(function() return obj[method] end)
    if not okf or type(fn) ~= "function" then return nil end
    local ok, a = pcall(fn, obj, ...)
    if ok then return a end
    return nil
end
local function say(player, text) try(player, "SendBroadcastMessage", TAG .. text) end
local function authExec(s) if AuthDBExecute then pcall(AuthDBExecute, s) end end
local function authQuery(s)
    if not AuthDBQuery then return nil end
    local ok, q = pcall(AuthDBQuery, s)
    if ok then return q end
end

authExec("CREATE TABLE IF NOT EXISTS ov_playmode_intents ("
    .. "account_id INT UNSIGNED NOT NULL PRIMARY KEY, mode VARCHAR(24) NOT NULL, "
    .. "expires_at INT UNSIGNED NOT NULL, KEY expires_at (expires_at))")

local function validMode(id)
    return type(id) == "string" and #id <= 24 and id:match("^[a-z][a-z0-9%-]*$") ~= nil and MODES[id] ~= nil
end

local function listText()
    local ids = {}
    for id in pairs(MODES) do ids[#ids + 1] = id end
    table.sort(ids)
    return table.concat(ids, ", ")
end

local function forget(account)
    pending[account] = nil
    authExec(string.format("DELETE FROM ov_playmode_intents WHERE account_id = %d", account))
end

local function intentOf(account)
    local g = pending[account]
    if not g then
        local q = authQuery(string.format("SELECT mode, expires_at - UNIX_TIMESTAMP() FROM ov_playmode_intents "
            .. "WHERE account_id = %d AND expires_at > UNIX_TIMESTAMP()", account))
        if q then
            local id, left = q:GetString(0), tonumber(q:GetInt32(1)) or 0
            if validMode(id) and left > 0 then
                g = { mode = id, exp = now() + math.min(left, TTL) }
                g.set = g.exp - TTL
                pending[account] = g
            end
        end
    end
    if g and g.exp <= now() then
        forget(account)
        return nil
    end
    return g
end

local function blocked(player)
    if try(player, "IsInCombat") then return "not in combat" end
    if try(player, "IsDead") then return "not while dead" end
    if try(player, "InBattleground") or try(player, "InArena") then return "not in a battleground or arena" end
    return nil
end

-- Start mode `id` for this player now. Returns true when it was handed to the mode's script.
local function start(player, id)
    local m = MODES[id]
    if not m then return false end
    local stop = blocked(player)
    if stop then
        say(player, m.title .. ": " .. stop .. ". Type |cffffff00.playmode " .. id .. "|r when you're free.")
        return false
    end
    if m.open then
        OVMod.Send(player, "wumodes", "open", "")
        say(player, "Community modes: pick one in the Leyline Modes window (or type |cffffff00/modes|r).")
        return true
    end
    if not OVMod.Dispatch then
        say(player, m.title .. " can't be started from here on this realm yet.")
        return false
    end
    local group = try(player, "GetGroup")
    local inParty = group ~= nil and #((try(group, "GetMembers")) or {}) > 1
    local step = inParty and m.party or m.solo
    say(player, "Starting " .. m.title .. (inParty and ": your party nearby is invited." or "."))
    if not OVMod.Dispatch(player, m.mod, step[1], step[2]) then
        say(player, m.title .. " isn't running on this realm right now.")
        return false
    end
    if not inParty and m.go then OVMod.Dispatch(player, m.mod, m.go, "") end
    if inParty then OVMod.Send(player, m.mod, "open", "") end   -- the lobby's window, for its Start button
    return true
end

-- A player asked (the command, or the launcher's addon): checked, rate-limited, started.
local function ask(player, id)
    id = tostring(id or ""):lower():match("^%s*(%S*)")
    if not validMode(id) then
        say(player, "Modes you can start: " .. listText() .. ". Every game: play.openvanilla.app/wrath/modes")
        return false
    end
    local guid = player:GetGUIDLow()
    if last[guid] and now() - last[guid] < GAP then
        say(player, "One start every few seconds.")
        return false
    end
    last[guid] = now()
    fresh[guid] = nil
    local account = player:GetAccountId()
    local g = pending[account]
    if g and g.mode == id then forget(account) end
    return start(player, id)
end

-- The account's waiting intent, with this character. why: "login" or "set".
local function act(player, why)
    local account = player:GetAccountId()
    local g = intentOf(account)
    if not g then return end
    local m = MODES[g.mode]
    -- only an ask ("set": online now, or .playmode) starts it at once; a login only when it is the first one
    -- after the click, soon after it, and not a brand new character's first login
    if why ~= "set" and (why == "again" or fresh[player:GetGUIDLow()] or now() - (g.set or 0) > LOGIN_FRESH) then
        say(player, "Waiting for you: " .. m.title .. ". Type |cffffff00.playmode " .. g.mode .. "|r when you're ready.")
        return
    end
    if blocked(player) then
        start(player, g.mode)   -- says why and how to try again; the intent stays
        return
    end
    forget(account)   -- used once, whatever the mode's script says next
    last[player:GetGUIDLow()] = now()
    start(player, g.mode)
end

local function later(player, delay, why)
    try(player, "RegisterEvent", function(_, _, _, p) act(p, why) end, delay, 1)
end

local function onlineByAccount(account)
    for _, p in ipairs((GetPlayersInWorld and GetPlayersInWorld()) or {}) do
        if p:GetAccountId() == account then return p end
    end
end

-- console: ovplay go <ACCOUNT> <id> | ovplay clear <ACCOUNT>
local function consoleCommand(command, handler)
    local verb, rest = command:match("^ovplay%s+(%a+)%s*(.*)$")
    if not verb then return nil end
    local function reply(msg) if handler then pcall(handler.SendSysMessage, handler, msg) end end
    local name, id
    if verb == "go" then
        name, id = rest:match("^(%w+)%s+(%S+)%s*$")
    elseif verb == "clear" then
        name = rest:match("^(%w+)%s*$")
    end
    if not name or #name > 16 or (verb == "go" and not validMode(id)) then
        reply("ovplay: usage: ovplay go <account> <mode> (" .. listText() .. ") | ovplay clear <account>")
        return false
    end
    name = name:upper()
    local q = authQuery(string.format("SELECT id FROM account WHERE username = '%s'", name))
    if not q then
        reply("ovplay: no such account " .. name)
        return false
    end
    local account = q:GetUInt32(0)
    if verb == "clear" then
        forget(account)
        reply("ovplay ok: " .. name .. " cleared")
        return false
    end
    pending[account] = { mode = id, exp = now() + TTL, set = now() }
    authExec(string.format("REPLACE INTO ov_playmode_intents (account_id, mode, expires_at) "
        .. "VALUES (%d, '%s', UNIX_TIMESTAMP() + %d)", account, id, TTL))
    local p = onlineByAccount(account)
    if p then later(p, 500, "set") end
    reply(string.format("ovplay ok: %s -> %s (%d min)%s", name, id, TTL / 60, p and ", online now" or ""))
    return false
end

local function onCommand(event, player, command, handler)
    if not player then return consoleCommand(command or "", handler) end
    local text = (command or ""):gsub("^[%.!]", "")
    local verb, arg = text:match("^(%S+)%s*(.-)%s*$")
    if not verb or verb:lower() ~= "playmode" then return nil end   -- ovplay included: never from a player
    arg = (arg or ""):lower()
    if arg == "cancel" then
        local account = player:GetAccountId()
        if intentOf(account) then forget(account); say(player, "Forgotten.") else say(player, "Nothing is waiting.") end
        return false
    end
    if arg == "" then
        local g = intentOf(player:GetAccountId())
        if g then
            fresh[player:GetGUIDLow()] = nil
            later(player, 100, "set")
            return false
        end
    end
    ask(player, arg)
    return false
end

local function onFirstLogin(event, player) fresh[player:GetGUIDLow()] = true end

local function onLogin(event, player)
    local g = intentOf(player:GetAccountId())
    if not g then
        fresh[player:GetGUIDLow()] = nil
        return
    end
    -- the first login after the click has its turn; any later one (a reconnect, another character) only reminds
    later(player, LOGIN_DELAY, g.seen and "again" or "login")
    g.seen = true
end

OVMod.On(MOD, "go", function(player, data) if #(data or "") <= 40 then ask(player, data) end end)

RegisterPlayerEvent(3, onLogin)        -- PLAYER_EVENT_ON_LOGIN
RegisterPlayerEvent(30, onFirstLogin)  -- PLAYER_EVENT_ON_FIRST_LOGIN
RegisterPlayerEvent(42, onCommand)     -- PLAYER_EVENT_ON_COMMAND

-- for stream/tests/test_ov_playmode.lua
OV_PLAYMODE_TEST = { MODES = MODES, pending = pending, last = last, act = act, ask = ask, validMode = validMode, TTL = TTL,
    LOGIN_FRESH = LOGIN_FRESH }
return OV_PLAYMODE_TEST
