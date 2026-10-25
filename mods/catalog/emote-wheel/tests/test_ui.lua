-- lua5.1 tests/test_ui.lua ui/WUEmoteWheel/WUEmoteWheel.lua
-- Loads the addon with stub frames, opens the wheel, changes a slot and does an emote.
local file = assert(arg[1], "path to ui/WUEmoteWheel/WUEmoteWheel.lua")
local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local function frame(name)
    local f = { scripts = {}, shown = true }
    local noop = function() end
    setmetatable(f, { __index = function(_, k) if type(k) == "string" and k:match("^%u") then return noop end end })
    function f:SetScript(n, fn) self.scripts[n] = fn end
    function f:Show() self.shown = true end
    function f:Hide() self.shown = false end
    function f:IsShown() return self.shown end
    function f:SetText(t) self.text = t end
    function f:SetPoint(...) self.point = { ... } end
    function f:CreateTexture() return frame() end
    function f:GetEffectiveScale() return 2 end
    function f:AddMessage(m) self.msgs = self.msgs or {}; self.msgs[#self.msgs + 1] = m end
    if name then _G[name] = f end
    return f
end
function CreateFrame(kind, name, parent) return frame(name) end
UIParent, DEFAULT_CHAT_FRAME = frame(), frame()
UISpecialFrames, SlashCmdList = {}, {}
tinsert = table.insert
local emotes = {}
function DoEmote(t) emotes[#emotes + 1] = t end
function GetCursorPosition() return 640, 400 end
dofile(file)

check("slash commands", SLASH_WUEMOTEWHEEL1 == "/wheel" and type(SlashCmdList.WUEMOTEWHEEL) == "function")
check("key binding names", BINDING_NAME_WUEMOTEWHEEL_TOGGLE == "Emote wheel")
local x1, y1 = WUEmoteWheel_Offset(1)
local x3, y3 = WUEmoteWheel_Offset(3)
local x5, y5 = WUEmoteWheel_Offset(5)
check("slot 1 at the top", x1 == 0 and y1 == 86)
check("slot 3 on the right (clockwise)", x3 == 86 and y3 == 0)
check("slot 5 at the bottom", x5 == 0 and y5 == -86)
check("commands", WUEmoteWheel_Command("") == "open" and WUEmoteWheel_Command(" RESET ") == "reset"
    and select(3, WUEmoteWheel_Command("set 3 kiss")) == "KISS" and select(2, WUEmoteWheel_Command("set 3 /kiss")) == 3
    and WUEmoteWheel_Command("set 9 kiss") == "help" and WUEmoteWheel_Command("set 3 explode") == "help"
    and WUEmoteWheel_Command("set 3 kiss; /quit") == "help")

SlashCmdList.WUEMOTEWHEEL("")
local W = WUEmoteWheelFrame
check("opens", W and W.shown)
check("at the cursor (UI scale applied)", W.point[4] == 320 and W.point[5] == 200)
check("Esc closes it", UISpecialFrames[1] == "WUEmoteWheelFrame")
check("eight buttons with the defaults", #W.buttons == 8 and W.buttons[1].text == "Wave" and W.buttons[8].text == "Roar")
W.buttons[3].scripts.OnClick(W.buttons[3])
check("a click does the emote and closes", emotes[1] == "DANCE" and not W.shown)

SlashCmdList.WUEMOTEWHEEL("set 3 kiss")
check("set a slot", WUEmoteWheelDB.slots[3] == "KISS" and W.buttons[3].text == "Kiss")
check("says so", DEFAULT_CHAT_FRAME.msgs[#DEFAULT_CHAT_FRAME.msgs]:match("slot 3 is now /kiss"))
check("the slot does the new emote", WUEmoteWheel_Do(3) == "KISS" and emotes[#emotes] == "KISS")
WUEmoteWheelDB.slots[4] = "RUNSCRIPT"
check("a saved junk value falls back to the default", WUEmoteWheel_Slot(4) == "LAUGH")
SlashCmdList.WUEMOTEWHEEL("reset")
check("reset", WUEmoteWheel_Slot(3) == "DANCE")
SlashCmdList.WUEMOTEWHEEL("what")
check("help line", DEFAULT_CHAT_FRAME.msgs[#DEFAULT_CHAT_FRAME.msgs]:match("/wheel set <1%-8>"))
WUEmoteWheel_Toggle()
check("toggle opens", W.shown)
WUEmoteWheel_Toggle()
check("toggle closes", not W.shown)
W.scripts.OnMouseUp(W, "RightButton")
check("right-click closes", not W.shown)

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
