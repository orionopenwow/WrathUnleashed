-- Golf (3.3.5a API): Leyline minigolf, the first mode on the play layer. /golf opens it.
--
-- The browser client (20261025i+) draws the course and the balls and simulates every shot through one function,
-- LeylineGolf(text) (see crates/benilla-app/src/golf.rs); this file is the game around it:
--   * the window: the realm's courses, Play here (invites party members nearby), the lobby, Tee off,
--     and Practice, which plays Meadow Nine right where you stand with no realm involved;
--   * the HUD while playing: a banner (course, hole, par), whose turn it is, a power meter, the scorecard,
--     and the controls (A/D aim, Shift fine, W/S zoom, hold Space for power, Esc to look around);
--   * the course editor: build holes piece by piece in the world (the client's free camera), test any hole,
--     keep courses in your saved variables and publish them to the realm for everyone's /golf;
--   * the referee: on a realm, realm/custom/lua_scripts/ov_golf.lua (OVMOD mod "wugolf") orders turns and
--     relays shots; in Practice the same rules run here (Referee below), through the same message handler.
-- Shots are two integers (aim in tenths of a degree, power in permille). Every client simulates them the
-- same way, so nobody sends ball positions: only where the roll ended, with a hash every client can compare.

local W = WrathUnleashedUI
local PREFIX, MOD = "OVMOD", "wugolf"
local WIN_W, WIN_H = 460, 400
local ANSWER_WAIT = 6
local COLORS = { "ffffff", "ff8c1f", "40ccff", "ff66bf", "ffe033", "8cff4d", "b380ff", "ff4d40" }
local PRACTICE_COURSE = [==[
# Meadow Nine: Leyline's first-party minigolf course. Open format: see crates/benilla-mode/src/golf.rs.
# Every hole is played on the same spot, where the session started; the tee is at 0 0 0 facing +z.
course Meadow Nine
by WrathUnleashed

hole 2 First Putt
tee  0 0 0
cup  0 0 10
turf 0 -0.25 5     1.5 0.25 6.5
wall  1.6 0.15 5   0.1 0.4 6.6
wall -1.6 0.15 5   0.1 0.4 6.6
wall 0 0.15 11.6   1.7 0.4 0.1
wall 0 0.15 -1.6   1.7 0.4 0.1

hole 3 Dogleg Right
tee  0 0 0
cup  6.5 0 8
turf 0 -0.25 4     1.25 0.25 5.25
turf 4.5 -0.25 8   3.25 0.25 1.25
wall -1.35 0.15 4      0.1 0.4 5.35
wall  1.35 0.15 2.65   0.1 0.4 4.0
wall 0 0.15 -1.35      1.35 0.4 0.1
wall 3.375 0.15 9.35   4.75 0.4 0.1
wall 4.725 0.15 6.65   3.375 0.4 0.1
wall 8.1 0.15 8        0.1 0.4 1.35
bump 1.35 0 6.65       0.25 0.5

hole 2 Up the Ramp
tee  0 0 0
cup  0 1 12.8
turf 0 -0.25 3        1.4 0.25 4
turf 0 0.263 8.579    1.4 0.25 1.581  0 -18.4
turf 0 0.75 12        1.4 0.25 2
wall  1.5 0.6 6.5     0.1 0.85 7.6
wall -1.5 0.6 6.5     0.1 0.85 7.6
wall 0 0.15 -1.1      1.6 0.4 0.1
wall 0 1.15 14.1      1.6 0.4 0.1

hole 3 The Windmill
tee  0 0 0
cup  0 0 12
turf 0 -0.25 6     1.5 0.25 7.5
spin 0 0.3 6       1.35 0.3 0.12  90
bump 0 0 6         0.18 0.75
wall  1.6 0.15 6   0.1 0.4 7.6
wall -1.6 0.15 6   0.1 0.4 7.6
wall 0 0.15 13.6   1.7 0.4 0.1
wall 0 0.15 -1.6   1.7 0.4 0.1

hole 3 Sand Trap
tee  0 0 0
cup  1 0 12
turf 0 -0.25 2       2 0.25 3
sand 0 -0.25 6.5     1.2 0.25 1.5
turf -1.6 -0.25 6.5  0.4 0.25 1.5
turf  1.6 -0.25 6.5  0.4 0.25 1.5
turf 0 -0.25 11      2 0.25 3
wall  2.1 0.15 6.5   0.1 0.4 7.6
wall -2.1 0.15 6.5   0.1 0.4 7.6
wall 0 0.15 14.1     2.2 0.4 0.1
wall 0 0.15 -1.1     2.2 0.4 0.1

hole 3 Bumper Alley
tee  0 0 0
cup  0 0 14
turf 0 -0.25 7      1.5 0.25 8.5
bump -0.6 0 4       0.3 0.5
bump  0.6 0 6.5     0.3 0.5
bump  0 0 7.9       0.22 0.5
bump -0.6 0 9.3     0.3 0.5
bump  0.6 0 11.6    0.3 0.5
wall  1.6 0.15 7    0.1 0.4 8.6
wall -1.6 0.15 7    0.1 0.4 8.6
wall 0 0.15 15.6    1.7 0.4 0.1
wall 0 0.15 -1.6    1.7 0.4 0.1

hole 3 Ice Bridge
tee  0 0 0
cup  0 0 12.5
turf 0 -0.25 1       1.5 0.25 2.5
ice  0 -0.25 6.5     0.6 0.25 3
turf 0 -0.25 12      1.5 0.25 2.5
water 0 -0.4 6.5     1.5 3
wall  1.6 0.15 1     0.1 0.4 2.5
wall -1.6 0.15 1     0.1 0.4 2.5
wall  1.6 0.15 12    0.1 0.4 2.5
wall -1.6 0.15 12    0.1 0.4 2.5
wall 0 0.15 14.6     1.7 0.4 0.1
wall 0 0.15 -1.6     1.7 0.4 0.1

hole 3 Slider Gate
tee  0 0 0
cup  0 0 11.5
turf 0 -0.25 6        1.5 0.25 7.5
wall -1.0 0.15 6      0.5 0.4 0.12
wall  1.0 0.15 6      0.5 0.4 0.12
slide -0.6 0.2 6.4    0.4 0.25 0.12   1.2 0   3
wall  1.6 0.15 6      0.1 0.4 7.6
wall -1.6 0.15 6      0.1 0.4 7.6
wall 0 0.15 13.6      1.7 0.4 0.1
wall 0 0.15 -1.6      1.7 0.4 0.1

hole 4 Grand Finale
tee  0 0 0
cup  0.8 1.5 15
turf 0 -0.25 3        1.5 0.25 4.5
boost 0 0 3.5         0.6 0.6  0 9
turf 0 0.516 9.588    1.5 0.25 2.136  0 -20.6
turf 0 1.25 14        2 0.25 2.5
bump -0.8 1.5 14.2    0.3 0.5
wall  1.6 0.6 4.95    0.1 0.85 6.55
wall -1.6 0.6 4.95    0.1 0.85 6.55
wall  2.1 1.65 14.05  0.1 0.4 2.55
wall -2.1 1.65 14.05  0.1 0.4 2.55
wall  1.85 1.65 11.4  0.25 0.4 0.1
wall -1.85 1.65 11.4  0.25 0.4 0.1
wall 0 1.65 16.6      2.2 0.4 0.1
wall 0 0.15 -1.6      1.7 0.4 0.1
]==]

local G = {
    courses = {}, parts = {}, players = {}, order = {}, score = {}, notes = {},
    playing = false, practice = false, hole = 0, par = 0, holeName = "", title = "",
}
W.Golf = G

local win, hud, aimFrame, results

local function now() return (GetTime and GetTime()) or 0 end
local function me() return UnitName and UnitName("player") or "You" end
local function has() return type(LeylineGolf) == "function" end
local function golf(text) if has() then return LeylineGolf(text) end end

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlight")
    fs:SetPoint(...)
    fs:SetJustifyH("LEFT")
    fs:SetText(text)
    return fs
end

local function button(parent, text, w, onClick, ...)
    if W.Style then local b = W.Style.Button(parent, text, w, onClick, nil, ...); b:SetHeight(22); return b end
    local b = CreateFrame("Button", nil, parent, "UIPanelButtonTemplate")
    b:SetWidth(w); b:SetHeight(22)
    b:SetText(text)
    b:SetPoint(...)
    b:SetScript("OnClick", onClick)
    return b
end

local function sound(name) if PlaySound then pcall(PlaySound, name) end end

local function status(text)
    G.status = text or ""
    if win then win.status:SetText(G.status) end
end

local function noteLine(text)
    G.notes[#G.notes + 1] = text
    if #G.notes > 3 then table.remove(G.notes, 1) end
    if hud then hud.note:SetText(table.concat(G.notes, "\n")) ; hud.noteAt = now() end
end

-- ---------------------------------------------------------------- talking to the realm

local function send(name, data)
    if not SendAddonMessage or not UnitName then return false end
    pcall(SendAddonMessage, PREFIX, MOD .. "\t" .. name .. "\t1/1\t" .. (data or ""), "WHISPER", UnitName("player"))
    return true
end

-- Long data (a published course) goes in parts, at most 30 a second.
local outbox = {}
local function sendLong(name, data)
    local CHUNK = 200
    local total = math.max(1, math.ceil(#data / CHUNK))
    if total > 64 then return false end
    for i = 1, total do
        outbox[#outbox + 1] = MOD .. "\t" .. name .. "\t" .. i .. "/" .. total .. "\t" .. data:sub((i - 1) * CHUNK + 1, i * CHUNK)
    end
    return true
end
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

local Referee   -- the practice referee, below
local dispatch

local function toRealm(name, data)
    if G.practice then return Referee.Receive(name, data or "") end
    return send(name, data)
end

-- ---------------------------------------------------------------- the HUD

local function colorName(name)
    local p = G.players[name]
    return "|cff" .. COLORS[((p and p.color) or 0) % #COLORS + 1] .. name .. "|r"
end

local function refreshScore()
    if not hud then return end
    local lines = {}
    local holes = G.holeCount or 0
    for _, name in ipairs(G.order) do
        local s = G.score[name] or {}
        local cells, total = {}, 0
        for h = 1, holes do
            local v = tonumber(s[h])
            cells[#cells + 1] = v and tostring(v) or (h == G.hole and "|cff808080.|r" or "|cff505050-|r")
            total = total + (v or 0)
        end
        lines[#lines + 1] = string.format("%s  %s  |cffffd100%d|r", colorName(name), table.concat(cells, " "), total)
    end
    hud.card:SetText(table.concat(lines, "\n"))
end

local function setBanner()
    if not hud then return end
    hud.title:SetText(string.format("|cffffd100%s|r   Hole %d of %d  ·  %s  ·  Par %d", G.title, G.hole, G.holeCount or 0, G.holeName, G.par))
end

local function setTurnText()
    if not hud then return end
    local t = G.turn
    if not t then hud.turn:SetText(""); return end
    if t.name == me() then
        hud.turn:SetText(string.format("|cff8fe36bYour turn|r  ·  stroke %d", t.stroke))
    else
        hud.turn:SetText(string.format("%s is putting  ·  stroke %d", colorName(t.name), t.stroke))
    end
end

local function showAimCapture(on)
    if not aimFrame then return end
    -- The client takes the aim on its next frame; until then "aiming=0" doesn't mean the aim ended.
    if on then G.aimArmed = now(); aimFrame:Show() else aimFrame:Hide() end
end

local function buildHud()
    hud = CreateFrame("Frame", "LeylineGolfHud", UIParent)
    hud:SetAllPoints(UIParent)
    hud:SetFrameStrata("HIGH")
    hud:EnableMouse(false)

    local top = CreateFrame("Frame", nil, hud)
    top:SetWidth(560); top:SetHeight(54)
    top:SetPoint("TOP", 0, -14)
    if W.Style then W.Style.Backdrop(top, W.Style.C.bg2) else top:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        tile = true, tileSize = 16, edgeSize = 14, insets = { left = 4, right = 4, top = 4, bottom = 4 } }) end
    top:SetBackdropColor(0.04, 0.08, 0.04, 0.82)
    top:SetBackdropBorderColor(0.55, 0.85, 0.4, 0.9)
    hud.title = top:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    hud.title:SetPoint("TOP", 0, -9)
    hud.turn = top:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
    hud.turn:SetPoint("TOP", 0, -29)

    -- The power meter, under the banner while you swing.
    local meter = CreateFrame("Frame", nil, hud)
    meter:SetWidth(320); meter:SetHeight(22)
    meter:SetPoint("BOTTOM", 0, 150)
    if W.Style then W.Style.Backdrop(meter, W.Style.C.bg2) else meter:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        tile = true, tileSize = 16, edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } }) end
    meter:SetBackdropColor(0, 0, 0, 0.75)
    local fill = meter:CreateTexture(nil, "ARTWORK")
    fill:SetTexture("Interface\\TargetingFrame\\UI-StatusBar")
    fill:SetPoint("LEFT", 4, 0)
    fill:SetHeight(14)
    fill:SetWidth(1)
    meter.fill = fill
    meter.text = meter:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    meter.text:SetPoint("CENTER")
    hud.meter = meter

    hud.keys = label(hud, "|cffffd100A / D|r aim   |cffffd100Shift|r fine   |cffffd100W / S|r zoom   |cffffd100hold Space|r power, release to putt   |cffffd100Esc|r look around",
        "GameFontHighlightSmall", "BOTTOM", 0, 126)
    hud.keys:SetJustifyH("CENTER")

    hud.resume = button(hud, "Back to the ball", 150, function()
        if G.turn and G.turn.name == me() then
            golf("aim " .. me() .. (G.lastAngle and (" " .. G.lastAngle) or ""))
            showAimCapture(true)
        end
    end, "BOTTOM", 0, 150)
    hud.resume:Hide()

    -- The scorecard, top right.
    local card = CreateFrame("Frame", nil, hud)
    card:SetWidth(300); card:SetHeight(150)
    card:SetPoint("TOPRIGHT", -18, -90)
    if W.Style then W.Style.Backdrop(card, W.Style.C.bg2) else card:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        tile = true, tileSize = 16, edgeSize = 12, insets = { left = 3, right = 3, top = 3, bottom = 3 } }) end
    card:SetBackdropColor(0.03, 0.05, 0.03, 0.78)
    card:SetBackdropBorderColor(0.4, 0.6, 0.3, 0.8)
    label(card, "Scorecard", "GameFontNormalSmall", "TOPLEFT", 10, -8)
    hud.card = label(card, "", "GameFontHighlightSmall", "TOPLEFT", 10, -24)
    hud.card:SetWidth(280)
    button(card, "Leave", 64, function() G.Leave() end, "BOTTOMRIGHT", -6, 6)

    hud.note = label(hud, "", "GameFontNormal", "TOP", 0, -76)
    hud.note:SetJustifyH("CENTER")

    hud:SetScript("OnUpdate", function()
        if G.stopAt and now() >= G.stopAt then return G.Stop() end
        if G.replayAt and now() >= G.replayAt then G.replayAt = nil; Referee.AutoShot() end
        if hud.noteAt and now() - hud.noteAt > 6 then hud.note:SetText(""); G.notes = {}; hud.noteAt = nil end
        local st = golf("state") or ""
        local aiming = st:match("aiming=1") ~= nil
        local power = tonumber(st:match("power=(%d+)")) or 0
        local angle = tonumber(st:match("angle=(%d+)"))
        local charging = st:match("charging=1") ~= nil
        if aiming and angle then G.lastAngle = angle end
        local myTurn = G.turn and G.turn.name == me() and not G.rolling
        if aiming then
            hud.meter:Show(); hud.keys:Show(); hud.resume:Hide()
            local p = power / 1000
            hud.meter.fill:SetWidth(math.max(1, 312 * p))
            hud.meter.fill:SetVertexColor(0.3 + 0.7 * p, 1 - 0.7 * p * p, 0.25)
            hud.meter.text:SetText(charging and (math.floor(p * 100 + 0.5) .. "%") or "Hold Space")
        else
            hud.meter:Hide(); hud.keys:Hide()
            if myTurn and not G.shotSent then hud.resume:Show() else hud.resume:Hide() end
        end
        if not aiming and aimFrame:IsShown() and now() - (G.aimArmed or 0) > 1 then showAimCapture(false) end
    end)

    -- While aiming, this frame takes the keyboard so A/D/W/S/Space aim instead of walking.
    -- Esc gives it back (look around, chat); "Back to the ball" takes it again.
    aimFrame = CreateFrame("Frame", "LeylineGolfAim", UIParent)
    aimFrame:SetAllPoints(UIParent)
    aimFrame:EnableKeyboard(true)
    aimFrame:EnableMouse(false)
    aimFrame:SetScript("OnKeyDown", function(_, key)
        if key == "ESCAPE" then
            golf("noaim")
            showAimCapture(false)
        elseif key == "ENTER" then
            golf("noaim")
            showAimCapture(false)
            if ChatFrame_OpenChat then pcall(ChatFrame_OpenChat, "") end
        end
    end)
    aimFrame:Hide()
    hud:Hide()
end

local function showResults(text)
    if not results then
        results = CreateFrame("Frame", "LeylineGolfResults", UIParent)
        results:SetWidth(360); results:SetHeight(240)
        results:SetPoint("CENTER", 0, 60)
        results:SetFrameStrata("DIALOG")
        if not W.Style then   -- Style.lua draws the window (S.Window, at its title)
            results:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
            edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
            insets = { left = 11, right = 12, top = 12, bottom = 11 } })
        end
        results:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
        do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
            local bg = results:CreateTexture(nil, "BACKGROUND")
            bg:SetTexture(0.094, 0.106, 0.137, 0.97)   -- #181b23 (Style.lua)
            bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
        end
        results.title = W.Style and W.Style.Window(results, "") or label(results, "", "GameFontNormalLarge", "TOP", 0, -20)
        results.body = label(results, "", "GameFontHighlight", "TOPLEFT", 26, -52)
        results.body:SetWidth(310)
        button(results, "Close", 90, function() results:Hide() end, "BOTTOM", 0, 16)
    end
    local rows = {}
    for name, t in text:gmatch("([^=;]+)=(%d+)") do rows[#rows + 1] = { name = name, t = tonumber(t) } end
    table.sort(rows, function(a, b) return a.t < b.t end)
    local lines = {}
    for i, r in ipairs(rows) do
        local d = r.t - (G.coursePar or 0)
        lines[#lines + 1] = string.format("%d.  %s   %d  (%s%d)", i, colorName(r.name), r.t, d > 0 and "+" or "", d)
    end
    results.title:SetText(G.title .. ": final")
    results.body:SetText(table.concat(lines, "\n"))
    results:Show()
    sound("LEVELUPSOUND")
end

-- ---------------------------------------------------------------- the messages (realm or practice)

local function tidy(s) return (tostring(s or ""):gsub("|", "")) end

dispatch = function(name, data)
    if name == "courses" then
        G.courses = {}
        for item in data:gmatch("[^;]+") do
            local key, title, holes, par, author = item:match("^([%w_]+),([^,]+),(%d+),(%d+),?(.*)$")
            if key then
                G.courses[#G.courses + 1] = { key = key, title = tidy(title), holes = tonumber(holes), par = tonumber(par),
                    author = tidy(author ~= "" and author or "Leyline") }
            end
        end
        G.waiting = nil
        G.Refresh()
        status(#G.courses > 0 and "Pick a course and Play here, or Practice on your own." or "No courses on this realm.")
    elseif name == "open" then   -- the realm's Play (ov_playmode.lua): show the window
        if not win or not win:IsShown() then G.Toggle() end
    elseif name == "invite" then
        local id, host, title = data:match("^(%d+) (%S+) (%S+)")
        if id then
            G.invite = { id = tonumber(id), host = tidy(host), title = tidy(title):gsub("_", " ") }
            sound("igPlayerInvite")
            G.Refresh()
            if not win or not win:IsShown() then G.Toggle() end
        end
    elseif name == "lobby" then
        local id, host, title, names = data:match("^(%d+) (%S+) (%S+) ?(.*)$")
        if id then
            G.lobby = { id = tonumber(id), host = tidy(host), title = tidy(title):gsub("_", " "), names = {} }
            for n in (names or ""):gmatch("[^,]+") do G.lobby.names[#G.lobby.names + 1] = tidy(n) end
            G.invite = nil
            G.Refresh()
        end
    elseif name == "session" then
        local id, x, y, z, o, title = data:match("^(%d+) (%S+) (%S+) (%S+) (%S+) (%S+)")
        if id then G.session = { id = tonumber(id), x = x, y = y, z = z, o = o }; G.title = tidy(title):gsub("_", " ") end
    elseif name == "course" then
        G.Begin(data, G.session and string.format("%s %s %s %s", G.session.x, G.session.y, G.session.z, G.session.o) or "here")
    elseif name == "hole" then
        local n, par, hname = data:match("^(%d+) (%d+) ?(.*)$")
        if n then
            G.hole, G.par, G.holeName = tonumber(n), tonumber(par), tidy(hname)
            G.turn, G.rolling = nil, nil
            golf("hole " .. G.hole)
            setBanner(); refreshScore()
            noteLine(string.format("Hole %d: %s, par %d", G.hole, G.holeName, G.par))
            sound("QUESTADDED")
        end
    elseif name == "turn" then
        local who, stroke, x, y, z, color, phase = data:match("^(%S+) (%d+) (%S+) (%S+) (%S+) (%d+) (%-?%d+)")
        if who then
            who = tidy(who)
            G.players[who] = G.players[who] or { color = tonumber(color) }
            G.players[who].color = tonumber(color)
            if G.turn and G.turn.name ~= who then golf("hide " .. G.turn.name) end
            G.turn = { name = who, stroke = tonumber(stroke) }
            G.rolling, G.shotSent = nil, nil
            golf("phase " .. phase)
            golf(string.format("ball %s %d %s %s %s", who, tonumber(color), x, y, z))
            if who == me() and not (Referee.R and Referee.R.replay and G.practice) then
                golf("aim " .. who)
                showAimCapture(true)
                if tonumber(stroke) == 1 then sound("RaidWarning") end
            end
            setTurnText()
        end
    elseif name == "shot" then
        local who, x, y, z, a, p, phase, stroke, shotNo = data:match("^(%S+) (%S+) (%S+) (%S+) (%d+) (%d+) (%-?%d+) (%d+) (%d+)")
        if who then
            G.rolling, G.shotNo = true, tonumber(shotNo)
            if who == me() then showAimCapture(false) end
            golf(string.format("shot %s %s %s %s %s %s %s", tidy(who), x, y, z, a, p, phase))
            sound("igMainMenuOptionCheckBoxOn")
        end
    elseif name == "score" then
        G.score = {}
        G.order = {}
        for who, list in data:gmatch("([^=;]+)=([^;]*)") do
            who = tidy(who)
            G.order[#G.order + 1] = who
            local s = {}
            for v in list:gmatch("[^,]+") do s[#s + 1] = v end
            G.score[who] = s
            G.players[who] = G.players[who] or { color = #G.order - 1 }
        end
        refreshScore()
    elseif name == "msg" then
        noteLine(tidy(data))
        if data:find("hole in one") then sound("AuctionWindowOpen") end
    elseif name == "top" then
        local key, rows = data:match("^([%w_]*)\t(.*)$")
        if key then
            G.top = { key = key, rows = {} }
            for id, n, st, v, pl in (rows or ""):gmatch("(%d+),([^,;]+),(%d+),(%d),(%d+)") do
                G.top.rows[#G.top.rows + 1] = { id = tonumber(id), name = tidy(n), strokes = tonumber(st), verified = v == "1", players = tonumber(pl) }
            end
            G.view = "top"
            G.Refresh()
            status(#G.top.rows > 0 and "Click a round to watch it (and check it)." or "No rounds on record for this course yet.")
        end
    elseif name == "live" then
        G.live = {}
        for id, host, title, hole, n in data:gmatch("(%d+),([^,;]+),([^,;]+),(%d+),(%d+)") do
            G.live[#G.live + 1] = { id = tonumber(id), host = tidy(host), title = tidy(title), hole = tonumber(hole), players = tonumber(n) }
        end
        G.view = "live"
        G.Refresh()
        status(#G.live > 0 and "Click a round to watch it." or "No rounds being played near you.")
    elseif name == "watching" then
        G.watching = true
        noteLine("Watching. /golf leave stops.")
    elseif name == "replay" then
        local head, inputs, text = data:match("^([^\n]*)\n([^\n]*)\n(.*)$")
        local id, who, claimed = (head or ""):match("^(%d+) (%S+) (%d+)")
        if id then
            local holes, h = {}, 0
            for part in (inputs .. "|"):gmatch("([^|]*)|") do
                h = h + 1
                holes[h] = {}
                for shot in part:gmatch("[^;]+") do holes[h][#holes[h] + 1] = shot end
            end
            G.Replay(text, { id = tonumber(id), who = tidy(who), claimed = tonumber(claimed), holes = holes })
        end
    elseif name == "published" then
        status("Published as " .. tidy(data) .. ".")
        G.Ask()
    elseif name == "done" then
        G.finished = true
        showResults(data)
    elseif name == "end" then
        -- After a finished round the last putt's celebration plays out first.
        if G.finished then G.StopSoon() else G.Stop() end
        if data ~= "" then status(tidy(data)) end
    end
end

-- The client's callbacks (golf.rs).
function G.OnShoot(angle, power)
    if not G.playing or not G.turn or G.turn.name ~= me() then return end
    G.shotSent = true
    toRealm("shot", string.format("%d %d", angle, power))
end

function G.OnRest(name, kind, x, y, z, hash)
    if not G.playing then return end
    G.rolling = nil
    if kind == "holed" and name == me() then sound("LEVELUPSOUND") end
    toRealm("rest", string.format("%d %s %.3f %.3f %.3f %s", G.shotNo or 0, kind, x, y, z, hash))
end

function G.OnError(text)
    noteLine("|cffff6060" .. tidy(text) .. "|r")
    status(tidy(text))
end

function G.OnMessage(prefix, msg, channel, sender)
    if prefix ~= PREFIX or type(msg) ~= "string" or channel ~= "WHISPER" then return end
    if UnitName and sender ~= UnitName("player") then return end
    local mod, name, i, n, data = msg:match("^([^\t]+)\t([^\t]+)\t(%d+)/(%d+)\t(.*)$")
    if mod ~= MOD or G.practice then return end
    i, n = tonumber(i), tonumber(n)
    if n < 1 or n > 32 or i < 1 or i > n then return end
    if n == 1 then G.parts[name] = nil; return dispatch(name, data) end
    local buf = G.parts[name]
    if i == 1 or not buf or buf.n ~= n then buf = { n = n, got = 0 }; G.parts[name] = buf end
    if not buf[i] then buf[i] = data; buf.got = buf.got + 1 end
    if buf.got == n then
        G.parts[name] = nil
        dispatch(name, table.concat(buf, "", 1, n))
    end
end

-- ---------------------------------------------------------------- starting and stopping

function G.Begin(text, where)
    if not has() then
        status("Minigolf needs the Leyline browser client (20261025i or newer).")
        return
    end
    if not hud then buildHud() end
    G.playing, G.hole, G.turn, G.rolling = true, 0, nil, nil
    G.holeCount, G.coursePar = 0, 0
    for par in text:gmatch("\nhole%s+(%d)") do G.holeCount = G.holeCount + 1; G.coursePar = G.coursePar + tonumber(par) end
    local t = text:match("\ncourse%s+([^\n]+)") or text:match("^course%s+([^\n]+)")
    if t and G.title == "" then G.title = tidy(t) end
    golf("load " .. (G.where or where) .. "\n" .. text)
    if win then win:Hide() end
    hud:Show()
    setBanner()
end

function G.StopSoon() G.stopAt = now() + 3 end

function G.Stop()
    G.stopAt, G.finished, G.watching = nil, nil, nil
    golf("end")
    G.playing, G.practice, G.turn, G.rolling, G.session, G.lobby = false, false, nil, nil, nil, nil
    G.title, G.score, G.order, G.players = "", {}, {}, {}
    if hud then hud:Hide() end
    showAimCapture(false)
    G.Refresh()
end

function G.Leave()
    if G.practice then G.Stop() return end
    send("leave", "")
    G.Stop()
end

function G.Practice(text, hole, where)
    if not has() then status("Minigolf needs the Leyline browser client (20261025i or newer)."); return end
    G.Stop()
    G.practice = true
    G.where = where
    Referee.Start(text or PRACTICE_COURSE, hole)
end

function G.Replay(text, replay)
    if not has() then status("Replays need the Leyline browser client (20261025i or newer)."); return end
    G.Stop()
    G.practice = true
    noteLine("Watching " .. replay.who .. "'s round (" .. replay.claimed .. " strokes)")
    Referee.Start(text, nil, replay)
end

function G.AskTop(key)
    if not key then status("Pick a course first."); return end
    send("top", key)
    status("Asking for the best rounds...")
end

function G.Watch(id) send("replay", tostring(id)); status("Fetching the round...") end

function G.PlayHere(key)
    G.practice = false
    send("start", key or "")
    status("Opening a game...")
end

-- ---------------------------------------------------------------- the practice referee
-- The realm's rules (ov_golf.lua) for one player, answering through the same messages.

Referee = {}

local function capFor(par) return math.min(par + 4, 9) end

-- replay = { id, who, claimed, holes = { { "a,p,ph", ... }, ... } }: play a recorded round shot for shot.
function Referee.Start(text, startHole, replay)
    local R = { holes = {}, hole = 1, strokes = {}, shotNo = 0, t0 = now(), only = startHole, replay = replay,
        who = replay and replay.who or me() }
    for raw in (text .. "\n"):gmatch("([^\n]*)\n") do
        local line = raw:gsub("#.*$", "")
        local word, rest = line:match("^%s*(%S+)%s*(.-)%s*$")
        if word == "hole" then
            local par, hname = rest:match("^(%d)%s*(.*)$")
            R.holes[#R.holes + 1] = { par = tonumber(par), name = hname ~= "" and hname or ("Hole " .. (#R.holes + 1)) }
        elseif word == "tee" and R.holes[#R.holes] then
            local x, y, z = rest:match("^(%S+)%s+(%S+)%s+(%S+)")
            R.holes[#R.holes].tee = { tonumber(x), tonumber(y), tonumber(z) }
        elseif word == "course" then
            R.title = rest
        end
    end
    Referee.R = R
    G.title = R.title or "Practice"
    dispatch("course", text)
    if startHole and R.holes[startHole] then R.hole = startHole end
    Referee.StartHole()
end

local function phase() return math.floor((now() - Referee.R.t0) * 120) end
local function who() return Referee.R and Referee.R.who or me() end

function Referee.Score()
    local R = Referee.R
    local cells = {}
    for h = 1, #R.holes do cells[#cells + 1] = R.strokes[h] and tostring(R.strokes[h]) or "-" end
    dispatch("score", who() .. "=" .. table.concat(cells, ","))
end

function Referee.StartHole()
    local R = Referee.R
    local h = R.holes[R.hole]
    R.ball = { h.tee[1], h.tee[2] + 0.11, h.tee[3] }
    R.done = false
    R.next = 1
    dispatch("hole", string.format("%d %d %s", R.hole, h.par, h.name))
    Referee.Score()
    Referee.Turn()
end

function Referee.Turn()
    local R = Referee.R
    R.phase = "aim"
    dispatch("turn", string.format("%s %d %.3f %.3f %.3f 0 %d", who(), (R.strokes[R.hole] or 0) + 1, R.ball[1], R.ball[2], R.ball[3], phase()))
    if R.replay then G.replayAt = now() + 1.4 end
end

-- The next logged shot of a replay, with its original phase (spinners stand where they stood).
function Referee.AutoShot()
    local R = Referee.R
    if not R or not R.replay or R.phase ~= "aim" then return end
    local shot = (R.replay.holes[R.hole] or {})[R.next]
    if not shot then
        R.mismatch = true
        dispatch("msg", "|cffff6060The record has no more shots for this hole: it doesn't match the score.|r")
        R.done = true
        R.phase = "between"
        return Referee.NextHole()
    end
    R.next = R.next + 1
    local a, p, ph = shot:match("^(%d+),(%d+),(%-?%d+)$")
    R.phase, R.shotNo = "rolling", R.shotNo + 1
    dispatch("shot", string.format("%s %.3f %.3f %.3f %s %s %s %d %d", who(), R.ball[1], R.ball[2], R.ball[3], a or 0, p or 0, ph or 0,
        (R.strokes[R.hole] or 0) + 1, R.shotNo))
end

function Referee.Receive(name, data)
    local R = Referee.R
    if not R then return end
    if name == "shot" and R.phase == "aim" and not R.replay then
        local a, p = data:match("^(%d+) (%d+)$")
        if not a then return end
        R.phase, R.shotNo = "rolling", R.shotNo + 1
        dispatch("shot", string.format("%s %.3f %.3f %.3f %s %s %d %d %d", who(), R.ball[1], R.ball[2], R.ball[3], a, p, phase(),
            (R.strokes[R.hole] or 0) + 1, R.shotNo))
    elseif name == "rest" and R.phase == "rolling" then
        local n, kind, x, y, z = data:match("^(%d+) (%a+) (%S+) (%S+) (%S+)")
        if tonumber(n) ~= R.shotNo then return end
        local par = R.holes[R.hole].par
        local s = (R.strokes[R.hole] or 0) + 1
        if kind == "out" or kind == "water" then
            s = s + 1
            dispatch("msg", kind == "water" and "Splash! +1" or "Off the course: +1")
        else
            R.ball = { tonumber(x), tonumber(y), tonumber(z) }
        end
        R.strokes[R.hole] = s
        if kind == "holed" then
            R.done = true
            local words = { [-3] = "an albatross", [-2] = "an eagle", [-1] = "a birdie", [0] = "par", [1] = "a bogey", [2] = "a double bogey" }
            dispatch("msg", "Holed out with " .. (s == 1 and "a hole in one!" or (words[s - par] or (s .. " strokes"))))
        elseif s >= capFor(par) then
            R.done = true
            R.strokes[R.hole] = capFor(par)
            dispatch("msg", "Picked up at " .. capFor(par))
        end
        Referee.Score()
        R.phase = "between"
        if R.done and R.replay and R.replay.holes[R.hole] and R.next <= #R.replay.holes[R.hole] then
            R.mismatch = true
            dispatch("msg", "|cffff6060The record has shots left on a finished hole: it doesn't match.|r")
        end
        if not R.done then return Referee.Turn() end
        return Referee.NextHole()
    end
end

function Referee.NextHole()
    local R = Referee.R
    do
        -- Testing one hole from the editor: straight back to the editor.
        if R.only then return G.StopSoon() end
        if R.hole < #R.holes then
            R.hole = R.hole + 1
            return Referee.StartHole()
        end
        local total = 0
        for _, v in pairs(R.strokes) do total = total + v end
        if R.replay then
            local ok = not R.mismatch and total == R.replay.claimed
            dispatch("msg", ok and string.format("|cff8fe36bReplay checks out: %d strokes, as recorded.|r", total)
                or string.format("|cffff6060This replay gives %d strokes; the record says %d. It doesn't check out.|r", total, R.replay.claimed))
            G.replayResult = ok
            return G.StopSoon()
        end
        dispatch("done", me() .. "=" .. total)
        if WrathUnleashedUIDB then
            WrathUnleashedUIDB.golfBest = WrathUnleashedUIDB.golfBest or {}
            local key = R.title or "course"
            local pb = WrathUnleashedUIDB.golfBest[key]
            if not pb or total < pb then
                WrathUnleashedUIDB.golfBest[key] = total
                if pb then dispatch("msg", "A new practice best: " .. total .. " (was " .. pb .. ")") end
            end
        end
        G.StopSoon()
    end
end


-- ---------------------------------------------------------------- the course editor

local E = { grids = { 0.25, 0.5, 1, 0.1, 0 }, grid = 1 }
G.Editor = E
local bar

local function estate()
    local st = golf("editorstate") or ""
    local t = {}
    for k, v in st:gmatch("(%a+)=([^ ]*)") do t[k] = v end
    t.name, t.msg = st:match("name=([^|]*)|(.*)$")
    return t
end

local PIECES = {
    { "select", "Select" }, { "turf", "Turf" }, { "sand", "Sand" }, { "ice", "Ice" }, { "wall", "Wall" },
    { "bump", "Bumper" }, { "water", "Water" }, { "boost", "Boost" }, { "spin", "Spinner" }, { "slide", "Slider" },
    { "tee", "Tee" }, { "cup", "Cup" },
}
local EXTRA = { boost = { "speed", "Speed (yd/s)" }, spin = { "spin", "Turn (deg/s)" }, slide = { "seconds", "Cycle (s)" } }

local function buildBar()
    bar = CreateFrame("Frame", "LeylineGolfEditor", UIParent)
    bar:SetWidth(780); bar:SetHeight(118)
    bar:SetPoint("BOTTOM", 0, 14)
    bar:SetFrameStrata("HIGH")
    bar:EnableMouse(true)
    if W.Style then W.Style.Backdrop(bar, W.Style.C.bg2) else bar:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background", edgeFile = "Interface\\Tooltips\\UI-Tooltip-Border",
        tile = true, tileSize = 16, edgeSize = 14, insets = { left = 4, right = 4, top = 4, bottom = 4 } }) end
    bar:SetBackdropColor(0.04, 0.06, 0.04, 0.88)
    bar:SetBackdropBorderColor(0.55, 0.85, 0.4, 0.9)
    bar.tools = {}
    for i, p in ipairs(PIECES) do
        local b = button(bar, p[2], 62, function() golf("editor tool " .. p[1]) end, "TOPLEFT", 8 + (i - 1) * 64, -8)
        b.key = p[1]
        bar.tools[#bar.tools + 1] = b
    end
    bar.prev = button(bar, "<", 24, function() E.Hole(-1) end, "TOPLEFT", 8, -34)
    bar.hole = label(bar, "Hole 1/1", "GameFontNormalSmall", "TOPLEFT", 36, -40)
    bar.next = button(bar, ">", 24, function() E.Hole(1) end, "TOPLEFT", 96, -34)
    button(bar, "+ Hole", 60, function() golf("editor addhole") end, "TOPLEFT", 124, -34)
    button(bar, "- Hole", 60, function() golf("editor delhole") end, "TOPLEFT", 186, -34)
    bar.parDown = button(bar, "Par -", 48, function() E.Par(-1) end, "TOPLEFT", 252, -34)
    bar.par = label(bar, "Par 2", "GameFontNormalSmall", "TOPLEFT", 304, -40)
    bar.parUp = button(bar, "Par +", 48, function() E.Par(1) end, "TOPLEFT", 346, -34)
    bar.gridBtn = button(bar, "Grid 0.25", 74, function()
        E.grid = E.grid % #E.grids + 1
        golf("editor grid " .. E.grids[E.grid])
    end, "TOPLEFT", 400, -34)
    button(bar, "Undo", 50, function() golf("editor undo") end, "TOPLEFT", 478, -34)
    button(bar, "Redo", 50, function() golf("editor redo") end, "TOPLEFT", 530, -34)
    button(bar, "Copy", 50, function() golf("editor dup") end, "TOPLEFT", 582, -34)
    button(bar, "Delete", 56, function() golf("editor delete") end, "TOPLEFT", 634, -34)
    button(bar, "Done", 72, function() E.Stop() end, "TOPLEFT", 696, -34)

    label(bar, "Course", "GameFontNormalSmall", "TOPLEFT", 10, -66)
    bar.title = CreateFrame("EditBox", nil, bar, "InputBoxTemplate")
    bar.title:SetWidth(150); bar.title:SetHeight(20); bar.title:SetPoint("TOPLEFT", 60, -62)
    bar.title:SetAutoFocus(false); bar.title:SetMaxLetters(48)
    bar.title:SetScript("OnEnterPressed", function(self) golf("editor title " .. (self:GetText() or "")); self:ClearFocus() end)
    bar.title:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    label(bar, "Hole name", "GameFontNormalSmall", "TOPLEFT", 222, -66)
    bar.name = CreateFrame("EditBox", nil, bar, "InputBoxTemplate")
    bar.name:SetWidth(140); bar.name:SetHeight(20); bar.name:SetPoint("TOPLEFT", 290, -62)
    bar.name:SetAutoFocus(false); bar.name:SetMaxLetters(40)
    bar.name:SetScript("OnEnterPressed", function(self) golf("editor name " .. (self:GetText() or "")); self:ClearFocus() end)
    bar.name:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    bar.extraLabel = label(bar, "", "GameFontNormalSmall", "TOPLEFT", 442, -66)
    bar.extra = CreateFrame("EditBox", nil, bar, "InputBoxTemplate")
    bar.extra:SetWidth(50); bar.extra:SetHeight(20); bar.extra:SetPoint("TOPLEFT", 530, -62)
    bar.extra:SetAutoFocus(false); bar.extra:SetMaxLetters(6)
    bar.extra:SetScript("OnEnterPressed", function(self)
        if bar.field then golf("editor set " .. bar.field .. " " .. (tonumber(self:GetText() or "") or 0)) end
        self:ClearFocus()
    end)
    bar.extra:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    button(bar, "Test hole", 80, function() E.Test() end, "TOPLEFT", 592, -60)
    button(bar, "Save", 46, function() E.Save() end, "TOPLEFT", 674, -60)
    button(bar, "Publish", 60, function() E.Publish() end, "TOPLEFT", 720, -60)
    bar.info = label(bar, "", "GameFontHighlightSmall", "TOPLEFT", 10, -90)
    bar.info:SetWidth(760)
    bar.keys = label(bar, "|cffffd100Click|r place / select  |cffffd100G|r carry  |cffffd100Q E|r turn  |cffffd100Z X|r tilt  |cffffd100arrows|r size  "
        .. "|cffffd100[ ]|r height  |cffffd100wheel|r raise  |cffffd100V|r copy  |cffffd100Del|r remove  |cffffd100Ctrl+Z / Y|r undo, redo  "
        .. "|cffffd100WASD Space C|r fly", "GameFontHighlightSmall", "TOPLEFT", 10, -104)
    bar.keys:SetWidth(760)
    bar:SetScript("OnUpdate", function()
        local t = estate()
        if t.on ~= "1" then return end
        bar.hole:SetText(string.format("Hole %s/%s", t.hole or "?", t.holes or "?"))
        bar.par:SetText("Par " .. (t.par or "?"))
        bar.gridBtn:SetText(t.grid == "0" and "Grid off" or ("Grid " .. (t.grid or "")))
        for _, b in ipairs(bar.tools) do
            if b.key == t.tool then b:LockHighlight() else b:UnlockHighlight() end
        end
        local sel = t.sel or "-"
        local kind, sx, sy, sz, yaw, pitch, a, b2, secs = sel:match("^(%a+):([^:]*):([^:]*):([^:]*):([^:]*):([^:]*):([^:]*):([^:]*):([^:]*)$")
        local line = kind and string.format("%s  %s x %s x %s yd  turn %s  tilt %s", kind, sx, sy, sz, yaw, pitch) or "Nothing selected"
        bar.info:SetText(line .. "   |cff8fe36b" .. tidy(t.msg or "") .. "|r")
        local ex = kind and EXTRA[kind]
        if ex then
            bar.field = ex[1]
            bar.extraLabel:SetText(ex[2]); bar.extraLabel:Show(); bar.extra:Show()
            if not bar.extra:HasFocus() then bar.extra:SetText(kind == "slide" and secs or a) end
        else
            bar.field = nil
            bar.extraLabel:Hide(); bar.extra:Hide()
        end
        if not bar.name:HasFocus() then bar.name:SetText(t.name or "") end
    end)
    bar:Hide()
end

function E.Hole(d)
    local t = estate()
    local n = (tonumber(t.hole) or 1) + d
    golf("editor hole " .. n)
end

function E.Par(d)
    local t = estate()
    golf("editor par " .. math.max(1, math.min(9, (tonumber(t.par) or 2) + d)))
end

function E.Start(text, title)
    if not E.Available() then status("The course editor needs the Leyline browser client (20261025j or newer)."); return end
    if G.playing then G.Stop() end
    if win then win:Hide() end
    if not bar then buildBar() end
    golf("editor on here\n" .. (text or ""))
    golf("editor author " .. me())
    if title then golf("editor title " .. title) end
    bar.title:SetText(title or (text and text:match("course%s+([^\n]+)")) or "My Course")
    bar:Show()
end

-- Back from a test round: the same course, same spot, same hole.
function E.Resume(saved)
    if not bar then buildBar() end
    golf("editor on keep\n" .. saved.text)
    golf("editor hole " .. saved.hole)
    golf("editor author " .. me())
    bar:Show()
end

function E.Stop()
    golf("editor off")
    if bar then bar:Hide() end
end

function E.Text() return golf("editortext") or "" end

-- The editor arrived with client 20261025j; an older client answers "ok" (and ignores the command).
function E.Available() return has() and (golf("editorstate") or ""):match("^on=") ~= nil end

function E.Test()
    local t = estate()
    local text = E.Text()
    if bar then bar:Hide() end
    golf("editor off")
    G.Practice(text, G.testing.hole, "keep")
    -- Practice cleared G.testing via Stop(); set it again for the way back.
    G.testing = { text = text, hole = tonumber(t.hole) or 1 }
end

function E.Save()
    local text = E.Text()
    local title = text:match("^course%s+([^\n]+)") or "My Course"
    WrathUnleashedUIDB = WrathUnleashedUIDB or {}
    WrathUnleashedUIDB.golfCourses = WrathUnleashedUIDB.golfCourses or {}
    WrathUnleashedUIDB.golfCourses[title] = text
    noteLine("Saved \"" .. tidy(title) .. "\" (your courses are in /golf).")
    if bar then bar.info:SetText("Saved " .. tidy(title)) end
end

function E.Publish()
    E.Save()
    local text = E.Text()
    if not sendLong("publish", text) then
        noteLine("|cffff6060This course is too big to publish in one go (about 12 KB at most).|r")
        return
    end
    noteLine("Publishing...")
end

function E.MyCourses()
    local list = {}
    for title, text in pairs((WrathUnleashedUIDB and WrathUnleashedUIDB.golfCourses) or {}) do
        list[#list + 1] = { title = title, text = text }
    end
    table.sort(list, function(a, b) return a.title < b.title end)
    return list
end

-- ---------------------------------------------------------------- the window

function G.Refresh()
    if not win then return end
    if G.view == "live" and G.live then
        win.listTitle:SetText("Live rounds near you")
        win.back:Show()
        for i, row in ipairs(win.rows) do
            local r = G.live[i]
            row.course, row.round, row.live = nil, nil, r
            if r then
                row.text:SetText(string.format("%s's %s  |cffa0a0a0hole %d, %d playing|r", r.host, r.title, r.hole, r.players))
                row:Show()
            else
                row:Hide()
            end
        end
        return G.RefreshLobby()
    end
    if G.view == "top" and G.top then
        win.listTitle:SetText("Best rounds: " .. (G.top.key or ""))
        win.back:Show()
        for i, row in ipairs(win.rows) do
            local r = G.top.rows[i]
            row.course, row.round, row.live = nil, r, nil
            if r then
                row.text:SetText(string.format("%d.  %s   %d strokes   %s", i, r.name, r.strokes,
                    r.verified and "|cff8fe36bverified|r" or ("|cffa0a0a0" .. (r.players > 1 and "unverified" or "solo") .. "|r")))
                row:Show()
            else
                row:Hide()
            end
        end
        return G.RefreshLobby()
    end
    win.listTitle:SetText("Courses on this realm")
    win.back:Hide()
    for i, row in ipairs(win.rows) do
        local c = G.courses[i]
        row.course, row.round, row.live = c, nil, nil
        if c then
            row.text:SetText(string.format("%s%s  |cffa0a0a0by %s, %d holes, par %d|r", c.key == G.pick and "|cff40ff40> |r" or "", c.title,
                c.author or "Leyline", c.holes, c.par))
            row:Show()
        else
            row:Hide()
        end
    end
    return G.RefreshLobby()
end

function G.RefreshLobby()
    local l = G.lobby
    if G.invite then
        win.lobby:SetText(string.format("|cffffd100%s|r invites you to %s.", G.invite.host, G.invite.title))
        win.join:Show(); win.go:Hide()
    elseif l then
        win.lobby:SetText(string.format("Lobby: %s  (host %s)\nPlayers: %s", l.title, l.host, table.concat(l.names, ", ")))
        win.join:Hide()
        if l.host == me() then win.go:Show() else win.go:Hide() end
    else
        win.lobby:SetText("")
        win.join:Hide(); win.go:Hide()
    end
    if not has() then
        win.play:Disable(); win.practice:Disable(); win.editor:Disable()
        status("Minigolf needs the Leyline browser client (20261025i or newer).")
    else
        win.play:Enable(); win.practice:Enable()
        if E.Available() then win.editor:Enable() else win.editor:Disable() end
    end
end

local function build()
    win = CreateFrame("Frame", "LeylineGolfFrame", UIParent)
    win:SetWidth(WIN_W); win:SetHeight(WIN_H)
    win:SetPoint("CENTER")
    win:SetFrameStrata("DIALOG")
    win:EnableMouse(true)
    win:SetMovable(true)
    win:RegisterForDrag("LeftButton")
    win:SetScript("OnDragStart", win.StartMoving)
    win:SetScript("OnDragStop", win.StopMovingOrSizing)
    if not W.Style then   -- Style.lua draws the window (S.Window, at its title)
        win:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    end
    win:SetBackdropColor(0.05, 0.06, 0.08, 0.95)   -- solid: the dialog texture draws see-through in the browser client
    do   -- a colour fill the engine draws itself (no texture file; the backdrop fill needs one)
        local bg = win:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.094, 0.106, 0.137, 0.97)   -- #181b23 (Style.lua)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    local _ = (W.Style and W.Style.Window(win, "Minigolf") or label(win, "Minigolf", "GameFontNormalLarge", "TOP", 0, -18))
    local close = (W.Style and W.Style.Close(win) or CreateFrame("Button", nil, win, "UIPanelCloseButton"))
    close:SetPoint("TOPRIGHT", -6, -6)
    tinsert(UISpecialFrames, "LeylineGolfFrame")
    win.listTitle = label(win, "Courses on this realm", "GameFontNormal", "TOPLEFT", 22, -48)
    win.back = button(win, "Courses", 70, function() G.view = "courses"; G.Refresh() end, "TOPRIGHT", -40, -44)
    win.back:Hide()
    win.rows = {}
    for i = 1, 6 do
        local row = CreateFrame("Button", nil, win)
        row:SetWidth(WIN_W - 44); row:SetHeight(20)
        row:SetPoint("TOPLEFT", 22, -66 - (i - 1) * 21)
        row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        row.text = label(row, "", "GameFontHighlight", "LEFT", 4, 0)
        row:SetScript("OnClick", function(self)
            if self.live then send("watch", tostring(self.live.id)); status("Joining as a spectator..."); return end
            if self.round then return G.Watch(self.round.id) end
            if self.course then G.pick = self.course.key; G.Refresh() end
        end)
        win.rows[i] = row
    end
    win.play = button(win, "Play here", 110, function() G.PlayHere(G.pick) end, "TOPLEFT", 22, -200)
    win.practice = button(win, "Practice", 100, function() G.Practice() end, "TOPLEFT", 138, -200)
    win.refresh = button(win, "Best rounds", 90, function() G.AskTop(G.pick) end, "TOPLEFT", 242, -200)
    win.editor = button(win, "Course editor", 100, function()
        local mine = E.MyCourses()
        local pick = mine[G.myPick or 0]
        E.Start(pick and pick.text, pick and pick.title)
    end, "TOPLEFT", 336, -200)
    win.liveBtn = button(win, "Live rounds", 96, function() send("live", ""); status("Looking for rounds nearby...") end, "TOPLEFT", 226, -272)
    win.mine = button(win, "My courses: new", 112, function()
        local mine = E.MyCourses()
        G.myPick = ((G.myPick or 0) + 1) % (#mine + 1)
        local pick = mine[G.myPick]
        win.mine:SetText(pick and ("Mine: " .. pick.title):sub(1, 18) or "My courses: new")
    end, "TOPLEFT", 326, -272)
    win.lobby = label(win, "", "GameFontHighlight", "TOPLEFT", 22, -234)
    win.lobby:SetWidth(WIN_W - 44)
    win.join = button(win, "Join", 90, function() if G.invite then send("join", tostring(G.invite.id)) end end, "TOPLEFT", 22, -272)
    win.go = button(win, "Tee off", 110, function() send("go", "") end, "TOPLEFT", 22, -272)
    win.leave = button(win, "Leave", 80, function() G.Leave() end, "TOPLEFT", 140, -272)
    win.info = label(win, "Play here opens a game where you stand and invites your party; everyone sees the same course "
        .. "and every roll. Practice plays Meadow Nine on your own. The course editor builds your own (pick one of yours first "
        .. "to edit it).", "GameFontHighlightSmall", "BOTTOMLEFT", 22, 44)
    win.info:SetWidth(WIN_W - 44)
    win.status = label(win, G.status or "", "GameFontHighlightSmall", "BOTTOMLEFT", 22, 22)
    win.status:SetWidth(WIN_W - 44)
    win:SetScript("OnUpdate", function()
        if G.waiting and G.askedAt and now() - G.askedAt > ANSWER_WAIT then
            G.waiting = nil
            status("This realm doesn't run minigolf yet. Practice works anywhere.")
        end
    end)
    win:SetScript("OnShow", function()
        sound("igCharacterInfoOpen")
        if #G.courses == 0 then G.Ask() end
        G.Refresh()
    end)
    win:Hide()
end

function G.Ask()
    G.askedAt, G.waiting = now(), true
    status("Asking the realm for its courses...")
    send("courses", "")
end

function G.Toggle()
    if not win then build() end
    if win:IsShown() then win:Hide() else win:Show() end
end

local listener = CreateFrame("Frame")
listener:RegisterEvent("CHAT_MSG_ADDON")
listener:SetScript("OnEvent", function(_, _, prefix, msg, channel, sender) G.OnMessage(prefix, msg, channel, sender) end)

SLASH_LEYLINEGOLF1, SLASH_LEYLINEGOLF2 = "/golf", "/minigolf"
SlashCmdList["LEYLINEGOLF"] = function(arg)
    arg = tostring(arg or ""):lower()
    if arg == "practice" then return G.Practice() end
    if arg == "edit" or arg == "editor" then return E.Start() end
    if arg == "leave" or arg == "quit" then return G.Leave() end
    G.Toggle()
end
