-- Modes (3.3.5a API): Leyline Modes, scripted minigames anyone can write. /modes opens it.
--
-- A mode is one Lua script. The session's host runs it (here, in a sandbox: the safe parts of the standard
-- library and the API below, nothing of the game's UI, nothing that can reach the network on its own); every
-- other player only draws what the host sends and sends back the keys the mode asked for. Joining someone
-- else's mode never runs their code on your client. The realm (realm/custom/lua_scripts/ov_modes.lua, OVMOD
-- mod "wumodes") makes the sessions and relays: host -> everyone "st" (state), players -> host "in" (keys).
--
-- The creator API is listed in ModeAPI.lua (the one source of truth; docs/CREATOR-API.md is made from it):
-- callbacks OnStart/OnTick/OnKey/OnJoin/OnLeave, and Ent, Players, HUD, Score, Camera, Timer, State, Vec, Mode,
-- Random, print, plus Devices for device modes (ModeDevices.lua). newEnv below builds exactly that, and the
-- tests check the two match. Every call into the script (loading it, each callback, each timer) runs under the
-- client's time guard (LeylineGuard); an error or a hang stops only that mode, with the line, into M.console
-- (the script editor's console, ModeScript.lua). Host.Reload swaps in a new script while it runs (hot reload).
-- Arena coordinates are yards in a frame placed where the host stood: x right, y up, z forward.

local W = WrathUnleashedUI
local API = W.ModeAPI   -- ModeAPI.lua, before this file in the .toc
if not API then return end
local PREFIX, MOD = "OVMOD", "wumodes"
local TICK = 0.05
local SEND_EVERY = 0.1
local GUARD_MS = API.GUARD_MS
local KEYS_OK = { BUTTON1 = 1 }
for _, k in ipairs(API.KEYS) do KEYS_OK[k] = 1 end

local M = { modes = {}, parts = {}, state = "idle", players = {}, score = {}, notes = {}, texts = {}, textOrder = {} }
W.Modes = M

local win, hud, keyFrame

local function now() return (GetTime and GetTime()) or 0 end
local function me() return UnitName and UnitName("player") or "You" end
local function has() return type(LeylineMode) == "function" and type(LeylineGuard) == "function" end
local function draw(text) if has() then LeylineMode(text) end end
local function tidy(s) return (tostring(s or ""):gsub("|", "")) end
local function sound(n) if PlaySound then pcall(PlaySound, n) end end

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end

local function button(parent, text, w, onClick, ...)
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(22)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end

local function status(text)
    M.status = text or ""
    if win then win.status:SetText(M.status) end
end

-- ---------------------------------------------------------------- the realm channel

local outbox = {}
local function send(name, data)
    data = data or ""
    local CHUNK = 200
    local total = math.max(1, math.ceil(#data / CHUNK))
    if total > 64 then return false end
    for i = 1, total do
        outbox[#outbox + 1] = MOD .. "\t" .. name .. "\t" .. i .. "/" .. total .. "\t" .. data:sub((i - 1) * CHUNK + 1, i * CHUNK)
    end
    return true
end
M.Send = send
local pump = CreateFrame("Frame")
pump.sentAt, pump.sent = 0, 0
pump:SetScript("OnUpdate", function(self)
    if #outbox == 0 then return end
    local t = now()
    if t - self.sentAt >= 1 then self.sentAt, self.sent = t, 0 end
    while #outbox > 0 and self.sent < 30 do
        local msg = table.remove(outbox, 1)
        if SendAddonMessage and UnitName then pcall(SendAddonMessage, PREFIX, msg, "WHISPER", UnitName("player")) end
        self.sent = self.sent + 1
    end
end)

-- ---------------------------------------------------------------- drawing state (every client)

local function noteLine(text)
    M.notes[#M.notes + 1] = text
    if #M.notes > 4 then table.remove(M.notes, 1) end
    if hud then hud.note:SetText(table.concat(M.notes, "\n")); hud.noteAt = now() end
end

local function refreshScore()
    if not hud then return end
    local rows = {}
    for name, v in pairs(M.score) do rows[#rows + 1] = { name = name, v = v } end
    table.sort(rows, function(a, b) if a.v ~= b.v then return a.v > b.v end return a.name < b.name end)
    local lines = {}
    for _, r in ipairs(rows) do lines[#lines + 1] = string.format("%s  |cffffd100%d|r", r.name, r.v) end
    hud.card:SetText(table.concat(lines, "\n"))
end

local function refreshTexts()
    if not hud then return end
    local lines = {}
    for _, slot in ipairs(M.textOrder) do
        local x = M.texts[slot]
        if x and (x.who == "*" or x.who == me()) then lines[#lines + 1] = x.text end
    end
    hud.texts:SetText(table.concat(lines, "\n"))
end

-- One state item, as the host sends it (and applies to itself):
--   e,id,shape,x,y,z,sx,sy,sz,yaw,color   m,id,x,y,z,yaw   d,id   h,text   b,text   s,name,score   c,name,follow,id,dist,height | c,name,top,height
--   p,name,text (a line for one player)   t,slot,who,text (a HUD.Text line; who is * or a name; empty text clears)
local function apply(item)
    local kind, rest = item:match("^(%a),(.*)$")
    if kind == "e" then
        local id, shape, x, y, z, sx, sy, sz, yaw, color = rest:match("^(%d+),(%a+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),([^,]+),(%x+)$")
        if id then draw(string.format("ent %s %s %s %s %s %s %s %s %s %s", id, shape, x, y, z, sx, sy, sz, yaw, color)) end
    elseif kind == "m" then
        local id, x, y, z, yaw = rest:match("^(%d+),([^,]+),([^,]+),([^,]+),([^,]+)$")
        if id then draw(string.format("mv %s %s %s %s %s", id, x, y, z, yaw)) end
    elseif kind == "d" then
        draw("del " .. (tonumber(rest) or 0))
    elseif kind == "h" then
        noteLine(tidy(rest))
    elseif kind == "p" then
        local name, text = rest:match("^([^,]*),(.*)$")
        if name and name == me() then noteLine(tidy(text)) end
    elseif kind == "t" then
        local slot, who, text = rest:match("^([%w_]+),([^,]*),(.*)$")
        if slot then
            if not M.texts[slot] then M.textOrder[#M.textOrder + 1] = slot end
            M.texts[slot] = { who = tidy(who), text = tidy(text) }
            if text == "" then
                M.texts[slot] = nil
                for i, x in ipairs(M.textOrder) do if x == slot then table.remove(M.textOrder, i) break end end
            end
            refreshTexts()
        end
    elseif kind == "b" then
        M.banner = tidy(rest)
        if hud then hud.banner:SetText(M.banner) end
    elseif kind == "s" then
        local name, v = rest:match("^([^,]+),(%-?%d+)$")
        if name then M.score[tidy(name)] = tonumber(v); refreshScore() end
    elseif kind == "c" then
        local name, how, a, b, c = rest:match("^([^,]+),(%a+),?([^,]*),?([^,]*),?([^,]*)$")
        if name == me() then
            if how == "follow" then draw(string.format("cam follow %s %s %s", a, b ~= "" and b or "7", c ~= "" and c or "4"))
            elseif how == "top" then draw("cam top " .. (a ~= "" and a or "30"))
            else draw("cam off") end
        end
    end
end

local function applyState(data)
    for item in data:gmatch("[^;]+") do apply(item) end
end

-- ---------------------------------------------------------------- the host: the sandbox and the loop

local Host = {}
M.Host = Host

-- The creator log: errors (with the script's line), print output and notes, newest last. The script editor's
-- console shows it (ModeScript.lua); M.onLog hears each new entry.
M.console = {}
function M.Log(kind, text, line)
    local e = { kind = kind, text = tidy(text):sub(1, 240), line = tonumber(line), at = now() }
    M.console[#M.console + 1] = e
    if #M.console > 60 then table.remove(M.console, 1) end
    if M.onLog then pcall(M.onLog, e) end
    return e
end

-- "mode:12: attempt to ..." -> 12, "attempt to ..."
local function lineOf(msg)
    local l, rest = tostring(msg or ""):match("mode:(%d+): ?(.*)$")
    return tonumber(l), rest
end
M.LineOf = lineOf

local function guardTrip(err) return tostring(err or ""):find("ran too long", 1, true) ~= nil end

local function newEnv(H)
    local env = {}
    -- The safe standard library: no string.dump, no loading code, no access to the game's globals.
    local s = {}
    for k, v in pairs(string) do if k ~= "dump" and k ~= "rep" then s[k] = v end end
    s.rep = function(str, n)
        str = tostring(str or "")
        n = math.min(math.floor(tonumber(n) or 0), 1000, math.floor(API.MAX_REP / math.max(1, #str)))
        return string.rep(str, math.max(0, n))
    end
    local m, t = {}, {}
    for k, v in pairs(math) do m[k] = v end
    m.random, m.randomseed = nil, nil
    for k, v in pairs(table) do t[k] = v end
    env.string, env.math, env.table = s, m, t
    -- A private copy for the string metatable while the script runs (call below), so ("x"):rep and ("x").dump
    -- reach the capped rep and no dump. The script never sees this table, so it can't change it.
    local priv = {}
    for k, v in pairs(s) do priv[k] = v end
    H.strlib = priv
    for _, k in ipairs(API.BASE) do env[k] = _G[k] end
    -- pcall can't swallow the time guard: a script that catches it gets it again, so a loop of pcalls still stops.
    env.pcall = function(fn, ...)
        local r = { n = 0 }
        local function pack(...) r.n = select("#", ...); for i = 1, r.n do r[i] = (select(i, ...)) end end
        pack(pcall(fn, ...))
        if not r[1] and guardTrip(r[2]) then error(r[2], 0) end
        return unpack(r, 1, r.n)
    end
    env.print = function(...)
        local parts = {}
        for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
        local text = tidy(table.concat(parts, " ")):sub(1, 120)
        noteLine("|cff9fd6ff[mode]|r " .. text)
        M.Log("print", text)
    end
    local seed = H.seed
    env.Random = function(n)
        seed = (seed * 1103515245 + 12345) % 2147483648
        n = math.max(1, math.floor(tonumber(n) or 1))
        return seed % n + 1
    end
    env.Mode = { Title = "A mode", Keys = {} }
    env.Mode.End = function(text) H.endText = tidy(text or "Game over") end

    local ents, nextId = {}, 1
    local function num(v, d) v = tonumber(v); if not v or v ~= v or math.abs(v) > 400 then return d end return v end
    local function col(c) c = tostring(c or "ffffff"):gsub("#", ""); if not c:match("^%x%x%x%x%x%x$") then c = "ffffff" end return c:lower() end
    local function full(e)
        return string.format("e,%d,%s,%.2f,%.2f,%.2f,%.2f,%.2f,%.2f,%.1f,%s", e.id, e.shape, e.x, e.y, e.z, e.sx, e.sy, e.sz, e.yaw, e.color)
    end
    local function remove(id)
        if not ents[id] then return end
        ents[id] = nil
        H.entCount = H.entCount - 1
        H.moved[id] = nil
        H.queue("d," .. id)
    end
    env.Ent = {
        Spawn = function(o)
            o = type(o) == "table" and o or {}
            if H.entCount >= API.MAX_ENTS then error("too many entities (" .. API.MAX_ENTS .. " at most)", 2) end
            local shape = (o.shape == "ball" or o.shape == "cyl") and o.shape or "box"
            local e = { id = nextId, shape = shape, x = num(o.x, 0), y = num(o.y, 0), z = num(o.z, 0),
                sx = num(o.sx, 1), sy = num(o.sy, 1), sz = num(o.sz, 1), yaw = num(o.yaw, 0), color = col(o.color) }
            nextId = nextId + 1
            ents[e.id] = e
            H.entCount = H.entCount + 1
            H.queue(full(e))
            return e.id
        end,
        Move = function(id, x, y, z, yaw)
            local e = ents[id]
            if not e then return end
            e.x, e.y, e.z, e.yaw = num(x, e.x), num(y, e.y), num(z, e.z), num(yaw, e.yaw)
            H.moved[id] = e
        end,
        Set = function(id, o)
            local e = ents[id]
            if not e or type(o) ~= "table" then return end
            for _, k in ipairs({ "x", "y", "z", "sx", "sy", "sz", "yaw" }) do if o[k] then e[k] = num(o[k], e[k]) end end
            if o.color then e.color = col(o.color) end
            if o.shape == "box" or o.shape == "ball" or o.shape == "cyl" then e.shape = o.shape end
            H.moved[id] = nil
            H.queue(full(e))
        end,
        Remove = remove,
        Get = function(id)
            local e = ents[id]
            if not e then return nil end
            return { x = e.x, y = e.y, z = e.z, sx = e.sx, sy = e.sy, sz = e.sz, yaw = e.yaw, color = e.color, shape = e.shape }
        end,
        Clear = function() local ids = {} for id in pairs(ents) do ids[#ids + 1] = id end for _, id in ipairs(ids) do remove(id) end end,
        Count = function() return H.entCount end,
    }
    H.ents, H.full = ents, full
    env.Players = {
        List = function() local l = {} for i, n in ipairs(H.players) do l[i] = n end return l end,
        Count = function() return #H.players end,
        Has = function(p) p = tostring(p) for _, n in ipairs(H.players) do if n == p then return true end end return false end,
    }
    local function clean(text) return (tidy(tostring(text or "")):gsub("[;\n]", " "):sub(1, API.MAX_TEXT)) end
    local texts, textOrder = {}, {}
    H.texts = texts
    env.HUD = {
        Say = function(text) H.queue("h," .. clean(text)) end,
        Banner = function(text) H.banner = clean(text); H.queue("b," .. H.banner) end,
        Tell = function(p, text) H.queue("p," .. (clean(p):gsub(",", "")) .. "," .. clean(text)) end,
        Text = function(slot, text, p)
            slot = (tostring(slot or ""):gsub("[^%w_]", "")):sub(1, 16)
            if slot == "" then return end
            local who = p and (clean(p):gsub(",", "")) or "*"
            text = text and clean(text) or ""
            if not texts[slot] then
                local n = 0
                for _ in pairs(texts) do n = n + 1 end
                if n >= API.MAX_TEXT_SLOTS then error("too many HUD.Text slots (" .. API.MAX_TEXT_SLOTS .. " at most)", 2) end
            end
            texts[slot] = text ~= "" and { who = who, text = text } or nil
            H.queue("t," .. slot .. "," .. who .. "," .. text)
        end,
    }
    local scores = {}
    local function setScore(p, v) scores[p] = v; H.queue("s," .. clean(p) .. "," .. v) end
    env.Score = {
        Set = function(p, v) setScore(tostring(p), math.floor(num(v, 0))) end,
        Add = function(p, v) p = tostring(p); setScore(p, (scores[p] or 0) + math.floor(num(v, 0))) end,
        Get = function(p) return scores[tostring(p)] or 0 end,
        Top = function()
            local l = {}
            for p, v in pairs(scores) do l[#l + 1] = { name = p, score = v } end
            table.sort(l, function(a, b) if a.score ~= b.score then return a.score > b.score end return a.name < b.name end)
            return l
        end,
        Reset = function() for p in pairs(scores) do setScore(p, 0) end end,
    }
    H.scores = scores
    env.Camera = {
        Follow = function(p, id, dist, height) H.queue(string.format("c,%s,follow,%d,%.1f,%.1f", clean(p), tonumber(id) or 0, num(dist, 7), num(height, 4))) end,
        Top = function(height) for _, p in ipairs(H.players) do H.queue(string.format("c,%s,top,%.1f", p, num(height, 30))) end end,
    }
    local function addTimer(sec, fn, every)
        if type(fn) ~= "function" then return nil end
        if #H.timers >= API.MAX_TIMERS then error("too many timers (" .. API.MAX_TIMERS .. " at most)", 3) end
        H.timerId = H.timerId + 1
        local tm = { id = H.timerId, at = H.clock + math.max(every and API.MIN_EVERY or 0, num(sec, 0)), fn = fn }
        if every then tm.every = math.max(API.MIN_EVERY, num(sec, 1)) end
        H.timers[#H.timers + 1] = tm
        return tm.id
    end
    env.Timer = {
        After = function(sec, fn) return addTimer(sec, fn, false) end,
        Every = function(sec, fn) return addTimer(sec, fn, true) end,
        Cancel = function(id)
            for i, tm in ipairs(H.timers) do if tm.id == id then table.remove(H.timers, i) return end end
            if H.firing and H.firing.id == id then H.firing.cancelled = true end
        end,
    }
    -- State: values with change events. The values survive a hot reload (Host.Reload); the handlers don't.
    local state, handlers, depth = H.state or {}, {}, 0
    H.state = state
    local nKeys, nHandlers = 0, 0
    for _ in pairs(state) do nKeys = nKeys + 1 end
    local function fire(list, key, value, old)
        for _, fn in ipairs(list or {}) do fn(value, old, key) end
    end
    env.State = {
        Set = function(key, value)
            key = tostring(key)
            if #key > 32 then error("State keys are 32 characters at most", 2) end
            local tv = type(value)
            if tv ~= "nil" and tv ~= "number" and tv ~= "string" and tv ~= "boolean" then error("State values are numbers, text or true/false", 2) end
            if tv == "string" then value = value:sub(1, 200) end
            local old = state[key]
            if old == value then return end
            if depth >= API.MAX_STATE_DEPTH then error("State change events went " .. API.MAX_STATE_DEPTH .. " deep (a loop?)", 2) end
            if old == nil then
                if nKeys >= API.MAX_STATE_KEYS then error("too many State keys (" .. API.MAX_STATE_KEYS .. " at most)", 2) end
                nKeys = nKeys + 1
            elseif value == nil then
                nKeys = nKeys - 1
            end
            state[key] = value
            depth = depth + 1
            local ok, err = pcall(function() fire(handlers[key], key, value, old); fire(handlers["*"], key, value, old) end)
            depth = depth - 1
            if not ok then error(err, 0) end
        end,
        Get = function(key, default)
            local v = state[tostring(key)]
            if v == nil then return default end
            return v
        end,
        On = function(key, fn)
            if type(fn) ~= "function" then return end
            if nHandlers >= API.MAX_STATE_HANDLERS then error("too many State handlers (" .. API.MAX_STATE_HANDLERS .. " at most)", 2) end
            key = tostring(key)
            handlers[key] = handlers[key] or {}
            table.insert(handlers[key], fn)
            nHandlers = nHandlers + 1
        end,
    }
    local sqrt, atan2, deg, rad, sin, cos = math.sqrt, math.atan2, math.deg, math.rad, math.sin, math.cos
    local function n0(v) v = tonumber(v) or 0 if v ~= v then return 0 end return v end
    env.Vec = {
        Len = function(x, z) x, z = n0(x), n0(z) return sqrt(x * x + z * z) end,
        Dist = function(x1, z1, x2, z2) local dx, dz = n0(x2) - n0(x1), n0(z2) - n0(z1) return sqrt(dx * dx + dz * dz) end,
        Dist3 = function(x1, y1, z1, x2, y2, z2)
            local dx, dy, dz = n0(x2) - n0(x1), n0(y2) - n0(y1), n0(z2) - n0(z1)
            return sqrt(dx * dx + dy * dy + dz * dz)
        end,
        Norm = function(x, z)
            x, z = n0(x), n0(z)
            local l = sqrt(x * x + z * z)
            if l < 1e-9 then return 0, 0, 0 end
            return x / l, z / l, l
        end,
        Angle = function(x, z) return deg(atan2(n0(x), n0(z))) end,
        Dir = function(a) a = rad(n0(a)) return sin(a), cos(a) end,
        Rotate = function(x, z, a)
            x, z, a = n0(x), n0(z), rad(n0(a))
            local c, s2 = cos(a), sin(a)
            return x * c + z * s2, z * c - x * s2
        end,
        Lerp = function(a, b, t) a, b = n0(a), n0(b) return a + (b - a) * n0(t) end,
        Clamp = function(v, lo, hi) return math.max(n0(lo), math.min(n0(hi), n0(v))) end,
    }
    env._G = env
    return env
end

-- The line a stopped script was on: the error's own "mode:N:", else the first "mode:N:" frame on the stack
-- (an endless loop stopped by the guard has no position of its own).
local function stackLine()
    local tb = (debugstack and debugstack(1, 30, 0)) or (debug and debug.traceback and debug.traceback()) or ""
    return tonumber(tostring(tb):match("mode:(%d+):"))
end

-- Strings share one metatable with the game's UI code. While a creator function runs, its __index is the mode's
-- private string table (no dump, the capped rep); it goes back right after. Returns the old one (nil: unchanged).
local smt = getmetatable and getmetatable("")
local function swapStrings(lib)
    if type(smt) ~= "table" or not lib then return nil end
    local old = smt.__index
    if not pcall(function() smt.__index = lib end) then return nil end
    return old
end
local function restoreStrings(old) if old ~= nil then pcall(function() smt.__index = old end) end end

-- Runs a creator function under the time guard; an error or a hang ends the mode with the message and the line.
-- Only this H fails: its state says why (H.failed, H.failedLine); nothing else is touched.
local function call(H, fn, ...)
    if type(fn) ~= "function" then return true end
    local n, args = select("#", ...), { ... }
    local line
    local oldStrings = swapStrings(H.strlib)
    LeylineGuard(GUARD_MS)
    local ok, err = xpcall(function() return fn(unpack(args, 1, n)) end, function(e)
        LeylineGuard(0)
        line = lineOf(e) or stackLine()
        return e
    end)
    LeylineGuard(0)
    restoreStrings(oldStrings)
    if not ok then
        local l, rest = lineOf(err)
        local msg
        if guardTrip(err) then msg = "mode script ran too long (an endless loop?)"
        else msg = (tidy(tostring(rest or err)):match("^[^\n]*") or ""):sub(1, 200) end
        H.failedLine = l or line
        H.failed = (H.failedLine and ("line " .. H.failedLine .. ": ") or "") .. msg
        M.Log("error", msg, H.failedLine)
        return false
    end
    return true
end
M.call = call

-- opts.state: State values to start with (a hot reload keeps them).
function Host.Load(text, players, seed, opts)
    if not has() then return nil, "Modes need the Leyline browser client (20261025k or newer)." end
    if type(text) ~= "string" or #text > API.MAX_SCRIPT then return nil, "That mode is too big (14 KB at most)." end
    -- The creator API's check first (blocked names, compiled chunks), on every path: Play, Play Here, a hosted
    -- mode from the realm, and a hot reload. Then the text compiles into the sandbox and nowhere else.
    local bad, why = API.Check(text)
    if bad then
        M.Log("error", why, bad > 0 and bad or nil)
        return nil, why, bad > 0 and bad or nil
    end
    local chunk, err = loadstring(text, "=mode")
    if not chunk then
        local l, rest = lineOf(err)
        M.Log("error", rest or err, l)
        return nil, "The mode has an error" .. (l and (" on line " .. l) or "") .. ": " .. tidy(rest or err), l
    end
    local H = { players = players, seed = seed or 1, entCount = 0, moved = {}, buffer = {}, timers = {}, timerId = 0, clock = 0, acc = 0, sendAcc = 0 }
    H.state = {}
    for k, v in pairs((opts and opts.state) or {}) do H.state[k] = v end
    H.queue = function(item) H.buffer[#H.buffer + 1] = item end
    local env = newEnv(H)
    setfenv(chunk, env)
    H.env = env
    -- Device modes: the device runtime is a library in the mode's own sandbox, under the same guard.
    if M.DEVICES_LIB and text:find("Devices", 1, true) then
        local lib = loadstring(M.DEVICES_LIB, "=devices")
        if lib then
            setfenv(lib, env)
            if not call(H, lib) then return nil, "The devices failed to load: " .. H.failed, H.failedLine end
        end
    end
    if not call(H, chunk) then return nil, "The mode failed to load: " .. H.failed, H.failedLine end
    local want = tonumber(env.Mode.Api)
    if want and want > API.VERSION then
        local why = "This mode needs creator API " .. want .. "; this client has " .. API.VERSION .. "."
        M.Log("error", why)
        return nil, why
    end
    local keys = {}
    for _, k in ipairs(type(env.Mode.Keys) == "table" and env.Mode.Keys or {}) do
        k = tostring(k):upper()
        if KEYS_OK[k] then keys[#keys + 1] = k end
    end
    H.keys = keys
    H.title = tidy(env.Mode.Title):sub(1, 40)
    return H
end

function Host.Start(H)
    call(H, H.env.OnStart, Host.copy(H.players))
end

function Host.copy(t) local c = {} for i, v in ipairs(t) do c[i] = v end return c end

-- Hot reload: the new script in a fresh sandbox, with the same players, seed, State values and scores. The old
-- shapes and HUD lines go, then the new OnStart builds the arena again. If the new script doesn't load, the old
-- one keeps running and this returns nil and the error.
function Host.Reload(H, text)
    local N, err, line = Host.Load(text, H.players, H.seed, { state = H.state })
    if not N then return nil, err, line end
    for id in pairs(H.ents) do N.queue("d," .. id) end
    for slot in pairs(H.texts or {}) do N.queue("t," .. slot .. ",*,") end
    for p, v in pairs(H.scores) do N.scores[p] = v; N.queue("s," .. p .. "," .. v) end
    N.reloaded = (H.reloaded or 0) + 1
    Host.Start(N)
    N.sendAcc = SEND_EVERY
    return N
end

-- One frame of the host: fixed ticks, timers, then the state out (to itself and, on a realm, to everyone).
function Host.Update(H, elapsed, out)
    if H.failed or H.endText then return end
    H.acc = math.min(H.acc + elapsed, 0.5)
    while H.acc >= TICK and not H.failed and not H.endText do
        H.acc = H.acc - TICK
        H.clock = H.clock + TICK
        call(H, H.env.OnTick, TICK)
        -- Due timers, oldest first, at most TIMERS_PER_TICK of them; the rest wait for the next tick.
        local due = {}
        for _, tm in ipairs(H.timers) do if tm.at <= H.clock then due[#due + 1] = tm end end
        table.sort(due, function(a, b) if a.at ~= b.at then return a.at < b.at end return a.id < b.id end)
        for j = 1, math.min(#due, API.TIMERS_PER_TICK) do
            if H.failed or H.endText then break end
            local tm = due[j]
            for i, x in ipairs(H.timers) do if x == tm then table.remove(H.timers, i) break end end
            H.firing = tm
            local ok = call(H, tm.fn)
            H.firing = nil
            if ok and tm.every and not tm.cancelled and #H.timers < API.MAX_TIMERS then
                tm.at = tm.at + tm.every
                if tm.at <= H.clock then tm.at = H.clock + tm.every end
                H.timers[#H.timers + 1] = tm
            end
        end
    end
    H.sendAcc = H.sendAcc + elapsed
    if H.sendAcc < SEND_EVERY and not H.failed and not H.endText then return end
    H.sendAcc = 0
    for id, e in pairs(H.moved) do H.queue(string.format("m,%d,%.2f,%.2f,%.2f,%.1f", id, e.x, e.y, e.z, e.yaw)) end
    H.moved = {}
    if #H.buffer > 0 then
        local data = table.concat(H.buffer, ";")
        H.buffer = {}
        out(data)
    end
end

function Host.Key(H, player, key, down)
    call(H, H.env.OnKey, player, key, down and true or false)
end

-- Everything the host has so far, for a player who joins late.
function Host.Snapshot(H)
    local items = {}
    for _, e in pairs(H.ents) do items[#items + 1] = H.full(e) end
    for p, v in pairs(H.scores) do items[#items + 1] = "s," .. p .. "," .. v end
    for slot, x in pairs(H.texts or {}) do items[#items + 1] = "t," .. slot .. "," .. x.who .. "," .. x.text end
    if H.banner then items[#items + 1] = "b," .. H.banner end
    return table.concat(items, ";")
end

-- ---------------------------------------------------------------- the session (realm or solo)

local function setHud(show)
    if not hud then
        hud = CreateFrame("Frame", "LeylineModesHud", UIParent)
        hud:SetAllPoints(UIParent)
        hud:SetFrameStrata("HIGH")
        hud:EnableMouse(false)
        local top = CreateFrame("Frame", nil, hud)
        top:SetWidth(520); top:SetHeight(36)
        top:SetPoint("TOP", 0, -14)
        top:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
            tile = true, tileSize = 16, edgeSize = 14, insets = { left = 4, right = 4, top = 4, bottom = 4 } })
        top:SetBackdropColor(0.05, 0.04, 0.1, 0.82)
        top:SetBackdropBorderColor(0.6, 0.5, 1, 0.9)
        hud.banner = top:CreateFontString(nil, "OVERLAY", "GameFontNormal")
        hud.banner:SetPoint("CENTER")
        hud.note = label(hud, "", "GameFontNormal", "TOP", 0, -58)
        hud.texts = label(hud, "", "GameFontHighlight", "TOPLEFT", 24, -150)   -- HUD.Text lines
        hud.note:SetJustifyH("CENTER")
        local card = CreateFrame("Frame", nil, hud)
        card:SetWidth(200); card:SetHeight(140)
        card:SetPoint("TOPRIGHT", -18, -90)
        card:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
            tile = true, tileSize = 16, edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } })
        card:SetBackdropColor(0.04, 0.03, 0.08, 0.78)
        label(card, "Scores", "GameFontNormalSmall", "TOPLEFT", 10, -8)
        hud.card = label(card, "", "GameFontHighlightSmall", "TOPLEFT", 10, -24)
        button(card, "Leave", 64, function() M.Leave() end, "BOTTOMRIGHT", -6, 6)
        hud.keys = label(hud, "", "GameFontHighlightSmall", "BOTTOM", 0, 126)
        hud.keys:SetJustifyH("CENTER")
        hud.back = button(hud, "Back to the game", 140, function() if keyFrame then keyFrame:Show() end end, "BOTTOM", 0, 150)
        hud:SetScript("OnUpdate", function(_, elapsed)
            if hud.noteAt and now() - hud.noteAt > 7 then hud.note:SetText(""); M.notes = {}; hud.noteAt = nil end
            if keyFrame and keyFrame:IsShown() then hud.back:Hide() else hud.back:Show() end
            M.Update(elapsed or 0.016)
        end)

        -- The mode's keys go to the mode, not to walking, while this frame is shown. Esc lets go.
        keyFrame = CreateFrame("Frame", "LeylineModesKeys", UIParent)
        keyFrame:SetAllPoints(UIParent)
        keyFrame:EnableKeyboard(true)
        keyFrame:EnableMouse(false)
        keyFrame:SetScript("OnKeyDown", function(_, key)
            if key == "ESCAPE" then keyFrame:Hide(); M.ReleaseAll() return end
            M.LocalKey(key, true)
        end)
        keyFrame:SetScript("OnKeyUp", function(_, key) M.LocalKey(key, false) end)
        keyFrame:Hide()
    end
    if show then hud:Show() else hud:Hide(); keyFrame:Hide() end
end

M.held = {}

function M.LocalKey(key, down)
    key = tostring(key or ""):upper()
    if not M.keySet or not M.keySet[key] then return end
    if (M.held[key] or false) == down then return end
    M.held[key] = down or nil
    if M.host then
        Host.Key(M.host, me(), key, down)
    elseif M.state == "play" then
        send("in", key .. (down and " 1" or " 0"))
    end
end

function M.ReleaseAll()
    for key in pairs(M.held) do M.LocalKey(key, false) end
end

local function begin(title, keys, origin)
    M.score, M.notes, M.banner, M.texts, M.textOrder = {}, {}, title, {}, {}
    setHud(true)
    hud.banner:SetText(title)
    M.keySet = {}
    for _, k in ipairs(keys) do M.keySet[k] = true end
    hud.keys:SetText(#keys > 0 and ("|cffffd100" .. table.concat(keys, " ") .. "|r  play   |cffffd100Esc|r  look around") or "")
    draw("clear")
    draw("origin " .. origin)
    if #keys > 0 then keyFrame:Show() end
    refreshScore()
    refreshTexts()
end

-- Host a mode: on the realm (others join) or solo (nothing leaves this client).
function M.HostRun(text, players, seed, origin, out)
    local H, err = Host.Load(text, players, seed)
    if not H then status(err); noteLine("|cffff6060" .. tostring(err) .. "|r"); return false end
    M.host, M.hostOut = H, out
    begin(H.title, H.keys, origin)
    Host.Start(H)
    -- The opening field shows at once, not on the first send tick.
    H.sendAcc = SEND_EVERY
    Host.Update(H, 0, function(data) applyState(data); if out then out(data) end end)
    return true
end

function M.Update(elapsed)
    local H = M.host
    if not H then return end
    Host.Update(H, elapsed, function(data)
        applyState(data)
        if M.hostOut then M.hostOut(data) end
    end)
    if H.failed then
        local why = "The mode stopped: " .. H.failed
        noteLine("|cffff6060" .. why .. "|r")
        M.Finish(why)
    elseif H.endText then
        M.Finish(H.endText)
    end
end

-- Hot reload: swap the running script for new text (the script editor's Save while you test). The game keeps
-- its players, State values and scores; the old shapes go and the new OnStart builds again. If the new text
-- doesn't load, the old script keeps running.
function M.Reload(text)
    local H = M.host
    if not H then return nil, "Nothing is running." end
    local N, err, line = Host.Reload(H, text)
    if not N then
        noteLine("|cffff6060Reload failed; the old script keeps running.|r")
        return nil, err, line
    end
    M.host = N
    M.keySet = {}
    for _, k in ipairs(N.keys) do M.keySet[k] = true end
    if hud then hud.keys:SetText(#N.keys > 0 and ("|cffffd100" .. table.concat(N.keys, " ") .. "|r  play   |cffffd100Esc|r  look around") or "") end
    if M.state == "play" then send("keys", table.concat(N.keys, " ")) end
    noteLine("|cff9fd6ffReloaded.|r")
    M.Log("info", "Reloaded: " .. N.title)
    return N
end

function M.Finish(text)
    local H = M.host
    M.host = nil
    if M.state == "play" and H then send("end", tidy(text):sub(1, 150)) end
    noteLine("|cffffd100" .. tidy(text) .. "|r")
    sound("LEVELUPSOUND")
    M.stopAt = now() + 4
    M.state = "finished"
end

function M.Stop()
    M.host, M.hostOut, M.state, M.lobby, M.stopAt = nil, nil, "idle", nil, nil
    M.ReleaseAll()
    draw("clear")
    draw("cam off")
    setHud(false)
    M.Refresh()
    -- The device editor's Play sets this to come back to the editor when the test ends.
    if M.onStop then local fn = M.onStop; M.onStop = nil; fn() end
end

function M.Leave()
    if M.state == "play" or M.state == "lobby" then send("leave", "") end
    M.Stop()
end

local updater = CreateFrame("Frame")
updater:SetScript("OnUpdate", function()
    if M.stopAt and now() >= M.stopAt then M.Stop() end
end)

-- Solo: run a mode here, alone (a test of your own script, or a mode for one player).
function M.Solo(text, origin)
    if not has() then status("Modes need the Leyline browser client (20261025k or newer)."); return end
    M.Stop()
    M.state = "solo"
    if win then win:Hide() end
    if not M.HostRun(text, { me() }, math.floor(now() * 1000) % 100000 + 1, origin or "here", nil) then M.state = "idle"; return false end
    return true
end

-- ---------------------------------------------------------------- messages from the realm

local function dispatch(name, data)
    if name == "modes" then
        M.modes = {}
        for item in data:gmatch("[^;]+") do
            local key, title, author, mn, mx = item:match("^([%w_]+),([^,]+),([^,]+),(%d+),(%d+)$")
            if key then M.modes[#M.modes + 1] = { key = key, title = tidy(title), author = tidy(author), min = tonumber(mn), max = tonumber(mx) } end
        end
        M.waiting = nil
        status(#M.modes > 0 and "Pick a mode: Host here (party nearby is invited) or Play solo." or "No modes on this realm yet.")
        M.Refresh()
    elseif name == "open" then   -- the realm's Play (ov_playmode.lua): show the window
        if not win or not win:IsShown() then M.Toggle() end
    elseif name == "invite" then
        local id, host, title = data:match("^(%d+) (%S+) (.+)$")
        if id then M.invite = { id = tonumber(id), host = tidy(host), title = tidy(title) }; sound("igPlayerInvite"); M.Refresh(); if not win or not win:IsShown() then M.Toggle() end end
    elseif name == "lobby" then
        local id, host, names, title = data:match("^(%d+) (%S+) (%S+) (.+)$")
        if id and M.dropLobbyUntil and M.state == "idle" and now() < M.dropLobbyUntil then
            M.dropLobbyUntil = nil   -- a Play Here test stopped before the realm answered (ModeScript.lua)
            return
        end
        if id then
            M.lobby = { id = tonumber(id), host = tidy(host), title = tidy(title), names = {} }
            for n in names:gmatch("[^,]+") do M.lobby.names[#M.lobby.names + 1] = tidy(n) end
            M.invite, M.state = nil, "lobby"
            M.Refresh()
        end
    elseif name == "start" then
        -- start <id> <host> <x> <y> <z> <o> <seed> <players,...> \n <script>  (the script only for the host)
        local head, script = data:match("^([^\n]*)\n?(.*)$")
        local id, host, x, y, z, o, seed, names = head:match("^(%d+) (%S+) (%S+) (%S+) (%S+) (%S+) (%d+) (%S+)")
        if not id then return end
        local players = {}
        for n in names:gmatch("[^,]+") do players[#players + 1] = tidy(n) end
        M.state = "play"
        if win then win:Hide() end
        local origin = string.format("%s %s %s %s", x, y, z, o)
        if host == me() then
            M.HostRun(script, players, tonumber(seed), origin, function(state) send("st", state) end)
            if M.host then send("keys", table.concat(M.host.keys, " ")) end
        else
            M.keys = {}
            begin(M.lobby and M.lobby.title or "Mode", {}, origin)
        end
    elseif name == "keys" then
        -- The host's mode says which keys it wants from the players.
        local keys = {}
        for k in data:gmatch("%S+") do if KEYS_OK[k] then keys[#keys + 1] = k end end
        if not M.host and M.state == "play" then
            M.keySet = {}
            for _, k in ipairs(keys) do M.keySet[k] = true end
            if hud then hud.keys:SetText("|cffffd100" .. table.concat(keys, " ") .. "|r  play   |cffffd100Esc|r  look around") end
            if #keys > 0 and keyFrame then keyFrame:Show() end
        end
    elseif name == "st" then
        if not M.host then applyState(data) end
    elseif name == "in" then
        local who, key, down = data:match("^(%S+) (%S+) ([01])$")
        if who and M.host and M.keySetFor(key) then Host.Key(M.host, tidy(who), key, down == "1") end
    elseif name == "joined" then
        -- A player joined mid-game: the host sends them everything so far.
        if M.host then send("snap", tidy(data) .. "\n" .. Host.Snapshot(M.host)) ; send("keys", table.concat(M.host.keys, " ")) end
        if M.host then
            local present = false
            for _, p in ipairs(M.host.players) do if p == tidy(data) then present = true end end
            if not present then table.insert(M.host.players, tidy(data)); call(M.host, M.host.env.OnJoin, tidy(data)) end
        end
    elseif name == "left" then
        if M.host then
            local who = tidy(data)
            for i, p in ipairs(M.host.players) do if p == who then table.remove(M.host.players, i) break end end
            call(M.host, M.host.env.OnLeave, who)
        end
    elseif name == "msg" then
        noteLine(tidy(data))
    elseif name == "end" then
        if M.state == "play" then
            if not M.host then noteLine("|cffffd100" .. tidy(data) .. "|r"); sound("LEVELUPSOUND") end
            M.host = nil
            M.state = "finished"
            M.stopAt = now() + 4
        end
    elseif name == "script" then
        M.Solo(data)
    elseif name == "invalid" then
        -- The realm refused a script (Publish or Play Here): <line>\n<why>
        local l, why = data:match("^(%d*)\n(.*)$")
        why = tidy(why or data)
        M.Log("error", why, tonumber(l))
        status(why)
        if M.OnInvalid then M.OnInvalid(why, tonumber(l)) end
    elseif name == "published" then
        status("Sent for review: " .. tidy(data) .. ". A GM approves new modes before others see them.")
    elseif name == "drafts" or name == "draft" or name == "dsaved" then
        if M.OnDraftMessage then M.OnDraftMessage(name, data) end
    end
end

M._dispatch = dispatch  -- for stream/tests/test_ov_modes.lua

function M.keySetFor(key)
    if not M.host then return false end
    for _, k in ipairs(M.host.keys) do if k == key then return true end end
    return false
end

function M.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local mod, name, i, n, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
    if mod ~= MOD then return end
    i, n = tonumber(i), tonumber(n)
    if n < 1 or n > 64 or i < 1 or i > n then return end
    if n == 1 then M.parts[name] = nil; return dispatch(name, data) end
    local buf = M.parts[name]
    if i == 1 or not buf or buf.n ~= n then buf = { n = n, got = 0 }; M.parts[name] = buf end
    if not buf[i] then buf[i] = data; buf.got = buf.got + 1 end
    if buf.got == n then
        M.parts[name] = nil
        dispatch(name, table.concat(buf, "", 1, n))
    end
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) M.OnMessage(prefix, msg, channel, sender) end)

-- ---------------------------------------------------------------- the built-in mode (for Play solo and the realm's list)

M.BUILTIN = [==[
-- Bumper Balls: push the others off the arena. Last ball rolling wins.
Mode.Title = "Bumper Balls"
Mode.Keys = { "W", "A", "S", "D", "SPACE" }

local R = 9            -- arena radius
local balls = {}       -- player -> { id, x, z, vx, vz, keys = {}, out }
local COLORS = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local round = 0

local function reset()
    round = round + 1
    local list = Players.List()
    for i, p in ipairs(list) do
        local a = (i - 1) / #list * math.pi * 2
        local b = balls[p] or {}
        b.x, b.z, b.vx, b.vz, b.out, b.keys, b.dash = math.sin(a) * (R - 3), math.cos(a) * (R - 3), 0, 0, false, b.keys or {}, 0
        if b.id then Ent.Move(b.id, b.x, 0.7, b.z) else
            b.id = Ent.Spawn{ shape = "ball", x = b.x, y = 0.7, z = b.z, sx = 1.4, sy = 1.4, sz = 1.4, color = COLORS[(i - 1) % #COLORS + 1] }
        end
        balls[p] = b
        Camera.Follow(p, b.id, 9, 6)
    end
    HUD.Banner("Bumper Balls - round " .. round)
    HUD.Say("WASD to roll, Space to dash. Knock everyone off!")
end

function OnStart(players)
    Ent.Spawn{ shape = "cyl", x = 0, y = -0.25, z = 0, sx = R * 2, sy = 0.5, sz = R * 2, color = "3a3550" }
    Ent.Spawn{ shape = "cyl", x = 0, y = 0.02, z = 0, sx = R * 2 - 0.6, sy = 0.06, sz = R * 2 - 0.6, color = "5a4f8a" }
    Ent.Spawn{ shape = "cyl", x = 0, y = 0.04, z = 0, sx = 3, sy = 0.06, sz = 3, color = "ffd24a" }
    for _, p in ipairs(players) do Score.Set(p, 0) end
    reset()
end

function OnKey(player, key, down)
    local b = balls[player]
    if not b then return end
    b.keys[key] = down or nil
    if key == "SPACE" and down and b.dash <= 0 and not b.out then
        local sp = math.sqrt(b.vx * b.vx + b.vz * b.vz)
        if sp > 0.1 then b.vx, b.vz = b.vx / sp * 14, b.vz / sp * 14 end
        b.dash = 2
    end
end

function OnLeave(player)
    local b = balls[player]
    if b and b.id then Ent.Remove(b.id) end
    balls[player] = nil
end

local over = false
function OnTick(dt)
    if over then return end
    local alive, last = 0, nil
    for p, b in pairs(balls) do
        if not b.out then
            local ax, az = 0, 0
            if b.keys.W then az = az + 1 end
            if b.keys.S then az = az - 1 end
            if b.keys.D then ax = ax + 1 end
            if b.keys.A then ax = ax - 1 end
            b.vx = (b.vx + ax * 18 * dt) * 0.985
            b.vz = (b.vz + az * 18 * dt) * 0.985
            b.dash = math.max(0, b.dash - dt)
        end
    end
    -- Bumps: equal balls trade momentum along the line between them.
    local list = {}
    for p, b in pairs(balls) do if not b.out then list[#list + 1] = b end end
    for i = 1, #list do for j = i + 1, #list do
        local a, c = list[i], list[j]
        local dx, dz = c.x - a.x, c.z - a.z
        local d = math.sqrt(dx * dx + dz * dz)
        if d < 1.4 and d > 0.001 then
            local nx, nz = dx / d, dz / d
            local rel = (a.vx - c.vx) * nx + (a.vz - c.vz) * nz
            if rel > 0 then
                local j2 = rel * 1.15
                a.vx, a.vz = a.vx - j2 * nx, a.vz - j2 * nz
                c.vx, c.vz = c.vx + j2 * nx, c.vz + j2 * nz
            end
            local push = (1.4 - d) / 2
            a.x, a.z = a.x - nx * push, a.z - nz * push
            c.x, c.z = c.x + nx * push, c.z + nz * push
        end
    end end
    for p, b in pairs(balls) do
        if not b.out then
            b.x, b.z = b.x + b.vx * dt, b.z + b.vz * dt
            if b.x * b.x + b.z * b.z > R * R then
                b.out = true
                HUD.Say(p .. " is out!")
                Ent.Move(b.id, b.x * 1.1, -6, b.z * 1.1)
            else
                Ent.Move(b.id, b.x, 0.7, b.z, math.deg(math.atan2(b.vx, b.vz)))
                alive, last = alive + 1, p
            end
        end
    end
    local n = Players.Count()
    if (n > 1 and alive <= 1) or (n == 1 and alive == 0) then
        if last then Score.Add(last, 1); HUD.Say(last .. " wins round " .. round .. "!") end
        if last and Score.Get(last) >= 3 then
            over = true
            Mode.End(last .. " wins Bumper Balls!")
            return
        end
        over = true
        Timer.After(2.5, function() over = false; reset() end)
    end
end
]==]


M.COINDASH = [==[
-- Coin Dash: grab the most coins in 60 seconds. Gold is 1, blue gems are 3.
Mode.Title = "Coin Dash"
Mode.Keys = { "W", "A", "S", "D" }
Mode.Players = { 1, 8 }

local R = 12
local runners, coins = {}, {}
local COLORS = { "ff5a3c", "3cb4ff", "ffd23c", "8cff5a", "c878ff", "ff78c8", "ffffff", "ff9628" }
local left, over = 60, false

local function spawnCoin()
    local a = Random(360) * math.pi / 180
    local d = math.sqrt(Random(1000) / 1000) * (R - 1.5)
    local gem = Random(6) == 1
    local id = Ent.Spawn{ shape = gem and "box" or "cyl", x = math.sin(a) * d, y = 0.8, z = math.cos(a) * d,
        sx = gem and 0.6 or 0.8, sy = gem and 0.6 or 0.15, sz = gem and 0.6 or 0.8, yaw = 45, color = gem and "50b4ff" or "ffd700" }
    coins[id] = { x = math.sin(a) * d, z = math.cos(a) * d, value = gem and 3 or 1, spin = 0 }
end

function OnStart(players)
    Ent.Spawn{ shape = "cyl", x = 0, y = -0.25, z = 0, sx = R * 2, sy = 0.5, sz = R * 2, color = "2f5a36" }
    Ent.Spawn{ shape = "cyl", x = 0, y = 0.02, z = 0, sx = R * 2 - 0.8, sy = 0.06, sz = R * 2 - 0.8, color = "4f8a4a" }
    for i, p in ipairs(players) do
        local a = (i - 1) / #players * math.pi * 2
        runners[p] = { x = math.sin(a) * 4, z = math.cos(a) * 4, keys = {},
            id = Ent.Spawn{ shape = "ball", x = math.sin(a) * 4, y = 0.6, z = math.cos(a) * 4, sx = 1.2, sy = 1.2, sz = 1.2, color = COLORS[(i - 1) % #COLORS + 1] } }
        Score.Set(p, 0)
        Camera.Follow(p, runners[p].id, 10, 9)
    end
    for i = 1, 14 do spawnCoin() end
    HUD.Banner("Coin Dash - 60")
    HUD.Say("WASD to run. Gold is 1, blue gems are 3!")
end

function OnKey(player, key, down)
    local r = runners[player]
    if r then r.keys[key] = down or nil end
end

function OnLeave(player)
    local r = runners[player]
    if r then Ent.Remove(r.id) end
    runners[player] = nil
end

local tick = 0
function OnTick(dt)
    if over then return end
    tick = tick + 1
    left = left - dt
    if tick % 20 == 0 then HUD.Banner("Coin Dash - " .. math.max(0, math.ceil(left))) end
    for p, r in pairs(runners) do
        local ax, az = 0, 0
        if r.keys.W then az = az + 1 end
        if r.keys.S then az = az - 1 end
        if r.keys.D then ax = ax + 1 end
        if r.keys.A then ax = ax - 1 end
        local n = math.sqrt(ax * ax + az * az)
        if n > 0 then ax, az = ax / n, az / n end
        r.x, r.z = r.x + ax * 7 * dt, r.z + az * 7 * dt
        local d = math.sqrt(r.x * r.x + r.z * r.z)
        if d > R - 0.6 then r.x, r.z = r.x / d * (R - 0.6), r.z / d * (R - 0.6) end
        Ent.Move(r.id, r.x, 0.6, r.z)
        for id, c in pairs(coins) do
            local dx, dz = c.x - r.x, c.z - r.z
            if dx * dx + dz * dz < 1.0 then
                Ent.Remove(id)
                coins[id] = nil
                Score.Add(p, c.value)
                spawnCoin()
            end
        end
    end
    if tick % 4 == 0 then
        for id, c in pairs(coins) do c.spin = (c.spin + 30) % 360; Ent.Move(id, c.x, 0.8, c.z, c.spin) end
    end
    if left <= 0 then
        over = true
        local best, who = -1, nil
        for p in pairs(runners) do if Score.Get(p) > best then best, who = Score.Get(p), p end end
        Mode.End((who or "Nobody") .. " wins Coin Dash with " .. math.max(best, 0) .. "!")
    end
end
]==]

M.TEMPLATE = [==[
-- My mode. OnStart builds the arena; OnTick runs 20 times a second; OnKey gets the keys below.
Mode.Title = "My Mode"
Mode.Keys = { "W", "A", "S", "D", "SPACE" }

local balls = {}

function OnStart(players)
    Ent.Spawn{ shape = "box", x = 0, y = -0.25, z = 0, sx = 16, sy = 0.5, sz = 16, color = "3a3a4a" }
    for i, p in ipairs(players) do
        balls[p] = { x = i * 2, z = 0, keys = {} }
        balls[p].id = Ent.Spawn{ shape = "ball", x = i * 2, y = 0.5, z = 0, color = "ffaa33" }
        Camera.Follow(p, balls[p].id)
    end
    HUD.Banner("My Mode")
end

function OnKey(player, key, down)
    if balls[player] then balls[player].keys[key] = down or nil end
end

function OnTick(dt)
    for p, b in pairs(balls) do
        if b.keys.W then b.z = b.z + 6 * dt end
        if b.keys.S then b.z = b.z - 6 * dt end
        if b.keys.D then b.x = b.x + 6 * dt end
        if b.keys.A then b.x = b.x - 6 * dt end
        Ent.Move(b.id, b.x, 0.5, b.z)
    end
end
]==]

-- The mode editor (write, Play, Play Here, Stop, Save, Publish, the error console) is ModeScript.lua: M.Editor.

-- ---------------------------------------------------------------- the window

function M.Ask()
    M.askedAt, M.waiting = now(), true
    status("Asking the realm for its modes...")
    send("list", "")
end

function M.Refresh()
    if not win then return end
    for i, row in ipairs(win.rows) do
        local m = M.modes[i]
        row.mode = m
        if m then
            row.text:SetText(string.format("%s%s  |cffa0a0a0by %s, %d-%d players|r", m.key == M.pick and "|cff40ff40> |r" or "", m.title, m.author, m.min, m.max))
            row:Show()
        else
            row:Hide()
        end
    end
    local l = M.lobby
    if M.invite then
        win.lobby:SetText(string.format("|cffffd100%s|r invites you to %s.", M.invite.host, M.invite.title))
        win.join:Show(); win.go:Hide()
    elseif l and M.state == "lobby" then
        win.lobby:SetText(string.format("Lobby: %s (host %s)\nPlayers: %s", l.title, l.host, table.concat(l.names, ", ")))
        win.join:Hide()
        if l.host == me() then win.go:Show() else win.go:Hide() end
    else
        win.lobby:SetText(""); win.join:Hide(); win.go:Hide()
    end
    if has() then win.solo:Enable(); win.host:Enable() else win.solo:Disable(); win.host:Disable()
        status("Modes need the Leyline browser client (20261025k or newer).") end
end

function M.MyModes()
    local list = {}
    for title, text in pairs((WrathUnleashedUIDB and WrathUnleashedUIDB.modes) or {}) do list[#list + 1] = { title = title, text = text } end
    table.sort(list, function(a, b) return a.title < b.title end)
    return list
end

function M.SaveMode(title, text)
    WrathUnleashedUIDB = WrathUnleashedUIDB or {}
    WrathUnleashedUIDB.modes = WrathUnleashedUIDB.modes or {}
    WrathUnleashedUIDB.modes[tidy(title):sub(1, 40)] = text
end

function M.Publish(text)
    if not send("publish", text) then status("That mode is too big to publish (about 12 KB at most)."); return end
    status("Publishing...")
end

local function build()
    win = CreateFrame("Frame", "LeylineModesFrame", UIParent)
    win:SetWidth(460); win:SetHeight(340)
    win:SetPoint("CENTER")
    win:SetFrameStrata("DIALOG")
    win:EnableMouse(true)
    win:SetMovable(true)
    win:RegisterForDrag("LeftButton")
    win:SetScript("OnDragStart", win.StartMoving)
    win:SetScript("OnDragStop", win.StopMovingOrSizing)
    win:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    win:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = win:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.05, 0.06, 0.08, 0.95)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    label(win, "Modes", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, win, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    tinsert(UISpecialFrames, "LeylineModesFrame")
    label(win, "Modes on this realm", "GameFontNormal", "TOPLEFT", 22, -48)
    win.rows = {}
    for i = 1, 6 do
        local row = CreateFrame("Button", nil, win)
        row:SetWidth(416); row:SetHeight(20)
        row:SetPoint("TOPLEFT", 22, -66 - (i - 1) * 21)
        row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        row.text = label(row, "", "GameFontHighlight", "LEFT", 4, 0)
        row:SetScript("OnClick", function(self) if self.mode then M.pick = self.mode.key; M.Refresh() end end)
        win.rows[i] = row
    end
    win.host = button(win, "Host here", 100, function()
        if not M.pick then status("Pick a mode first."); return end
        send("host", M.pick); status("Opening a game...")
    end, "TOPLEFT", 22, -200)
    win.solo = button(win, "Play solo", 100, function()
        if M.pick then send("solo", M.pick); status("Fetching the mode...") else M.Solo(M.BUILTIN) end
    end, "TOPLEFT", 126, -200)
    button(win, "Refresh", 80, function() M.Ask() end, "TOPLEFT", 230, -200)
    button(win, "Mode editor", 100, function() win:Hide(); M.Editor() end, "TOPLEFT", 314, -200)
    win.lobby = label(win, "", "GameFontHighlight", "TOPLEFT", 22, -232)
    win.lobby:SetWidth(416)
    win.join = button(win, "Join", 90, function() if M.invite then send("join", tostring(M.invite.id)) end end, "TOPLEFT", 22, -268)
    win.go = button(win, "Start", 90, function() send("go", "") end, "TOPLEFT", 22, -268)
    button(win, "Leave", 80, function() M.Leave() end, "TOPLEFT", 118, -268)
    win.status = label(win, M.status or "", "GameFontHighlightSmall", "BOTTOMLEFT", 22, 22)
    win.status:SetWidth(416)
    win:SetScript("OnUpdate", function()
        if M.waiting and M.askedAt and now() - M.askedAt > 6 then
            M.waiting = nil
            status("This realm doesn't run modes yet. Play solo works anywhere (Bumper Balls).")
        end
    end)
    win:SetScript("OnShow", function() sound("igCharacterInfoOpen"); if #M.modes == 0 then M.Ask() end; M.Refresh() end)
    win:Hide()
end

function M.Toggle()
    if not win then build() end
    if win:IsShown() then win:Hide() else win:Show() end
end

SLASH_LEYLINEMODES1, SLASH_LEYLINEMODES2 = "/modes", "/mode"
SlashCmdList["LEYLINEMODES"] = function(arg)
    arg = tostring(arg or ""):lower()
    if arg == "leave" or arg == "quit" then return M.Leave() end
    if arg == "bumper" or arg == "solo" then return M.Solo(M.BUILTIN) end
    if arg == "coins" or arg == "coin" then return M.Solo(M.COINDASH) end
    if arg == "edit" or arg == "editor" then return M.Editor() end
    if (arg == "devices" or arg == "device") and M.DeviceEditor then return M.DeviceEditor() end
    if (arg == "plates" or arg == "pads") and M.PLATES then return M.Solo(M.PLATES) end
    for _, ex in ipairs(W.ModeExamples or {}) do if arg == ex.key then return M.Solo(ex.text) end end   -- ModeExamples.lua
    M.Toggle()
end
