-- ModeScript (3.3.5a API): the Leyline Modes script editor. /modes edit opens it (and "Mode editor" in /modes).
--
--   The script      a multi-line box with line numbers, a monospace face and keyword colours (Colours on/off).
--   The console     errors with their line (click one to go there), print output and notes. Errors come from the
--                   check before Play (ModeAPI.lua's API.Check, then Lua's own syntax check), from the sandbox while
--                   it runs (Modes.lua's M.console), and from the realm ("invalid" on Play Here and Publish).
--   Play            runs a copy of the script here, alone. Play Here hosts a copy on the realm where you stand and
--                   invites your party nearby (the realm checks it first: size, rate, blocked names). Stop ends
--                   either and brings the editor back with your text as you left it. Neither ever saves.
--   Save            keeps the script here and on your account (the realm's drafts, mod_mode_drafts). Saving while
--                   a test runs hot-reloads it: the new script replaces the old one in place (Modes.lua M.Reload).
--   Publish         saves, then sends it for GM review.
-- Creator code still runs only in Modes.lua's sandbox under its time guard; this file only edits text.

local W = WrathUnleashedUI
local M = W.Modes
local API = W.ModeAPI
if not M or not API then return end

local S = { playing = nil, colour = true, savedText = nil, title = nil, scroll = 0, startPick = 0, minePick = 0 }
M.ScriptEditor = S

local ed
local PLAY_HERE_GAP = 5      -- seconds between Play Here requests (the realm checks too)
local SAVE_GAP = 2.2         -- the realm takes one draft save each 2 s; a quicker save goes up a moment later
local MONO = "Interface\\AddOns\\WrathUnleashedUI\\Fonts\\DejaVuSansMono.ttf"

local function now() return (GetTime and GetTime()) or 0 end
local function tidy(s) return (tostring(s or ""):gsub("|", "")) end
local function send(name, data) if M.Send then return M.Send(name, data) end end

local function label(parent, text, font, ...)
    local fs = parent:CreateFontString(nil, "OVERLAY", font or "GameFontHighlightSmall")
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

local function info(text) S.info = text; if ed then ed.info:SetText(text or "") end end

-- ---------------------------------------------------------------- text helpers (pure; the tests use them)

local KEYWORDS = {}
for w in ("and break do else elseif end false for function if in local nil not or repeat return then true until while"):gmatch("%a+") do KEYWORDS[w] = true end
local APINAMES = { Random = true, print = true, _G = true }
for _, ns in ipairs(API.NAMESPACES) do APINAMES[ns.name] = true end
for _, cb in ipairs(API.CALLBACKS) do APINAMES[cb.name] = true end
APINAMES.Devices = true
S.KEYWORDS, S.APINAMES = KEYWORDS, APINAMES

local C = { kw = "ffc792ea", api = "ffffcb6b", str = "ffa5d6a7", com = "ff7f8c8d", num = "fff78c6c" }

-- The script with colour codes, for the layer drawn under the edit box. Only colour codes are added (and each
-- "|" doubled), so it lays out exactly like the plain text.
function S.Colorize(text)
    local out, i, n = {}, 1, #text
    local function put(col, s)
        s = s:gsub("|", "||")
        if col then out[#out + 1] = "|c" .. col .. s .. "|r" else out[#out + 1] = s end
    end
    local function longEnd(at)
        local eq = text:match("^%[(=*)%[", at)
        if not eq then return nil end
        local _, e = text:find("]" .. eq .. "]", at + #eq + 2, true)
        return e or n
    end
    while i <= n do
        local c = text:sub(i, i)
        if text:sub(i, i + 1) == "--" then
            local e = longEnd(i + 2) or ((text:find("\n", i, true) or (n + 1)) - 1)
            put(C.com, text:sub(i, e)); i = e + 1
        elseif c == "[" and text:match("^%[=*%[", i) then
            local e = longEnd(i); put(C.str, text:sub(i, e)); i = e + 1
        elseif c == '"' or c == "'" then
            local j = i + 1
            while j <= n do
                local d = text:sub(j, j)
                if d == "\\" then j = j + 2 elseif d == c or d == "\n" then break else j = j + 1 end
            end
            if j > n then j = n end
            if text:sub(j, j) == "\n" then j = j - 1 end
            put(C.str, text:sub(i, j)); i = j + 1
        elseif c:match("[%a_]") then
            local w = text:match("^[%a_][%w_]*", i)
            put(KEYWORDS[w] and C.kw or (APINAMES[w] and C.api) or nil, w); i = i + #w
        elseif c:match("%d") then
            local w = text:match("^[%w%.]+", i); put(C.num, w); i = i + #w
        else
            local w = text:match("^[^%w_\"'%[%-]+", i) or c
            put(nil, w); i = i + #w
        end
    end
    return table.concat(out)
end

-- Line numbers for the gutter. rowsOf(line) says how many screen rows a line wraps to (1 without a measure).
function S.Gutter(text, rowsOf)
    local out, n = {}, 0
    for line in ((text or "") .. "\n"):gmatch("([^\n]*)\n") do
        n = n + 1
        out[#out + 1] = tostring(n)
        for _ = 2, (rowsOf and rowsOf(line) or 1) do out[#out + 1] = "" end
    end
    return table.concat(out, "\n"), n
end

-- The character offset where a line starts (0-based, as EditBox:SetCursorPosition takes it), and its length.
function S.LineStart(text, line)
    local pos, n = 0, 1
    for l in ((text or "") .. "\n"):gmatch("([^\n]*)\n") do
        if n == line then return pos, #l end
        pos, n = pos + #l + 1, n + 1
    end
    return #(text or ""), 0
end

-- The check before a test: the creator API's rules (no blocked names), then Lua's own syntax check. Nothing runs.
-- Returns true, or false, line, message (also logged to the console).
function S.Check(text)
    local line, why = API.Check(text)
    if line then
        M.Log("error", why, line > 0 and line or nil)
        return false, line, why
    end
    local chunk, err = loadstring(text, "=mode")
    if not chunk then
        local l, rest = M.LineOf(err)
        M.Log("error", rest or err, l)
        return false, l, tidy(rest or err)
    end
    return true
end

local function titleOf(text) return tidy((text or ""):match('Mode%.Title%s*=%s*"([^"\n]+)"') or "My Mode"):sub(1, 40) end

-- ---------------------------------------------------------------- the editor's text

function S.Text() return ed and ed.box:GetText() or S.pending or "" end
function S.SetText(text)
    text = tostring(text or "")
    if ed then ed.box:SetText(text) else S.pending = text end
    S.Changed()
end

function S.Dirty() return S.savedText ~= S.Text() end

local function header()
    if not ed then return end
    local t = S.title and ("\"" .. S.title .. "\"") or "new script"
    ed.title:SetText("Mode editor  |cffa0a0a0" .. t .. (S.Dirty() and "  (not saved)" or "") .. "|r")
end

local mono
local function monoFont()
    if mono ~= nil then return mono or nil end
    mono = false
    if CreateFont then
        local f = CreateFont("LeylineModesMono")
        local ok = f and pcall(f.SetFont, f, MONO, 12, "")
        if ok and f.GetFont and f:GetFont() then mono = f end
    end
    return mono or nil
end

-- The gutter and the colour layer follow the text; they are redrawn a moment after typing stops.
function S.Changed()
    S.changedAt = now()
    S.redraw = true
    if ed then ed.count:SetText(#S.Text() .. " / " .. API.MAX_SCRIPT) end
    header()
end

local function redraw()
    if not ed then return end
    S.redraw = false
    local text = S.Text()
    local wrapW = (ed.box.GetWidth and ed.box:GetWidth()) or 0
    local meter = ed.meter
    local function rowsOf(line)
        if not meter or not meter.GetStringWidth or wrapW <= 0 or line == "" then return 1 end
        meter:SetText((line:gsub("|", "||")))
        local w = tonumber(meter:GetStringWidth()) or 0
        return math.max(1, math.ceil(w / wrapW - 0.001))
    end
    ed.gutter:SetText((S.Gutter(text, rowsOf)))
    if S.colour then
        ed.layer:SetText(S.Colorize(text))
        ed.layer:Show()
        ed.box:SetTextColor(1, 1, 1, 0)        -- the edit box keeps the caret and selection; the layer shows the text
    else
        ed.layer:SetText("")
        ed.layer:Hide()
        ed.box:SetTextColor(0.92, 0.92, 0.92, 1)
    end
    if ed.sf.UpdateScrollChildRect then ed.sf:UpdateScrollChildRect() end
end
S.Redraw = redraw

function S.SetColour(on)
    S.colour = on and true or false
    WrathUnleashedUIDB = WrathUnleashedUIDB or {}
    WrathUnleashedUIDB.modeColours = S.colour
    if ed then ed.colourBtn:SetText(S.colour and "Colours: on" or "Colours: off") end
    redraw()
end

function S.GotoLine(line)
    line = tonumber(line)
    if not line or not ed then return end
    local text = S.Text()
    local pos, len = S.LineStart(text, line)
    S.at = line
    ed.box:SetFocus()
    ed.box:SetCursorPosition(pos)
    if ed.box.HighlightText then ed.box:HighlightText(pos, pos + len) end
    local lh = 14
    if ed.sf.SetVerticalScroll then
        local maxScroll = (ed.sf.GetVerticalScrollRange and ed.sf:GetVerticalScrollRange()) or 0
        ed.sf:SetVerticalScroll(math.max(0, math.min(maxScroll, (line - 6) * lh)))
    end
    info("Line " .. line .. ".")
end

-- ---------------------------------------------------------------- the console

local ROWS = 6
function S.RefreshConsole()
    if not ed then return end
    local list = M.console
    local first = math.max(1, #list - ROWS + 1 - S.scroll)
    for i = 1, ROWS do
        local row, e = ed.rows[i], list[first + i - 1]
        row.entry = e
        if e then
            local head = e.kind == "error" and "|cffff6060" .. (e.line and ("Line " .. e.line) or "Error") .. "|r"
                or e.kind == "print" and "|cff9fd6ffprint|r" or "|cffa0a0a0note|r"
            row.text:SetText(head .. "  " .. e.text)
            row:Show()
        else
            row:Hide()
        end
    end
end

function S.Clear()
    for i = #M.console, 1, -1 do M.console[i] = nil end
    S.scroll = 0
    S.RefreshConsole()
end

-- The first error in the console that has a line (newest first).
function S.LastError()
    for i = #M.console, 1, -1 do
        local e = M.console[i]
        if e.kind == "error" then return e end
    end
end

M.onLog = function(e)
    S.scroll = 0
    S.RefreshConsole()
    if e.kind == "error" and e.line and ed and ed:IsShown() then info("Error on line " .. e.line .. ": " .. e.text) end
end

-- ---------------------------------------------------------------- Play, Play Here, Stop

local bar   -- the small bar while a test runs: Edit, Start (in a lobby), Stop

local function busy()
    return M.host ~= nil or (M.state ~= nil and M.state ~= "idle")
end

local function beginTest(kind)
    S.playing = kind
    M.onStop = function() S.Restore() end
    if ed then ed:Hide() end
    if bar then bar:Show() end
    S.RefreshBar()
end

function S.Play()
    if S.playing then S.Stop() end
    if busy() then info("Leave the game you're in first (/modes leave)."); return false end
    local text = S.Text()
    if not S.Check(text) then
        local e = S.LastError()
        info("It didn't start: " .. (e and ((e.line and ("line " .. e.line .. ": ") or "") .. e.text) or "the script has an error."))
        if e and e.line then S.GotoLine(e.line) end
        return false
    end
    S.playText = text
    -- M.Solo stops whatever ran before (and its onStop), so the test is marked as begun only once it runs.
    if not M.Solo(text, "here") then
        S.Show()
        local e = S.LastError()
        info("It didn't start: " .. tostring(M.status or ""))
        if e and e.line then S.GotoLine(e.line) end
        return false
    end
    beginTest("solo")
    M.Log("info", "Playing a copy of " .. titleOf(text) .. " here. Save to hot-reload it.")
    return true
end

function S.PlayHere()
    if S.playing then S.Stop() end
    if busy() then info("Leave the game you're in first (/modes leave)."); return false end
    if S.hereAt and now() - S.hereAt < PLAY_HERE_GAP then info("One moment before the next test."); return false end
    local text = S.Text()
    if not S.Check(text) then
        local e = S.LastError()
        info("It didn't start: " .. (e and e.text or "the script has an error."))
        if e and e.line then S.GotoLine(e.line) end
        return false
    end
    S.hereAt = now()
    S.playText = text
    if not send("test", text) then info("That script is too big to send."); return false end
    beginTest("here")
    M.Log("info", "Asked the realm to host a copy of " .. titleOf(text) .. " here; your party nearby is invited.")
    return true
end

function S.Stop()
    if not S.playing then return end
    if M.state ~= "idle" or M.host then M.Leave()
    else
        -- Play Here before the realm answered: leave the test it is opening, and drop its lobby when it comes.
        if S.playing == "here" then send("leave", ""); M.dropLobbyUntil = now() + 10 end
        S.Restore()
    end
end

-- Back from a test. The test ran a copy, so the editor's text and your saved draft are as you left them.
function S.Restore()
    S.playing, S.playText = nil, nil
    M.onStop = nil
    if bar then bar:Hide() end
    S.Show()
    info("Stopped. Your script is as you left it.")
end

M.OnInvalid = function(why, line)
    if S.playing == "here" and not M.host then
        S.playing, M.onStop = nil, nil
        if bar then bar:Hide() end
        M.state = "idle"
        S.Show()
    end
    if ed and ed:IsShown() then info("The realm refused it: " .. tidy(why)); if line then S.GotoLine(line) end end
end

-- ---------------------------------------------------------------- Save (hot reload), Publish, drafts

function S.Save()
    local text = S.Text()
    if #text < API.MIN_SCRIPT then info("Write a little more first."); return false end
    if #text > API.MAX_SCRIPT then M.Log("error", "The script is too big (" .. API.MAX_SCRIPT .. " bytes at most)."); return false end
    local title = titleOf(text)
    M.SaveMode(title, text)
    S.title, S.savedText = title, text
    S.remoteDue = title .. "\n" .. text
    S.flushSave()
    header()
    if S.playing and M.host then
        if not S.Check(text) then
            info("Saved. Not reloaded: the script has an error (see the console).")
            return true, false
        end
        local N, err = M.Reload(text)
        if N then info("Saved and reloaded.") else info("Saved. Not reloaded: " .. tidy(err)) end
        return true, N ~= nil
    end
    info("Saved \"" .. title .. "\" here and on your account.")
    return true
end

-- The draft goes to the realm now, or once the realm's 2 s gap has passed.
function S.flushSave()
    if not S.remoteDue then return end
    if S.sentAt and now() - S.sentAt < SAVE_GAP then return end
    send("dsave", S.remoteDue)
    S.remoteDue, S.sentAt = nil, now()
end

function S.Publish()
    local text = S.Text()
    local ok = S.Check(text)
    if not ok then info("Fix the error first (see the console)."); return false end
    S.Save()
    M.Publish(text)
    info("Sent for review. A GM approves new modes before others see them.")
    return true
end

function S.StartFrom()
    local list = { { "Template", M.TEMPLATE }, { "Bumper Balls", M.BUILTIN }, { "Coin Dash", M.COINDASH } }
    for _, ex in ipairs(W.ModeExamples or {}) do list[#list + 1] = { ex.title, ex.text } end
    S.startPick = S.startPick % #list + 1
    local pick = list[S.startPick]
    S.SetText(pick[2])
    S.title, S.savedText = nil, nil
    header()
    if ed then ed.startBtn:SetText(("Start from: " .. pick[1]):sub(1, 30)) end
    info("Opened " .. pick[1] .. ". Save keeps your own copy.")
end

-- Your scripts: the ones saved here, and the ones on your account (asked for when the editor opens).
function S.Mine()
    local list, seen = {}, {}
    for _, m in ipairs(M.MyModes()) do
        if not m.text:find("Devices.Run", 1, true) then list[#list + 1] = m; seen[m.title] = true end
    end
    for _, t in ipairs((M.DevEditor and M.DevEditor.remote) or {}) do if not seen[t] then list[#list + 1] = { title = t } end end
    return list
end

function S.OpenNext()
    local mine = S.Mine()
    if #mine == 0 then info("Nothing saved yet."); return end
    S.minePick = S.minePick % #mine + 1
    local m = mine[S.minePick]
    if m.text then S.Load(m.title, m.text)
    else send("dload", m.title); info("Fetching \"" .. tidy(m.title) .. "\" from your account...") end
end

-- Opens a saved script: the editor's text and the saved copy are the same.
function S.Load(title, text)
    S.SetText(text)
    S.title, S.savedText = tidy(title), text
    header()
    info("Opened \"" .. tidy(title) .. "\".")
end

-- The API, from ModeAPI.lua, into the console.
function S.ShowAPI()
    M.Log("info", "Creator API " .. API.VERSION .. ": OnStart OnTick OnKey OnJoin OnLeave; Random print; docs/CREATOR-API.md")
    for _, ns in ipairs(API.NAMESPACES) do
        local fns = {}
        for _, f in ipairs(ns.fns) do fns[#fns + 1] = f.name end
        M.Log("info", ns.name .. ": " .. table.concat(fns, " "))
    end
end

-- ---------------------------------------------------------------- the window

local function buildBar()
    bar = CreateFrame("Frame", "LeylineModesTestBar", UIParent)
    bar:SetWidth(330); bar:SetHeight(34)
    bar:SetPoint("BOTTOM", 0, 180)
    bar:SetFrameStrata("DIALOG")
    bar:EnableMouse(true)
    local bg = bar:CreateTexture(nil, "BACKGROUND")
    bg:SetTexture(0.05, 0.04, 0.1, 0.85)
    bg:SetAllPoints(bar)
    bar.label = label(bar, "Testing", "GameFontNormalSmall", "LEFT", 10, 0)
    bar.edit = button(bar, "Edit", 56, function() S.Show() end, "RIGHT", -150, 0)
    bar.start = button(bar, "Start", 60, function() send("go", "") end, "RIGHT", -86, 0)
    bar.stop = button(bar, "Stop", 70, function() S.Stop() end, "RIGHT", -8, 0)
    bar:SetScript("OnUpdate", function() S.RefreshBar() end)
    bar:Hide()
end

function S.RefreshBar()
    if not bar then return end
    if M.state == "lobby" and M.lobby and M.lobby.host == (UnitName and UnitName("player")) then bar.start:Show() else bar.start:Hide() end
    local what = S.playing == "here" and (M.state == "lobby" and "Test lobby: press Start" or "Testing with your party") or "Testing here"
    bar.label:SetText(what)
end

local function build()
    ed = CreateFrame("Frame", "LeylineModesEditor", UIParent)
    ed:SetWidth(760); ed:SetHeight(580)
    ed:SetPoint("CENTER")
    ed:SetFrameStrata("DIALOG")
    ed:EnableMouse(true)
    ed:SetMovable(true)
    ed:RegisterForDrag("LeftButton")
    ed:SetScript("OnDragStart", ed.StartMoving)
    ed:SetScript("OnDragStop", ed.StopMovingOrSizing)
    if not W.Style then   -- Style.lua draws the window (S.Window, at its title)
        ed:SetBackdrop({ bgFile = "Interface\\Tooltips\\UI-Tooltip-Background",
        edgeFile = "Interface\\DialogFrame\\UI-DialogBox-Border", tile = true, tileSize = 32, edgeSize = 32,
        insets = { left = 11, right = 12, top = 12, bottom = 11 } })
    end
    ed:SetBackdropColor(0.05, 0.06, 0.08, 0.95)
    do
        local bg = ed:CreateTexture(nil, "BACKGROUND")
        bg:SetTexture(0.094, 0.106, 0.137, 0.97)   -- #181b23 (Style.lua)
        bg:SetPoint("TOPLEFT", 10, -10); bg:SetPoint("BOTTOMRIGHT", -10, 10)
    end
    ed.title = W.Style and W.Style.Window(ed, "Mode editor") or label(ed, "Mode editor", "GameFontNormal", "TOPLEFT", 22, -18)
    local close = (W.Style and W.Style.Close(ed) or CreateFrame("Button", nil, ed, "UIPanelCloseButton"))
    close:SetPoint("TOPRIGHT", -6, -6)
    tinsert(UISpecialFrames, "LeylineModesEditor")

    -- The script: a scroll frame around one frame holding the line numbers, the colour layer and the edit box.
    local font = monoFont() or ChatFontNormal or GameFontHighlight
    local sf = CreateFrame("ScrollFrame", "LeylineModesEditorScroll", ed, "UIPanelScrollFrameTemplate")
    sf:SetPoint("TOPLEFT", 22, -42)
    sf:SetPoint("BOTTOMRIGHT", -40, 212)
    local page = CreateFrame("Frame", nil, sf)
    page:SetWidth(680); page:SetHeight(300)
    local gutterBg = page:CreateTexture(nil, "BACKGROUND")
    gutterBg:SetTexture(0.1, 0.1, 0.14, 1)
    gutterBg:SetPoint("TOPLEFT", 0, 0); gutterBg:SetPoint("BOTTOMLEFT", 0, 0); gutterBg:SetWidth(34)
    local gutter = page:CreateFontString(nil, "OVERLAY")
    gutter:SetFontObject(font)
    gutter:SetPoint("TOPRIGHT", page, "TOPLEFT", 30, 0)
    gutter:SetJustifyH("RIGHT"); gutter:SetJustifyV("TOP")
    gutter:SetTextColor(0.45, 0.47, 0.55)
    local box = CreateFrame("EditBox", "LeylineModesEditorBox", page)
    box:SetMultiLine(true)
    box:SetAutoFocus(false)
    box:SetFontObject(font)
    box:SetPoint("TOPLEFT", 40, 0)
    box:SetWidth(636)
    box:SetTextInsets(0, 0, 0, 0)
    box:SetMaxLetters(API.MAX_SCRIPT)
    local layer = page:CreateFontString(nil, "ARTWORK")
    layer:SetFontObject(font)
    layer:SetPoint("TOPLEFT", box, "TOPLEFT", 0, 0)
    layer:SetWidth(636)
    layer:SetJustifyH("LEFT"); layer:SetJustifyV("TOP")
    local meter = page:CreateFontString(nil, "ARTWORK")
    meter:SetFontObject(font)
    meter:Hide()
    box:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
    box:SetScript("OnTabPressed", function(self) self:Insert("    ") end)
    box:SetScript("OnTextChanged", function(self)
        S.Changed()
        local h = (self.GetHeight and self:GetHeight()) or 300
        page:SetHeight(math.max(300, h))
        if sf.UpdateScrollChildRect then sf:UpdateScrollChildRect() end
    end)
    box:SetScript("OnCursorChanged", function(self, x, y, w, h)
        if ScrollingEdit_OnCursorChanged then ScrollingEdit_OnCursorChanged(self, x, y, w, h) end
    end)
    box:SetScript("OnUpdate", function(self, elapsed)
        if ScrollingEdit_OnUpdate then ScrollingEdit_OnUpdate(self, elapsed, sf) end
    end)
    page:EnableMouse(true)
    page:SetScript("OnMouseDown", function() box:SetFocus() end)
    sf:SetScrollChild(page)
    ed.sf, ed.page, ed.box, ed.gutter, ed.layer, ed.meter = sf, page, box, gutter, layer, meter

    -- The console.
    label(ed, "Console", "GameFontNormalSmall", "BOTTOMLEFT", 22, 194)
    button(ed, "Clear", 54, function() S.Clear() end, "BOTTOMLEFT", 86, 190)
    local con = CreateFrame("Frame", nil, ed)
    con:SetPoint("BOTTOMLEFT", 22, 96); con:SetWidth(700); con:SetHeight(92)
    local cbg = con:CreateTexture(nil, "BACKGROUND")
    cbg:SetTexture(0.02, 0.02, 0.04, 0.9)
    cbg:SetAllPoints(con)
    con:EnableMouseWheel(true)
    con:SetScript("OnMouseWheel", function(_, d)
        S.scroll = math.max(0, math.min(math.max(0, #M.console - ROWS), S.scroll + (d > 0 and 1 or -1)))
        S.RefreshConsole()
    end)
    ed.rows = {}
    for i = 1, ROWS do
        local row = CreateFrame("Button", nil, con)
        row:SetWidth(692); row:SetHeight(15)
        row:SetPoint("TOPLEFT", 4, -2 - (i - 1) * 15)
        row:SetHighlightTexture("Interface\\QuestFrame\\UI-QuestTitleHighlight", "ADD")
        row.text = label(row, "", "GameFontHighlightSmall", "LEFT", 2, 0)
        row.text:SetWidth(688)
        row:SetScript("OnClick", function(self) if self.entry and self.entry.line then S.GotoLine(self.entry.line) end end)
        row:Hide()
        ed.rows[i] = row
    end

    -- The buttons.
    ed.play = button(ed, "Play", 70, function() S.Play() end, "BOTTOMLEFT", 22, 64)
    ed.here = button(ed, "Play Here", 90, function() S.PlayHere() end, "BOTTOMLEFT", 96, 64)
    ed.stop = button(ed, "Stop", 64, function() S.Stop() end, "BOTTOMLEFT", 190, 64)
    ed.save = button(ed, "Save", 64, function() S.Save() end, "BOTTOMLEFT", 268, 64)
    button(ed, "Publish", 76, function() S.Publish() end, "BOTTOMLEFT", 336, 64)
    button(ed, "Check", 64, function() if S.Check(S.Text()) then info("No problems found.") else local e = S.LastError(); if e and e.line then S.GotoLine(e.line) end end end,
        "BOTTOMLEFT", 416, 64)
    ed.startBtn = button(ed, "Start from: Template", 170, function() S.StartFrom() end, "BOTTOMLEFT", 22, 38)
    button(ed, "Open mine", 84, function() S.OpenNext() end, "BOTTOMLEFT", 196, 38)
    button(ed, "Device editor", 104, function() local t = S.Text(); ed:Hide(); if M.DeviceEditor then M.DeviceEditor(t) end end, "BOTTOMLEFT", 284, 38)
    button(ed, "API", 50, function() S.ShowAPI() end, "BOTTOMLEFT", 392, 38)
    ed.colourBtn = button(ed, "Colours: on", 96, function() S.SetColour(not S.colour) end, "BOTTOMLEFT", 446, 38)
    ed.count = label(ed, "", "GameFontHighlightSmall", "BOTTOMRIGHT", -40, 68)
    ed.count:SetJustifyH("RIGHT")
    ed.info = label(ed, "Play tests a copy here; Play Here hosts a copy for your party. Save while testing reloads it.",
        "GameFontHighlightSmall", "BOTTOMLEFT", 22, 18)
    ed.info:SetWidth(700)

    ed:SetScript("OnShow", function() send("dlist", ""); S.RefreshButtons() end)
    -- Redraw the gutter and colours a moment after typing stops; send a delayed draft save.
    ed:SetScript("OnUpdate", function()
        if S.redraw and now() - (S.changedAt or 0) > 0.25 then redraw() end
    end)
    ed:Hide()
    if S.pending then box:SetText(S.pending); S.pending = nil end
    local db = WrathUnleashedUIDB or {}
    if db.modeColours == false then S.colour = false end
    ed.colourBtn:SetText(S.colour and "Colours: on" or "Colours: off")
end

-- While a test runs, Stop is on and Save hot-reloads.
function S.RefreshButtons()
    if not ed then return end
    S.RefreshConsole()
    if S.playing then ed.stop:Enable(); ed.save:SetText("Save+reload") else ed.stop:Disable(); ed.save:SetText("Save") end
    header()
end

local ticker = CreateFrame("Frame")
ticker:SetScript("OnUpdate", function() if S.remoteDue then S.flushSave() end end)

function S.Show()
    if not ed then build() end
    if not bar then buildBar() end
    ed:Show()
    S.RefreshButtons()
    redraw()
end

function M.Editor(text)
    if not ed then build(); buildBar() end
    if text then
        S.SetText(text)
        S.title, S.savedText = nil, nil
    elseif (ed.box:GetText() or "") == "" then
        S.SetText(M.TEMPLATE)
    end
    S.Show()
end
S.Open = M.Editor

-- A script draft from your account opens here (device layouts still open in the device editor).
local devDrafts = M.OnDraftMessage
M.OnDraftMessage = function(name, data)
    if name == "draft" then
        local title, text = tostring(data or ""):match("^([^\n]*)\n(.*)$")
        if text and not text:find("Devices.Run", 1, true) then
            if not ed then build(); buildBar() end
            S.Load(title, text)
            S.Show()
            return
        end
    elseif name == "dsaved" and S.title and tidy(data) == S.title and ed and ed:IsShown() then
        info("Saved \"" .. S.title .. "\" on your account.")
    end
    if devDrafts then devDrafts(name, data) end
end
