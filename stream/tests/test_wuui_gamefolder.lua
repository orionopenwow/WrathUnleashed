-- lua5.1 stream/tests/test_wuui_gamefolder.lua [addon dir]
-- Fake 3.3.5a API: loads every file of WrathUnleashedUI in .toc order and checks "Your game folder"
-- (GameFolder.lua): the status line ("Streamed: ..." / "Whole world: your game folder") under the Esc menu and in
-- the Leyline window, the "Use my game folder" button and /folder (WUUI_GAMEFOLDER_ASK = "pick", which the page
-- takes), the page's WUUI_GAMEFOLDER state (on, build, label, the realm's answer, a browser that can't keep
-- folders, a page that doesn't offer it), no page at all (the desktop client), and no game-brand names.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end

-- ---------------------------------------------------------------- fake widgets (as test_wuui_collections.lua)
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
    if template == "OptionsSliderTemplate" and name then  -- the template's Low / High labels
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
local realmName = "WrathUnleashed"
function GetRealmName() return realmName end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
local clock = 100
function GetTime() return clock end
function SendAddonMessage() end

local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
local at = {}
for i, f in ipairs(files) do at[f] = i end
check(".toc loads GameFolder.lua before Leyline.lua", at["GameFolder.lua"] and at["Leyline.lua"] and at["GameFolder.lua"] < at["Leyline.lua"])
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
local G = assert(W.GameFolder, "W.GameFolder")

local seen = {}
local function tick(n)
    for _ = 1, n or 1 do
        clock = clock + 0.6
        for _, f in ipairs(frames) do
            local fn = f.scripts.OnUpdate
            if fn and f.parent == nil then fn(f, 0.6) end
        end
    end
end
local function remember(t) if t then seen[#seen + 1] = t end return t end

-- ---------------------------------------------------------------- no page (the desktop client)
check("no page: streamed line", remember(G.Line()):find(G.STREAMED, 1, true) ~= nil)
check("no page: the help says it is for the browser game", remember(G.Help()):find("In the browser game", 1, true)
    and G.Help():find("play.openvanilla.app/wrath/docs/play", 1, true))
check("Esc menu shows the status line", G.menuLine and G.menuLine.parent == GameMenuFrame and G.menuLine.text:find(G.STREAMED, 1, true))
local ok, msg = G.Ask()
check("Ask sets the page's global", ok and WUUI_GAMEFOLDER_ASK == "pick" and remember(msg):find("folder picker"))

-- the Leyline window's row
SlashCmdList.WULEYLINE()
local win = W.Leyline.Window()
check("the Leyline window has the game-folder row", win and win.folder and win.folder.button.text == "Use my game folder"
    and win.folder.line.text:find(G.STREAMED, 1, true))
tick(math.ceil(G.ASK_WAIT / 0.6) + 1)
check("an ask nobody took: cleared, and the row says it works in the browser game",
    WUUI_GAMEFOLDER_ASK == nil and remember(win.folder.help.text):find("works in the browser game", 1, true))

-- ---------------------------------------------------------------- the page: streamed, folder offered
WUUI_GAMEFOLDER = { page = true, on = false, realm = "held", keeps = true, allowed = true }
win.folder.note = nil
tick()
check("page, no folder: streamed line, drop help", win.folder.line.text:find(G.STREAMED, 1, true)
    and remember(win.folder.help.text):find("Drop your game folder on the page", 1, true)
    and win.folder.button.enabled ~= false)
win.folder.button:Fire("OnClick")
check("the button asks the page", WUUI_GAMEFOLDER_ASK == "pick" and remember(win.folder.help.text):find("folder picker", 1, true))
WUUI_GAMEFOLDER_ASK = nil   -- the page took it (wrath-page.js FOLDER_TAKE)
tick(math.ceil(G.ASK_WAIT / 0.6) + 1)
check("a taken ask: no 'browser game' note", not win.folder.help.text:find("works in the browser game", 1, true))

WUUI_GAMEFOLDER = { page = true, on = false, keeps = false, allowed = true }
win.folder.note = nil
tick()
check("Firefox/Safari: asks on each visit", remember(win.folder.help.text):find("asks for it on each visit", 1, true))

-- ---------------------------------------------------------------- the folder is in use
WUUI_GAMEFOLDER = { page = true, on = true, build = 12340, label = "Data", ownOnly = 51234, realm = "lifted", keeps = true, allowed = true }
tick()
check("folder on: whole world", remember(win.folder.line.text):find(G.WHOLE, 1, true) and not win.folder.line.text:find("not confirmed"))
check("folder on: build and folder name, nothing uploaded", remember(win.folder.help.text):find("build 12340", 1, true)
    and win.folder.help.text:find('"Data"', 1, true) and win.folder.help.text:find("Nothing is uploaded", 1, true))
check("folder on: the button is off", win.folder.button.enabled == false)
check("Esc menu line follows", G.menuLine.text:find(G.WHOLE, 1, true))
ok, msg = G.Ask()
check("folder on: Ask says it is in use", not ok and remember(msg):find("already in use") and WUUI_GAMEFOLDER_ASK == nil)
WUUI_GAMEFOLDER.realm = "failed"
tick()
check("the realm did not confirm: said so", remember(win.folder.line.text):find("has not confirmed", 1, true))
WUUI_GAMEFOLDER.label = "x|cffff0000y"
check("a folder name can't inject colour codes", not G.Help():find("|c", 1, true))

-- ---------------------------------------------------------------- a page that does not offer it (a hop, a guest)
WUUI_GAMEFOLDER = { page = true, on = false, allowed = false }
ok, msg = G.Ask()
check("not offered here: no ask, says why", not ok and WUUI_GAMEFOLDER_ASK == nil and remember(msg):find("after you sign in"))
WUUI_GAMEFOLDER = "junk"
check("a junk global counts as no page", G.State() == nil and G.Line():find(G.STREAMED, 1, true))

-- /folder
WUUI_GAMEFOLDER = { page = true, on = false, allowed = true }
local said
DEFAULT_CHAT_FRAME = { AddMessage = function(_, t) said = t end }
check("/folder and /gamefolder", SLASH_WUFOLDER1 == "/folder" and SLASH_WUFOLDER2 == "/gamefolder")
SlashCmdList.WUFOLDER()
check("/folder asks the page and says so", WUUI_GAMEFOLDER_ASK == "pick" and remember(said):find("folder picker"))

local bad = {}
for _, t in ipairs(seen) do
    local l = t:lower()
    for _, w in ipairs({ "world of warcraft", "warcraft", "blizzard", "lich king" }) do
        if l:find(w, 1, true) then bad[#bad + 1] = t end
    end
    if l:find("%f[%a]wow%f[%A]") then bad[#bad + 1] = t end
end
check("no game-brand names in what it shows", #bad == 0)

print(string.format("%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
