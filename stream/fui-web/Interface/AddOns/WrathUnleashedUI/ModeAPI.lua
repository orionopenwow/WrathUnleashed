-- ModeAPI (3.3.5a API): the Leyline Modes creator API, as data. The one source of truth for what a mode script
-- can use.
--
-- Read by:
--   Modes.lua                      builds the sandbox from it, and checks scripts with API.Check before running them
--   ModeScript.lua                 the script editor (keyword colours, the API list)
--   tools/creator-api/gen.lua      writes docs/CREATOR-API.md and docs/creator-api.html from it
--   stream/tests/test_ov_modes.lua checks the sandbox has exactly what this lists, and the docs are up to date
-- realm/custom/lua_scripts/ov_modes.lua keeps a copy of BLOCKED and of Check (the realm never loads this file;
-- the tests keep the two in step).
--
-- This file is plain data plus one pure function, so it loads in the game and in plain Lua 5.1 (dofile).

local API = {}

API.VERSION = 2            -- bump when something is added; each entry says the version it arrived in (since)

-- ------------------------------------------------------------------ limits (enforced by Modes.lua / ov_modes.lua)
API.MAX_SCRIPT = 14336     -- bytes of script
API.MIN_SCRIPT = 20
API.GUARD_MS = 30          -- each call into the script (load, every callback, every timer) is stopped after this
API.TICK = 0.05            -- OnTick runs 20 times a second
API.MAX_ENTS = 300
API.MAX_TIMERS = 64        -- timers waiting at once
API.TIMERS_PER_TICK = 16   -- timers that fire in one tick; the rest fire on the next
API.MIN_EVERY = 0.05       -- the shortest Timer.Every
API.MAX_STATE_KEYS = 128
API.MAX_STATE_HANDLERS = 128
API.MAX_STATE_DEPTH = 8    -- a change event that sets state that fires a change event ... at most 8 deep
API.MAX_TEXT_SLOTS = 8     -- HUD.Text slots
API.MAX_TEXT = 120         -- characters in one HUD line
API.MAX_REP = 65536        -- string.rep's longest result

API.LIMITS = {
    { "MAX_SCRIPT", "bytes of script (about 14 KB)" },
    { "GUARD_MS", "milliseconds each call into your script may run; then the mode stops with the line it was on" },
    { "MAX_ENTS", "shapes at once" },
    { "MAX_TIMERS", "timers waiting at once" },
    { "TIMERS_PER_TICK", "timers that fire in one tick (the rest fire next tick)" },
    { "MAX_STATE_KEYS", "State keys" },
    { "MAX_STATE_DEPTH", "change events inside change events" },
    { "MAX_TEXT_SLOTS", "HUD.Text slots" },
    { "MAX_TEXT", "characters in one HUD line" },
}

-- Keys a mode may ask for in Mode.Keys.
API.KEYS = { "W", "A", "S", "D", "Q", "E", "F", "R", "SPACE", "UP", "DOWN", "LEFT", "RIGHT", "1", "2", "3", "4" }

-- ------------------------------------------------------------------ what the script can see
-- The safe standard library: base functions and three libraries.
API.BASE = { "pairs", "ipairs", "next", "select", "type", "tostring", "tonumber", "unpack", "pcall", "error", "assert" }
API.LIBS = {
    { name = "string", about = "Lua's string library without string.dump. string.rep's result is capped at 64 KB." },
    { name = "math", about = "Lua's math library without math.random and math.randomseed (use Random)." },
    { name = "table", about = "Lua's table library." },
}

-- What a script defines. The host calls these; each call is under the time guard.
API.CALLBACKS = {
    { name = "OnStart", args = "players", since = 1, about = "The game starts. players is a list of names, like { \"Ann\", \"Bo\" }. Build the arena here." },
    { name = "OnTick", args = "dt", since = 1, about = "20 times a second; dt is 0.05." },
    { name = "OnKey", args = "player, key, down", since = 1, about = "A player pressed (down = true) or let go of one of Mode.Keys." },
    { name = "OnJoin", args = "player", since = 1, about = "Someone joined a game that was already running." },
    { name = "OnLeave", args = "player", since = 1, about = "Someone left." },
}

