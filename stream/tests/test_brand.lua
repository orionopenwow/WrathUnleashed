-- lua5.1 stream/tests/test_brand.lua [addon dir] [lua_scripts dir]
-- The Leyline brand switch in game. The realm half (ov_modapi.lua OVMod.Brand, fake mod-ale) and the addon
-- (WrathUnleashedUI, every file in .toc order, fake 3.3.5a API) talk over OVMOD:
--   off (no flag file, no OV_LEYLINE_BRAND): nothing is sent, the addon's ask goes unanswered, chat lines keep the
--     [WrathUnleashed] tag, the Leyline window says "Back to Wrath";
--   on (the flag file brand.sh writes): a login pushes "wubrand"/"brand" (leyline, Wrath Unleashed), the ask is
--     answered, chat says [Leyline], the Leyline window's home realm is "Wrath Unleashed" (ov_leyline.lua's row for
--     this realm too), and nothing the window shows names an old brand.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local scripts = arg[2] or "realm/custom/lua_scripts"

local pass, fail = 0, 0
local function check(name, ok)
    if ok then pass = pass + 1; print("PASS " .. name) else fail = fail + 1; print("FAIL " .. name) end
end
-- "Wrath Unleashed" (with the space) is the main realm's own name now (owner 2026-10-30 23:32), not an old one
local OLD = { "WrathUnleashed", "Open Vanilla", "OpenVanilla", "Back to Wrath" }
local function hasOld(s)
    if type(s) ~= "string" then return false end
    s = s:gsub("WrathUnleashedUI", "")
    s = s:gsub("Wrath Unleashed", "")
    for _, w in ipairs(OLD) do if s:find(w, 1, true) then return w end end
    return false
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

-- ---------------------------------------------------------------- the realm (ov_leyline.lua under fake mod-ale)
GetRealmName = function() return realmName end

