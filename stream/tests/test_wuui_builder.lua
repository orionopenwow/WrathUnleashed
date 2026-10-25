-- lua5.1 stream/tests/test_wuui_builder.lua [addon dir] [ov_build.lua] [ov_modapi.lua]
-- Fake 3.3.5a API: loads every file of WrathUnleashedUI in .toc order, opens the Builder window from
-- Esc > Mods & Workshop, and runs real round trips through ov_build.lua and ov_modapi.lua (fake mod-ale):
-- the catalog over OVMOD, search and categories, Spawn, the nudges and turns, Undo, Delete, Save / Share / Load
-- with the code box, "isn't on this realm" without the script, and no game-brand names on screen.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local server = arg[2] or "realm/custom/lua_scripts/ov_build.lua"
local modapi = arg[3] or server:gsub("ov_build%.lua$", "ov_modapi.lua")

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets (as test_wuui_leyline.lua)
local frames, created = {}, {}
local Frame = {}
Frame.__index = function(self, k)
    local v = rawget(Frame, k)
    if v ~= nil then return v end
    if type(k) == "string" and k:match("^%u") then return function() end end -- other widget methods: no-ops
    return nil
end
function Frame:SetScript(n, fn) self.scripts[n] = fn end
function Frame:GetScript(n) return self.scripts[n] end
function Frame:Fire(n, ...) local fn = self.scripts[n]; if fn then return fn(self, ...) end end
function Frame:Show()
    local was = self:IsVisible(); self.shown = true
    if not was and self:IsVisible() then self:Fire("OnShow") end
end
function Frame:Hide()
    local was = self:IsVisible(); self.shown = false
    if was then self:Fire("OnHide") end
end
function Frame:IsShown() return self.shown end
function Frame:IsVisible()
    if not self.shown then return false end
    return self.parent == nil or self.parent.top or self.parent:IsVisible()