-- Settings a script sets at the top.
API.FIELDS = {
    { name = "Mode.Title", value = "\"My Mode\"", since = 1, about = "Shown in /modes and on the banner (40 characters)." },
    { name = "Mode.Keys", value = "{ \"W\", \"A\", \"S\", \"D\" }", since = 1, about = "The keys captured from every player while they play. Esc lets go." },
    { name = "Mode.Players", value = "{ 1, 8 }", since = 1, about = "The fewest and most players." },
    { name = "Mode.Api", value = "2", since = 2, about = "The API version the script needs. An older client says so instead of running it." },
}

-- The functions, by table. args/returns are for the docs; Modes.lua implements them.
API.NAMESPACES = {
    { name = "Ent", about = "Shapes in the arena. Every player sees them; moves are eased smoothly.", fns = {
        { name = "Spawn", args = "{ shape, x, y, z, sx, sy, sz, yaw, color }", returns = "id", since = 1,
          about = "Adds a shape: \"box\", \"ball\" or \"cyl\". Sizes are full widths in yards, yaw is degrees, color is \"rrggbb\"." },
        { name = "Move", args = "id, x, y, z [, yaw]", since = 1, about = "Moves a shape." },
        { name = "Set", args = "id, { field = value, ... }", since = 1, about = "Changes any field: x y z sx sy sz yaw color shape." },
        { name = "Remove", args = "id", since = 1, about = "Removes a shape." },
        { name = "Get", args = "id", returns = "table or nil", since = 1, about = "A copy of a shape's fields." },
        { name = "Clear", args = "", since = 2, about = "Removes every shape." },
        { name = "Count", args = "", returns = "n", since = 2, about = "How many shapes there are." },
    } },
    { name = "Players", about = "The players in the game, by name.", fns = {
        { name = "List", args = "", returns = "{ names }", since = 1, about = "A copy of the list." },
        { name = "Count", args = "", returns = "n", since = 1, about = "How many." },
        { name = "Has", args = "player", returns = "true/false", since = 2, about = "Whether that player is in the game." },
    } },
    { name = "HUD", about = "Text on the players' screens. Text is one line, 120 characters at most.", fns = {
        { name = "Banner", args = "text", since = 1, about = "Sets the banner at the top, for everyone." },
        { name = "Say", args = "text", since = 1, about = "Posts a line under the banner, for everyone (a broadcast)." },
        { name = "Tell", args = "player, text", since = 2, about = "Posts a line under the banner for one player only." },
        { name = "Text", args = "slot, text [, player]", since = 2,
          about = "Your own HUD: a named line in the panel on the left (8 slots). With a player, only they see it. Empty text clears it." },
    } },
    { name = "Score", about = "The scoreboard on everyone's screen, one number per player.", fns = {
        { name = "Set", args = "player, n", since = 1, about = "Sets a score." },
        { name = "Add", args = "player, n", since = 1, about = "Adds to a score (n can be negative)." },
        { name = "Get", args = "player", returns = "n", since = 1, about = "Reads a score (0 if none)." },
        { name = "Top", args = "", returns = "{ { name, score }, ... }", since = 2, about = "Every score, highest first." },
        { name = "Reset", args = "", since = 2, about = "Sets every score to 0." },
    } },
    { name = "Camera", about = "Each player's camera.", fns = {
        { name = "Follow", args = "player, id [, distance, height]", since = 1, about = "That player's camera follows a shape." },
        { name = "Top", args = "[height]", since = 1, about = "A top-down view for everyone." },
    } },
    { name = "Timer", about = "Run code later. Each timer runs under the time guard, like a callback.", fns = {
        { name = "After", args = "seconds, fn", returns = "id", since = 1, about = "Runs fn once, later." },
        { name = "Every", args = "seconds, fn", returns = "id", since = 2, about = "Runs fn again and again (0.05 s at the shortest)." },
        { name = "Cancel", args = "id", since = 2, about = "Stops a timer." },
    } },
    { name = "State", about = "Named values with change events. They survive a hot reload; handlers do not.", fns = {
        { name = "Set", args = "key, value", since = 2, about = "Sets a value (a number, text, true/false or nil). Handlers run only if it changed." },
        { name = "Get", args = "key [, default]", returns = "value", since = 2, about = "Reads a value." },
        { name = "On", args = "key, fn(value, old, key)", since = 2, about = "Runs fn when key changes. Use \"*\" for every key." },
    } },
    { name = "Vec", about = "Small helpers for positions on the ground (x, z) and angles in degrees.", fns = {
        { name = "Len", args = "x, z", returns = "length", since = 2, about = "The length of (x, z)." },
        { name = "Dist", args = "x1, z1, x2, z2", returns = "distance", since = 2, about = "The distance between two points on the ground." },
        { name = "Dist3", args = "x1, y1, z1, x2, y2, z2", returns = "distance", since = 2, about = "The distance in 3D." },
        { name = "Norm", args = "x, z", returns = "x, z, length", since = 2, about = "(x, z) scaled to length 1 (0, 0 stays 0, 0)." },
        { name = "Angle", args = "x, z", returns = "degrees", since = 2, about = "The yaw that faces along (x, z), as Ent.Move takes it." },
        { name = "Dir", args = "degrees", returns = "x, z", since = 2, about = "The unit step for a yaw." },
        { name = "Rotate", args = "x, z, degrees", returns = "x, z", since = 2, about = "(x, z) turned by a yaw." },
        { name = "Lerp", args = "a, b, t", returns = "number", since = 2, about = "From a to b by t (0 to 1)." },
        { name = "Clamp", args = "v, low, high", returns = "number", since = 2, about = "v kept between low and high." },
    } },
    { name = "Mode", about = "The mode itself (see the settings above).", fns = {
        { name = "End", args = "text", since = 1, about = "Ends the game and shows everyone the text." },
    } },
}

