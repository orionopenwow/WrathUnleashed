-- Your game folder (3.3.5a API): what the browser page reads the world from, shown in the game.
--   Streamed play covers Dalaran, the capitals and the starting areas. A player who drops their own 3.3.5a game
--   folder on the page (or picks it with "Use my game folder") plays the whole world: the page reads the folder
--   on their computer (nothing is uploaded) and the realm lifts its zone limit for the account.
-- Shown in the Leyline window (Esc > Mods & Workshop > Leyline realms), under the Esc menu, and by /folder.
--
-- The page (stream/www-files/wrath-page.js, ownfiles.js) talks to the game through two globals, on a 1 s poll
-- while the bridge is up (a /reload wipes globals; the page sets the state again each second):
--   page -> game   WUUI_GAMEFOLDER = { page = true, on = bool, build = n, label = "Data", ownOnly = n,
--                                      realm = "lifted"|"held"|"unknown"|"failed", keeps = bool, allowed = bool }
--   game -> page   WUUI_GAMEFOLDER_ASK = "pick"   (the page takes and clears it, then opens the folder picker)
-- Without a page (the desktop client) the global is never set: the window says the button is for the browser.

local W = WrathUnleashedUI
local G = {}
local ASK_WAIT = 8   -- seconds: the ask still pending after this = no page took it
local STREAMED = "Streamed: Dalaran, capitals, starting areas"
local WHOLE = "Whole world: your game folder"
local HELP = "play.openvanilla.app/wrath/docs/play"

local function now() return (GetTime and GetTime()) or 0 end

function G.State()
    local s = WUUI_GAMEFOLDER
    if type(s) ~= "table" or s.page ~= true then return nil end
    return s
end

-- The one-line status: colour-coded, as shown in the Leyline window and under the Esc menu.
function G.Line()
    local s = G.State()
    if s and s.on then
        if s.realm == "failed" or s.realm == "held" then
            return "|cff40ff40" .. WHOLE .. "|r |cffffd100(the realm has not confirmed yet)|r"
        end
        return "|cff40ff40" .. WHOLE .. "|r"
    end
    return "|cffffd100" .. STREAMED .. "|r"
end

-- The line under it: what the button does here, or what is in use.
function G.Help()
    local s = G.State()
    if not s then
        return "In the browser game you can drop your own 3.3.5a game folder on the page to go anywhere. How: " .. HELP
    end
    if s.on then
        local bits = {}
        if type(s.label) == "string" and s.label ~= "" then bits[#bits + 1] = "\"" .. s.label:gsub("|", "") .. "\"" end
        if tonumber(s.build) then bits[#bits + 1] = "build " .. tonumber(s.build) end
        return "Read from your folder " .. table.concat(bits, ", ") .. " on this computer. Nothing is uploaded."
    end
    if s.allowed == false then
        return "Your game folder works on the streamed page after you sign in. How: " .. HELP
    end
    return "Drop your 3.3.5a game folder on the page, or press Use my game folder: it is read on your computer, "
        .. "nothing is uploaded." .. (s.keeps == false and " This browser asks for it on each visit." or "")
end

-- Ask the page for the folder picker. Returns ok, message.
function G.Ask()
    local s = G.State()
    if s and s.on then return false, "Your game folder is already in use: the whole world is open." end
    if s and s.allowed == false then return false, G.Help() end
    WUUI_GAMEFOLDER_ASK = "pick"
    G.asking = now()
    return true, "Opening the folder picker in the page... choose your 3.3.5a game folder there."
end

-- Called often (the window's OnUpdate): an ask nobody took means there is no page.
function G.Tick()
    if G.asking and now() - G.asking > ASK_WAIT then
        G.asking = nil
        if WUUI_GAMEFOLDER_ASK == "pick" then
            WUUI_GAMEFOLDER_ASK = nil
            return "Using your game folder works in the browser game. How: " .. HELP
        end
    end
end

-- The row in a window: the status line, the help line and the button. `y` is the row's offset from the top.
function G.Attach(win, y, width)
    local line = win:CreateFontString(nil, "OVERLAY", "GameFontNormal")
    line:SetPoint("TOPLEFT", 20, y)
    line:SetJustifyH("LEFT")
    local help = win:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    help:SetPoint("TOPLEFT", 20, y - 18)
    help:SetJustifyH("LEFT")
    help:SetWidth((width or 560) - 200)
    local b = CreateFrame("Button", nil, win, "UIPanelButtonTemplate")
    b:SetWidth(150); b:SetHeight(22)
    b:SetPoint("TOPRIGHT", -20, y + 2)
    b:SetText("Use my game folder")
    local row = { line = line, help = help, button = b }
    function row.Refresh()
        line:SetText(G.Line())
        help:SetText(row.note or G.Help())
        local s = G.State()
        if s and s.on then b:Disable() else b:Enable() end
    end
    b:SetScript("OnClick", function()
        local _, msg = G.Ask()
        row.note = msg
        row.Refresh()
    end)
    row.Refresh()
    G.rows[#G.rows + 1] = row
    return row
end
G.rows = {}

-- Every row (and the Esc menu line) follows the page's state.
local ticker = CreateFrame("Frame")
local acc = 0
ticker:SetScript("OnUpdate", function(_, elapsed)
    acc = acc + (elapsed or 0)
    if acc < 0.5 then return end
    acc = 0
    local note = G.Tick()
    for _, row in ipairs(G.rows) do
        if note then row.note = note end
        local s = G.State()
        if s and s.on then row.note = nil end
        row.Refresh()
    end
    if G.menuLine then G.menuLine:SetText(G.Line()) end
end)

-- Under the Esc menu: the same status line.
if GameMenuFrame then
    local fs = GameMenuFrame:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
    fs:SetPoint("TOP", GameMenuFrame, "BOTTOM", 0, -6)
    fs:SetText(G.Line())
    G.menuLine = fs
end

SLASH_WUFOLDER1, SLASH_WUFOLDER2 = "/folder", "/gamefolder"
SlashCmdList["WUFOLDER"] = function()
    local ok, msg = G.Ask()
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffffd100Game folder:|r " .. G.Line() .. " - " .. msg) end
    return ok
end

W.GameFolder = G
G.STREAMED, G.WHOLE, G.ASK_WAIT, G.HELP = STREAMED, WHOLE, ASK_WAIT, HELP