-- ---------------------------------------------------------------- the realm: ov_modapi.lua + ov_leyline.lua
local env = {}
local realGetenv = os.getenv
local flagFile = os.tmpname()
os.remove(flagFile)
local datFile = os.tmpname() .. ".dat"
do local f = assert(io.open(datFile, "wb")); f:write('return { updated = 999000, realms = {} }\n'); f:close() end
env.OV_BRAND_FILE = flagFile
env.OV_LEYLINE_FILE = datFile
os.getenv = function(k) if env[k] ~= nil then return env[k] end return realGetenv(k) end
local serverClock = 1000000
os.time = function() return serverClock end
local addonHooks, loginHooks = {}, {}
function RegisterServerEvent(id, fn) if id == 30 then addonHooks[#addonHooks + 1] = fn end end
function RegisterPlayerEvent(id, fn) if id == 3 then loginHooks[#loginHooks + 1] = fn end end
function GetPlayersInWorld() return { {} } end
local function fireClient(prefix, msg, channel, sender)
    for _, f in ipairs(frames) do
        if f.events.CHAT_MSG_ADDON then f:Fire("OnEvent", "CHAT_MSG_ADDON", prefix, msg, channel, sender) end
    end
end
local received, timers = {}, {}
local player = { GetGUIDLow = function() return 1 end }
function player:SendAddonMessage(prefix, msg) received[#received + 1] = { prefix, msg }; fireClient(prefix, msg, "WHISPER", "Tester") end
function player:RegisterEvent(fn, delay, rep) timers[#timers + 1] = fn end
dofile(scripts .. "/ov_modapi.lua")
dofile(scripts .. "/ov_leyline.lua")
local OVMod = assert(_G.OVMod)
local function login()
    for _, h in ipairs(loginHooks) do h(3, player) end
    local t = timers; timers = {}
    for _, fn in ipairs(t) do fn(1, 3000, 1, player) end
end

function SendAddonMessage(prefix, msg, channel, target)
    if target == UnitName("player") then for _, h in ipairs(addonHooks) do h(30, player, 7, prefix, msg, player) end end
end
local chat = {}
DEFAULT_CHAT_FRAME = { AddMessage = function(_, m) chat[#chat + 1] = m end }

-- ---------------------------------------------------------------- 1. the realm half, off
local b = OVMod.Brand()
check("off by default: the old names", b.on == false and b.name == "WrathUnleashed" and b.realm == "WrathUnleashed" and b.home == "Wrath")
login()
check("off: a login sends nothing", #received == 0)

-- ---------------------------------------------------------------- 2. the addon, off
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)
check("addon: off until the realm says otherwise", W.Brand and W.Brand.on == false and W.Brand.back == "Back to Wrath")
for _, f in ipairs(frames) do
    if f.events.PLAYER_ENTERING_WORLD then f:Fire("OnEvent", "PLAYER_ENTERING_WORLD") end
end
local function brandSent() local n = 0; for _, r in ipairs(received) do if r[2]:find("^wubrand") then n = n + 1 end end; return n end
check("off: the addon's ask is not answered", brandSent() == 0 and W.Brand.on == false)
-- the hello is answered brand on or off (WrathUnleashedUI applies its defaults on a Leyline realm only)
check("off: the realm's hello is answered, so the addon knows a Leyline realm", #received == 1 and received[1][2] == "wuhello\thi\t1/1\t1" and W.LeylineRealm == true)
W.Say("hello")
check("off: chat lines wait a moment for the realm's word", #chat == 0 or not chat[#chat]:find("hello", 1, true))
for _ = 1, 40 do for _, f in ipairs(frames) do f:Fire("OnUpdate", 0.1) end end
local saw = false
for _, m in ipairs(chat) do if m:find("hello", 1, true) then saw = m end end
check("off: then the old tag", saw and saw:find("[WrathUnleashed]", 1, true) ~= nil)
check("off: the Leyline window says Back to Wrath", W.Leyline and (function()
    SlashCmdList.WULEYLINE(""); local win = W.Leyline.Window(); return win and win.back.text == "Back to Wrath" end)())

-- ---------------------------------------------------------------- 3. the realm half, on (brand.sh's flag file)
do local f = assert(io.open(flagFile, "wb")); f:write("on\n"); f:close() end
check("the flag is looked at no more than every 30 s", OVMod.BrandOn() == false)
serverClock = serverClock + 31
b = OVMod.Brand()
check("on: Leyline and Wrath Unleashed", b.on == true and b.name == "Leyline" and b.realm == "Wrath Unleashed" and b.home == "Wrath Unleashed")
env.OV_LEYLINE_REALM_NAME = "Frost|cffff0000 Hall"
check("on: OV_LEYLINE_REALM_NAME, cleaned", OVMod.Brand().realm == "Frostcffff0000 Hall")
env.OV_LEYLINE_REALM_NAME = nil
env.OV_LEYLINE_BRAND = "0"
check("OV_LEYLINE_BRAND=0 wins over the flag", OVMod.Brand().on == false)
env.OV_LEYLINE_BRAND = nil

local before = #received
realmName = "Wrath Unleashed"   -- brand.sh renames the realm list entry
login()
check("on: a login tells the addon (OVMOD wubrand brand)", #received == before + 1 and received[#received][1] == "OVMOD"
    and received[#received][2] == "wubrand\tbrand\t1/1\tleyline\tWrath Unleashed")
check("on: the addon has it", W.Brand.on == true and W.Brand.name == "Leyline" and W.Brand.home == "Wrath Unleashed"
    and W.Brand.back == "Back to Wrath Unleashed")
before = #received
SendAddonMessage("OVMOD", "wubrand\task\t1/1\t", "WHISPER", "Tester")
check("on: the addon's ask is answered", #received == before + 1)

W.Say("later")
local lastChat; for _, m in ipairs(chat) do if m:find("later", 1, true) then lastChat = m end end
check("on: chat says [Leyline]", lastChat and lastChat:find("[Leyline]", 1, true) ~= nil and not hasOld(lastChat))
local win = W.Leyline.Window()
check("on: the open window's home button is relabelled", win.back.text == "Back to Wrath Unleashed")
-- the realm list: this realm's row comes from ov_leyline.lua, named by the brand
win:Hide(); SlashCmdList.WULEYLINE("")
serverClock = serverClock + 60
W.Leyline.Request(true)
local row
for _, r in ipairs(win.rows or {}) do if r:IsShown() and r.realm and r.realm.id == "this" then row = r end end
check("on: this realm's row is Wrath Unleashed", row and row.name:GetText():find("^Wrath Unleashed"))
win.back:Fire("OnClick")
check("on: Back on the home realm says so", win.info:GetText() == "You're on Wrath Unleashed now.")
local bad = {}
for _, f in ipairs(created) do
    if f.IsVisible and f:IsVisible() and f.parent and (f.parent == win or (f.parent.parent == win)) then
        local w = hasOld(f.text); if w then bad[#bad + 1] = (f.text or "") end
    end
end
check("on: nothing the window shows names an old brand", #bad == 0)
if #bad > 0 then print("  " .. table.concat(bad, " | ")) end

os.remove(flagFile); os.remove(datFile)
print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