API.GLOBALS = {
    { name = "Random", args = "n", returns = "1..n", since = 1, about = "A whole number from 1 to n, from a seed shared by the game." },
    { name = "print", args = "...", since = 1, about = "Writes to the host's screen and the editor's console, for debugging." },
}

-- Device modes get one more table (ModeDevices.lua); it is there only when the script uses Devices.
API.DEVICES = {
    { name = "Run", args = "[=[ layout ]=]", since = 1, about = "Builds the mode from devices and wires (see MODES.md)." },
    { name = "On", args = "id, event, fn(player)", since = 1, about = "Runs fn on a device's event." },
    { name = "Call", args = "id, function, argument, player", since = 1, about = "Calls a device's function." },
}

-- ------------------------------------------------------------------ what the script can't see
-- Never in the sandbox. The tests check each is absent.
API.ABSENT = {
    "getfenv", "setfenv", "loadstring", "load", "loadfile", "dofile", "require", "module",
    "getmetatable", "setmetatable", "rawget", "rawset", "rawequal", "newproxy", "collectgarbage", "gcinfo",
    "debug", "os", "io", "package", "coroutine", "xpcall",
    "CreateFrame", "SendAddonMessage", "SendChatMessage", "RunScript", "UnitName", "GetTime", "LeylineMode",
    "LeylineGuard", "WrathUnleashedUI", "WrathUnleashedUIDB", "SlashCmdList", "hooksecurefunc", "debugstack",
}

