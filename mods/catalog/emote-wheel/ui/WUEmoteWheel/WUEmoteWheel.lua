-- WUEmoteWheel: a ring of eight emotes around your cursor (WrathUnleashed mod "emote-wheel").
--   /wheel                  opens the wheel at the cursor; click an emote, or Esc / right-click to close
--   /wheel set 3 kiss       puts /kiss in slot 3 (slots 1-8, clockwise from the top)
--   /wheel reset            back to the default eight
-- A key for it: Key Bindings > WrathUnleashed > Emote wheel.
local SLOTS, RADIUS, SIZE = 8, 86, 54
local DEFAULTS = { "WAVE", "CHEER", "DANCE", "LAUGH", "BOW", "THANK", "POINT", "ROAR" }
-- Emote tokens the wheel offers: the stock /emote commands that need no target.
local KNOWN = {
    WAVE = "Wave", CHEER = "Cheer", DANCE = "Dance", LAUGH = "Laugh", BOW = "Bow", THANK = "Thank",
    POINT = "Point", ROAR = "Roar", KISS = "Kiss", CLAP = "Clap", SALUTE = "Salute", FLEX = "Flex",
    CRY = "Cry", SHY = "Shy", CHICKEN = "Chicken", TRAIN = "Train", SIT = "Sit", KNEEL = "Kneel",
    APPLAUD = "Applaud", HUG = "Hug", NO = "No", YES = "Yes", BEG = "Beg", RUDE = "Rude",
    GREET = "Greet", VICTORY = "Victory", SHRUG = "Shrug", CURIOUS = "Curious", SNEEZE = "Sneeze",
}
WUEMOTEWHEEL_KNOWN = KNOWN
BINDING_HEADER_WUEMOTEWHEEL = "WrathUnleashed"
BINDING_NAME_WUEMOTEWHEEL_TOGGLE = "Emote wheel"

local wheel

local function db()
    WUEmoteWheelDB = WUEmoteWheelDB or {}
    WUEmoteWheelDB.slots = WUEmoteWheelDB.slots or {}
    return WUEmoteWheelDB
end

-- The emote token in a slot (saved choice, else the default).
function WUEmoteWheel_Slot(i)
    local s = db().slots[i]
    if s and KNOWN[s] then return s end
    return DEFAULTS[i]
end

-- x, y offset of slot i from the wheel's centre: slot 1 at the top, then clockwise.
function WUEmoteWheel_Offset(i, n, r)
    n, r = n or SLOTS, r or RADIUS
    local a = (i - 1) * 2 * math.pi / n
    local x, y = r * math.sin(a), r * math.cos(a)
    return math.floor(x * 100 + 0.5) / 100, math.floor(y * 100 + 0.5) / 100
end

-- "set 3 kiss" -> "set", 3, "KISS"; "reset" -> "reset"; "" -> "open"; anything else -> "help"
function WUEmoteWheel_Command(text)
    text = (text or ""):lower():gsub("^%s+", ""):gsub("%s+$", "")
    if text == "" then return "open" end
    if text == "reset" then return "reset" end
    local slot, emote = text:match("^set%s+(%d)%s+/?(%a+)$")
    slot = tonumber(slot)
    if slot and slot >= 1 and slot <= SLOTS and KNOWN[emote:upper()] then return "set", slot, emote:upper() end
    return "help"
end

local function say(msg)
    if DEFAULT_CHAT_FRAME then DEFAULT_CHAT_FRAME:AddMessage("|cffffcc66[Emote wheel]|r " .. msg) end
end

function WUEmoteWheel_Refresh()
    if not wheel then return end
    for i, b in ipairs(wheel.buttons) do
        b.token = WUEmoteWheel_Slot(i)
        b:SetText(KNOWN[b.token])
    end
end

function WUEmoteWheel_Do(i)
    local token = WUEmoteWheel_Slot(i)
    if wheel then wheel:Hide() end
    DoEmote(token)
    return token
end

local function build()
    wheel = CreateFrame("Frame", "WUEmoteWheelFrame", UIParent)
    wheel:SetWidth(2 * RADIUS + SIZE); wheel:SetHeight(2 * RADIUS + SIZE)
    wheel:SetFrameStrata("DIALOG")
    wheel:EnableMouse(true)
    wheel:SetScript("OnMouseUp", function(self, mouse) if mouse == "RightButton" then self:Hide() end end)
    local ring = wheel:CreateTexture(nil, "BACKGROUND")
    ring:SetTexture("Interface\\Minimap\\UI-Minimap-Background")
    ring:SetPoint("CENTER")
    ring:SetWidth(2 * RADIUS + 24); ring:SetHeight(2 * RADIUS + 24)
    ring:SetVertexColor(0, 0, 0, 0.55)
    wheel.buttons = {}
    for i = 1, SLOTS do
        local b = CreateFrame("Button", "WUEmoteWheelButton" .. i, wheel, "UIPanelButtonTemplate")
        b:SetWidth(SIZE + 18); b:SetHeight(24)
        local x, y = WUEmoteWheel_Offset(i)
        b:SetPoint("CENTER", wheel, "CENTER", x, y)
        b:SetScript("OnClick", function() WUEmoteWheel_Do(i) end)
        wheel.buttons[i] = b
    end
    tinsert(UISpecialFrames, "WUEmoteWheelFrame")   -- Esc closes it
    wheel:Hide()
end

function WUEmoteWheel_Open()
    if not wheel then build() end
    WUEmoteWheel_Refresh()
    local x, y = GetCursorPosition()
    local s = UIParent:GetEffectiveScale()
    wheel:ClearAllPoints()
    wheel:SetPoint("CENTER", UIParent, "BOTTOMLEFT", x / s, y / s)
    wheel:Show()
end

function WUEmoteWheel_Toggle()
    if wheel and wheel:IsShown() then wheel:Hide() else WUEmoteWheel_Open() end
end

SLASH_WUEMOTEWHEEL1, SLASH_WUEMOTEWHEEL2 = "/wheel", "/emotewheel"
SlashCmdList["WUEMOTEWHEEL"] = function(msg)
    local cmd, slot, token = WUEmoteWheel_Command(msg)
    if cmd == "open" then
        WUEmoteWheel_Toggle()
    elseif cmd == "set" then
        db().slots[slot] = token
        WUEmoteWheel_Refresh()
        say(string.format("slot %d is now /%s.", slot, token:lower()))
    elseif cmd == "reset" then
        db().slots = {}
        WUEmoteWheel_Refresh()
        say("back to the default emotes.")
    else
        say("/wheel opens it. /wheel set <1-8> <emote> (for example /wheel set 3 kiss), /wheel reset.")
    end
end
