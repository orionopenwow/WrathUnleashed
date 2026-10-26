-- Modes (3.3.5a API): Leyline Modes, scripted minigames anyone can write. /modes opens it.
--
-- A mode is one Lua script. The session's host runs it (here, in a sandbox: the safe parts of the standard
-- library and the API below, nothing of the game's UI, nothing that can reach the network on its own); every
-- other player only draws what the host sends and sends back the keys the mode asked for. Joining someone
-- else's mode never runs their code on your client. The realm (realm/custom/lua_scripts/ov_modes.lua, OVMOD
-- mod "wumodes") makes the sessions and relays: host -> everyone "st" (state), players -> host "in" (keys).
--
-- The creator API (see docs/MODES.md):
--   Mode.Title, Mode.Keys = { "W", "A", "S", "D", "SPACE" }       keys captured from every player while playing
--   function OnStart(players) end                                  players = { "Ann", "Bo" }
--   function OnTick(dt) end                                        20 times a second, dt = 0.05
--   function OnKey(player, key, down) end                          a player pressed or released one of Mode.Keys
--   function OnLeave(player) end
--   function OnJoin(player) end                                    someone joined a game already running
--   Ent.Spawn{ shape = "box"|"ball"|"cyl", x, y, z, sx, sy, sz, yaw, color = "ff8800" } -> id
--   Ent.Move(id, x, y, z [, yaw]), Ent.Set(id, { color = "...", sx = ... }), Ent.Remove(id), Ent.Get(id) -> table
--   Players.List() -> names, Players.Count()
--   HUD.Say(text)                     a line under everyone's banner;  HUD.Banner(text)
--   Score.Set(player, n), Score.Add(player, n), Score.Get(player)
--   Camera.Follow(player, id [, distance, height]), Camera.Top([height])
--   Timer.After(seconds, fn)          Random(n) -> 1..n (seeded per session)
--   Mode.End(text)                    finish: everyone sees the result
--   Devices.Run[=[ ... ]=]            a mode made of devices and wires, no code (ModeDevices.lua)
-- Arena coordinates are yards in a frame placed where the host stood: x right, y up, z forward.

local W = WrathUnleashedUI
local PREFIX, MOD = "OVMOD", "wumodes"
local TICK = 0.05
local SEND_EVERY = 0.1
local GUARD_MS = 30
local KEYS_OK = { W = 1, A = 1, S = 1, D = 1, Q = 1, E = 1, SPACE = 1, UP = 1, DOWN = 1, LEFT = 1, RIGHT = 1, F = 1, R = 1,
    ["1"] = 1, ["2"] = 1, ["3"] = 1, ["4"] = 1, BUTTON1 = 1 }

local M = { modes = {}, parts = {}, state = "idle", players = {}, score = {}, notes = {} }
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

-- One state item, as the host sends it (and applies to itself):
--   e,id,shape,x,y,z,sx,sy,sz,yaw,color   m,id,x,y,z,yaw   d,id   h,text   b,text   s,name,score   c,name,follow,id,dist,height | c,name,top,height
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