-- A script that names one of these is refused before it runs (in the editor, on Play, and by the realm on
-- Publish and Play Here), with the line. They're absent anyway; naming one is either a mistake or an attempt.
API.BLOCKED = {
    "getfenv", "setfenv", "loadstring", "loadfile", "dofile", "require", "getmetatable", "setmetatable",
    "rawget", "rawset", "rawequal", "newproxy", "collectgarbage", "gcinfo", "debug", "coroutine", "os", "io",
    "LeylineMode", "LeylineGuard",
}

-- ------------------------------------------------------------------ the check (pure; no code is run)
-- Returns nil if the script is fine, or line, message for the first problem. Strings and comments are skipped;
-- a blocked name is only a problem where it is a name of its own (not a field, like t.os).
function API.Check(text)
    if type(text) ~= "string" then return 0, "No script." end
    if #text > API.MAX_SCRIPT then return 0, "The script is too big (" .. API.MAX_SCRIPT .. " bytes at most)." end
    if text:find("\27", 1, true) then return 0, "Compiled chunks aren't allowed." end
    local blocked = {}
    for _, n in ipairs(API.BLOCKED) do blocked[n] = true end
    local i, n, line = 1, #text, 1
    local prev, prev2 = "", ""      -- the last two significant characters before a name
    local function longEnd(at)
        local eq = text:match("^%[(=*)%[", at)
        if not eq then return nil end
        local close = "]" .. eq .. "]"
        local s, e = text:find(close, at + #eq + 2, true)
        e = e or n
        return e
    end
    while i <= n do
        local c = text:sub(i, i)
        if c == "\n" then
            line = line + 1; i = i + 1
        elseif c:match("%s") then
            i = i + 1
        elseif text:sub(i, i + 1) == "--" then
            local e = longEnd(i + 2)
            if not e then e = (text:find("\n", i, true) or (n + 1)) - 1 end
            local _, nl = text:sub(i, e):gsub("\n", "")
            line = line + nl; i = e + 1
        elseif c == "[" and text:match("^%[=*%[", i) then
            local e = longEnd(i)
            local _, nl = text:sub(i, e):gsub("\n", "")
            line = line + nl; i = e + 1; prev2, prev = prev, "]"
        elseif c == '"' or c == "'" then
            local j = i + 1
            while j <= n do
                local d = text:sub(j, j)
                if d == "\\" then j = j + 2
                elseif d == c or d == "\n" then break
                else j = j + 1 end
            end
            i = j + 1; prev2, prev = prev, '"'
        elseif c:match("[%a_]") then
            local name = text:match("^[%a_][%w_]*", i)
            local field = (prev == "." and prev2 ~= ".") or prev == ":"
            if field and name == "dump" then return line, "Line " .. line .. ": string.dump isn't available in modes." end
            if field and name == "rep" and prev == ":" then
                return line, "Line " .. line .. ": use string.rep(s, n), not s:rep(n) (string.rep is the capped one)."
            end
            if not field and blocked[name] then return line, "Line " .. line .. ": " .. name .. " isn't available in modes." end
            i = i + #name; prev2, prev = prev, "a"
        elseif c:match("%d") then
            local num = text:match("^0[xX]%x+", i) or text:match("^%d+%.?%d*[eE][%+%-]?%d+", i) or text:match("^%d+%.?%d*", i)
            i = i + #num; prev2, prev = prev, "0"
        else
            i = i + 1; prev2, prev = prev, c
        end
    end
    return nil
end

-- The set of top-level names a fresh sandbox has (the tests compare it with the real one).
function API.EnvNames()
    local s = { _G = true }
    for _, k in ipairs(API.BASE) do s[k] = true end
    for _, l in ipairs(API.LIBS) do s[l.name] = true end
    for _, ns in ipairs(API.NAMESPACES) do s[ns.name] = true end
    for _, g in ipairs(API.GLOBALS) do s[g.name] = true end
    return s
end

local W = rawget(_G, "WrathUnleashedUI")
if type(W) == "table" then W.ModeAPI = API end
return API