end
function Frame:SetText(t) self.text = t end
function Frame:GetText() return self.text end
function Frame:Enable() self.enabled = true end
function Frame:Disable() self.enabled = false end
function Frame:RegisterEvent(e) self.events[e] = true end
function Frame:UnregisterEvent(e) self.events[e] = nil end
function Frame:GetName() return self.name end
function Frame:GetParent() return self.parent end
function Frame:GetHeight() return self.h or 0 end
function Frame:SetHeight(h) self.h = h end
local function new(kind, name, parent)
    local f = setmetatable({ kind = kind, name = name, parent = parent, scripts = {}, events = {}, shown = true }, Frame)
    if name then _G[name] = f end
    created[#created + 1] = f
    return f
end
function Frame:CreateFontString() return new("FontString", nil, self) end
function Frame:CreateTexture() return new("Texture", nil, self) end
function CreateFrame(kind, name, parent, template)
    local f = new(kind, name, parent); frames[#frames + 1] = f
    if template == "OptionsSliderTemplate" and name then
        new("FontString", name .. "Low", f); new("FontString", name .. "High", f)
    end
    return f
end

UIParent = new("Frame", "UIParent"); UIParent.top = true
function UIParent:GetScale() return 1 end
GameMenuFrame = new("Frame", "GameMenuFrame"); GameMenuFrame.top = true; GameMenuFrame.h = 300
UISpecialFrames = {}
function tinsert(t, v) table.insert(t, v) end
SlashCmdList = {}
DEFAULT_CHAT_FRAME = { AddMessage = function() end }
function GetScreenHeight() return 981 end
function InCombatLockdown() return false end
function SetBinding() return 1 end
function SetBindingClick() return 1 end
function SaveBindings() end
function SetCVar() end
function HasAction() return false end
function UnitLevel() return 80 end
function UnitClass() return "Mage", "MAGE" end
function UnitName() return "Tester" end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
local clock = 100
function GetTime() return clock end

-- ---------------------------------------------------------------- the realm (ov_build.lua + ov_modapi.lua, fake mod-ale)
local realGetenv, realTime = os.getenv, os.time
local serverClock = 1000000
os.time = function() return serverClock end
os.getenv = function() return nil end
local onServerAddon
function RegisterServerEvent(id, fn) if id == 30 then onServerAddon = fn end end
function RegisterPlayerEvent() end
function CreateLuaEvent() end
function CharDBExecute() end
function CharDBQuery() return nil end
local objects, nextGuid = {}, 1
local map0 = { GetWorldObject = function(_, g) return objects[g] end }
function PerformIngameSpawn(kind, entry, map, inst, x, y, z, o, save)
    nextGuid = nextGuid + 1
    local go = { guid = nextGuid, entry = entry, x = x, y = y, z = z, o = o }
    function go:GetGUID() return self.guid end
    function go:RemoveFromWorld() objects[self.guid] = nil end
    objects[go.guid] = go
    return go
end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end
local chat = {}
local player = { x = -9448.55, y = 68.24, z = 56.32, o = 0 }
function player:GetGUIDLow() return 7 end
function player:GetName() return "Tester" end
function player:GetGMRank() return 1 end
function player:GetMapId() return 0 end
function player:GetMap() return map0 end
function player:GetX() return self.x end
function player:GetY() return self.y end
function player:GetZ() return self.z end
function player:GetO() return self.o end
function player:SendBroadcastMessage(m) chat[#chat + 1] = m end
function player:SendAddonMessage(prefix, msg) fireClient(prefix, msg, "WHISPER", "Tester") end
package.preload["ov_modapi"] = function() return dofile(modapi) end
dofile(server)
local T = assert(OV_BUILD_TEST)
os.getenv = realGetenv

local sent = {}
function SendAddonMessage(prefix, msg, channel, target)
    sent[#sent + 1] = { prefix, msg, channel, target }
    if target == UnitName("player") and onServerAddon then onServerAddon(30, player, 7, prefix, msg, player) end
end

-- ---------------------------------------------------------------- load the addon in .toc order
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
local at = {}
for i, f in ipairs(files) do at[f] = i end
check(".toc lists Builder.lua (before Leyline.lua)", at["Builder.lua"] and at["Builder.lua"] < at["Leyline.lua"])
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
local B = assert(W.Builder, "W.Builder")
check("builds nothing until opened", B.Window() == nil)
check("/builder", SLASH_WUBUILDER1 == "/builder" and SlashCmdList.WUBUILDER)

-- Esc > Mods & Workshop > Builder
GameMenuButtonAddOns:Fire("OnClick")
local mods = _G.WrathUnleashedModsFrame
local open
for _, f in ipairs(created) do if f.parent == mods and f.text == "Builder" then open = f end end
check("Mods & Workshop has a Builder button", mods and mods:IsShown() and open)
open:Fire("OnClick")
local win = B.Window()
check("it opens the Builder window and closes the panel", win and win:IsShown() and not mods:IsShown())
check("Esc closes it", UISpecialFrames[#UISpecialFrames] == "WrathUnleashedBuilderFrame")
check("asked for the catalog over OVMOD, whispered to self", sent[1] and sent[1][1] == "OVMOD" and sent[1][2] == "wubuild\tcatalog\t1/1\t"
    and sent[1][3] == "WHISPER" and sent[1][4] == "Tester")

local function shown()
    local out = {}
    for _, r in ipairs(win.rows) do if r:IsShown() then out[#out + 1] = r end end
    return out
end
check("the catalog arrives: a page of rows", #B.catalog == #T.CATALOG() and #shown() == #win.rows and win.count:GetText():find("of " .. #B.catalog))
check("state arrived: not selected, in Goldshire green", win.sel:GetText():find("Nothing selected") and win.sel:GetText():find("Goldshire green"))
check("Spawn waits for a pick", win.spawn.enabled == false)

-- search and categories
win.search:SetText("lant"); win.search:Fire("OnTextChanged")
check("search filters", #shown() == 2 and shown()[1].name:GetText():find("Lantern"))
win.search:SetText(""); win.search:Fire("OnTextChanged")
win.catBtn:Fire("OnClick")
check("category: seating", win.catBtn:GetText() == "Category: seating" and #shown() == 5)
for _ = 1, #B.CATS - 1 do win.catBtn:Fire("OnClick") end
check("categories go round to all", win.catBtn:GetText() == "Category: all")
win.list:Fire("OnMouseWheel", -1)
check("mouse wheel scrolls", B.offset == 1)
win.list:Fire("OnMouseWheel", 1)

-- pick and spawn
shown()[1]:Fire("OnClick")
check("a pick names the Spawn button", win.spawn.enabled and win.spawn:GetText() == "Spawn Wooden Chair")
win.spawn:Fire("OnClick")
local id = T.selected[7]
local p = id and T.props[id]
check("Spawn places it on the realm", p and p.entry == 2413 and objects[T.live[id]])
check("the state shows the selection", win.sel:GetText():find("Selected: Wooden Chair") and win.sel:GetText():find("props 1/50"))
check("the realm said so in chat", chat[#chat]:find("Wooden Chair placed"))

-- nudges and turns
local z0 = p.z
win.nudge["z+"]:Fire("OnClick")
check("z + moves it up one step (1 yd)", math.abs(p.z - (z0 + 1)) < 1e-6 and sent[#sent][2] == "wubuild\tcmd\t1/1\tmove z 1")
win.stepBtn:Fire("OnClick")
win.nudge["x-"]:Fire("OnClick")
check("the step button: 3 yd", win.stepBtn:GetText() == "Step 3 yd" and sent[#sent][2]:find("move x %-3$"))
win.stepBtn:Fire("OnClick")
win.nudge["y+"]:Fire("OnClick")
check("and round to 0.25 yd", sent[#sent][2]:find("move y 0%.25$"))
local o0 = p.o
win.turnL:Fire("OnClick")
check("turn +15 degrees", math.abs(p.o - (o0 + math.rad(15))) < 1e-6)
serverClock = serverClock + 1
win.turnR:Fire("OnClick")
check("turn -15 degrees", math.abs(p.o - o0) < 1e-6)
win.undo:Fire("OnClick")
check("Undo", math.abs(p.o - (o0 + math.rad(15))) < 1e-6 and chat[#chat]:find("Undone"))

-- save / share / load with the box
win.code:SetText("my camp")
win.save:Fire("OnClick")
check("Save takes the name from the box", T.builds[7] and T.builds[7]["mycamp"] and chat[#chat]:find("Saved 'mycamp'"))
win.code:SetText("mycamp")
win.share:Fire("OnClick")
local code = T.builds[7].mycamp.code
check("Share puts the code in the box", code and win.code:GetText() == code)
win.delete:Fire("OnClick")
check("Delete", next(T.props) == nil and win.sel:GetText():find("Nothing selected") and win.sel:GetText():find("props 0/50"))
win.load:Fire("OnClick")
check("Load the code from the box", (function() local n = 0; for _ in pairs(T.props) do n = n + 1 end; return n == 1 end)()
    and chat[#chat]:find("Pasted '" .. code .. "'"))
win.code:SetText("bad|name")
local before = #sent
win.load:Fire("OnClick")
check("a bad name never leaves the window", #sent == before and win.status:GetText():find("Type a build name"))

-- the client ignores messages that aren't the realm's answer to us
fireClient("OVMOD", "wubuild\tstate\t1/1\tsel=1,2,Spoof;mine=9/9;area=x;code=-", "WHISPER", "Someone")
check("ignores other senders", not win.sel:GetText():find("Spoof"))
-- a catalog in two parts
fireClient("OVMOD", "wubuild\tcatalog\t1/2\t2413,chair,seating,Wooden", "WHISPER", "Tester")
fireClient("OVMOD", "wubuild\tcatalog\t2/2\t Chair;181075,table,tables,Table", "WHISPER", "Tester")
check("multi-part catalog reassembled", #B.catalog == 2 and B.catalog[1].name == "Wooden Chair")

-- no realm script: says so
onServerAddon = nil
win.reload:Fire("OnClick")
check("asking...", win.status:GetText():find("^Asking"))
clock = clock + 10
win:Fire("OnUpdate", 0.1)
check("no answer: the Builder isn't on this realm", win.status:GetText():find("isn't on this realm"))

win:Hide()
SlashCmdList.WUBUILDER("")
check("/builder toggles it", win:IsShown())

-- nothing the window shows names the game or its maker
local bad
for _, f in ipairs(created) do
    local t = (f.kind == "FontString" or f.kind == "Button") and f.text or nil
    if t and (t:lower():find("warcraft") or t:lower():find("%f[%w]wow%f[%W]") or t:lower():find("lich king")
        or t:lower():find("blizzard") or t:find("Open ?Vanilla") or t:find("OpenWoW")) then bad = t end
end
check("no game-brand or old project names on screen", bad == nil)
if bad then print("  shown: " .. bad) end

os.time = realTime
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
