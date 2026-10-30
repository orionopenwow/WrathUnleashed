-- lua5.1 tests/test_ui.lua ui/DalaranDice/DalaranDice.lua
-- Loads the addon with a stub frame and feeds it addon messages.
local file = assert(arg[1], "path to ui/DalaranDice/DalaranDice.lua")
local function frame()
    local f = { shown = false, text = "", events = {} }
    function f:Show() self.shown = true end
    function f:Hide() self.shown = false end
    function f:IsShown() return self.shown end
    function f:SetText(t) self.text = t end
    function f:SetBackdrop() end
    function f:SetBackdropColor() end
    function f:RegisterEvent(e) self.events[e] = true end
    return f
end
DalaranDiceFrame, DalaranDiceFrameText, SlashCmdList = frame(), frame(), {}
dofile(file)

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

local F = DalaranDiceFrame
DalaranDice_OnLoad(F)
check("listens for addon messages", F.events.CHAT_MSG_ADDON)
check("other mods ignored", DalaranDice_Parse("OVMOD", "pings\tping\t1/1\t1,2,3") == nil)
check("other prefixes ignored", DalaranDice_Parse("CAIO", "dalaran-dice\troll\t1/1\tA,2,6,8,3 5") == nil)
check("bad data ignored", DalaranDice_Parse("OVMOD", "dalaran-dice\troll\t1/1\tA,2,6") == nil)
check("parses a roll", DalaranDice_Parse("OVMOD", "dalaran-dice\troll\t1/1\tTester,2,6,8,3 5") == "Tester: 2d6 = |cffffff008|r (3 5)")
for i = 1, 7 do
    DalaranDice_OnEvent(F, "CHAT_MSG_ADDON", "OVMOD", "dalaran-dice\troll\t1/1\tP" .. i .. ",1,20," .. i .. "," .. i, "WHISPER", "P")
end
local lines = {}
for l in (DalaranDiceFrameText.text .. "\n"):gmatch("(.-)\n") do lines[#lines + 1] = l end
check("keeps five lines, newest first", #lines == 5 and lines[1]:match("^P7") and lines[5]:match("^P3"))
check("shows itself on a roll", F.shown)
SlashCmdList.DALARAN_DICE()
check("/dicelog hides it", not F.shown)
check("slash command name", SLASH_DALARAN_DICE1 == "/dicelog")

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