local function newEnv(H)
    local env = {}
    -- The safe standard library: no string.dump, no loading code, no access to the game's globals.
    local s = {}
    for k, v in pairs(string) do if k ~= "dump" and k ~= "rep" then s[k] = v end end
    s.rep = function(str, n) n = math.min(tonumber(n) or 0, 1000) return string.rep(str, n) end
    local m, t = {}, {}
    for k, v in pairs(math) do m[k] = v end
    m.random, m.randomseed = nil, nil
    for k, v in pairs(table) do t[k] = v end
    env.string, env.math, env.table = s, m, t
    for _, k in ipairs({ "pairs", "ipairs", "next", "select", "type", "tostring", "tonumber", "unpack", "pcall", "error", "assert" }) do
        env[k] = _G[k]
    end
    env.print = function(...)
        local parts = {}
        for i = 1, select("#", ...) do parts[#parts + 1] = tostring((select(i, ...))) end
        noteLine("|cff9fd6ff[mode]|r " .. tidy(table.concat(parts, " ")):sub(1, 120))
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
    env.Ent = {
        Spawn = function(o)
            o = type(o) == "table" and o or {}
            if H.entCount >= 300 then error("too many entities (300 at most)", 2) end
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
        Remove = function(id)
            if not ents[id] then return end
            ents[id] = nil
            H.entCount = H.entCount - 1
            H.moved[id] = nil
            H.queue("d," .. id)
        end,
        Get = function(id)
            local e = ents[id]
            if not e then return nil end
            return { x = e.x, y = e.y, z = e.z, sx = e.sx, sy = e.sy, sz = e.sz, yaw = e.yaw, color = e.color, shape = e.shape }
        end,
    }
    H.ents, H.full = ents, full
    env.Players = {
        List = function() local l = {} for i, n in ipairs(H.players) do l[i] = n end return l end,
        Count = function() return #H.players end,
    }
    local function clean(text) return tidy(tostring(text or "")):gsub("[;\n]", " "):sub(1, 120) end
    env.HUD = {
        Say = function(text) H.queue("h," .. clean(text)) end,
        Banner = function(text) H.queue("b," .. clean(text)) end,
    }
    local scores = {}
    env.Score = {
        Set = function(p, v) p = tostring(p); scores[p] = math.floor(num(v, 0)); H.queue("s," .. clean(p) .. "," .. scores[p]) end,
        Add = function(p, v) p = tostring(p); scores[p] = (scores[p] or 0) + math.floor(num(v, 0)); H.queue("s," .. clean(p) .. "," .. scores[p]) end,
        Get = function(p) return scores[tostring(p)] or 0 end,
    }
    H.scores = scores
    env.Camera = {
        Follow = function(p, id, dist, height) H.queue(string.format("c,%s,follow,%d,%.1f,%.1f", clean(p), tonumber(id) or 0, num(dist, 7), num(height, 4))) end,
        Top = function(height) for _, p in ipairs(H.players) do H.queue(string.format("c,%s,top,%.1f", p, num(height, 30))) end end,
    }
    env.Timer = {
        After = function(sec, fn)
            if type(fn) ~= "function" then return end
            H.timers[#H.timers + 1] = { at = H.clock + math.max(0, num(sec, 0)), fn = fn }
        end,
    }
    env._G = env
    return env
end

-- Runs a creator function under the time guard; an error or a hang ends the mode with the message.
local function call(H, fn, ...)
    if type(fn) ~= "function" then return true end
    LeylineGuard(GUARD_MS)
    local ok, err = pcall(fn, ...)
    LeylineGuard(0)
    if not ok then
        H.failed = tidy(tostring(err)):sub(1, 200)
        return false
    end
    return true
end

function Host.Load(text, players, seed)
    if not has() then return nil, "Modes need the Leyline browser client (20261025k or newer)." end
    if type(text) ~= "string" or #text > 14 * 1024 then return nil, "That mode is too big (14 KB at most)." end
    if text:find("\27", 1, true) then return nil, "Compiled chunks aren't allowed." end
    local chunk, err = loadstring(text, "=mode")
    if not chunk then return nil, "The mode has an error: " .. tidy(err) end
    local H = { players = players, seed = seed or 1, entCount = 0, moved = {}, buffer = {}, timers = {}, clock = 0, acc = 0, sendAcc = 0 }
    H.queue = function(item) H.buffer[#H.buffer + 1] = item end
    local env = newEnv(H)
    setfenv(chunk, env)
    H.env = env
    -- Device modes: the device runtime is a library in the mode's own sandbox, under the same guard.
    if M.DEVICES_LIB and text:find("Devices", 1, true) then
        local lib = loadstring(M.DEVICES_LIB, "=devices")
        if lib then
            setfenv(lib, env)
            if not call(H, lib) then return nil, "The devices failed to load: " .. H.failed end
        end
    end
    if not call(H, chunk) then return nil, "The mode failed to load: " .. H.failed end
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

-- One frame of the host: fixed ticks, timers, then the state out (to itself and, on a realm, to everyone).
function Host.Update(H, elapsed, out)
    if H.failed or H.endText then return end
    H.acc = math.min(H.acc + elapsed, 0.5)
    while H.acc >= TICK and not H.failed and not H.endText do
        H.acc = H.acc - TICK
        H.clock = H.clock + TICK
        call(H, H.env.OnTick, TICK)
        local due = {}
        for i = #H.timers, 1, -1 do
            if H.timers[i].at <= H.clock then due[#due + 1] = table.remove(H.timers, i) end
        end
        for j = #due, 1, -1 do call(H, due[j].fn) end
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

-- Everything the host has spawned so far, for a player who joins late.
function Host.Snapshot(H)
    local items = {}
    for _, e in pairs(H.ents) do items[#items + 1] = H.full(e) end
    for p, v in pairs(H.scores) do items[#items + 1] = "s," .. p .. "," .. v end
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
    M.score, M.notes, M.banner = {}, {}, title
    setHud(true)
    hud.banner:SetText(title)
    M.keySet = {}
    for _, k in ipairs(keys) do M.keySet[k] = true end
    hud.keys:SetText(#keys > 0 and ("|cffffd100" .. table.concat(keys, " ") .. "|r  play   |cffffd100Esc|r  look around") or "")
    draw("clear")
    draw("origin " .. origin)
    if #keys > 0 then keyFrame:Show() end
    refreshScore()
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
    M.HostRun(text, { me() }, math.floor(now() * 1000) % 100000 + 1, origin or "here", nil)
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
    elseif name == "invite" then
        local id, host, title = data:match("^(%d+) (%S+) (.+)$")
        if id then M.invite = { id = tonumber(id), host = tidy(host), title = tidy(title) }; sound("igPlayerInvite"); M.Refresh(); if not win or not win:IsShown() then M.Toggle() end end
    elseif name == "lobby" then
        local id, host, names, title = data:match("^(%d+) (%S+) (%S+) (.+)$")
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

-- ---------------------------------------------------------------- the mode editor: write, run, save, publish

local ed
local function buildEditor()
    ed = CreateFrame("Frame", "LeylineModesEditor", UIParent)
    ed:SetWidth(640); ed:SetHeight(520)
    ed:SetPoint("CENTER")
    ed:SetFrameStrata("DIALOG")
    ed:EnableMouse(true)
    ed:SetMovable(true)
    ed:RegisterForDrag("LeftButton")
    ed:SetScript("OnDragStart", ed.StartMoving)
    ed:SetScript("OnDragStop", ed.StopMovingOrSizing)
    ed:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    ed:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = ed:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.05, 0.06, 0.08, 0.95)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    label(ed, "Mode editor", "GameFontNormalLarge", "TOP", 0, -18)
    local close = CreateFrame("Button", nil, ed, "UIPanelCloseButton")
    close:SetPoint("TOPRIGHT", -6, -6)
    tinsert(UISpecialFrames, "LeylineModesEditor")
    local sf = CreateFrame("ScrollFrame", "LeylineModesEditorScroll", ed, "UIPanelScrollFrameTemplate")
    sf:SetPoint("TOPLEFT", 22, -46)
    sf:SetPoint("BOTTOMRIGHT", -40, 84)
    local box = CreateFrame("EditBox", "LeylineModesEditorBox", sf)
    box:SetMultiLine(true)
    box:SetAutoFocus(false)
    box:SetFontObject(ChatFontNormal or GameFontHighlight)
    box:SetWidth(570)
    box:SetMaxLetters(14 * 1024)
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    box:SetScript("OnTextChanged", function(self) sf:UpdateScrollChildRect() ed.count:SetText(#(self:GetText() or "") .. " / 14336") end)
    sf:SetScrollChild(box)
    ed.box = box
    ed.count = label(ed, "", "GameFontHighlightSmall", "BOTTOMRIGHT", -40, 66)
    ed.count:SetJustifyH("RIGHT")
    button(ed, "Run solo", 90, function()
        local text = box:GetText() or ""
        M.SaveMode(text:match('Mode%.Title%s*=%s*"([^"\n]+)"') or "My Mode", text)
        ed:Hide()
        M.Solo(text)
    end, "BOTTOMLEFT", 22, 40)
    button(ed, "Save", 70, function()
        local text = box:GetText() or ""
        local title = text:match('Mode%.Title%s*=%s*"([^"\n]+)"') or "My Mode"
        M.SaveMode(title, text)
        ed.info:SetText("Saved \"" .. tidy(title) .. "\".")
    end, "BOTTOMLEFT", 116, 40)
    button(ed, "Publish", 80, function() M.Publish(box:GetText() or ""); ed.info:SetText("Sent for review.") end, "BOTTOMLEFT", 190, 40)
    button(ed, "Template", 80, function() box:SetText(M.TEMPLATE) end, "BOTTOMLEFT", 274, 40)
    button(ed, "Bumper Balls", 100, function() box:SetText(M.BUILTIN) end, "BOTTOMLEFT", 358, 40)
    button(ed, "Coin Dash", 86, function() box:SetText(M.COINDASH) end, "BOTTOMLEFT", 462, 40)
    button(ed, "Device editor", 106, function() local t = box:GetText() or ""; ed:Hide(); if M.DeviceEditor then M.DeviceEditor(t) end end,
        "BOTTOMLEFT", 166, 14)
    ed.mine = button(ed, "Mine: -", 140, function()
        local mine = M.MyModes()
        if #mine == 0 then ed.info:SetText("Nothing saved yet."); return end
        M.myPick = (M.myPick or 0) % #mine + 1
        local pick = mine[M.myPick]
        box:SetText(pick.text)
        ed.mine:SetText(("Mine: " .. pick.title):sub(1, 22))
    end, "BOTTOMLEFT", 22, 14)
    ed.info = label(ed, "Docs: docs/MODES.md. Run solo tests it here; Publish sends it to a GM for review.", "GameFontHighlightSmall", "BOTTOMLEFT", 278, 20)
    ed.info:SetWidth(330)
    ed:Hide()
end

function M.Editor(text)
    if not ed then buildEditor() end
    if text then ed.box:SetText(text) elseif (ed.box:GetText() or "") == "" then ed.box:SetText(M.TEMPLATE) end
    ed:Show()
end

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
    M.Toggle()
end
