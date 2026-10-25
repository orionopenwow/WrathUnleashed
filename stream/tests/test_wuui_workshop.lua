-- lua5.1 stream/tests/test_wuui_workshop.lua [addon dir] [WUModCatalog.lua]
-- Fake 3.3.5a API: loads WrathUnleashedUI in .toc order plus the generated mod list (WUModCatalog.lua, from
-- `wu-mod.py catalog --lua`; stream/tests/test_workshop.py makes one from mods/catalog), opens
-- Esc > Mods & Workshop > Workshop, and checks the rows, the on/off switches and the links.
local dir = arg[1] or "stream/fui-web/Interface/AddOns/WrathUnleashedUI"
local catalogFile = arg[2]

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
    if type(k) == "string" and k:match("^%u") then return function() end end
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
function Frame:SetChecked(v) self.checked = v and true or false end
function Frame:GetChecked() return self.checked end
function Frame:RegisterEvent(e) self.events[e] = true end
function Frame:GetName() return self.name end
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
function GetCVar() return "1" end
function HasAction() return false end
function UnitLevel() return 80 end
function UnitClass() return "Mage", "MAGE" end
function UnitName() return "Tester" end
function PlaySound() end
function HideUIPanel(f) f:Hide() end
function GetTime() return 100 end
function SendAddonMessage() end

-- addons in this client: enabled state by name
local enabled = { DalaranDice = 1, WUPings = 1, WUEmoteWheel = 1 }
function GetNumAddOns() return 3 end
function GetAddOnInfo(name)
    if type(name) == "number" then name = ({ "DalaranDice", "WUPings", "WUEmoteWheel" })[name] end
    return name, name, "", enabled[name], 1
end
function EnableAddOn(name) enabled[name] = 1 end
function DisableAddOn(name) enabled[name] = nil end

-- ---------------------------------------------------------------- load
if catalogFile then
    dofile(catalogFile)
else
    WU_MOD_CATALOG = {
        { id = "pings", name = "Pings", version = "0.1.0", kind = "both", description = "Ping a spot.",
          permissions = { "chat", "timers" }, addons = { "WUPings" } },
        { id = "emote-wheel", name = "Emote Wheel", version = "0.1.0", kind = "ui", description = "Eight emotes.",
          permissions = {}, addons = { "WUEmoteWheel" } },
        { id = "dalaran-dice", name = "Dalaran Dice", version = "0.1.0", kind = "both", description = "Roll dice.",
          permissions = { "commands", "chat", "db" }, addons = { "DalaranDice" } },
    }
end
check("the generated mod list loads", type(WU_MOD_CATALOG) == "table" and #WU_MOD_CATALOG >= 3)
local files = {}
for line in io.lines(dir .. "/WrathUnleashedUI.toc") do
    if line:match("%.lua%s*$") then files[#files + 1] = line:gsub("%s+$", "") end
end
for _, f in ipairs(files) do dofile(dir .. "/" .. f) end
local W = assert(WrathUnleashedUI)

local rows = W.CatalogRows(WU_MOD_CATALOG)
check("rows sorted by name", rows[1].name == "Dalaran Dice" and rows[2].name == "Emote Wheel" and rows[3].name == "Pings")
check("row title has version and kind", rows[3].title:match("^Pings |cff9d9d9dv0%.1%.0 %- Realm %+ addon|r$") ~= nil)
check("junk entries skipped", #W.CatalogRows({ { id = 1 }, "x", { name = "No id" } }) == 0 and #W.CatalogRows(nil) == 0)
check("a realm-only mod has no switch", W.ModAddonsOn({ addons = {} }) == nil)

-- Esc > Mods & Workshop > Workshop
GameMenuButtonAddOns:Fire("OnClick")
local panel = _G.WrathUnleashedModsFrame
check("Mods & Workshop opens", panel and panel:IsShown())
local tab
for _, f in ipairs(created) do if f.parent == panel and f.text == "Workshop" then tab = f end end
tab:Fire("OnClick")
local page = panel.pages[3]
check("Workshop tab shown", page:IsShown())
local shown = {}
for _, cb in ipairs(page.rows) do if cb.row then shown[#shown + 1] = cb end end
check("lists the installed mods", #shown == math.min(4, #rows) and shown[1].title.text:match("^Dalaran Dice"))
check("each with its description", shown[3].line.text ~= "" and shown[3].line.text == rows[3].line)
check("addon mods have a ticked switch", shown[1]:IsShown() and shown[1].checked == true)

local pingsRow
for _, cb in ipairs(page.rows) do if cb.row and cb.row.id == "pings" then pingsRow = cb end end
pingsRow:SetChecked(false); pingsRow:Fire("OnClick")
check("unticking turns the mod's addon off", enabled.WUPings == nil and enabled.DalaranDice == 1)
pingsRow:SetChecked(true); pingsRow:Fire("OnClick")
check("ticking turns it back on", enabled.WUPings == 1)
enabled.WUEmoteWheel = nil
panel.RefreshWorkshop()
local wheelRow
for _, cb in ipairs(page.rows) do if cb.row and cb.row.id == "emote-wheel" then wheelRow = cb end end
check("a disabled addon shows unticked", wheelRow.checked == false)

local links, box = {}, page.copyBox
for _, f in ipairs(created) do
    if f.parent == page and f.kind == "Button" and f.label then links[#links + 1] = f end
end
check("four links", #links == 4)
links[1]:Fire("OnClick")
check("first link copies the Workshop site", box.text == "https://play.openvanilla.app/wrath/mods")

WU_MOD_CATALOG = nil
panel.RefreshWorkshop()
local any = false
for _, cb in ipairs(page.rows) do if cb.row then any = true end end
check("no mod list: an empty Workshop, no error", not any)

-- nothing the window shows names the game brand
local bad = {}
for _, f in ipairs(created) do
    local t = type(f.text) == "string" and f.text:lower() or ""
    for _, w in ipairs({ "world of warcraft", "warcraft", "lich king", "blizzard" }) do
        if t:find(w, 1, true) then bad[#bad + 1] = f.text end
    end
    if t:find("%f[%w]wow%f[%W]") then bad[#bad + 1] = f.text end
end
check("no game-brand names", #bad == 0)

print(string.format("\n%d/%d passed", pass, pass + fail))
os.exit(fail == 0 and 0 or 1)
